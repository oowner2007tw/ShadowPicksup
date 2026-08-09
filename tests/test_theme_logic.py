import unittest

from analyze_twse_momentum import (
    THEME_MAPPING,
    apply_market_lifecycle,
    annotate_new_stocks,
    canonicalize_theme,
    review_theme_mapping,
    telegram_messages,
)


class ThemeTaxonomyTests(unittest.TestCase):
    @staticmethod
    def lifecycle_stock(code="1111", tier="A"):
        return {
            "code": code,
            "name": f"Stock {code}",
            "tier": tier,
            "signal_score": 3.0,
            "score_factor": 1.0,
            "avg_rank": 5.0,
            "windows": ["1d", "2d", "3d"],
            "appearances": 3,
            "continuity": 3,
            "is_provisional": False,
            "theme_basis": "種子題材對照",
        }

    @classmethod
    def lifecycle_report(cls, stocks=None, theme_name="Test Theme"):
        stocks = stocks or []
        themes = [{"name": theme_name, "tier": 1, "score": 14, "stocks": stocks}] if stocks else []
        return {"themes": themes, "unmapped_candidates": [], "review_summary": {}}

    def test_seed_coverage_is_expanded(self):
        self.assertGreaterEqual(len(THEME_MAPPING), 70)

    def test_synonyms_and_supply_chain_names_share_a_theme(self):
        expected = "AI 基礎建設 / 高速傳輸"
        self.assertEqual(canonicalize_theme("AI 伺服器"), expected)
        self.assertEqual(canonicalize_theme("伺服器機櫃零組件"), expected)
        self.assertEqual(canonicalize_theme("高速傳輸"), expected)
        self.assertEqual(canonicalize_theme("AI資料中心液冷"), expected)
        self.assertEqual(canonicalize_theme("AI無人機與邊緣運算"), "邊緣 AI / AIoT")
        self.assertEqual(canonicalize_theme("金融科技"), "電商 / 數位支付")

    def test_reviewed_candidate_gets_a_provisional_theme(self):
        mapping = review_theme_mapping({
            "product_hypothesis": "軟板材料",
            "theme_hypotheses": ["軟板材料 / FCCL", "電子材料"],
            "confidence": "medium",
        })
        self.assertEqual(mapping["theme"], "PCB / 高階材料")
        self.assertTrue(mapping["provisional"])
        self.assertLess(mapping["score_factor"], 1.0)

    def test_new_tag_compares_all_visible_stocks_with_previous_report(self):
        report = {
            "themes": [{"stocks": [{"code": "1111"}, {"code": "2222"}]}],
            "unmapped_candidates": [{"code": "3333"}],
        }

        annotate_new_stocks(report, {"1111", "3333"})

        self.assertFalse(report["themes"][0]["stocks"][0]["is_new"])
        self.assertTrue(report["themes"][0]["stocks"][1]["is_new"])
        self.assertFalse(report["unmapped_candidates"][0]["is_new"])

    def test_new_tag_stays_off_without_a_previous_report(self):
        report = {"themes": [{"stocks": [{"code": "1111"}]}], "unmapped_candidates": []}
        annotate_new_stocks(report, None)
        self.assertFalse(report["themes"][0]["stocks"][0]["is_new"])

    def test_stock_cools_for_two_reports_then_exits_on_the_third(self):
        previous = self.lifecycle_report([self.lifecycle_stock()])

        first_miss = apply_market_lifecycle(self.lifecycle_report(), previous)
        first_stock = first_miss["themes"][0]["stocks"][0]
        self.assertEqual(first_stock["miss_streak"], 1)
        self.assertEqual(first_stock["lifecycle_status"], "退潮中")
        self.assertFalse(first_stock["is_active"])
        self.assertIn("退潮中 1/2", "\n".join(telegram_messages(first_miss)))

        second_miss = apply_market_lifecycle(self.lifecycle_report(), first_miss)
        second_stock = second_miss["themes"][0]["stocks"][0]
        self.assertEqual(second_stock["miss_streak"], 2)
        self.assertEqual(second_stock["lifecycle_status"], "即將剔除")

        third_miss = apply_market_lifecycle(self.lifecycle_report(), second_miss)
        self.assertEqual(third_miss["themes"], [])
        self.assertEqual(third_miss["exited_stocks"][0]["code"], "1111")
        self.assertIn("今日正式汰換", "\n".join(telegram_messages(third_miss)))

    def test_tier_change_and_theme_launch_are_annotated(self):
        previous = self.lifecycle_report([self.lifecycle_stock(tier="S")], "Existing Theme")
        current = self.lifecycle_report([self.lifecycle_stock(tier="B")], "Existing Theme")
        result = apply_market_lifecycle(current, previous)
        stock = result["themes"][0]["stocks"][0]
        self.assertEqual(stock["previous_tier"], "S")
        self.assertEqual(stock["tier_change"], "down")

        launch = apply_market_lifecycle(
            self.lifecycle_report([self.lifecycle_stock(code="2222")], "New Theme"),
            previous,
        )
        new_theme = next(theme for theme in launch["themes"] if theme["name"] == "New Theme")
        self.assertEqual(new_theme["lifecycle"], "啟動")


if __name__ == "__main__":
    unittest.main()
