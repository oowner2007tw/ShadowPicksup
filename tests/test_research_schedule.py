import unittest
from datetime import date, timedelta

from research_product_mapping import REVIEW_INTERVAL_DAYS, is_current


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


if __name__ == "__main__":
    unittest.main()
