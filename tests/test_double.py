"""Offline Double (孖寶) tests. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import itertools
import json
import unittest
from datetime import timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location("base", Path(__file__).resolve().parent / "test_recorder.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
rec, M, P1, DAY, MID = base.rec, base.M, base.P1, base.DAY, base.MID


def dbl_pools(races, t, nested=False, drop_node=False):
    """Double pools for every race that has a following race, in the same state as that leg-1 race."""
    pools = []
    for race, nxt in zip(races, races[1:]):
        _, sell, _, _, nodes = race.at(t)
        first = [i for i in range(1, race.field + 1) if i not in race.scratched]
        second = [i for i in range(1, nxt.field + 1) if i not in nxt.scratched]
        value = lambda a, b: str(round(10 + a * 3 + b + (t.minute % 5) / 10, 1))
        if nested:
            odds = [{"combString": f"{a:02}", "oddsValue": None,
                     "bankerOdds": [{"combString": f"{b:02}", "oddsValue": value(a, b)} for b in second]} for a in first]
        else:
            odds = [{"combString": f"{a:02}-{b:02}", "oddsValue": value(a, b)} for a, b in itertools.product(first, second)]
        if drop_node:
            odds = odds[1:]
        pools.append({"id": f"{MID}DBL{race.no}", "oddsType": "DBL", "leg": {"races": [race.no, race.no + 1]},
                      "sellStatus": sell, "status": sell, "oddsLastUpdateTime": t.isoformat(),
                      "oddsNodes": odds if nodes else []})
    return pools


def simulate_dbl(races, start, end, step=8, **kw):
    recorder, t = rec.Recorder(), start
    while t <= end:
        meeting, pools = base.meeting_at(races, t)
        recorder.observe(meeting, pools, t)
        recorder.observe_dbl(meeting, dbl_pools(races, t, **kw), t)
        t += timedelta(seconds=step)
    return recorder


class DoubleRecording(unittest.TestCase):
    def test_leg1_race_gets_all_four_points_with_ordered_pairs(self):
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 + M(65))
        record = recorder.dbl_record(1, DAY, "HV", MID)
        self.assertEqual(record["missing"], {})
        self.assertEqual((record["leg1"], record["leg2"]), (1, 2))
        self.assertEqual(len(record["combinations"]), 144)                    # 12 x 12, both orders kept
        pairs = {c["combination"] for c in record["combinations"]}
        self.assertIn("1-2", pairs)
        self.assertIn("2-1", pairs)
        post, p = P1, record["points"]
        for name, minutes in (("t5", 5), ("t3", 3), ("t2", 2)):
            at = rec.stamp(p[name]["observed_at"])
            self.assertTrue(post - M(minutes) <= at <= post - M(minutes) + rec.WINDOW, name)
        self.assertEqual(p["after_start"]["basis"], "closed_board_after_stop_sell")
        self.assertEqual(p["after_start"]["sell_status"], "STOP_SELL")
        changes = record["combinations"][0]["drop_pct"]
        self.assertEqual(set(changes), {"t5_to_t3", "t3_to_t2", "t2_to_after_start", "t3_to_after_start"})
        json.dumps(record)

    def test_second_pair_is_anchored_to_its_own_leg1_off(self):
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 + M(65))
        record = recorder.dbl_record(2, DAY, "HV", MID)
        self.assertEqual(record["missing"], {})
        t5 = rec.stamp(record["points"]["t5"]["observed_at"])
        self.assertTrue(P1 + M(30) - M(5) <= t5 <= P1 + M(30) - M(5) + rec.WINDOW)

    def test_last_race_has_no_double(self):
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 + M(95))
        self.assertTrue(recorder.state[3]["dbl"]["done"])
        record = recorder.dbl_record(3, DAY, "HV", MID)
        self.assertEqual(set(record["missing"].values()), {"last_race_has_no_double"})

    def test_scratched_horses_are_left_out_of_the_grid(self):
        races = base.card(3, {1: {"scratched": (3,)}, 2: {"scratched": (5,)}})
        record = simulate_dbl(races, P1 - M(45), P1 + M(5)).dbl_record(1, DAY, "HV", MID)
        self.assertEqual(record["missing"], {})
        self.assertEqual(len(record["combinations"]), 11 * 11)
        self.assertFalse([c for c in record["combinations"] if c["combination"].startswith("3-")])
        self.assertEqual(record["points"]["t3"]["field_check"], "matches_declared_runners")

    def test_delayed_off_still_gets_after_start_and_is_archived_promptly(self):
        """R4 on 2026-11-14 was posted for 14:25 but went off at 14:29:57; polling used to stop at post+70s."""
        races = base.card(3, {1: {"delay": 5}})
        recorder, t, done_at = rec.Recorder(), P1 - M(45), None
        while t <= P1 + M(12):
            meeting, pools = base.meeting_at(races, t)
            recorder.observe(meeting, pools, t)
            if recorder.dbl_wanted(t):          # the production loop only queries while this is true
                recorder.observe_dbl(meeting, dbl_pools(races, t), t)
            if done_at is None and recorder.state[1].get("dbl", {}).get("done"):
                done_at = t
            t += timedelta(seconds=8)
        record = recorder.dbl_record(1, DAY, "HV", MID)
        self.assertEqual(record["missing"], {})
        self.assertEqual(record["points"]["after_start"]["basis"], "closed_board_after_stop_sell")
        self.assertTrue(P1 + M(5) <= done_at <= P1 + M(5) + rec.WINDOW * 2, "archived right after the delayed off")

    def test_a_30_minute_delay_keeps_final_open_fresh(self):
        """With a 20 min cap final_open went stale (~10 min before the close); it must stay within seconds."""
        races = base.card(2, {1: {"delay": 30}})
        recorder, t = rec.Recorder(), P1 - M(45)
        while t <= P1 + M(40):
            meeting, pools = base.meeting_at(races, t)
            recorder.observe(meeting, pools, t)
            if recorder.dbl_wanted(t):
                recorder.observe_dbl(meeting, dbl_pools(races, t), t)
            t += timedelta(seconds=8)
        record = recorder.dbl_record(1, DAY, "HV", MID)
        self.assertEqual(record["missing"], {})
        self.assertTrue(rec.stamp(record["points"]["after_start"]["observed_at"]) >= P1 + M(30))
        self.assertTrue(0 <= record["final_open"]["seconds_before_close"] <= 10, record["final_open"]["seconds_before_close"])

    def test_waiting_for_a_delayed_off_has_a_limit(self):
        recorder = simulate_dbl(base.card(2, {1: {"delay": 90}}), P1 - M(45), P1 + M(30))
        self.assertTrue(recorder.dbl_wanted(P1 + M(44)))
        self.assertFalse(recorder.dbl_wanted(P1 + M(46)))

    def test_final_open_is_the_last_open_board_even_when_the_off_is_late(self):
        races = base.card(3, {1: {"delay": 5}})
        _, pub = base.simulate(races, P1 - M(45), P1 + M(12))
        qin = pub[1][1]
        dbl = simulate_dbl(races, P1 - M(45), P1 + M(12)).dbl_record(1, DAY, "HV", MID)
        for name, record in (("QIN", qin), ("DBL", dbl)):
            final = record["final_open"]
            self.assertIsNotNone(final, name)
            self.assertEqual(final["sell_status"], "START_SELL", name)
            self.assertTrue(rec.stamp(record["points"]["t2"]["observed_at"]) < rec.stamp(final["observed_at"]), name)
            self.assertTrue(P1 + M(4) <= rec.stamp(final["observed_at"]) <= P1 + M(5), name)   # just before the real close
            self.assertTrue(0 <= final["seconds_before_close"] <= 10, name)
            row = record["combinations"][0]
            self.assertEqual(row["final_open_odds"], final["odds"][row["combination"]], name)
            self.assertIsNotNone(row["final_drop_pct_from_t3"], name)
        self.assertEqual(qin["win_final_open"]["sell_status"], "START_SELL")
        self.assertIsNotNone(qin["win_runners"][0]["final_open_odds"])
        json.dumps(qin), json.dumps(dbl)

    def test_final_open_survives_hand_over(self):
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 - M(1))
        again = rec.Recorder.load(json.loads(json.dumps(recorder.dump())))
        self.assertEqual(again.state[1]["last_open_at"], recorder.state[1]["last_open_at"])
        self.assertEqual(again.state[1]["dbl"]["last_open_at"], recorder.state[1]["dbl"]["last_open_at"])

    def test_unfinished_doubles_are_settled_when_the_run_ends(self):
        """Run ended with R2's Double still open (2026-11-14: Double R10-R11 was never written)."""
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 + M(29))      # stops one minute before R2's off
        self.assertFalse(recorder.state[2]["dbl"].get("done"))
        recorder.finish_dbl()
        self.assertTrue(recorder.state[1]["dbl"]["done"] and recorder.state[2]["dbl"]["done"])
        self.assertEqual(recorder.state[3]["dbl"].get("published"), "n/a")  # last race has no Double: never archived
        record = recorder.dbl_record(2, DAY, "HV", MID)
        self.assertEqual(record["leg1"], 2)
        self.assertTrue(all(record["points"][k] for k in ("t5", "t3", "t2")))
        self.assertIn("after_start", record["missing"])                    # the gap is labelled, not silent
        self.assertIsNotNone(record["final_open"])
        json.dumps(record)

    def test_close_points_follow_the_real_close_whatever_the_delay(self):
        """c5/c3/c2 are measured back from the observed close, so a 10 or 30 minute delay still gives true 5/3/2."""
        for delay in (0, 10, 30):
            races = base.card(2, {1: {"delay": delay}})
            _, pub = base.simulate(races, P1 - M(45), P1 + M(delay) + M(12))
            qin = pub[1][1]
            dbl = simulate_dbl(races, P1 - M(45), P1 + M(delay) + M(12)).dbl_record(1, DAY, "HV", MID)
            close = rec.stamp(qin["events"]["stop_sell"])
            for name, record, key in (("QIN", qin, "close_points"), ("WIN", qin, "win_close_points"), ("DBL", dbl, "close_points")):
                self.assertEqual(record[key.replace("points", "missing")], {}, (delay, name))
                for point, minutes in (("c5", 5), ("c3", 3), ("c2", 2)):
                    at = rec.stamp(record[key][point]["observed_at"])
                    self.assertLessEqual(abs(at - (close - M(minutes))), timedelta(seconds=30), (delay, name, point))
                    self.assertEqual(record[key][point]["sell_status"], "START_SELL", (delay, name, point))
            row = qin["combinations"][0]
            self.assertEqual(set(row["close_odds"]), {"c5", "c3", "c2"})
            self.assertEqual(set(row["close_drop_pct"]), {"c5_to_c3", "c3_to_c2"})
            self.assertEqual(set(qin["win_runners"][0]["close_odds"]), {"c5", "c3", "c2"})
            json.dumps(qin), json.dumps(dbl)

    def test_a_delay_announced_late_still_gets_true_close_points(self):
        """Posted for P1, then the off keeps slipping: 5 min late, then 12, then 20 (the post time never changes)."""
        races = base.card(2, {1: {"delay": 20}})
        _, pub = base.simulate(races, P1 - M(45), P1 + M(32))
        record = pub[1][1]
        close = rec.stamp(record["events"]["stop_sell"])
        self.assertGreaterEqual(close, P1 + M(20))
        for point, minutes in (("c5", 5), ("c3", 3), ("c2", 2)):
            at = rec.stamp(record["close_points"][point]["observed_at"])
            self.assertLessEqual(abs(at - (close - M(minutes))), timedelta(seconds=30), point)
            self.assertGreater(at, P1 + M(14), "taken minutes before the real close, not at the old schedule")

    def test_rolling_samples_stay_small_and_are_not_carried_over_a_hand_over(self):
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 - M(1))
        ring = recorder.state[1]["ring"]
        self.assertLessEqual(len(ring["qin"]), 8 * 60 // 20 + 2)
        self.assertLessEqual(len(recorder.state[1]["dbl"]["ring"]["dbl"]), 8 * 60 // 20 + 2)
        dumped = json.loads(json.dumps(recorder.dump()))
        self.assertNotIn("ring", dumped["1"])
        self.assertNotIn("ring", dumped["1"]["dbl"])
        again = rec.Recorder.load(dumped)
        record = again.dbl_record(1, DAY, "HV", MID)         # a record from a taken-over run labels the gap
        self.assertEqual(set(record["close_missing"].values()), {"close_not_observed"})

    def test_a_bug_in_the_new_fields_never_blocks_the_existing_record(self):
        races = base.card(2)
        recorder = simulate_dbl(races, P1 - M(45), P1 + M(12))
        _, pub = base.simulate(races, P1 - M(45), P1 + M(12))
        good = pub[1][1]
        saved = rec.close_points, rec.final_open
        rec.close_points = lambda *a, **k: (_ for _ in ()).throw(KeyError("boom"))
        rec.final_open = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
        try:
            _, pub2 = base.simulate(races, P1 - M(45), P1 + M(12))
            broken_qin = pub2[1][1]
            broken_dbl = recorder.dbl_record(1, DAY, "HV", MID)
        finally:
            rec.close_points, rec.final_open = saved
        for broken in (broken_qin, broken_dbl):
            self.assertTrue(all(broken["points"][k] for k in ("t5", "t3", "t2", "after_start")))
            self.assertIsNone(broken["final_open"])
            self.assertEqual(set(broken["close_missing"].values()), {"error_KeyError"})
        self.assertEqual(broken_qin["combinations"][0]["odds"], good["combinations"][0]["odds"])
        self.assertEqual(broken_qin["win_runners"][0]["odds"], good["win_runners"][0]["odds"])
        json.dumps(broken_qin), json.dumps(broken_dbl)

    def test_polling_stops_after_the_off_and_skips_races_already_off(self):
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 + M(2))
        self.assertTrue(recorder.state[1]["dbl"]["done"] or not recorder.dbl_wanted(P1 + M(3)))
        self.assertFalse(recorder.dbl_wanted(P1 + M(3)))
        late = simulate_dbl(base.card(3), P1 + M(2), P1 + M(40))
        self.assertFalse(late.dbl_wanted(P1 + M(10)))

    def test_banker_partner_layout_gives_the_same_board(self):
        flat = simulate_dbl(base.card(3), P1 - M(45), P1 + M(5)).dbl_record(1, DAY, "HV", MID)
        nested = simulate_dbl(base.card(3), P1 - M(45), P1 + M(5), nested=True).dbl_record(1, DAY, "HV", MID)
        self.assertEqual(flat["combinations"], nested["combinations"])

    def test_real_hkjc_slash_notation_keeps_leg_order(self):
        """HKJC publishes Double combinations as "leg1/leg2" (checked against the live source, 2026-11-14)."""
        races = base.card(2)
        pool = dbl_pools(races, P1 - M(10))[0]
        for node in pool["oddsNodes"]:
            node["combString"] = node["combString"].replace("-", "/")
            node["oddsDropValue"], node["hotFavourite"], node["bankerOdds"] = 0, False, []
        board = rec.dbl_board(pool, {"runners": []}, {"runners": []}, P1)
        self.assertEqual(len(board["odds"]), 144)
        self.assertIn("2-1", board["odds"])
        self.assertNotEqual(board["odds"]["2-1"], board["odds"]["1-2"])

    def test_incomplete_grid_is_never_recorded(self):
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 + M(5), drop_node=True)
        record = recorder.dbl_record(1, DAY, "HV", MID)
        self.assertEqual(record["combinations"], [])
        self.assertTrue(all(v for v in record["missing"].values()))

    def test_pool_identity_must_match(self):
        pools = dbl_pools(base.card(3), P1)
        self.assertEqual(sorted(rec.dbl_pools_by_race(MID, pools)), [1, 2])
        pools[0]["leg"]["races"] = [1, 3]
        self.assertEqual(sorted(rec.dbl_pools_by_race(MID, pools)), [2])
        self.assertEqual(rec.dbl_pools_by_race("MTG_OTHER", dbl_pools(base.card(3), P1)), {})

    def test_state_survives_hand_over_and_double_polling_is_gated(self):
        recorder = simulate_dbl(base.card(3), P1 - M(45), P1 - M(4))
        saved = json.loads(json.dumps(recorder.dump()))
        again = rec.Recorder.load(saved)
        self.assertEqual(again.state[1]["dbl"]["points"].keys(), recorder.state[1]["dbl"]["points"].keys())
        self.assertTrue(again.dbl_wanted(P1 - M(4)))
        self.assertFalse(again.dbl_wanted(P1 - M(20)))
        again.dbl_archived = {1, 2, 3}
        self.assertFalse(again.dbl_wanted(P1 - M(4)))


