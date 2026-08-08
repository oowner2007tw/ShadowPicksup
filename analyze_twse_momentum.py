"""Build a Taiwan stock momentum report from Fubon gain-ranking pages.

Run: python analyze_twse_momentum.py
Outputs: report.json and public/report.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

WINDOWS = (1, 2, 3, 4, 5, 10, 20)
BASE_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zg_A_0_{days}.djhtm"
OUTPUTS = (Path("report.json"), Path("public/report.json"))
APP_DATA = Path("app/report-data.ts")
HISTORY_DIR = Path("data/history")

# Replace or expand this mock mapping with your preferred industry/concept taxonomy.
THEME_MAPPING = {
    "6213": "AI 基礎建設 / 高速傳輸", "2368": "AI 基礎建設 / 高速傳輸",
    "3037": "AI 基礎建設 / 高速傳輸", "2313": "AI 基礎建設 / 高速傳輸",
    "6531": "記憶體 / IC 設計", "3006": "記憶體 / IC 設計",
    "2408": "記憶體 / IC 設計", "2344": "記憶體 / IC 設計",
    "2049": "機器人 / 智慧製造", "2464": "機器人 / 智慧製造", "4540": "機器人 / 智慧製造",
    "3167": "機器人 / 智慧製造", "1597": "機器人 / 智慧製造", "4576": "機器人 / 智慧製造",
    "6213": "AI 基礎建設 / 高速傳輸", "6269": "AI 基礎建設 / 高速傳輸",
    "6426": "AI 基礎建設 / 高速傳輸", "3450": "AI 基礎建設 / 高速傳輸",
    "3653": "AI 基礎建設 / 高速傳輸", "8996": "AI 基礎建設 / 高速傳輸",
    "7711": "AI 基礎建設 / 高速傳輸", "6805": "AI 基礎建設 / 高速傳輸",
    "2455": "AI 基礎建設 / 高速傳輸", "8021": "AI 基礎建設 / 高速傳輸",
    "2337": "記憶體 / IC 設計", "2451": "記憶體 / IC 設計",
    "4967": "記憶體 / IC 設計", "4961": "記憶體 / IC 設計",
}
WEIGHT = {"S": 4, "A": 3, "B": 2, "C": 1}
RECENT_WINDOWS = {1, 2, 3}
EARLY_CLUSTER_MIN = 2


class TableTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] = []
        self.in_cell = False
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row = []
        elif tag in ("td", "th"):
            self.in_cell = True
            self.text = []

    def handle_data(self, data):
        if self.in_cell: self.text.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.row.append(" ".join("".join(self.text).split()))
            self.in_cell = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)


def fetch_ranking(days: int) -> dict[str, dict]:
    """Return stock name and current ranking position for one observation window."""
    request = Request(BASE_URL.format(days=days), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=25) as response:
        html = response.read().decode("big5", errors="ignore")
    parser = TableTextParser(); parser.feed(html)
    found: dict[str, dict] = {}
    for row in parser.rows:
        joined = " ".join(row)
        match = re.search(r"^\s*(\d+)\s+(\d{4,6})\s+([^\s]+)", joined)
        if match:
            percentages = re.findall(r"([+-]?\s*[\d,.]+)\s*%", joined)
            gain_pct = float(percentages[-1].replace(" ", "").replace(",", "")) if percentages else None
            found[match.group(2)] = {"name": match.group(3), "rank": int(match.group(1)), "gain_pct": gain_pct}
    if not found:
        raise RuntimeError(f"No rankings parsed from {days}d; source layout may have changed.")
    return found


def repeated_tier(count: int, avg_rank: float) -> str | None:
    """Repeated appearance + stronger ranking gives the established momentum tiers."""
    if count >= 5 and avg_rank <= 30: return "S"
    if count >= 3 and avg_rank <= 40: return "A"
    if count >= 2: return "B"
    return None


def build_report(rankings: dict[int, dict[str, dict]]) -> dict:
    seen: dict[str, list[dict]] = defaultdict(list)
    for day, stocks in rankings.items():
        for code, data in stocks.items():
            seen[code].append({"day": day, **data})

    candidates: dict[str, list[dict]] = defaultdict(list)
    early_by_theme: dict[str, list[dict]] = defaultdict(list)
    for code, observations in seen.items():
        theme = THEME_MAPPING.get(code)
        if not theme: continue  # Single, unmapped names are not a usable thematic signal.
        days = sorted(item["day"] for item in observations)
        avg_rank = sum(item["rank"] for item in observations) / len(observations)
        gains = [item["gain_pct"] for item in observations if item["gain_pct"] is not None]
        record = {"code": code, "name": observations[0]["name"], "windows": [f"{day}d" for day in days], "appearances": len(observations), "avg_rank": round(avg_rank, 1), "avg_gain_pct": round(sum(gains) / len(gains), 2) if gains else None, "latest_window": f"{min(days)}d"}
        tier = repeated_tier(len(observations), avg_rank)
        if tier:
            record["tier"] = tier
            candidates[theme].append(record)
        # Recent single appearances survive only if they form a theme cluster.
        elif len(observations) == 1 and days[0] in RECENT_WINDOWS and avg_rank <= 30:
            early_by_theme[theme].append(record)

    for theme, early_stocks in early_by_theme.items():
        if len(early_stocks) >= EARLY_CLUSTER_MIN:
            for record in early_stocks:
                record["tier"] = "C"  # Theme-confirmed early observation, not a buy signal.
                candidates[theme].append(record)

    themes = []
    for name, stocks in candidates.items():
        stocks.sort(key=lambda stock: (-WEIGHT[stock["tier"]], stock["avg_rank"], stock["code"]))
        themes.append({"name": name, "score": sum(WEIGHT[stock["tier"]] for stock in stocks), "stocks": stocks})
    themes.sort(key=lambda theme: (-theme["score"], theme["name"]))
    for tier, theme in enumerate(themes, 1): theme["tier"] = tier
    return {"generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "freshness": "fresh", "last_error": None, "source_urls": {f"{day}d": BASE_URL.format(days=day) for day in WINDOWS}, "themes": themes}


def print_report(report: dict) -> None:
    print("\n" + "=" * 50 + "\nMomentum Theme & Stock Tier Report\n" + "=" * 50)
    for theme in report["themes"]:
        print(f"\nTheme Tier {theme['tier']}: {theme['name']} (score: {theme['score']})")
        for stock in theme["stocks"]:
            print(f"  Tier {stock['tier']} | {stock['code']} {stock['name']} | {', '.join(stock['windows'])} | avg rank {stock['avg_rank']}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        report = build_report({day: fetch_ranking(day) for day in WINDOWS})
    except Exception as error:
        if not OUTPUTS[0].exists():
            raise
        report = json.loads(OUTPUTS[0].read_text(encoding="utf-8"))
        report["freshness"] = "stale"
        report["last_error"] = str(error)
        print(f"Fetch failed; retaining last successful report: {error}")
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    for output in OUTPUTS: output.write_text(payload, encoding="utf-8")
    APP_DATA.write_text(f"// Generated by analyze_twse_momentum.py. Do not edit manually.\nexport const report = {payload} as const;\n", encoding="utf-8")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if report["freshness"] == "fresh":
        (HISTORY_DIR / f"{report['generated_at'][:10]}.json").write_text(payload, encoding="utf-8")
    print_report(report)


if __name__ == "__main__":
    main()
