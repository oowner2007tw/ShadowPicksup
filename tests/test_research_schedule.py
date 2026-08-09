import unittest
from datetime import date, timedelta

from research_product_mapping import REVIEW_INTERVAL_DAYS, is_current, research_targets


class ResearchScheduleTests(unittest.TestCase):
    def test_review_interval_is_45_days(self):
        self.assertEqual(REVIEW_INTERVAL_DAYS, 45)

    def test_review_expires_after_45_days(self):
        source_urls = ["https://example.com/company-source"]
        reviewed_45_days_ago = {
            "source_urls": source_urls,
            "reviewed_at": (date.today() - timedelta(days=45)).isoformat(),
        }
        reviewed_46_days_ago = {
            "source_urls": source_urls,
            "reviewed_at": (date.today() - timedelta(days=46)).isoformat(),
        }

        self.assertTrue(is_current(reviewed_45_days_ago))
        self.assertFalse(is_current(reviewed_46_days_ago))

    def test_cooling_candidates_are_not_researched(self):
        report = {
            "unmapped_candidates": [
                {"code": "9998", "name": "Active", "tier": "B", "signal_score": 2.0, "is_active": True},
                {"code": "9999", "name": "Cooling", "tier": "A", "signal_score": 3.0, "is_active": False},
            ]
        }
        codes = {target["code"] for target in research_targets(report, {"entries": {}}, False)}
        self.assertIn("9998", codes)
        self.assertNotIn("9999", codes)


if __name__ == "__main__":
    unittest.main()
