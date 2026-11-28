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

    def test_chance_of_shortening_and_price_band_are_given_per_horse(self):
        pred = windrop.predict_windrop(state("5"), "t3")
        probs = [h["shorten_prob_10pct"] for h in pred["horses"]]
        self.assertEqual(probs, sorted(probs, reverse=True))
        for h in pred["horses"]:
            self.assertTrue(0 < h["shorten_prob_10pct"] < 1 and 0 < h["shorten_prob_any"] < 1)
            self.assertLess(h["predicted_close_low"], h["predicted_close_odds"])
            self.assertLess(h["predicted_close_odds"], h["predicted_close_high"])
        self.assertIn("brier_10pct", windrop.VALIDATION["t3"])

    def test_flag_list_is_every_horse_predicted_at_least_5_percent_shorter_not_a_top_n(self):
        pred = windrop.predict_windrop(state("5"), "t3")
        by_row = [h["horse"] for h in pred["horses"] if h["predicted_drop_pct"] >= 5]
        self.assertEqual(pred["flagged"], by_row)
        self.assertTrue(all(h["flagged"] == (h["predicted_drop_pct"] >= 5) for h in pred["horses"]))
        self.assertIn("5", pred["flagged"])
        self.assertIn("0.95", pred["flag_rule"])
        self.assertIn("flagged_per_race", pred["flag_validation"])
        flat = state("5")                                                  # nothing stands out: no horse needs to be flagged
        flat["points"]["t3"] = qin_board(None)
        self.assertLessEqual(len(windrop.predict_windrop(flat, "t3")["flagged"]), 3)

    def test_longshots_are_flagged_from_the_quinella_trend_not_from_favourite_ness(self):
        s = state("8", "t2")
        s["points"]["t5"] = qin_board(None)                                # before: nothing stands out
        pred = windrop.predict_longshot(s)
        self.assertEqual(pred["model"], "windrop_longshot_v1")
        self.assertTrue(all(h["win_odds"] >= 20 for h in pred["horses"]))
        self.assertEqual({h["horse"] for h in pred["horses"]}, {"6", "7", "8"})
        self.assertIn("8", pred["flagged"])
        self.assertEqual(pred["horses"][0]["horse"], "8")                  # the biggest Quinella drop comes first
        self.assertNotIn("shorten_prob_10pct", pred["horses"][0])         # a flag only, no price or chance
        json.dumps(pred)
        self.assertEqual(windrop.predict_longshot({"points": {}})["error"], "need_t5_t2_quinella_and_t2_win_boards")

    def test_longshot_and_flag_outcomes_count_what_happened(self):
        s = state("8", "t2")
        s["points"]["t5"] = qin_board(None)
        pred = windrop.predict_longshot(s)
        out = windrop.longshot_outcome(pred, {"after_start": {"odds": {**WIN, "8": 40.0}}})        # 50 -> 40: 8 shortened 20%
        self.assertEqual((out["flagged_n"], out["flagged_fell_10pct"]), (len(pred["flagged"]), 1))
        self.assertEqual(windrop.longshot_outcome(pred, {}), {"missing": "no_after_start"})
        self.assertIsNone(windrop.longshot_outcome(None, {}))
        main = windrop.predict_windrop(state("5"), "t3")
        res = windrop.windrop_outcome(main, {"after_start": {"odds": {**WIN, "5": 9.0}}})
        self.assertGreaterEqual(res["flagged_n"], 1)
        self.assertGreaterEqual(res["flagged_fell_10pct"], 1)
        self.assertIn("missed_fell_10pct", res)

    def test_quinella_fly_states_follow_the_share_gap_and_tie_is_never_excluded(self):
        self.assertEqual([windrop.qin_fly_state(g) for g in (2.0, 0.01, 0.0, -0.3, -1.0, -1.01, -8.0)],
                         ["fly", "fly", "tie", "tie", "tie", "no_fly", "no_fly"])
        pred = windrop.predict_windrop(state("5"), "t3")
        rows = {h["horse"]: h for h in pred["horses"]}
        for h in rows.values():
            self.assertAlmostEqual(h["qin_gap_pp"], h["qin_support_pct"] - h["win_implied_pct"], delta=0.02)
            self.assertEqual(h["qin_fly_state"], windrop.qin_fly_state(h["qin_gap_pp"]))
            self.assertEqual(set(h["qin_fly_points"]), {"t3"})
        self.assertEqual(rows["5"]["qin_fly_state"], "fly")
        groups = [pred["qin_fly"], pred["qin_tie"], pred["qin_no_fly"]]
        self.assertEqual(sorted(sum(groups, [])), sorted(rows))                        # every horse in exactly one state
        self.assertTrue(all(rows[h]["qin_gap_pp"] < -1 for h in pred["qin_no_fly"]))   # only the clearly-below horses are excluded
        self.assertTrue(all(-1 <= rows[h]["qin_gap_pp"] <= 0 for h in pred["qin_tie"]))
        self.assertIn("qin_fly_validation", pred)
        json.dumps(pred)

    def test_quinella_fly_is_tracked_across_t5_t3_t2_when_the_earlier_boards_exist(self):
        s = state("5", "t2")
        s["points"]["t5"] = qin_board("5")
        s["points"]["t3"] = qin_board("5")
        s["win_points"]["t3"] = {"odds": dict(WIN), "observed_at": "x"}
        pred = windrop.predict_windrop(s, "t2")
        five = next(h for h in pred["horses"] if h["horse"] == "5")
        self.assertEqual(set(five["qin_fly_points"]), {"t5", "t3", "t2"})
        self.assertTrue(five["qin_fly_all_points"])
        self.assertIn("5", pred["qin_fly"])

    def rising_state(self):
        s = state("5", "t2")
        s["points"]["after_rollover"] = qin_board(None)
        s["points"]["t5"] = qin_board("3")             # horse 3 is the Quinella favourite at t5, horse 5 at t3 and t2
        s["points"]["t3"] = qin_board("5")
        s["win_points"]["t3"] = {"odds": dict(WIN), "observed_at": "x"}
        return s

    def test_quinella_share_path_starts_at_the_previous_payout_and_counts_steps_up(self):
        pred = windrop.predict_windrop(self.rising_state(), "t2")
        rows = {h["horse"]: h for h in pred["horses"]}
        five = rows["5"]
        self.assertEqual(list(five["qin_pct_path"]), ["after_rollover", "t5", "t3", "t2"])
        self.assertEqual((five["qin_rise_steps"], five["qin_rise_steps_possible"]), (1, 3))     # down at t5, up at t3, unchanged at t2 (not a rise)
        self.assertFalse(five["qin_rise_all_steps"])
        path = five["qin_pct_path"]
        self.assertAlmostEqual(five["qin_rise_from_rollover_pct"], 100 * (path["t2"] / path["after_rollover"] - 1), delta=0.2)
        self.assertAlmostEqual(five["qin_rise_from_t5_pct"], 100 * (path["t2"] / path["t5"] - 1), delta=0.2)
        self.assertGreater(five["qin_rise_from_t5_pct"], 0)
        self.assertIn("3", pred["qin_fall5_from_t5"])                 # 3 lost far more than 5% of its share from t5 to t2
        self.assertNotIn("5", pred["qin_fall5_from_t5"])
        self.assertIn("qin_rise_validation", pred)
        json.dumps(pred)

    def test_fly_and_rising_marks_only_fly_horses_that_rose_at_every_step(self):
        s = state("5", "t2")
        s["points"]["after_rollover"] = qin_board(None)
        s["points"]["t5"] = qin_board(None)
        s["points"]["t3"] = qin_board(None)
        s["win_points"]["t3"] = {"odds": dict(WIN), "observed_at": "x"}
        # make horse 5's Quinella prices shorten step by step so its share rises at every point
        for point, factor in (("t5", 0.95), ("t3", 0.90), ("t2", 0.85)):
            s["points"][point] = {**s["points"][point], "odds": {k: (round(v * factor, 2) if "5" in k.split("-") else v)
                                                                 for k, v in s["points"][point]["odds"].items()}}
        pred = windrop.predict_windrop(s, "t2")
        rows = {h["horse"]: h for h in pred["horses"]}
        self.assertTrue(rows["5"]["qin_rise_all_steps"])
        self.assertEqual(rows["5"]["qin_fly_and_rising"], rows["5"]["qin_fly_state"] == "fly")
        self.assertIn("5", pred["qin_fly_and_rising"] if rows["5"]["qin_fly_state"] == "fly" else ["5"])
        for h in pred["horses"]:
            self.assertEqual(h["qin_fly_and_rising"], h["qin_fly_state"] == "fly" and h["qin_rise_all_steps"])
        self.assertEqual(pred["qin_fly_and_rising"], [h["horse"] for h in pred["horses"] if h["qin_fly_and_rising"]])
        out = windrop.windrop_outcome(pred, {"after_start": {"odds": dict(WIN)}})
        self.assertEqual(out["flyrise_n"], len(pred["qin_fly_and_rising"]))

    def test_all_steps_up_needs_the_after_rollover_board(self):
        s = state("5", "t2")
        s["points"]["t5"], s["points"]["t3"] = qin_board(None), qin_board(None)
        s["win_points"]["t3"] = {"odds": dict(WIN), "observed_at": "x"}
        pred = windrop.predict_windrop(s, "t2")                         # race 1: no after_rollover board
        for h in pred["horses"]:
            self.assertFalse(h["qin_rise_all_steps"])
            self.assertNotIn("qin_rise_from_rollover_pct", h)
            self.assertEqual(h["qin_rise_steps_possible"], 2)
        self.assertEqual(pred["qin_rise_all_steps"], [])

    def test_rise_outcome_counts_the_all_steps_up_and_fall_groups(self):
        pred = windrop.predict_windrop(self.rising_state(), "t2")
        out = windrop.windrop_outcome(pred, {"after_start": {"odds": {**WIN, "3": 9.0, "5": 9.0}}})
        self.assertEqual(out["fall5_n"], len(pred["qin_fall5_from_t5"]))
        self.assertIn("fall5_fell_10pct", out)
        self.assertIn("rise_all_n", out)

    def test_quinella_fly_outcome_counts_each_group(self):
        pred = windrop.predict_windrop(state("5"), "t3")
        out = windrop.windrop_outcome(pred, {"after_start": {"odds": {**WIN, "5": 9.0}}})
        self.assertEqual(out["fly_n"] + out["tie_n"] + out["nofly_n"], len(pred["horses"]))
        self.assertGreaterEqual(out["fly_fell_10pct"], 1)
        self.assertEqual(out["fell_10pct_total"], out["fly_fell_10pct"] + out["tie_fell_10pct"] + out["nofly_fell_10pct"])

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
        self.assertEqual(names, sorted(f"race-0{i}-windrop-{pt}-600-1.json" for i in (1, 2, 3) for pt in ("t1", "t10", "t2", "t3", "t5")))
        for point, early, late in (("t5", 6, 4), ("t3", 4, 2), ("t2", 3, 1), ("t1", 2, 0)):
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
                self.assertIn("flagged", body["prediction"])
                self.assertEqual(body["longshot"] is not None, point == "t2")
                if point == "t2":
                    self.assertEqual(record["windrop_longshot"], body["longshot"])
                    self.assertIn("windrop_longshot_outcome", record)
                self.assertEqual(record["windrop"][point], body["prediction"])
                self.assertIn(record["windrop_outcome"][point].get("top_hits", "missing"), range(0, 4) if "top_hits" in record["windrop_outcome"][point] else ["missing"])

    def test_t1_is_recorded_one_minute_before_the_off_and_predicted_with_the_t2_fit_labelled_unvalidated(self):
        self.run_main(base.card(3), P1 - M(45), "602")
        record = json.loads(base.FakeArchive.files["qin-history/2026-11-11_HV/race-01-602-1.json"])
        self.assertNotIn("t1", record["missing"])
        point = record["points"]["t1"]
        self.assertTrue(P1 - M(1) <= rec.stamp(point["observed_at"]) <= P1 - M(1) + rec.WINDOW)
        pred = record["windrop"]["t1"]
        self.assertNotIn("error", pred)
        self.assertEqual(pred["validation"]["unvalidated"], True)
        self.assertEqual(pred["flag_validation"]["coefs_from"], "t2")
        self.assertEqual(pred["qin_fly_validation"]["unvalidated"], True)
        self.assertEqual(set(record["windrop_outcome"]["t1"]) >= {"flagged_n", "flagged_fell_10pct"}, True)
        self.assertEqual(windrop.COEFS["t1"], windrop.COEFS["t2"])
        self.assertEqual(windrop.PROB["qin"]["t1"], windrop.PROB["qin"]["t2"])

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
        self.assertEqual(len([p for p in self.files("predictions/") if "-windrop-" not in p and not p.endswith(".md")]), 6)
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
        self.assertEqual(sorted(due), [(1, "t1"), (1, "t10"), (1, "t2"), (1, "t3"), (1, "t5")])
        for point in windrop.POINTS:
            recorder.state[1][f"windrop_{point}_published"] = True
        again = rec.Recorder.load(json.loads(json.dumps(recorder.dump())))
        self.assertEqual(again.make_windrops(t), [])
        self.assertEqual(again.state[1]["windrop_t2"], recorder.state[1]["windrop_t2"])


