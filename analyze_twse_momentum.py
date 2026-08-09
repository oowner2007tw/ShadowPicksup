"""Build a Taiwan stock momentum report from Fubon gain-ranking pages.

Run: python analyze_twse_momentum.py
Outputs: report.json and public/report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from copy import deepcopy
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
PRODUCT_MAPPING_FILE = Path("data/product-theme-mapping.json")
INFERENCE_REVIEW_FILE = Path("data/product-inference-review.json")
TELEGRAM_MESSAGE_LIMIT = 3900

# Canonical themes merge product synonyms and adjacent upstream/downstream
# segments. Seed members are conservative anchors; LLM-reviewed candidates
# can join the same clusters as explicitly labelled provisional members.
THEME_CATALOG = {
    "AI 基礎建設 / 高速傳輸": {
        "aliases": ["AI 伺服器", "AI伺服器", "資料中心基礎設施", "AI資料中心液冷", "伺服器機櫃零組件", "高速傳輸", "連接器 / 線束", "散熱 / 機構件"],
        "seed_members": ["6213", "2368", "3037", "2313", "6269", "6426", "3450", "3653", "8996", "7711", "6805", "2455", "8021", "2382", "3231", "6669", "2356", "2376", "3017", "3324"],
    },
    "記憶體 / IC 設計": {
        "aliases": ["記憶體", "DRAM", "NAND Flash", "NOR Flash", "記憶體控制 IC", "IC 設計"],
        "seed_members": ["6531", "3006", "2408", "2344", "2337", "2451", "4967", "4961", "8299", "3260", "5351"],
    },
    "機器人 / 智慧製造": {
        "aliases": ["機器人", "智慧製造", "自動化設備", "工業機器人", "機器視覺", "智慧物流與倉儲數位化"],
        "seed_members": ["2049", "2464", "4540", "3167", "1597", "4576", "4583", "8374"],
    },
    "PCB / 高階材料": {
        "aliases": ["PCB 材料", "PCB材料", "軟板材料 / FCCL", "FCCL", "電子材料", "銅箔基板", "CCL", "高階 PCB"],
        "seed_members": ["6274", "8046", "4958", "2383", "5349"],
    },
    "先進封裝 / IC 載板": {
        "aliases": ["先進封裝", "IC 載板", "IC載板", "ABF 載板", "CoWoS", "封裝測試"],
        "seed_members": ["3189", "3711", "2449", "6239"],
    },
    "特用化學 / 高階材料": {
        "aliases": ["特用化學", "特用化學材料", "材料升級", "合成橡膠", "高階材料"],
        "seed_members": ["2103", "4722", "1717", "4763"],
    },
    "生技醫療 / 製藥": {
        "aliases": ["生技醫療", "原料藥 / 製藥", "原料藥", "製藥", "新藥", "視力矯正需求", "學名藥", "特殊製劑CDMO"],
        "seed_members": ["1762", "1795", "4743", "6472"],
    },
    "半導體 IP / RISC-V": {
        "aliases": ["RISC-V", "半導體 IP / CPU", "半導體 IP", "CPU IP", "處理器 IP"],
        "seed_members": ["6533", "3443", "3661"],
    },
    "儲能 / 電池": {
        "aliases": ["儲能", "電池模組", "電池", "備援電源", "能源管理"],
        "seed_members": ["6781", "3211", "4931"],
    },
    "金屬材料 / 資源循環": {
        "aliases": ["金屬材料", "資源循環", "金屬回收", "鎢鈷材料", "循環經濟"],
        "seed_members": ["7610", "2031", "9958"],
    },
    "電力控制 / 工業自動化": {
        "aliases": ["繼電器 / 電控零組件", "繼電器", "工業自動化", "電控零組件", "重電"],
        "seed_members": ["7788", "1504", "1513", "1514", "1536"],
    },
    "光電 / 電子零組件": {
        "aliases": ["光電照明", "電子零組件", "LED", "光電元件", "照明應用"],
        "seed_members": ["2491", "2426", "2393"],
    },
    "邊緣 AI / AIoT": {
        "aliases": ["AIoT與邊緣AI", "AI無人機與邊緣運算", "邊緣運算", "AIoT", "AI 無人機"],
        "seed_members": [],
    },
    "網通 / 寬頻升級": {
        "aliases": ["家庭寬頻升級", "寬頻升級", "網通", "衛星通訊", "無線通訊"],
        "seed_members": [],
    },
    "電商 / 數位支付": {
        "aliases": ["台灣電商", "金融科技", "數位支付", "第三方支付", "電商平台"],
        "seed_members": [],
    },
    "營建 / 不動產": {
        "aliases": ["耐震建築", "台灣不動產開發", "大台北都會區不動產開發", "營建", "建材"],
        "seed_members": [],
    },
    "電動車 / 綠色運輸": {
        "aliases": ["電動車與高效率馬達", "電動自行車", "電動車", "高效率馬達", "綠色運輸"],
        "seed_members": [],
    },
    "消費電子 / 顯示器": {
        "aliases": ["遊戲主機", "顯示器供應鏈", "消費電子", "顯示器", "遊戲機"],
        "seed_members": [],
    },
    "石化 / 原物料": {
        "aliases": ["石化上游原料", "石化", "煉油", "塑化原料"],
        "seed_members": [],
    },
}
THEME_MAPPING = {
    code: theme
    for theme, definition in THEME_CATALOG.items()
    for code in definition["seed_members"]
}
PROVISIONAL_SCORE_FACTOR = {"high": 0.85, "medium": 0.70, "low": 0.55}

# Product-level inference is deliberately separate from the curated mapping.
# It lets strong but newly observed names enter the model without claiming that
# the ranking source itself supplied an industry classification. Review entries
# periodically and promote them to THEME_MAPPING once the taxonomy is approved.
PRODUCT_THEME_INFERENCE: dict[str, dict] = {}
WEIGHT = {"S": 4, "A": 3, "B": 2, "C": 1}
REVIEW_ORDER = {"S": 0, "A": 1, "B": 2}
RECENT_WINDOWS = {1, 2, 3}
EARLY_CLUSTER_MIN = 2
C_STAGNATION_LIMIT = 5
NATURAL_DOWNGRADE = {"S": "A", "A": "B", "B": "C", "C": "C"}
COOLING_TIER_FACTOR = {"A": 0.65, "B": 0.40, "C": 0.20}
TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}


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


def load_product_theme_inference() -> dict[str, dict]:
    """Load only explicitly approved mappings for the official theme pool."""
    mappings = dict(PRODUCT_THEME_INFERENCE)
    if PRODUCT_MAPPING_FILE.exists():
        document = json.loads(PRODUCT_MAPPING_FILE.read_text(encoding="utf-8"))
        mappings.update({
            code: entry for code, entry in document.get("entries", {}).items()
            if entry.get("approval_status") == "approved"
        })
    return mappings


def load_inference_reviews() -> dict[str, dict]:
    """Load LLM hypotheses for explicitly labelled provisional assignment."""
    if not INFERENCE_REVIEW_FILE.exists():
        return {}
    return json.loads(INFERENCE_REVIEW_FILE.read_text(encoding="utf-8")).get("entries", {})


def normalize_theme_name(name: str) -> str:
    return re.sub(r"[\s/／・、_()（）-]+", "", name).lower()


def canonicalize_theme(name: str) -> str:
    """Collapse a product/theme synonym into one canonical supply-chain cluster."""
    normalized = normalize_theme_name(name)
    for canonical, definition in THEME_CATALOG.items():
        for alias in [canonical, *definition["aliases"]]:
            alias_normalized = normalize_theme_name(alias)
            if normalized == alias_normalized or (len(alias_normalized) >= 4 and alias_normalized in normalized):
                return canonical
    return name.strip()


def review_theme_mapping(review: dict | None) -> dict | None:
    """Turn an LLM hypothesis into a visible, discounted provisional mapping."""
    if not review or not review.get("theme_hypotheses"):
        return None
    theme = canonicalize_theme(review["theme_hypotheses"][0])
    if not theme:
        return None
    confidence = review.get("confidence", "low")
    return {
        "theme": theme,
        "product_label": f"疑似 {review.get('product_hypothesis', theme)}",
        "basis": "LLM 題材假說",
        "confidence": confidence,
        "provisional": True,
        "score_factor": PROVISIONAL_SCORE_FACTOR.get(confidence, 0.55),
    }


def resolve_theme(code: str, product_mappings: dict[str, dict], review: dict | None = None) -> dict | None:
    """Return a curated, approved, or explicitly labelled provisional theme."""
    if code in THEME_MAPPING:
        return {"theme": THEME_MAPPING[code], "product_label": None, "basis": "種子題材對照", "confidence": "已收錄", "provisional": False, "score_factor": 1.0}
    if code in product_mappings:
        mapping = dict(product_mappings[code])
        mapping["theme"] = canonicalize_theme(mapping["theme"])
        mapping.setdefault("provisional", False)
        mapping.setdefault("score_factor", 1.0)
        return mapping
    return review_theme_mapping(review)


def candidate_review_state(tier: str, review: dict | None) -> tuple[str, str]:
    """Return deterministic priority and review state for unmapped strong stocks."""
    priority = "P1／本輪必覆核" if tier in {"S", "A"} else "P2／依動能排程覆核"
    if not review:
        return priority, "等待 LLM 研究"
    if review.get("source_urls"):
        return priority, "LLM 假說／來源待人工確認"
    return priority, "LLM 初步假說／待來源驗證"


def repeated_tier(count: int, effective_appearances: float, avg_rank_percentile: float, continuity: int) -> str | None:
    """Tier established momentum by quality, recency and continuity—not raw count alone."""
    if count >= 5 and effective_appearances >= 3.8 and avg_rank_percentile <= 0.30 and continuity >= 4: return "S"
    if count >= 3 and effective_appearances >= 2.3 and avg_rank_percentile <= 0.45 and continuity >= 2: return "A"
    if count >= 2 and effective_appearances >= 1.35 and avg_rank_percentile <= 0.60: return "B"
    return None


def report_stock_codes(report: dict) -> set[str]:
    """Return every stock currently visible in a theme or review pool."""
    themed = {
        stock["code"]
        for theme in report.get("themes", [])
        for stock in theme.get("stocks", [])
    }
    unmapped = {stock["code"] for stock in report.get("unmapped_candidates", [])}
    return themed | unmapped


def load_previous_report(reference_day: str | None = None) -> dict | None:
    """Load the latest successful report before today for lifecycle comparison."""
    reference_day = reference_day or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    previous_reports: list[tuple[str, dict]] = []
    if HISTORY_DIR.exists():
        for path in HISTORY_DIR.glob("*.json"):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                report_day = str(report.get("generated_at", path.stem))[:10]
                if report_day < reference_day and report.get("freshness", "fresh") == "fresh":
                    previous_reports.append((report_day, report))
            except (OSError, ValueError, TypeError):
                continue
    if not previous_reports:
        return None
    _, latest_report = max(previous_reports, key=lambda item: item[0])
    return latest_report


def load_previous_stock_codes(reference_day: str | None = None) -> set[str] | None:
    """Load the NEW-tag baseline without treating the first run as all-new."""
    previous_report = load_previous_report(reference_day)
    return report_stock_codes(previous_report) if previous_report else None


def annotate_new_stocks(report: dict, previous_codes: set[str] | None) -> dict:
    """Mark stocks absent from the prior successful report; no baseline means no false NEW tags."""
    for theme in report.get("themes", []):
        for stock in theme.get("stocks", []):
            stock["is_new"] = previous_codes is not None and stock["code"] not in previous_codes
    for stock in report.get("unmapped_candidates", []):
        stock["is_new"] = previous_codes is not None and stock["code"] not in previous_codes
    return report


def index_report_stocks(report: dict | None) -> dict[str, tuple[dict, str | None]]:
    """Index visible stocks together with their current theme, if any."""
    if not report:
        return {}
    indexed: dict[str, tuple[dict, str | None]] = {}
    for theme in report.get("themes", []):
        for stock in theme.get("stocks", []):
            indexed[stock["code"]] = (stock, theme["name"])
    for stock in report.get("unmapped_candidates", []):
        indexed[stock["code"]] = (stock, None)
    return indexed


def tier_change(current_tier: str, previous_stock: dict | None, has_baseline: bool) -> str:
    if not has_baseline:
        return "baseline"
    if not previous_stock:
        return "new"
    if not previous_stock.get("is_active", True):
        return "returning"
    previous_tier = previous_stock.get("tier", current_tier)
    if TIER_ORDER[current_tier] < TIER_ORDER.get(previous_tier, TIER_ORDER[current_tier]):
        return "up"
    if TIER_ORDER[current_tier] > TIER_ORDER.get(previous_tier, TIER_ORDER[current_tier]):
        return "down"
    return "same"


def apply_market_lifecycle(report: dict, previous_report: dict | None) -> dict:
    """Apply stepwise demotion and a five-session Tier C observation period."""
    previous_index = index_report_stocks(previous_report)
    current_index = index_report_stocks(report)
    has_baseline = previous_report is not None
    previous_signature = (previous_report or {}).get("market_signature")
    current_signature = report.get("market_signature")
    advances_session = not has_baseline or not previous_signature or not current_signature or previous_signature != current_signature
    report["new_trading_session"] = advances_session
    exited_stocks: list[dict] = []
    terminal_codes: set[str] = set()

    for code, (stock, current_theme) in list(current_index.items()):
        previous_stock = previous_index.get(code, (None, None))[0]
        previous_tier = previous_stock.get("tier") if previous_stock else None
        raw_tier = stock["tier"]
        displayed_tier = raw_tier
        if previous_stock and advances_session:
            previous_position = TIER_ORDER.get(previous_tier, TIER_ORDER[raw_tier])
            raw_position = TIER_ORDER[raw_tier]
            if raw_position > previous_position + 1:
                displayed_tier = NATURAL_DOWNGRADE[previous_tier]

        previous_c_days = int(previous_stock.get("c_stagnant_days", 0)) if previous_stock else 0
        if displayed_tier == "C":
            c_stagnant_days = previous_c_days + 1 if advances_session and previous_tier == "C" else previous_c_days if not advances_session and previous_tier == "C" else 1
        else:
            c_stagnant_days = 0

        if displayed_tier == "C" and c_stagnant_days > C_STAGNATION_LIMIT:
            exited_stocks.append({
                "code": code,
                "name": stock["name"],
                "previous_tier": previous_tier or "C",
                "theme": current_theme,
                "c_stagnant_days": c_stagnant_days,
                "reason": f"Tier C 已完整觀察 {C_STAGNATION_LIMIT} 個交易日仍未轉強",
            })
            terminal_codes.add(code)
            continue

        stock["raw_tier"] = raw_tier
        stock["tier"] = displayed_tier
        stock["is_active"] = True
        stock["miss_streak"] = 0
        stock["c_stagnant_days"] = c_stagnant_days
        stock["base_score_factor"] = stock.get("score_factor", 1.0)
        stock["is_new"] = has_baseline and previous_stock is None
        stock["previous_tier"] = previous_tier
        stock["tier_change"] = tier_change(displayed_tier, previous_stock, has_baseline)
        if displayed_tier == "C":
            stock["lifecycle_status"] = f"C 觀察 {c_stagnant_days}/{C_STAGNATION_LIMIT}"
        else:
            stock["lifecycle_status"] = {
                "new": "新進",
                "returning": "回溫",
                "up": "升級",
                "down": "自然降級",
                "same": "持穩",
                "baseline": "基準",
            }[stock["tier_change"]]

    if terminal_codes:
        for theme in report.get("themes", []):
            theme["stocks"] = [stock for stock in theme.get("stocks", []) if stock["code"] not in terminal_codes]
        report["unmapped_candidates"] = [
            stock for stock in report.get("unmapped_candidates", []) if stock["code"] not in terminal_codes
        ]
        for code in terminal_codes:
            current_index.pop(code, None)

    themes_by_name = {theme["name"]: theme for theme in report.get("themes", [])}
    for code, (previous_stock, previous_theme) in previous_index.items():
        if code in current_index or code in terminal_codes:
            continue

        previous_tier = previous_stock.get("tier", "C")
        previous_c_days = int(previous_stock.get("c_stagnant_days", 0))
        if advances_session:
            displayed_tier = NATURAL_DOWNGRADE[previous_tier]
            c_stagnant_days = previous_c_days + 1 if previous_tier == "C" else 1 if displayed_tier == "C" else 0
        else:
            displayed_tier = previous_tier
            c_stagnant_days = previous_c_days

        if displayed_tier == "C" and c_stagnant_days > C_STAGNATION_LIMIT:
            exited_stocks.append({
                "code": code,
                "name": previous_stock["name"],
                "previous_tier": previous_tier,
                "theme": previous_theme,
                "c_stagnant_days": c_stagnant_days,
                "reason": f"Tier C 已完整觀察 {C_STAGNATION_LIMIT} 個交易日仍未轉強",
            })
            continue

        cooling_stock = deepcopy(previous_stock)
        base_factor = previous_stock.get("base_score_factor", previous_stock.get("score_factor", 1.0))
        tier_changed = displayed_tier != previous_tier
        if tier_changed:
            lifecycle_status = "自然降級"
        elif displayed_tier == "C":
            lifecycle_status = f"C 觀察 {c_stagnant_days}/{C_STAGNATION_LIMIT}"
        else:
            lifecycle_status = previous_stock.get("lifecycle_status", "持穩")
        cooling_stock.update({
            "tier": displayed_tier,
            "raw_tier": None,
            "is_active": False,
            "is_new": False,
            "miss_streak": int(previous_stock.get("miss_streak", 0)) + (1 if advances_session else 0),
            "c_stagnant_days": c_stagnant_days,
            "previous_tier": previous_tier,
            "tier_change": "down" if tier_changed else previous_stock.get("tier_change", "same"),
            "lifecycle_status": lifecycle_status,
            "base_score_factor": base_factor,
            "score_factor": base_factor * COOLING_TIER_FACTOR.get(displayed_tier, 1.0),
        })
        if previous_theme:
            theme = themes_by_name.setdefault(previous_theme, {
                "name": previous_theme,
                "stocks": [],
                "mapping_basis": previous_report and next(
                    (item.get("mapping_basis", []) for item in previous_report.get("themes", []) if item["name"] == previous_theme),
                    [],
                ),
            })
            theme["stocks"].append(cooling_stock)
        else:
            report.setdefault("unmapped_candidates", []).append(cooling_stock)

    previous_themes = {theme["name"]: theme for theme in (previous_report or {}).get("themes", [])}
    themes = []
    for theme in themes_by_name.values():
        stocks = theme["stocks"]
        if not stocks:
            continue
        stocks.sort(key=lambda stock: (not stock.get("is_active", True), -stock["signal_score"], -WEIGHT[stock["tier"]], stock["avg_rank"], stock["code"]))
        active_stocks = [stock for stock in stocks if stock.get("is_active", True)]
        cooling_count = len(stocks) - len(active_stocks)
        core_strength = sum(stock["signal_score"] * stock.get("score_factor", 1.0) for stock in stocks[:3])
        breadth_bonus = min(len(active_stocks), 5) * 0.5
        early_cluster_count = sum(stock["tier"] == "C" and stock.get("is_active", True) for stock in stocks)
        early_cluster_bonus = 1 if early_cluster_count >= EARLY_CLUSTER_MIN else 0
        score = round(core_strength * 4 + breadth_bonus + early_cluster_bonus)
        previous_theme = previous_themes.get(theme["name"])
        previous_active = sum(stock.get("is_active", True) for stock in previous_theme.get("stocks", [])) if previous_theme else 0
        previous_score = previous_theme.get("score", 0) if previous_theme else 0
        if not has_baseline:
            lifecycle = "成熟"
        elif not previous_theme:
            lifecycle = "啟動"
        elif active_stocks and (len(active_stocks) > previous_active or score >= previous_score * 1.15) and score > previous_score * 0.8:
            lifecycle = "擴散"
        elif not active_stocks or len(active_stocks) < previous_active or score <= previous_score * 0.8:
            lifecycle = "退潮"
        else:
            lifecycle = "成熟"
        themes.append({
            **theme,
            "score": score,
            "core_strength": round(core_strength, 2),
            "breadth": len(stocks),
            "active_breadth": len(active_stocks),
            "cooling_count": cooling_count,
            "provisional_count": sum(stock.get("is_provisional", False) for stock in stocks),
            "early_cluster_count": early_cluster_count,
            "mapping_basis": sorted({stock.get("theme_basis", "") for stock in stocks if stock.get("theme_basis")}),
            "lifecycle": lifecycle,
        })

    themes.sort(key=lambda theme: (-theme["score"], theme["name"]))
    for theme_rank, theme in enumerate(themes, 1):
        previous_theme = previous_themes.get(theme["name"])
        theme["previous_tier"] = previous_theme.get("tier") if previous_theme else None
        theme["tier_change"] = "new" if not previous_theme else ("up" if theme_rank < previous_theme.get("tier", theme_rank) else "down" if theme_rank > previous_theme.get("tier", theme_rank) else "same")
        theme["tier"] = theme_rank
    report["themes"] = themes
    report["unmapped_candidates"].sort(key=lambda stock: (not stock.get("is_active", True), REVIEW_ORDER.get(stock["tier"], 9), -stock["signal_score"], stock["avg_rank"], stock["code"]))
    report["exited_stocks"] = sorted(exited_stocks, key=lambda stock: (TIER_ORDER.get(stock.get("previous_tier"), 9), stock["code"]))
    report["lifecycle_summary"] = {
        "launching": sum(theme["lifecycle"] == "啟動" for theme in themes),
        "expanding": sum(theme["lifecycle"] == "擴散" for theme in themes),
        "mature": sum(theme["lifecycle"] == "成熟" for theme in themes),
        "cooling": sum(theme["lifecycle"] == "退潮" for theme in themes),
        "exited": len(exited_stocks),
    }
    return report


def build_report(rankings: dict[int, dict[str, dict]]) -> dict:
    signature_payload = {
        str(day): [
            [code, stock.get("rank"), stock.get("gain_pct")]
            for code, stock in sorted(stocks.items())
        ]
        for day, stocks in sorted(rankings.items())
    }
    market_signature = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    seen: dict[str, list[dict]] = defaultdict(list)
    for day, stocks in rankings.items():
        for code, data in stocks.items():
            seen[code].append({"day": day, **data})

    candidates: dict[str, list[dict]] = defaultdict(list)
    early_by_theme: dict[str, list[dict]] = defaultdict(list)
    unmapped_candidates: list[dict] = []
    product_mappings = load_product_theme_inference()
    inference_reviews = load_inference_reviews()
    for code, observations in seen.items():
        llm_review = inference_reviews.get(code)
        mapping = resolve_theme(code, product_mappings, llm_review)
        theme = mapping["theme"] if mapping else None
        days = sorted(item["day"] for item in observations)
        avg_rank = sum(item["rank"] for item in observations) / len(observations)
        avg_rank_percentile = sum(item["rank_percentile"] for item in observations) / len(observations)
        effective_appearances = sum(RECENCY_WEIGHT[item["day"]] for item in observations)
        continuity = longest_continuous_run(days)
        continuity_ratio = continuity / len(days)
        gains = [item["gain_pct"] for item in observations if item["gain_pct"] is not None]
        signal_score = effective_appearances * (1.15 - avg_rank_percentile) * (0.75 + continuity_ratio * 0.25)
        record = {"code": code, "name": observations[0]["name"], "windows": [f"{day}d" for day in days], "appearances": len(observations), "effective_appearances": round(effective_appearances, 2), "continuity": continuity, "avg_rank": round(avg_rank, 1), "avg_rank_percentile": round(avg_rank_percentile * 100, 1), "signal_score": round(signal_score, 2), "avg_gain_pct": round(sum(gains) / len(gains), 2) if gains else None, "latest_window": f"{min(days)}d", "theme_basis": mapping["basis"] if mapping else "待產品推論", "theme_confidence": mapping["confidence"] if mapping else "未映射", "product_label": mapping["product_label"] if mapping else None, "is_provisional": mapping.get("provisional", False) if mapping else False, "score_factor": mapping.get("score_factor", 1.0) if mapping else 0.0, "llm_review": llm_review}
        tier = repeated_tier(len(observations), effective_appearances, avg_rank_percentile, continuity)
        if tier:
            record["tier"] = tier
            if theme:
                candidates[theme].append(record)
            else:
                record["review_priority"], record["review_status"] = candidate_review_state(tier, llm_review)
                unmapped_candidates.append(record)
        # Recent single appearances survive only if they form a theme cluster.
        elif theme and len(observations) == 1 and days[0] in RECENT_WINDOWS and avg_rank_percentile <= 0.30:
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
        core_strength = sum(stock["signal_score"] * stock["score_factor"] for stock in stocks[:3])
        breadth_bonus = min(len(stocks), 5) * 0.5
        early_cluster_bonus = 1 if sum(stock["tier"] == "C" for stock in stocks) >= EARLY_CLUSTER_MIN else 0
        themes.append({"name": name, "score": round(core_strength * 4 + breadth_bonus + early_cluster_bonus), "core_strength": round(core_strength, 2), "breadth": len(stocks), "provisional_count": sum(stock["is_provisional"] for stock in stocks), "early_cluster_count": sum(stock["tier"] == "C" for stock in stocks), "mapping_basis": sorted({stock["theme_basis"] for stock in stocks}), "stocks": stocks})
    themes.sort(key=lambda theme: (-theme["score"], theme["name"]))
    for tier, theme in enumerate(themes, 1): theme["tier"] = tier
    unmapped_candidates.sort(key=lambda stock: (REVIEW_ORDER[stock["tier"]], -stock["signal_score"], stock["avg_rank"], stock["code"]))
    review_summary = {
        "required": sum(stock["tier"] in {"S", "A"} for stock in unmapped_candidates),
        "reviewed": sum(stock["llm_review"] is not None for stock in unmapped_candidates),
        "source_verified": sum(bool(stock["llm_review"] and stock["llm_review"].get("source_urls")) for stock in unmapped_candidates),
    }
    return {"generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "market_signature": market_signature, "freshness": "fresh", "last_error": None, "source_urls": {f"{day}d": BASE_URL.format(days=day) for day in WINDOWS}, "themes": themes, "unmapped_candidates": unmapped_candidates, "review_summary": review_summary}


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

    def append_section(section: str) -> None:
        if len(messages[-1]) + len(section) > TELEGRAM_MESSAGE_LIMIT:
            messages.append(f"🔥 台股題材地圖｜續報\n{section.lstrip()}")
        else:
            messages[-1] += section

    def stock_state_label(stock: dict) -> str:
        c_watch = f"〔C 觀察 {stock.get('c_stagnant_days', 0)}/{C_STAGNATION_LIMIT}〕" if stock.get("tier") == "C" else ""
        if stock.get("tier_change") == "down":
            return f"〔{stock.get('previous_tier')}→{stock['tier']} 自然降級〕{c_watch}"
        if stock.get("tier_change") == "up":
            return f"〔{stock.get('previous_tier')}→{stock['tier']} 升級〕"
        if stock.get("tier_change") == "returning":
            return "〔回溫〕"
        if c_watch:
            return c_watch
        return f"〔{stock['lifecycle_status']}〕" if not stock.get("is_active", True) else ""

    for theme in report["themes"]:
        theme_change = "" if not theme.get("previous_tier") or theme.get("tier_change") == "same" else f"｜昨 {theme['previous_tier']} → 今 {theme['tier']}"
        lines = [f"\n🏆 題材 Tier {theme['tier']}：{theme['name']}（{theme['score']} 分）〔{theme.get('lifecycle', '成熟')}〕{theme_change}"]
        for stock in theme["stocks"]:
            inference_label = "〔疑似題材／LLM〕" if stock["is_provisional"] else ("〔產品面推論〕" if stock["theme_basis"] == "產品面推論" else "")
            new_label = "〔NEW〕" if stock.get("is_new") else ""
            state_label = stock_state_label(stock)
            lines.append(
                f"• Tier {stock['tier']}｜{stock['code']} {stock['name']}｜"
                f"{stock['appearances']}x｜連續 {stock['continuity']} 格｜"
                f"動能 {stock['signal_score']}｜{', '.join(stock['windows'])}{new_label}{state_label}{inference_label}"
            )
        append_section("\n".join(lines))

    if report.get("unmapped_candidates"):
        lines = ["\n🧭 待產品推論候選（已符合標的 Tier，尚待映射）"]
        for stock in report["unmapped_candidates"]:
            new_label = "〔NEW〕" if stock.get("is_new") else ""
            state_label = stock_state_label(stock)
            lines.append(f"• Tier {stock['tier']}｜{stock['code']} {stock['name']}{new_label}{state_label}｜動能 {stock['signal_score']}｜{', '.join(stock['windows'])}")
        append_section("\n".join(lines))

    if report.get("exited_stocks"):
        lines = ["\n♻️ 今日正式汰換"]
        for stock in report["exited_stocks"]:
            theme = f"｜{stock['theme']}" if stock.get("theme") else "｜尚無題材"
            lines.append(f"• 前 Tier {stock['previous_tier']}｜{stock['code']} {stock['name']}{theme}｜{stock['reason']}")
        append_section("\n".join(lines))

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
        previous_report = load_previous_report()
        report = apply_market_lifecycle(
            build_report({day: fetch_ranking(day) for day in WINDOWS}),
            previous_report,
        )
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
            if not send_telegram_report(report):
                raise SystemExit("Telegram delivery failed.")
    print_report(report)


if __name__ == "__main__":
    main()
