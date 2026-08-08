"""Build a Taiwan stock momentum report from Fubon gain-ranking pages.

Run: python analyze_twse_momentum.py
Outputs: report.json and public/report.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WINDOWS = (1, 2, 3, 4, 5, 10, 20)
WINDOW_INDEX = {day: index for index, day in enumerate(WINDOWS)}
# The windows overlap. Recency weights reduce the false confidence that comes
# from counting 1d, 2d, 3d… as fully independent observations.
RECENCY_WEIGHT = {1: 1.00, 2: 0.95, 3: 0.90, 4: 0.85, 5: 0.80, 10: 0.65, 20: 0.50}
BASE_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zg_A_0_{days}.djhtm"
OUTPUTS = (Path("report.json"), Path("public/report.json"))
APP_DATA = Path("app/report-data.ts")
HISTORY_DIR = Path("data/history")
TELEGRAM_MESSAGE_LIMIT = 3900

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

# Product-level inference is deliberately separate from the curated mapping.
# It lets strong but newly observed names enter the model without claiming that
# the ranking source itself supplied an industry classification. Review entries
# periodically and promote them to THEME_MAPPING once the taxonomy is approved.
PRODUCT_THEME_INFERENCE = {
    "2059": {
        "theme": "伺服器導軌 / 機櫃滑軌",
        "product_label": "伺服器導軌、機櫃滑軌",
        "basis": "產品面推論",
        "confidence": "待覆核",
    },
    "8039": {
        "theme": "軟板材料 / FCCL",
        "product_label": "軟板材料、FCCL",
        "basis": "產品面推論",
        "confidence": "待覆核",
    },
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
    universe_size = max(len(found), 1)
    for item in found.values():
        # 0.0 is the top of this specific list and 1.0 is the bottom.
        item["rank_percentile"] = round((item["rank"] - 1) / max(universe_size - 1, 1), 4)
    return found


def longest_continuous_run(days: list[int]) -> int:
    """Return longest uninterrupted run in the ordered observation windows."""
    positions = sorted(WINDOW_INDEX[day] for day in days)
    longest = run = 1
    for previous, current in zip(positions, positions[1:]):
        run = run + 1 if current == previous + 1 else 1
        longest = max(longest, run)
    return longest


def resolve_theme(code: str) -> dict | None:
    """Return a curated theme or an explicitly labelled product inference."""
    if code in THEME_MAPPING:
        return {"theme": THEME_MAPPING[code], "product_label": None, "basis": "人工題材對照", "confidence": "已收錄"}
    return PRODUCT_THEME_INFERENCE.get(code)


def repeated_tier(count: int, effective_appearances: float, avg_rank_percentile: float, continuity: int) -> str | None:
    """Tier established momentum by quality, recency and continuity—not raw count alone."""
    if count >= 5 and effective_appearances >= 3.8 and avg_rank_percentile <= 0.30 and continuity >= 4: return "S"
    if count >= 3 and effective_appearances >= 2.3 and avg_rank_percentile <= 0.45 and continuity >= 2: return "A"
    if count >= 2 and effective_appearances >= 1.35 and avg_rank_percentile <= 0.60: return "B"
    return None


def build_report(rankings: dict[int, dict[str, dict]]) -> dict:
    seen: dict[str, list[dict]] = defaultdict(list)
    for day, stocks in rankings.items():
        for code, data in stocks.items():
            seen[code].append({"day": day, **data})

    candidates: dict[str, list[dict]] = defaultdict(list)
    early_by_theme: dict[str, list[dict]] = defaultdict(list)
    for code, observations in seen.items():
        mapping = resolve_theme(code)
        if not mapping: continue  # Unknown product relationship remains excluded until reviewed.
        theme = mapping["theme"]
        days = sorted(item["day"] for item in observations)
        avg_rank = sum(item["rank"] for item in observations) / len(observations)
        avg_rank_percentile = sum(item["rank_percentile"] for item in observations) / len(observations)
        effective_appearances = sum(RECENCY_WEIGHT[item["day"]] for item in observations)
        continuity = longest_continuous_run(days)
        continuity_ratio = continuity / len(days)
        gains = [item["gain_pct"] for item in observations if item["gain_pct"] is not None]
        signal_score = effective_appearances * (1.15 - avg_rank_percentile) * (0.75 + continuity_ratio * 0.25)
        record = {"code": code, "name": observations[0]["name"], "windows": [f"{day}d" for day in days], "appearances": len(observations), "effective_appearances": round(effective_appearances, 2), "continuity": continuity, "avg_rank": round(avg_rank, 1), "avg_rank_percentile": round(avg_rank_percentile * 100, 1), "signal_score": round(signal_score, 2), "avg_gain_pct": round(sum(gains) / len(gains), 2) if gains else None, "latest_window": f"{min(days)}d", "theme_basis": mapping["basis"], "theme_confidence": mapping["confidence"], "product_label": mapping["product_label"]}
        tier = repeated_tier(len(observations), effective_appearances, avg_rank_percentile, continuity)
        if tier:
            record["tier"] = tier
            candidates[theme].append(record)
        # Recent single appearances survive only if they form a theme cluster.
        elif len(observations) == 1 and days[0] in RECENT_WINDOWS and avg_rank_percentile <= 0.30:
            early_by_theme[theme].append(record)

    for theme, early_stocks in early_by_theme.items():
        early_windows = {stock["latest_window"] for stock in early_stocks}
        has_immediate_signal = any(stock["latest_window"] in {"1d", "2d"} for stock in early_stocks)
        # A new theme needs breadth, quality and at least one very recent signal.
        if len(early_stocks) >= EARLY_CLUSTER_MIN and len(early_windows) >= 2 and has_immediate_signal:
            for record in early_stocks:
                record["tier"] = "C"  # Theme-confirmed early observation, not a buy signal.
                candidates[theme].append(record)

    themes = []
    for name, stocks in candidates.items():
        stocks.sort(key=lambda stock: (-stock["signal_score"], -WEIGHT[stock["tier"]], stock["avg_rank"], stock["code"]))
        core_strength = sum(stock["signal_score"] for stock in stocks[:3])
        breadth_bonus = min(len(stocks), 5) * 0.5
        early_cluster_bonus = 1 if sum(stock["tier"] == "C" for stock in stocks) >= EARLY_CLUSTER_MIN else 0
        themes.append({"name": name, "score": round(core_strength * 4 + breadth_bonus + early_cluster_bonus), "core_strength": round(core_strength, 2), "breadth": len(stocks), "early_cluster_count": sum(stock["tier"] == "C" for stock in stocks), "mapping_basis": sorted({stock["theme_basis"] for stock in stocks}), "stocks": stocks})
    themes.sort(key=lambda theme: (-theme["score"], theme["name"]))
    for tier, theme in enumerate(themes, 1): theme["tier"] = tier
    return {"generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "freshness": "fresh", "last_error": None, "source_urls": {f"{day}d": BASE_URL.format(days=day) for day in WINDOWS}, "themes": themes}


def print_report(report: dict) -> None:
    print("\n" + "=" * 50 + "\nMomentum Theme & Stock Tier Report\n" + "=" * 50)
    for theme in report["themes"]:
        print(f"\nTheme Tier {theme['tier']}: {theme['name']} (score: {theme['score']})")
        for stock in theme["stocks"]:
            print(f"  Tier {stock['tier']} | {stock['code']} {stock['name']} | {', '.join(stock['windows'])} | avg rank {stock['avg_rank']}")


def telegram_messages(report: dict) -> list[str]:
    """Render the report in Telegram-safe plain text chunks."""
    header = "🔥 台股題材地圖｜每日追蹤"
    messages = [header]
    for theme in report["themes"]:
        lines = [f"\n🏆 題材 Tier {theme['tier']}：{theme['name']}（{theme['score']} 分）"]
        for stock in theme["stocks"]:
            inference_label = "〔產品面推論〕" if stock["theme_basis"] == "產品面推論" else ""
            lines.append(
                f"• Tier {stock['tier']}｜{stock['code']} {stock['name']}｜"
                f"{stock['appearances']}x｜連續 {stock['continuity']} 格｜"
                f"動能 {stock['signal_score']}｜{', '.join(stock['windows'])}{inference_label}"
            )
        section = "\n".join(lines)
        if len(messages[-1]) + len(section) > TELEGRAM_MESSAGE_LIMIT:
            messages.append(f"🔥 台股題材地圖｜續報\n{section.lstrip()}")
        else:
            messages[-1] += section
    return messages


def send_telegram_report(report: dict) -> bool:
    """Send a fresh report only when Telegram credentials are configured."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set.")
        return False

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        for message in telegram_messages(report):
            data = urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
            request = Request(endpoint, data=data, method="POST")
            with urlopen(request, timeout=20) as response:
                response.read()
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"Telegram delivery failed: {error}")
        return False
    print(f"Telegram delivered: {len(report['themes'])} theme clusters.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Taiwan stock momentum report.")
    parser.add_argument("--no-telegram", action="store_true", help="Write the report without sending Telegram notifications.")
    args = parser.parse_args()
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
        if not args.no_telegram:
            send_telegram_report(report)
    print_report(report)


if __name__ == "__main__":
    main()