if __name__ == "__main__":
    unittest.main()


class T10Windrop(unittest.TestCase):
    """t10 = ten minutes before the off: predicted with the t5 fit (unvalidated), plus the t10 -> now move on later predictions."""

    def test_t10_uses_the_t5_fit_without_rise_fields_and_is_labelled_unvalidated(self):
        s = {"points": {"t10": qin_board("5")}, "win_points": {"t10": {"odds": dict(WIN), "observed_at": "x"}}}
        pred = windrop.predict_windrop(s, "t10")
        self.assertEqual((pred["model"], pred["at_point"]), ("windrop_v1", "t10"))
        self.assertTrue(pred["validation"]["unvalidated"])
        self.assertEqual(pred["validation"]["coefs_from"], "t5")
        self.assertTrue(pred["flag_validation"]["unvalidated"])
        self.assertEqual(pred["horses"][0]["horse"], "5")
        self.assertNotIn("qin_rise_all_steps", pred)
        self.assertNotIn("qin_pct_path", pred["horses"][0])
        self.assertIsNone(pred["horses"][0]["win_move_pct_t5_to_now"])
        same_as_t5 = windrop.predict_windrop({"points": {"t5": qin_board("5")},
                                              "win_points": {"t5": {"odds": dict(WIN), "observed_at": "x"}}}, "t5")
        self.assertEqual([h["score"] for h in pred["horses"]], [h["score"] for h in same_as_t5["horses"]])
        json.dumps(pred)

    def test_t10_without_its_boards_is_an_error_not_a_guess(self):
        self.assertIn("error", windrop.predict_windrop({"points": {}, "win_points": {}}, "t10"))

    def test_t5_and_later_predictions_show_the_move_since_t10_and_stay_otherwise_unchanged(self):
        base_state = state("5", point="t5")
        without = windrop.predict_windrop(base_state, "t5")
        win10 = {k: v * 1.1 for k, v in WIN.items()}
        with_t10 = dict(base_state)
        with_t10["points"] = {**base_state["points"], "t10": qin_board(None)}
        with_t10["win_points"] = {**base_state["win_points"], "t10": {"odds": win10, "observed_at": "x"}}
        pred = windrop.predict_windrop(with_t10, "t5")
        row = next(h for h in pred["horses"] if h["horse"] == "5")
        self.assertGreater(row["qin_move_pct_t10_to_now"], 0)          # horse 5's Quinella share rose against the neutral t10 board
        self.assertAlmostEqual(row["win_move_pct_t10_to_now"], 100 * (win10["5"] - WIN["5"]) / win10["5"], places=1)
        self.assertNotIn("qin_move_pct_t10_to_now", without["horses"][0])
        for old, new in zip(without["horses"], pred["horses"]):        # scores, ranks, fly states are untouched
            for key in ("horse", "score", "rank", "predicted_close_odds", "qin_fly_state"):
                self.assertEqual(old.get(key), new.get(key))
        self.assertEqual(without["flagged"], pred["flagged"])
