"""Scorecard and backtest script tests. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base, double = load(HERE / "test_recorder.py", "test_recorder_r"), load(HERE / "test_double.py", "test_double_r")
report = load(ROOT / "research" / "windrop" / "report.py", "windrop_report")
backtest = load(ROOT / "research" / "windrop" / "backtest.py", "windrop_backtest")
rec, M, P1 = base.rec, base.M, base.P1


class Scorecard(unittest.TestCase):
    run_main, setUp, tearDown = base.MainLoop.run_main, base.MainLoop.setUp, base.MainLoop.tearDown
    dbl_source = staticmethod(double.dbl_pools)

    def records(self):
        return [json.loads(v) for k, v in sorted(base.FakeArchive.files.items()) if k.startswith("qin-history/")]

    def test_scorecard_adds_up_what_the_race_records_say(self):
        self.run_main(base.card(3), P1 - M(45), "800")
        records = self.records()
        totals, expected, longshot = report.aggregate(records)
        self.assertEqual(totals[("windrop", "t2")]["races"], 3)
        self.assertEqual(totals[("windrop_dbl", "first")]["races"], 2)          # race 1 has no Double edge
        self.assertEqual(totals[("windrop_combined", "t5")]["races"], 2)
        for (key, point), t in totals.items():
            self.assertGreaterEqual(t["flagged_n"], t["flagged_fell_any"])
            self.assertGreaterEqual(t["flagged_fell_any"], t["flagged_fell_10pct"])
            self.assertGreater(t["horses"], 0)
        text = report.render(records)
        self.assertIn("| Quinella (windrop_v1) | t2 | 3 |", text)
        self.assertIn("| Double (windrop_dbl_v1) | first | 2 |", text)
        self.assertIn("validated", text)

    def test_predictions_without_an_outcome_or_with_errors_are_left_out(self):
        self.run_main(base.card(3), P1 - M(45), "801")
        records = self.records()
        records[0]["windrop_outcome"]["t2"] = {"missing": "no_after_start"}
        records[1]["windrop"]["t2"] = {"model": "windrop_v1", "at_point": "t2", "error": "need_t2_quinella_board"}
        totals, _, _ = report.aggregate(records)
        self.assertEqual(totals[("windrop", "t2")]["races"], 1)


class BacktestScript(unittest.TestCase):
    def test_feature_helpers_and_logistic_fit(self):
        self.assertAlmostEqual(float(backtest.z([1, 2, 3]).mean()), 0.0)
        self.assertEqual(list(backtest.z([5, 5, 5])), [0.0, 0.0, 0.0])
        self.assertAlmostEqual(backtest.rank_corr([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        import numpy as np
        a = backtest.fit_logistic(np.array([-2., -1, 0, 1, 2, 3]), np.array([0., 0, 0, 1, 1, 1]))
        self.assertGreater(a[1], 0)
        self.assertLess(1 / (1 + np.exp(-(a[0] + a[1] * -2))), 0.5)

    def test_loader_reads_a_checkout_in_the_odds_data_layout(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "qin-history" / "2026-11-11_HV"
            day.mkdir(parents=True)
            self.assertEqual(backtest.load_races(tmp), [])                        # nothing recorded: no races, no crash


if __name__ == "__main__":
    unittest.main()
