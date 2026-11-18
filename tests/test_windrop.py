"""windrop_v1 tests. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import math
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("base", Path(__file__).resolve().parent / "test_recorder.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
rec, M, P1 = base.rec, base.M, base.P1
windrop = rec.windrop

HORSES = [str(i) for i in range(1, 9)]
WIN = {"1": 3.0, "2": 4.0, "3": 6.0, "4": 8.0, "5": 12.0, "6": 20.0, "7": 30.0, "8": 50.0}


def qin_board(favoured=None, boost=0.5):
    """Quinella board consistent with the WIN prices; `favoured` combinations are priced shorter by `boost`."""
    odds = {}
    for a in range(1, 9):
        for b in range(a + 1, 9):
            price = 0.5 * WIN[str(a)] * WIN[str(b)]
            if favoured in (str(a), str(b)):
                price *= boost
            odds[f"{a}-{b}"] = round(max(price, 1.5), 2)
    return {"observed_at": "2026-11-11T18:37:00+08:00", "odds": odds}


def state(favoured="5", point="t3", win_t5=None):
    win = {"odds": dict(WIN), "observed_at": "x"}
    return {"points": {point: qin_board(favoured)},
            "win_points": {point: win, "t5": {"odds": win_t5 or dict(WIN), "observed_at": "x"}}}


class Model(unittest.TestCase):
    def test_horse_the_quinella_likes_more_than_win_ranks_first_and_is_predicted_to_shorten(self):
        pred = windrop.predict_windrop(state("5"), "t3")
        self.assertEqual(pred["model"], "windrop_v1")
        self.assertEqual(pred["horses"][0]["horse"], "5")
        self.assertGreater(pred["horses"][0]["lead_pct"], 20)
        self.assertGreater(pred["horses"][0]["predicted_drop_pct"], 0)
        self.assertLess(pred["horses"][0]["predicted_close_odds"], pred["horses"][0]["win_odds"])
        self.assertEqual(pred["top"], [h["horse"] for h in pred["horses"][:3]])
        self.assertEqual([h["rank"] for h in pred["horses"]], list(range(1, 9)))
        json.dumps(pred)

    def test_prediction_matches_the_documented_formula(self):
        pred = windrop.predict_windrop(state("5"), "t3")
        c = windrop.COEFS["t3"]
        row = pred["horses"][0]
        self.assertAlmostEqual(row["predicted_close_odds"], round(row["win_odds"] * math.exp(-(c["c0"] + c["c1"] * row["score"])), 1), places=1)

    def test_t5_needs_no_earlier_board_and_t3_t2_use_the_win_move_since_t5(self):
        s = state("5", "t5")
        pred = windrop.predict_windrop(s, "t5")
        self.assertIsNone(pred["horses"][0]["win_move_pct_t5_to_now"])
        s = state("5", "t2", win_t5={**WIN, "8": 60.0})            # 8 has shortened 60 -> 50 since t5
        row = next(h for h in windrop.predict_windrop(s, "t2")["horses"] if h["horse"] == "8")
        self.assertAlmostEqual(row["win_move_pct_t5_to_now"], 100 * (60 - 50) / 60, places=1)

    def test_missing_boards_are_labelled_not_guessed(self):
        self.assertEqual(windrop.predict_windrop({"points": {}}, "t2")["error"], "need_t2_quinella_board")
        s = state("5")
        s["win_points"] = {}
        self.assertEqual(windrop.predict_windrop(s, "t3")["error"], "need_win_t3_and_t5_board")
        s = state("5")
        s["points"]["t3"]["odds"] = {k: v for k, v in s["points"]["t3"]["odds"].items() if k in ("1-2", "1-3", "2-3")}
        self.assertEqual(windrop.predict_windrop(s, "t3")["error"], "too_few_comparable_horses")

    def test_capped_or_unit_prices_are_not_weights_and_missing_horses_are_skipped(self):
        s = state("5")
        s["points"]["t3"]["odds"]["1-2"] = 1.0
        s["win_points"]["t3"]["odds"].pop("8")
        pred = windrop.predict_windrop(s, "t3")
        self.assertNotIn("8", [h["horse"] for h in pred["horses"]])
        self.assertEqual(windrop.qin_shares({"1-2": 1.0, "1-3": 11.0, "2-3": None}), {"1": 0.5, "3": 0.5})

    def test_outcome_compares_predicted_and_actual_close(self):
        s = state("5")
        pred = windrop.predict_windrop(s, "t3")
        final = {**WIN, "5": 9.0}                                    # 12 -> 9: 5 really shortened by 25%
        out = windrop.windrop_outcome(pred, {"after_start": {"odds": final}})
        self.assertIn("5", out["actual_top"])
        self.assertGreaterEqual(out["top_hits"], 1)
        self.assertEqual(out["top_n"], 3)
        self.assertEqual(next(r for r in out["horses"] if r["horse"] == "5")["actual_drop_pct"], 25.0)
        self.assertEqual(windrop.windrop_outcome(pred, {}), {"missing": "no_after_start"})
        self.assertIsNone(windrop.windrop_outcome(None, {}))
        json.dumps(out)


class WindropInMainLoop(unittest.TestCase):
    run_main, setUp, tearDown = base.MainLoop.run_main, base.MainLoop.setUp, base.MainLoop.tearDown
    dbl_source = staticmethod(lambda races, t: [])

    def files(self, prefix):
        return sorted(p for p in base.FakeArchive.files if p.startswith(prefix))

    def test_each_race_gets_t5_t3_t2_windrop_files_before_the_race_and_repeats_them_in_its_record(self):
        self.run_main(base.card(3), P1 - M(45), "600")
        names = [p.rsplit("/", 1)[1] for p in self.files("predictions/") if "-windrop-" in p and "-windrop-dbl-" not in p]
        self.assertEqual(names, sorted(f"race-0{i}-windrop-{pt}-600-1.json" for i in (1, 2, 3) for pt in ("t2", "t3", "t5")))
        for point, early, late in (("t5", 6, 4), ("t3", 4, 2), ("t2", 3, 1)):
            for i in (1, 2, 3):
                path = f"predictions/2026-11-11_HV/race-0{i}-windrop-{point}-600-1.json"
                body = json.loads(base.FakeArchive.files[path])
                self.assertEqual((body["kind"], body["point"], body["prediction"]["model"]), ("windrop", point, "windrop_v1"))
                self.assertNotIn("error", body["prediction"])
                self.assertGreaterEqual(len(body["prediction"]["horses"]), 6)
                written, post = rec.stamp(body["written_at"]), rec.stamp(body["post_time"])
                self.assertLess(written, post, "available before the race, not after")
                self.assertGreaterEqual(written, post - M(early))
                self.assertLessEqual(written, post - M(late) + M(1))
                record = json.loads(base.FakeArchive.files[f"qin-history/2026-11-11_HV/race-0{i}-600-1.json"])
                self.assertEqual(record["windrop"][point], body["prediction"])
                self.assertIn(record["windrop_outcome"][point].get("top_hits", "missing"), range(0, 4) if "top_hits" in record["windrop_outcome"][point] else ["missing"])

    def test_a_windrop_bug_never_blocks_the_quinella_or_the_other_predictions(self):
        saved = windrop.predict_windrop
        windrop.predict_windrop = lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("boom"))
        try:
            self.run_main(base.card(3), P1 - M(45), "601")
        finally:
            windrop.predict_windrop = saved
        self.assertEqual(len(self.files("qin-history/")), 3)
        body = json.loads(base.FakeArchive.files[next(p for p in self.files("predictions/") if "-windrop-" in p and "-windrop-dbl-" not in p)])
        self.assertEqual(body["prediction"]["error"], "ZeroDivisionError")
        self.assertEqual(len([p for p in self.files("predictions/") if "-windrop-" not in p]), 6)
        for path in self.files("qin-history/"):
            record = json.loads(base.FakeArchive.files[path])
            self.assertTrue(all(record["points"][k] for k in ("t5", "t3", "t2", "after_start")))

    def test_windrop_state_survives_a_hand_over_without_being_rewritten(self):
        recorder = rec.Recorder()
        t = P1 - M(45)
        races = base.card(2)
        while t <= P1 - M(1):
            meeting, pools = base.meeting_at(races, t)
            recorder.observe(meeting, pools, t)
            t += base.timedelta(seconds=8)
        due = recorder.make_windrops(t)
        self.assertEqual(sorted(due), [(1, "t2"), (1, "t3"), (1, "t5")])
        for point in windrop.POINTS:
            recorder.state[1][f"windrop_{point}_published"] = True
        again = rec.Recorder.load(json.loads(json.dumps(recorder.dump())))
        self.assertEqual(again.make_windrops(t), [])
        self.assertEqual(again.state[1]["windrop_t2"], recorder.state[1]["windrop_t2"])


if __name__ == "__main__":
    unittest.main()
