"""抓取富邦台股漲幅排行，產生題材與標的 Tier 報告。

執行：python analyze_twse_momentum.py
輸出：report.json（網站可直接匯入此檔的資料結構）與終端機報告。
"""
from __future__ import annotations

import json, re, sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

WINDOWS = (1, 2, 3, 4, 5, 10, 20)
BASE_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zg_A_0_{days}.djhtm"
OUTPUT = Path("report.json")
WEB_OUTPUT = Path("public/report.json")
INCLUDE_UNMAPPED = False  # 設為 True 可在報告最後保留「未分類」標的。
# 請依研究邏輯自行擴充或替換。未映射標的會歸入「未分類」。
THEME_MAPPING = {
    "6213": "AI 基礎建設 / 高速傳輸", "2368": "AI 基礎建設 / 高速傳輸",
    "3037": "AI 基礎建設 / 高速傳輸", "2313": "AI 基礎建設 / 高速傳輸",
    "6531": "記憶體 / IC 設計", "3006": "記憶體 / IC 設計",
    "2408": "記憶體 / IC 設計", "2344": "記憶體 / IC 設計",
    "2049": "機器人 / 智慧製造", "2464": "機器人 / 智慧製造", "4540": "機器人 / 智慧製造",
}
WEIGHT = {"S": 3, "A": 2, "B": 1}

class TableTextParser(HTMLParser):
    def __init__(self): super().__init__(); self.rows=[]; self.row=[]; self.in_cell=False; self.text=[]
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row=[]
        elif tag in ("td", "th"): self.in_cell=True; self.text=[]
    def handle_data(self, data):
        if self.in_cell: self.text.append(data)
    def handle_endtag(self, tag):
        if tag in ("td", "th"): self.row.append(" ".join("".join(self.text).split())); self.in_cell=False
        elif tag == "tr" and self.row: self.rows.append(self.row)

def fetch_ranking(days: int) -> dict[str, str]:
    """回傳 {股票代號: 股票名稱}。若網站版型改變，調整本函式的解析規則。"""
    request = Request(BASE_URL.format(days=days), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=25) as response:
        html = response.read().decode("big5", errors="ignore")
    parser = TableTextParser(); parser.feed(html)
    found = {}
    for row in parser.rows:
        joined = " ".join(row)
        match = re.search(r"\b(\d{4,6})\s+([^\s]+)", joined)
        if match: found[match.group(1)] = match.group(2)
    if not found: raise RuntimeError(f"{days}d 未解析到排行資料，請檢查來源頁面格式。")
    return found

def stock_tier(appearances: list[int]) -> str | None:
    count = len(appearances)
    return "S" if count >= 5 else "A" if count >= 3 else "B" if count == 2 else None

def build_report(rankings: dict[int, dict[str, str]]) -> dict:
    seen: dict[str, list[int]] = defaultdict(list); names = {}
    for day, stocks in rankings.items():
        for code, name in stocks.items(): seen[code].append(day); names[code] = name
    grouped: dict[str, list[dict]] = defaultdict(list)
    for code, days in seen.items():
        tier = stock_tier(days)
        if not tier: continue  # 僅出現一次的短線雜訊不顯示
        theme = THEME_MAPPING.get(code)
        if theme is None and not INCLUDE_UNMAPPED:
            continue
        grouped[theme or "未分類"].append({"code": code, "name": names[code], "tier": tier, "windows": [f"{day}d" for day in sorted(days)]})
    themes = []
    for name, stocks in grouped.items():
        stocks.sort(key=lambda x: (-WEIGHT[x["tier"]], x["code"]))
        themes.append({"name": name, "score": sum(WEIGHT[s["tier"]] for s in stocks), "stocks": stocks})
    themes.sort(key=lambda x: (-x["score"], x["name"]))
    for index, theme in enumerate(themes, 1): theme["tier"] = index
    return {"generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "source_urls": {f"{d}d": BASE_URL.format(days=d) for d in WINDOWS}, "themes": themes}

def print_report(report: dict) -> None:
    print("\n" + "=" * 45 + "\n🔥 【盤面強勢題材與標的 Tier 分析報告】 🔥\n" + "=" * 45)
    for theme in report["themes"]:
        print(f"\n🏆 可能性題材 Tier {theme['tier']}：{theme['name']} (總權重分數：{theme['score']})")
        for i, stock in enumerate(theme["stocks"]):
            branch = "└──" if i == len(theme["stocks"]) - 1 else "├──"
            print(f"  {branch} 標的 Tier {stock['tier']}：{stock['code']} {stock['name']} (上榜區塊：{', '.join(stock['windows'])})")
    print("\n" + "=" * 45)

def main() -> None:
    # Windows 預設 cp950 主控台無法印出 emoji；可用時切換成 UTF-8。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rankings = {day: fetch_ranking(day) for day in WINDOWS}
    report = build_report(rankings)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    WEB_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(report); print(f"\n已輸出：{OUTPUT.resolve()}")

if __name__ == "__main__": main()
