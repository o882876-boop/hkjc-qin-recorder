"""windrop_dbl_v1 tests. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import math
import unittest
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base, double = load("test_recorder"), load("test_double")
rec, M, P1 = base.rec, base.M, base.P1
windrop = rec.windrop

W1 = {"1": 3.0, "2": 4.0, "3": 6.0, "4": 8.0, "5": 12.0, "6": 20.0, "7": 30.0, "8": 50.0}     # race N-1, after the close
W2 = {"1": 3.0, "2": 4.5, "3": 6.0, "4": 8.0, "5": 12.0, "6": 20.0, "7": 30.0, "8": 50.0}     # race N at `first`
IMPLIED = {**W2, "5": 8.0}                                                                    # the Double rates 5 much shorter
AT = "2026-11-18T19:00:00+08:00"


def frozen(bogus_for=()):
    return {f"{a}-{b}": round(W1[a] * IMPLIED[b] * (0.2 if a in bogus_for else 1.0), 2) for a in W1 for b in W2}


def qin_board(favoured=None):
    odds = {}
    for a in range(1, 9):
        for b in range(a + 1, 9):
            price = 0.5 * W2[str(a)] * W2[str(b)]
            if favoured in (str(a), str(b)):
                price *= 0.5
            odds[f"{a}-{b}"] = round(max(price, 1.5), 2)
    return {"observed_at": AT, "target_at": AT, "odds": odds}


def pair(favoured="5", dbl=None):
    prev = {"win_points": {"after_start": {"odds": dict(W1)}}, "dbl": {"last_open": {"odds": dbl or frozen()}}}
    s = {"points": {"t5": qin_board(favoured), "t2": qin_board(favoured)},
         "win_points": {k: {"odds": dict(W2), "observed_at": AT} for k in ("before_rollover", "t5", "t2")}}
    return s, prev


class Model(unittest.TestCase):
    def test_horse_the_double_rates_shorter_than_win_ranks_first(self):
        s, prev = pair()
        pred = windrop.predict_dbl(s, prev, "first")
        self.assertEqual((pred["model"], pred["inputs"]), ("windrop_dbl_v1", ["WIN", "DBL"]))
        row = pred["horses"][0]
        self.assertEqual(row["horse"], "5")
        self.assertAlmostEqual(row["dbl_implied_win_odds"], 8.0, places=1)
        self.assertAlmostEqual(row["edge_pct"], 50.0, places=0)
        self.assertGreater(row["predicted_drop_pct"], 0)
        self.assertLess(row["predicted_close_odds"], row["win_odds"])
        self.assertEqual(pred["both_signals"], [])                       # no Quinella signal at `first`
        c = windrop.DBL_COEFS["first"]
        self.assertAlmostEqual(row["predicted_close_odds"], round(row["win_odds"] * math.exp(-(c["c0"] + c["c1"] * row["score"])), 1), places=1)
        json.dumps(pred)

    def test_t5_and_t2_add_the_quinella_lead_and_flag_horses_with_both_signals(self):
        for point in ("t5", "t2"):
            s, prev = pair("5")
            pred = windrop.predict_dbl(s, prev, point)
            self.assertEqual(pred["inputs"], ["WIN", "DBL", "QIN"])
            self.assertEqual(pred["horses"][0]["horse"], "5")
            self.assertIn("5", pred["both_signals"])
            self.assertEqual(pred["horses"][0]["signals_fired"], 2)
            self.assertGreater(pred["horses"][0]["lead_pct"], 20)
        s, prev = pair("2")                                              # Quinella likes 2, the Double likes 5
        row = {h["horse"]: h for h in windrop.predict_dbl(s, prev, "t2")["horses"]}
        self.assertEqual((row["5"]["signals_fired"], row["2"]["signals_fired"]), (1, 1))

    def test_leg1_horses_above_ten_times_are_ignored(self):
        s, prev = pair()
        clean = windrop.predict_dbl(s, prev, "first")
        s2, prev2 = pair(dbl=frozen(bogus_for=("5", "6", "7", "8")))     # leg-1 horses at 12x or more carry nonsense prices
        noisy = windrop.predict_dbl(s2, prev2, "first")
        self.assertEqual([h["edge_pct"] for h in clean["horses"]], [h["edge_pct"] for h in noisy["horses"]])
        s3, prev3 = pair(dbl=frozen(bogus_for=("1",)))                   # a 3x leg-1 horse does count
        self.assertNotEqual(clean["horses"][0]["edge_pct"], windrop.predict_dbl(s3, prev3, "first")["horses"][-1]["edge_pct"])

    def test_missing_inputs_are_labelled_not_guessed(self):
        s, prev = pair()
        prev["win_points"] = {}
        self.assertEqual(windrop.predict_dbl(s, prev, "first")["error"], "need_leg1_win_after_start_board")
        s, prev = pair()
        prev["dbl"] = {}
        self.assertEqual(windrop.predict_dbl(s, prev, "first")["error"], "need_frozen_double_board")
        s, prev = pair()
        s["win_points"].pop("before_rollover")
        self.assertEqual(windrop.predict_dbl(s, prev, "first")["error"], "need_win_first_board")
        s, prev = pair()
        s["points"].pop("t2")
        self.assertEqual(windrop.predict_dbl(s, prev, "t2")["error"], "need_t2_quinella_board")
        s, prev = pair(dbl={k: v for k, v in frozen().items() if k.endswith(("-1", "-2", "-3"))})
        self.assertEqual(windrop.predict_dbl(s, prev, "first")["error"], "too_few_comparable_horses")

    def test_frozen_double_prefers_last_open_then_t2_then_the_closed_board(self):
        board = lambda v: {"odds": {"1-1": v}}
        d = {"last_open": board(1.5), "points": {"t2": board(2.5)}, "closed_board": board(3.5)}
        self.assertEqual(windrop.dbl_frozen({"dbl": d}), {"1-1": 1.5})
        d.pop("last_open")
        self.assertEqual(windrop.dbl_frozen({"dbl": d}), {"1-1": 2.5})
        d["points"] = {}
        self.assertEqual(windrop.dbl_frozen({"dbl": d}), {"1-1": 3.5})
        self.assertEqual(windrop.dbl_frozen({}), {})

    def test_outcome_works_with_the_shared_checker(self):
        s, prev = pair()
        pred = windrop.predict_dbl(s, prev, "first")
        out = windrop.windrop_outcome(pred, {"after_start": {"odds": {**W2, "5": 9.0}}})
        self.assertIn("5", out["actual_top"])
        self.assertEqual(out["top_n"], 3)


class InRecorder(unittest.TestCase):
    def recorder(self, s, prev):
        recorder = rec.Recorder()
        recorder.state = {1: prev, 2: s}
        return recorder

    def test_waits_for_the_previous_race_then_labels_the_gap(self):
        s, prev = pair()
        prev["win_points"] = {}
        recorder = self.recorder(s, prev)
        seen = rec.stamp(AT)
        self.assertNotIn((2, "first"), recorder.make_windrops_dbl(seen + timedelta(minutes=5)))   # still waiting for race N-1
        self.assertNotIn("windrop_dbl_first", s)
        due = recorder.make_windrops_dbl(seen + timedelta(minutes=11))
        self.assertEqual((2, "first") in due, True)
        self.assertEqual(s["windrop_dbl_first"]["error"], "need_leg1_win_after_start_board")

    def test_predicts_at_once_when_everything_is_there_and_never_for_race_one(self):
        s, prev = pair()
        recorder = self.recorder(s, prev)
        due = recorder.make_windrops_dbl(rec.stamp(AT))
        self.assertEqual(sorted(due), [(2, "first"), (2, "t2"), (2, "t5")])
        self.assertEqual(s["windrop_dbl_first"]["horses"][0]["horse"], "5")
        for point in windrop.DBL_POINTS:
            s[f"windrop_dbl_{point}_published"] = True
        self.assertEqual(recorder.make_windrops_dbl(rec.stamp(AT)), [])
        again = rec.Recorder.load(json.loads(json.dumps(recorder.dump())))
        self.assertEqual(again.make_windrops_dbl(rec.stamp(AT)), [])
        self.assertEqual(again.state[2]["windrop_dbl_t2"], s["windrop_dbl_t2"])


class InMainLoop(unittest.TestCase):
    run_main, setUp, tearDown = base.MainLoop.run_main, base.MainLoop.setUp, base.MainLoop.tearDown
    dbl_source = staticmethod(double.dbl_pools)

    def files(self, prefix):
        return sorted(p for p in base.FakeArchive.files if p.startswith(prefix))

    def test_races_two_and_up_get_first_t5_t2_files_before_the_race_and_repeat_them_in_the_record(self):
        self.run_main(base.card(3), P1 - M(45), "700")
        names = [p.rsplit("/", 1)[1] for p in self.files("predictions/") if "-windrop-dbl-" in p]
        self.assertEqual(names, sorted(f"race-0{i}-windrop-dbl-{pt}-700-1.json" for i in (2, 3) for pt in ("first", "t2", "t5")))
        for i in (2, 3):
            for point in ("first", "t5", "t2"):
                body = json.loads(base.FakeArchive.files[f"predictions/2026-11-11_HV/race-0{i}-windrop-dbl-{point}-700-1.json"])
                self.assertEqual((body["kind"], body["prediction"]["model"], body["race"]), ("windrop_dbl", "windrop_dbl_v1", i))
                self.assertNotIn("error", body["prediction"])
                self.assertLess(rec.stamp(body["written_at"]), rec.stamp(body["post_time"]), "available before the race")
                record = json.loads(base.FakeArchive.files[f"qin-history/2026-11-11_HV/race-0{i}-700-1.json"])
                self.assertEqual(record["windrop_dbl"][point], body["prediction"])
                self.assertIn("windrop_dbl_outcome", record)
        record1 = json.loads(base.FakeArchive.files["qin-history/2026-11-11_HV/race-01-700-1.json"])
        self.assertEqual(set(record1["windrop_dbl"].values()), {None})

    def test_a_windrop_dbl_bug_never_blocks_the_other_records(self):
        saved = windrop.predict_dbl
        windrop.predict_dbl = lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("boom"))
        try:
            self.run_main(base.card(3), P1 - M(45), "701")
        finally:
            windrop.predict_dbl = saved
        self.assertEqual(len(self.files("qin-history/")), 3)
        self.assertEqual(len(self.files("dbl-history/")), 2)
        body = json.loads(base.FakeArchive.files[next(p for p in self.files("predictions/") if "-windrop-dbl-" in p)])
        self.assertEqual(body["prediction"]["error"], "ZeroDivisionError")
        self.assertEqual(len([p for p in self.files("predictions/") if "-windrop-" in p and "-windrop-dbl-" not in p]), 9)


if __name__ == "__main__":
    unittest.main()
