"""LLM research queue for product and theme hypotheses.

This script never writes the approved product-theme mapping.  It only records
evidence-backed hypotheses for later human approval.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from analyze_twse_momentum import THEME_CATALOG, THEME_MAPPING

REPORT_FILE = Path("report.json")
REVIEW_FILE = Path("data/product-inference-review.json")
MODEL = os.getenv("OPENAI_RESEARCH_MODEL", "gpt-5.6-terra")
REVIEW_INTERVAL_DAYS = 90


def load_json(path: Path, fallback: dict) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def response_text(payload: dict) -> tuple[str, list[str]]:
    text_parts: list[str] = []
    urls: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text_parts.append(content.get("text", ""))
            for annotation in content.get("annotations", []):
                if annotation.get("type") == "url_citation" and annotation.get("url"):
                    urls.append(annotation["url"])
    text = payload.get("output_text") or "".join(text_parts)
    return text, list(dict.fromkeys(urls))


def parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(match.group(0))


def ask_model(code: str, name: str, seed_theme: str | None) -> dict:
    # GitHub Secrets pasted from a clipboard can contain a trailing newline.
    # Trim surrounding whitespace before constructing the Authorization header.
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    seed_context = f"Existing seed theme (unverified): {seed_theme}" if seed_theme else "No existing seed theme."
    taxonomy = ", ".join(THEME_CATALOG)
    prompt = f"""Research Taiwan-listed company {code} {name}. {seed_context}
Use web search. Prefer the company's official product pages, annual reports, investor presentations, or exchange company profile.
When supported by evidence, prefer one of these canonical themes so synonyms and upstream/downstream companies cluster together: {taxonomy}.
Do not infer from company name alone. Return exactly one JSON object, no markdown:
{{
  "product_hypothesis": "concise Traditional Chinese product description",
  "supply_chain_tags": ["product or supply-chain tags, 1-4 items"],
  "theme_hypotheses": ["possible market themes, 1-3 items"],
  "rationale": "under 120 Traditional Chinese characters; distinguish evidence from inference",
  "confidence": "low|medium|high",
  "official_source_urls": ["official source URLs only"],
  "source_status": "verified_candidate|insufficient_evidence"
}}
If official evidence cannot be found, use an empty official_source_urls array and source_status insufficient_evidence."""
    body = json.dumps({
        "model": MODEL,
        "reasoning": {"effort": "low"},
        "tools": [{"type": "web_search"}],
        "max_output_tokens": 3000,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "product_theme_research",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "product_hypothesis": {"type": "string"},
                        "supply_chain_tags": {"type": "array", "items": {"type": "string"}},
                        "theme_hypotheses": {"type": "array", "items": {"type": "string"}},
                        "rationale": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                        "official_source_urls": {"type": "array", "items": {"type": "string"}},
                        "source_status": {"type": "string", "enum": ["verified_candidate", "insufficient_evidence"]},
                    },
                    "required": [
                        "product_hypothesis", "supply_chain_tags", "theme_hypotheses",
                        "rationale", "confidence", "official_source_urls", "source_status",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "input": prompt,
    }).encode("utf-8")
    request = Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"OpenAI API error {error.code}: {error.read().decode('utf-8', 'replace')[:400]}") from error
    except URLError as error:
        raise RuntimeError(f"OpenAI API connection failed: {error}") from error
    text, citation_urls = response_text(payload)
    result = parse_json(text)
    official_urls = result.get("official_source_urls", [])
    if not isinstance(official_urls, list):
        official_urls = []
    result["source_urls"] = list(dict.fromkeys([*official_urls, *citation_urls]))[:6]
    return result


def is_current(entry: dict) -> bool:
    if not entry.get("source_urls") or not entry.get("reviewed_at"):
        return False
    try:
        return date.fromisoformat(entry["reviewed_at"]) >= date.today() - timedelta(days=REVIEW_INTERVAL_DAYS)
    except ValueError:
        return False


def research_targets(report: dict, reviews: dict, bootstrap: bool) -> list[dict]:
    candidates = report.get("unmapped_candidates", [])
    priority = {"S": 0, "A": 1, "B": 2}
    targets = [
        {"code": stock["code"], "name": stock["name"], "seed_theme": THEME_MAPPING.get(stock["code"]), "sort": (0, priority.get(stock["tier"], 9), -stock["signal_score"])}
        for stock in candidates
    ]
    candidate_codes = {target["code"] for target in targets}
    for code, theme in THEME_MAPPING.items():
        if code not in candidate_codes:
            targets.append({"code": code, "name": "", "seed_theme": theme, "sort": (1, 9, code)})
    targets.sort(key=lambda target: target["sort"])
    # Both the scheduled and initial runs skip a recently sourced review.  The
    # bootstrap workflow simply uses a larger batch, so repeated manual runs
    # continue through the queue instead of paying to repeat the same companies.
    return [target for target in targets if not is_current(reviews.get("entries", {}).get(target["code"], {}))]


def main() -> None:
    parser = argparse.ArgumentParser(description="Research product/theme hypotheses with OpenAI web search grounding.")
    parser.add_argument("--bootstrap", action="store_true", help="Include all seed mapping and current candidate targets.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum companies per run; 0 processes the entire pending queue.")
    args = parser.parse_args()
    if args.limit < 0:
        raise SystemExit("--limit cannot be negative")
    report = load_json(REPORT_FILE, {})
    if report.get("freshness") != "fresh":
        raise SystemExit("Research skipped because report.json is not fresh")
    reviews = load_json(REVIEW_FILE, {"schema_version": 2, "description": "LLM product/theme research; not approved mappings.", "entries": {}})
    reviews["schema_version"] = 2
    reviews.setdefault("entries", {})
    targets = research_targets(report, reviews, args.bootstrap)
    if args.limit:
        targets = targets[:args.limit]
    for target in targets:
        result = ask_model(target["code"], target["name"], target["seed_theme"])
        official = result.get("official_source_urls", [])
        status = "LLM 假說／來源待人工確認" if official else "LLM 初步假說／待來源驗證"
        reviews["entries"][target["code"]] = {
            "product_hypothesis": result.get("product_hypothesis", "待覆核"),
            "supply_chain_tags": result.get("supply_chain_tags", []),
            "theme_hypotheses": result.get("theme_hypotheses", []),
            "rationale": result.get("rationale", "待覆核"),
            "confidence": result.get("confidence", "low"),
            "source_urls": result.get("source_urls", []),
            "source_status": status,
            "reviewed_at": date.today().isoformat(),
            "model": MODEL,
        }
        # Checkpoint each completed company so a later API/rate-limit failure
        # does not discard earlier research from the same full-queue run.
        REVIEW_FILE.write_text(json.dumps(reviews, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Researched {target['code']} {target['name'] or 'seed mapping'}", flush=True)
    REVIEW_FILE.write_text(json.dumps(reviews, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Research queue completed: {len(targets)} companies using {MODEL}.", flush=True)


if __name__ == "__main__":
    main()