class DoubleInMainLoop(unittest.TestCase):
    run_main, setUp, tearDown = base.MainLoop.run_main, base.MainLoop.setUp, base.MainLoop.tearDown
    dbl_source = staticmethod(dbl_pools)

    def test_double_records_are_archived_per_leg1_race_next_to_quinella(self):
        races = base.card(3)
        self.run_main(races, P1 - M(45), "400")
        paths = sorted(p for p in base.FakeArchive.files if p.startswith("dbl-history/"))
        self.assertEqual([p.rsplit("/", 1)[1] for p in paths], ["race-01-400-1.json", "race-02-400-1.json"])
        for path in paths:
            record = json.loads(base.FakeArchive.files[path])
            self.assertEqual(record["missing"], {}, path)
        self.assertTrue(any(p.startswith("qin-history/") for p in base.FakeArchive.files))

    def test_main_loop_always_writes_every_double_even_if_polling_missed_the_window(self):
        calls = {"n": 0}

        def flaky(races, t):                  # the Double endpoint fails after the first 20 minutes of the card
            calls["n"] += 1
            if t > P1 + M(1):
                raise ValueError("HKJC Double endpoint down")
            return dbl_pools(races, t)

        type(self).dbl_source = staticmethod(flaky)
        try:
            self.run_main(base.card(3), P1 - M(45), "402")
        finally:
            type(self).dbl_source = staticmethod(dbl_pools)
        paths = sorted(p.rsplit("/", 1)[1] for p in base.FakeArchive.files if p.startswith("dbl-history/"))
        self.assertEqual(paths, ["race-01-402-1.json", "race-02-402-1.json"])

    def test_double_failure_does_not_disturb_quinella_records(self):
        def broken(races, t):
            raise ValueError("HKJC Double endpoint down")

        type(self).dbl_source = staticmethod(broken)
        try:
            self.run_main(base.card(3), P1 - M(45), "401")
        finally:
            type(self).dbl_source = staticmethod(dbl_pools)
        qin = [p for p in base.FakeArchive.files if p.startswith("qin-history/")]
        self.assertEqual(len(qin), 3)
        for path in qin:
            record = json.loads(base.FakeArchive.files[path])
            self.assertTrue(all(record["points"][k] for k in ("t5", "t3", "t2", "after_start")), path)
        # Doubles are still written, empty and with a reason, so a gap is never silent.
        dbl = [p for p in base.FakeArchive.files if p.startswith("dbl-history/")]
        self.assertEqual(len(dbl), 2)
        for path in dbl:
            record = json.loads(base.FakeArchive.files[path])
            self.assertFalse(any(record["points"].values()))
            self.assertTrue(all(record["missing"].values()))


if __name__ == "__main__":
    unittest.main()
