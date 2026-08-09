import unittest

from analyze_twse_momentum import (
    THEME_MAPPING,
    canonicalize_theme,
    review_theme_mapping,
)


class ThemeTaxonomyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
