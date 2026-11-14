"""t2 prediction tests. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("base", Path(__file__).resolve().parent / "test_recorder.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
rec, M, P1, DAY = base.rec, base.M, base.P1, base.DAY

HORSES = [str(i) for i in range(1, 9)]


def board(drop_by_horse, start=10.0):
    """A Quinella board whose price for a pair shortens by the mean of its horses' drops."""
    return {"observed_at": "x", "odds": {f"{a}-{b}": round(start * (1 - (drop_by_horse[str(a)] + drop_by_horse[str(b)]) / 200), 4)
                                         for a in range(1, 9) for b in range(a + 1, 9)}}


def win(drop_by_horse, start=5.0):
    return {"observed_at": "x", "odds": {h: round(start * (1 - drop_by_horse[h] / 100), 4) for h in HORSES}}


def state(early, late, after=None):
    flat = {h: 0.0 for h in HORSES}
    pts = {"t5": board(flat), "t2": board(early), "after_start": board(after or flat) if after else None}
    pts["t2"]["observed_at"] = pts["t2"]["target_at"] = "2026-11-11T18:38:00+08:00"
    pts["after_start"] = None if after is None else board({h: early[h] + (after[h] if after else 0) for h in HORSES})
    wpts = {"t5": win(flat), "t2": win(early)}
    return {"points": pts, "win_points": wpts}


class Prediction(unittest.TestCase):
    EARLY = {"1": 30, "2": 25, "3": 10, "4": 0, "5": 0, "6": -5, "7": -10, "8": 15}

    def test_horses_that_shortened_most_before_t2_rank_first(self):
        pred = rec.predict_t2(state(self.EARLY, None))
        self.assertEqual(pred["model"], "momentum_v1")
        self.assertEqual(pred["top"], ["1", "2", "8"])
        self.assertEqual([h["horse"] for h in pred["horses"]][:3], ["1", "2", "8"])
        self.assertEqual(pred["inputs"], ["QIN", "WIN"])
        self.assertEqual(pred["reference_point"], "t5")
        self.assertEqual(pred["horses"][0]["win_odds_t2"], win(self.EARLY)["odds"]["1"])
        json.dumps(pred)

    def test_quinella_alone_is_used_when_win_is_missing(self):
        s = state(self.EARLY, None)
        s["win_points"] = {}
        pred = rec.predict_t2(s, use_win=False)
        self.assertEqual(pred["inputs"], ["QIN"])
        self.assertEqual(pred["top"], ["1", "2", "8"])

    def test_not_enough_data_is_labelled_not_guessed(self):
        self.assertEqual(rec.predict_t2({"points": {"t2": {"odds": {}}}})["error"], "need_t2_and_an_earlier_board")
        s = state(self.EARLY, None)
        s["points"]["t2"]["odds"] = {k: v for k, v in s["points"]["t2"]["odds"].items() if k.startswith("1-")}
        self.assertEqual(rec.predict_t2(s)["error"], "too_few_comparable_horses")

    def test_outcome_counts_hits_against_what_really_happened(self):
        later = {"1": 20, "2": 18, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0, "8": 12}   # keeps shortening, same order
        s = state(self.EARLY, later, after=later)
        pred = rec.predict_t2(s)
        out = rec.predict_outcome(pred, s["points"], s["win_points"] | {"after_start": win({h: self.EARLY[h] + later[h] for h in HORSES})})
        self.assertEqual(out["qin_top_hits"], 3)
        self.assertEqual(set(out["qin_actual_top"]), {"1", "2", "8"})
        self.assertAlmostEqual(out["qin_chance_hits"], 9 / 8, places=2)
        self.assertEqual(rec.predict_outcome(pred, {"t2": s["points"]["t2"]}, {}), {"missing": "no_after_start"})
        self.assertIsNone(rec.predict_outcome(None, s["points"], {}))


class PredictionInMainLoop(unittest.TestCase):
    run_main, setUp, tearDown = base.MainLoop.run_main, base.MainLoop.setUp, base.MainLoop.tearDown
    dbl_source = staticmethod(lambda races, t: [])

    def files(self, prefix):
        return sorted(p for p in base.FakeArchive.files if p.startswith(prefix))

    def test_each_race_gets_one_prediction_file_written_at_t2_and_repeated_in_its_record(self):
        self.run_main(base.card(3), P1 - M(45), "500")
        paths = self.files("predictions/")
        self.assertEqual([p.rsplit("/", 1)[1] for p in paths], [f"race-0{i}-500-1.json" for i in (1, 2, 3)])
        for path in paths:
            body = json.loads(base.FakeArchive.files[path])
            self.assertEqual(body["prediction"]["model"], "momentum_v1")
            self.assertEqual(len(body["prediction"]["top"]), 3)
            record = json.loads(base.FakeArchive.files[path.replace("predictions/", "qin-history/")])
            self.assertEqual(record["t2_prediction"], body["prediction"])
            self.assertIn("qin_top_hits", record["t2_prediction_outcome"])
            written = rec.stamp(body["written_at"]); post = rec.stamp(body["post_time"])
            self.assertLess(written, post, "available before the race, not after")
            self.assertGreaterEqual(written, post - M(2))

    def test_a_prediction_bug_never_blocks_the_quinella_records(self):
        saved = rec.predict_t2
        rec.predict_t2 = lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("boom"))
        try:
            self.run_main(base.card(3), P1 - M(45), "501")
        finally:
            rec.predict_t2 = saved
        self.assertEqual(len(self.files("qin-history/")), 3)
        body = json.loads(base.FakeArchive.files[self.files("predictions/")[0]])
        self.assertEqual(body["prediction"]["error"], "ZeroDivisionError")
        for path in self.files("qin-history/"):
            record = json.loads(base.FakeArchive.files[path])
            self.assertTrue(all(record["points"][k] for k in ("t5", "t3", "t2", "after_start")))

    def test_prediction_state_survives_a_hand_over_without_being_rewritten(self):
        recorder = rec.Recorder()
        t = P1 - M(45)
        races = base.card(2)
        while t <= P1 - M(1):
            meeting, pools = base.meeting_at(races, t)
            recorder.observe(meeting, pools, t)
            t += base.timedelta(seconds=8)
        due = recorder.make_predictions(t)
        self.assertEqual(due, [1])
        recorder.state[1]["t2_prediction_published"] = True
        again = rec.Recorder.load(json.loads(json.dumps(recorder.dump())))
        self.assertEqual(again.make_predictions(t), [])
        self.assertEqual(again.state[1]["t2_prediction"], recorder.state[1]["t2_prediction"])


if __name__ == "__main__":
    unittest.main()
