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
        self.assertFalse([p for p in base.FakeArchive.files if p.startswith("dbl-history/")])


if __name__ == "__main__":
    unittest.main()
