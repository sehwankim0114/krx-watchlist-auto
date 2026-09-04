"""Unit/regression tests for the isolated V8.5.0 preview, standard library only."""
import copy
import csv
import json
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_table_metrics_v850 import (CONTRACT, atr_wilder, current_streak, direction_runs,
    indicators, ma_info, matches_decliners24, normalize_bars, number, period_return, shift_months)
from build_stock_table_preview_v850 import COMPACT_COLUMNS, build, compact_row, ticker


def sample(values):
    result, d = [], date(2026, 1, 2)
    for v in values:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        result.append({"date":d.isoformat(),"close":v,"high":v+2,"low":v-2,"volume":100,"trading_value":100*v})
        d += timedelta(days=1)
    return result


def measure(bars, full=None):
    full = full or bars
    sessions = [b["date"] for b in full]
    return indicators(bars, full[-1]["date"], sessions, full)


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.bars = sample([100+i*.5 for i in range(150)])

    def test_non_finite_numbers_missing(self):
        for x in (True, None, "", "nan", "inf", "-inf", "bad"):
            self.assertIsNone(number(x))
        self.assertEqual(number("1,234"),1234)

    def test_exact_ticker(self):
        self.assertEqual(ticker("5930"),"005930")
        for value in ("a005930", "1005930", "005930.KS", "5930.0", ""):
            with self.assertRaises(ValueError): ticker(value)

    def test_month_end_and_leap_year(self):
        self.assertEqual(shift_months("2026-03-31",1),"2026-02-28")
        self.assertEqual(shift_months("2024-03-31",1),"2024-02-29")
        self.assertEqual(shift_months("2026-01-31",3),"2025-10-31")

    def test_finite_close_required(self):
        for bad in (0,-1,"nan",None):
            b=copy.deepcopy(self.bars); b[-1]["close"]=bad
            with self.assertRaises(ValueError): normalize_bars(b,b[-1]["date"])

    def test_future_bars_excluded(self):
        b=copy.deepcopy(self.bars)
        b.append({"date":"2099-01-01","close":99999})
        self.assertEqual(measure(self.bars),indicators(b,self.bars[-1]["date"],[r["date"] for r in self.bars],self.bars))

    def test_conflicting_duplicate_rejected(self):
        b=copy.deepcopy(self.bars); duplicate=dict(b[-1]); duplicate["close"]+=1; b.append(duplicate)
        with self.assertRaises(ValueError): normalize_bars(b,self.bars[-1]["date"])

    def test_identical_duplicate_deduplicated(self):
        self.assertEqual(len(normalize_bars(self.bars+[self.bars[-1]],self.bars[-1]["date"])),150)

    def test_input_order_does_not_change_metrics(self):
        self.assertEqual(measure(self.bars),measure(list(reversed(self.bars)),self.bars))

    def test_gap_not_silently_compressed(self):
        self.assertEqual(measure(self.bars[:50]+self.bars[51:],self.bars)["status"],"HISTORY_SESSION_GAPS")

    def test_missing_last_date_not_current(self):
        self.assertEqual(measure(self.bars[:-1],self.bars)["status"],"LATEST_OFFICIAL_BAR_MISSING")

    def test_non_market_date_not_added(self):
        b=self.bars+[{"date":"2026-01-03","close":100,"high":102,"low":98}]
        self.assertEqual(measure(b,self.bars)["status"],"NON_MARKET_SESSION_BAR")

    def test_mean_runs_legacy_flat_policy(self):
        r=direction_runs([10,11,11,12,11,10,10,11])
        self.assertAlmostEqual(r["average"],7/3)
        self.assertEqual(r["up_average"],2)
        self.assertEqual(r["down_average"],3)

    def test_streak_flat_stops(self):
        self.assertEqual(current_streak([10,9,9])["days"],0)
        self.assertEqual(current_streak([10,9,9,8])["days"],1)

    def test_streak_counts_changes_not_prices(self):
        r=current_streak([100,95,90])
        self.assertEqual(r["days"],2)
        self.assertEqual(r["direction"],-1)
        self.assertEqual(r["change_pct"],-10)

    def test_no_zero_mean_for_all_flat(self):
        self.assertIsNone(direction_runs([100]*61)["average"])

    def test_short_history_not_ma120(self):
        r=measure(self.bars[-60:],self.bars)
        self.assertIsNone(r["ma"]["120"]["direction"])
        self.assertIsNone(r["run"]["average"])
        self.assertIsNone(r["returns"]["3"]["pct"])
        self.assertFalse(r["matches_decliners_24"])

    def test_ma_slope_needs_five_more_bars(self):
        r=ma_info([100]*120,120)
        self.assertEqual(r["value"],100)
        self.assertIsNone(r["direction"])
        self.assertEqual(ma_info([100]*125,120)["direction"],0)

    def test_ma_120_reference_mean(self):
        closes=[b["close"] for b in self.bars]
        self.assertEqual(ma_info(closes,120)["value"],sum(closes[-120:])/120)
        self.assertEqual(ma_info(closes,120)["direction"],1)

    def test_atr_constant_range(self):
        self.assertEqual(atr_wilder(sample([100]*40)),4)

    def test_atr_includes_gap_and_wilder_smoothing(self):
        b=sample([100]*15+[120])
        self.assertAlmostEqual(atr_wilder(b),(4*13+22)/14)

    def test_atr_short_and_invalid_ohlc(self):
        self.assertIsNone(atr_wilder(sample([100]*14)))
        b=normalize_bars(self.bars,self.bars[-1]["date"]); b[-1]["high"]=None
        self.assertIsNone(atr_wilder(b))

    def test_invalid_ohlc_does_not_fabricate_atr(self):
        b=copy.deepcopy(self.bars); b[-1]["low"]=0
        r=measure(b,self.bars)
        self.assertEqual(r["status"],"OK")
        self.assertIsNone(r["atr14"]["krw"])
        self.assertIsNone(r["range_3m"]["low"])

    def test_calendar_return_exact_anchor(self):
        sessions=[b["date"] for b in self.bars]
        r=period_return(self.bars,sessions[-1],1,sessions)
        lookup={b["date"]:b["close"] for b in self.bars}
        self.assertAlmostEqual(r["pct"],100*(lookup[sessions[-1]]/lookup[r["start_date"]]-1),places=3)

    def test_same_series_rs_zero(self):
        self.assertEqual(measure(self.bars)["rs_kospi_pp"],{"1":0.,"3":0.})

    def test_missing_fundamentals_remain_missing(self):
        r=measure(self.bars)
        self.assertIsNone(r["investment_score_100"])
        self.assertIsNone(r["earnings_outlook_change"])
        self.assertEqual(r["rs_sector_pp"],{"1":None,"3":None})

    def test_new_low_excluded(self):
        r=measure(sample([250-i for i in range(150)]))
        self.assertEqual(r["swing"]["phase"],"NEW_LOW")
        self.assertFalse(r["matches_decliners_24"])

    def test_low_price_position_is_not_automatic_rebound(self):
        r=measure(sample([200-i*.5 for i in range(150)]))
        self.assertFalse(r["swing"]["bottom_rebound"])

    def test_24_exact_boundaries_and_phase(self):
        base={"run":{"average":2.5},"streak":{"direction":-1,"days":3},
              "swing":{"phase":"BOTTOM_REBOUND","bottom_rebound":True,"new_20d_low":False}}
        self.assertTrue(matches_decliners24(base))
        for avg,expected in ((1.99,False),(2,True),(3.999,True),(4,False),(None,False)):
            b=copy.deepcopy(base); b["run"]["average"]=avg
            self.assertEqual(matches_decliners24(b),expected)
        for days in (0,1,5,None):
            b=copy.deepcopy(base); b["streak"]["days"]=days; self.assertFalse(matches_decliners24(b))
        for phase in ("TOP_DECLINE","UPTREND_PULLBACK","EARLY_REBOUND_UNCONFIRMED"):
            b=copy.deepcopy(base); b["swing"]["phase"]=phase; self.assertFalse(matches_decliners24(b))
        b=copy.deepcopy(base); b["swing"]["new_20d_low"]=True; self.assertFalse(matches_decliners24(b))

    def test_standalone_swing_deferred(self):
        self.assertFalse(CONTRACT["standalone_swing_table_enabled"])
        self.assertEqual(CONTRACT["release_stage"],"PREVIEW_ONLY")

    def test_compact_retains_identity_and_metrics(self):
        m=measure(self.bars)
        r={"name":"TEST","ticker":"005930","metrics":m,"analysis":{},"sector_theme":None}
        compact=compact_row(r)
        self.assertEqual(len(compact),len(COMPACT_COLUMNS))
        out=dict(zip(COMPACT_COLUMNS,compact))
        self.assertEqual(out["ticker"],"005930")
        self.assertEqual(out["ma"][3],[m["ma"]["120"]["value"],m["ma"]["120"]["direction"]])
        self.assertEqual(out["atr14"][0],m["atr14"]["krw"])

    def test_builder_cannot_write_inside_repo(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaisesRegex(ValueError,"OUTSIDE_REPOSITORY"):
                build(root,root/"api")

    def test_builder_cannot_overwrite_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"repo"; root.mkdir()
            existing=Path(d)/"existing"; existing.mkdir()
            with self.assertRaisesRegex(ValueError,"NEW_DIRECTORY"):
                build(root,existing)


class BuilderIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.repo=Path(cls.temp.name)/"repo"
        (cls.repo/"api").mkdir(parents=True)
        (cls.repo/"latest").mkdir()
        bars=sample([100+i*.5 for i in range(150)])
        cls.basis=bars[-1]["date"]
        cls.status={"status":"STALE_OFFICIAL","api_sync_ok":True,"critical_errors":[],
            "official_fresh_now":False,"safe_to_analyze_as_latest":False,"build_id":"fixture-build",
            "confirmed_basis_date":cls.basis,"computed_expected_official_trading_date":"2027-01-01",
            "rules_version":"fixture-v1","rules_sha256":"fixture-hash"}
        cls.kospi={"status":"OK","row_count":30,"build_id":"fixture-build","rules_version":"fixture-v1",
            "rules_sha256":"fixture-hash","rows":[{"code":f"{i:06}","analysis_date":cls.basis} for i in range(1,31)]}
        cls.restore()
        def csvfile(name,fields,rows):
            with (cls.repo/"latest"/name).open("w",encoding="utf-8",newline="") as f:
                w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
        csvfile("universe_raw_history_latest.csv",["date","close","high","low","volume","trading_value","market","ticker"],
                [dict(b,market="KOSPI",ticker=f"{i:06}") for i in range(1,31) for b in bars])
        csvfile("kospi_universe_summary_latest.csv",["market","ticker","name","last_date"],
                [{"market":"KOSPI","ticker":f"{i:06}","name":f"STOCK{i}","last_date":cls.basis} for i in range(1,801)])
        csvfile("official_index_history_latest.csv",["market","date","official_index_close"],
                [{"market":"KOSPI","date":b["date"],"official_index_close":b["close"]} for b in bars])
        for cmd in (["git","init","--quiet"],["git","config","user.name","Preview Test"],
            ["git","config","user.email","preview@example.invalid"],["git","add","."],
            ["git","commit","--quiet","-m","Temporary fixture"]):
            subprocess.run(cmd,cwd=cls.repo,check=True,capture_output=True)

    @classmethod
    def restore(cls):
        (cls.repo/"api/status.json").write_text(json.dumps(cls.status),encoding="utf-8")
        (cls.repo/"api/kospi_watchlist.json").write_text(json.dumps(cls.kospi),encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def tearDown(self):
        self.restore()

    def output(self):
        return Path(self.temp.name)/self.id().split(".")[-1]

    def test_stale_preview_never_allows_production(self):
        report=build(self.repo,self.output())
        self.assertFalse(report["source_official_fresh_now"])
        self.assertFalse(report["production_activation_allowed"])
        self.assertTrue(report["source_files_unchanged"])
        self.assertEqual(report["kospi_rows"],30)
        self.assertEqual(report["decliners_rows"],0)
        p=json.loads((self.output()/"kospi.json").read_text())
        self.assertTrue(all(r["request_time_price"] is None for r in p["rows"]))
        pages=list(self.output().glob("*.compact.*.json"))
        self.assertTrue(all(p.stat().st_size<=30000 for p in pages))

    def test_fresh_preview_also_requires_explicit_activation(self):
        s={**self.status,"status":"READY","official_fresh_now":True,"safe_to_analyze_as_latest":True}
        (self.repo/"api/status.json").write_text(json.dumps(s))
        self.assertFalse(build(self.repo,self.output())["production_activation_allowed"])

    def test_build_mismatch_rejected(self):
        p={**self.kospi,"build_id":"wrong"}; (self.repo/"api/kospi_watchlist.json").write_text(json.dumps(p))
        with self.assertRaisesRegex(ValueError,"BUILD_ID_MISMATCH"): build(self.repo,self.output())

    def test_rule_mismatch_rejected(self):
        p={**self.kospi,"rules_sha256":"wrong"}; (self.repo/"api/kospi_watchlist.json").write_text(json.dumps(p))
        with self.assertRaisesRegex(ValueError,"RULES_MISMATCH"): build(self.repo,self.output())

    def test_api_sync_failure_rejected(self):
        p={**self.status,"api_sync_ok":False}; (self.repo/"api/status.json").write_text(json.dumps(p))
        with self.assertRaisesRegex(ValueError,"NOT_SYNCHRONIZED"): build(self.repo,self.output())

    def test_selected_date_mismatch_rejected(self):
        p=copy.deepcopy(self.kospi); p["rows"][0]["analysis_date"]="2099-01-01"
        (self.repo/"api/kospi_watchlist.json").write_text(json.dumps(p))
        with self.assertRaisesRegex(ValueError,"ANALYSIS_DATE_MISMATCH"): build(self.repo,self.output())

    def test_duplicate_selected_ticker_rejected(self):
        p=copy.deepcopy(self.kospi); p["rows"][1]["code"]=p["rows"][0]["code"]
        (self.repo/"api/kospi_watchlist.json").write_text(json.dumps(p))
        with self.assertRaisesRegex(ValueError,"DUPLICATE_KOSPI_TICKERS"): build(self.repo,self.output())

    def test_selected_30_contract(self):
        p=copy.deepcopy(self.kospi); p["rows"].pop()
        (self.repo/"api/kospi_watchlist.json").write_text(json.dumps(p))
        with self.assertRaisesRegex(ValueError,"EXACTLY_30_ROWS"): build(self.repo,self.output())


if __name__ == "__main__":
    unittest.main(verbosity=2)
