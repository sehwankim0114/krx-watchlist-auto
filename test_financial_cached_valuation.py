"""Regression checks for repricing cached financial reports."""
import unittest

from financial_valuation_enricher import refresh_cached_valuation


class CachedValuationTests(unittest.TestCase):
    def setUp(self):
        self.cached = {
            "ticker": "000100",
            "financial_report_code": "11011",
            "financial_basis": "2025 사업보고서",
            "financial_data_status": "READY",
            "net_income": "100",
            "total_equity": "500",
            "revenue": "900",
            "operating_profit": "120",
            "total_liabilities": "400",
            "previous_revenue": "800",
            "previous_operating_profit": "110",
            "previous_net_income": "80",
            "market_cap": "700",
            "listed_shares": "100",
            "valuation_price_basis_date": "2026-09-18",
            "per_annualized": "7",
            "pbr": "1.4",
            "fetched_at_kst": "2026-10-01T10:00:00+09:00",
        }

    def test_cached_report_is_repriced_without_changing_financial_period(self):
        result = refresh_cached_valuation(self.cached, {
            "market_cap": 1000.0,
            "listed_shares": 100.0,
            "price_basis_date": "2026-10-16",
        })
        self.assertEqual(result["valuation_price_basis_date"], "2026-10-16")
        self.assertEqual(result["market_cap"], 1000)
        self.assertEqual(result["per_annualized"], 10)
        self.assertEqual(result["pbr"], 2)
        self.assertEqual(result["valuation_data_status"], "READY")
        self.assertEqual(result["financial_basis"], "2025 사업보고서")
        self.assertEqual(result["fetched_at_kst"], self.cached["fetched_at_kst"])
        self.assertEqual(self.cached["valuation_price_basis_date"], "2026-09-18")

    def test_missing_current_market_data_clears_stale_valuation(self):
        result = refresh_cached_valuation(self.cached, {})
        self.assertEqual(result["valuation_price_basis_date"], "")
        self.assertEqual(result["per_annualized"], "")
        self.assertEqual(result["pbr"], "")
        self.assertEqual(result["valuation_data_status"], "LIMITED_NO_MARKET_CAP")


if __name__ == "__main__":
    unittest.main()
