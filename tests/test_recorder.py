"""Offline race-day simulations. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import itertools
import json
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location("recorder", Path(__file__).resolve().parents[1] / "recorder.py")
rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec)

HK = rec.HK
DAY = "2026-11-11"
MID = "MTG_20261111_0001"
P1 = datetime(2026, 11, 11, 18, 40, tzinfo=HK)
M = lambda minutes: timedelta(minutes=minutes)


class FakeRace:
    """HKJC-like race: DECLARED -> CLOSED at the off -> RESULT; WIN pool -> PAYOUT."""

    def __init__(self, no, post, delay=0, result=6, payout=9, closed_status=True, nodes_after_close=True,
                 suspend=None, scratched=(), void=False, post_shown=None, field=12, abandon=None):
        self.no, self.post, self.off = no, post, post + M(delay)
        self.result, self.payout, self.closed_status = result, payout, closed_status
        self.nodes_after_close, self.suspend, self.scratched = nodes_after_close, suspend, set(scratched)
        self.void, self.post_shown, self.field = void, post_shown, field
        self.abandon = abandon      # (selling stops, pools refunded, race status ABANDONED), as on 2026-11-14 R6

    def at(self, t):
        shown = self.post_shown(t) if self.post_shown else self.post
        if self.void:
            return "VOIDED", "STOP_SELL", "STOP_SELL", shown, True
        if self.abandon and t >= self.abandon[0]:
            return ("ABANDONED" if t >= self.abandon[2] else "DECLARED", "STOP_SELL",
                    "REFUND_AFTER_CLOSE" if t >= self.abandon[1] else "STOP_SELL", shown, True)
        if self.suspend and self.suspend[0] <= t < self.suspend[1]:
            return "DECLARED", "STOP_SELL", "START_SELL", shown, True
        if t < self.off:
            return "DECLARED", "START_SELL", "START_SELL", shown, True
        status = "CLOSED" if self.closed_status else "DECLARED"
        if t >= self.off + M(self.result):
            status = "RESULT"
        win = "PAYOUT" if t >= self.off + M(self.payout) else "STOP_SELL"
        return status, "STOP_SELL", win, shown, self.nodes_after_close

    def snapshot(self, t):
        status, sell, win, shown, nodes = self.at(t)
        runners = [{"no": str(i), "status": "Scratched" if i in self.scratched else "Declared", "standbyNo": ""}
                   for i in range(1, self.field + 1)]
        odds = []
        if nodes:
            for a, b in itertools.combinations(range(1, self.field + 1), 2):
                value = "SCR" if {a, b} & self.scratched else str(round(4 + a + b + (t.minute % 7) / 10, 1))
                odds.append({"combString": f"{a:02},{b:02}", "oddsValue": value})
        race = {"no": self.no, "postTime": shown.isoformat(), "status": status,
                "wageringFieldSize": self.field, "runners": runners}
        pools = [{"id": f"{MID}QIN{self.no}", "oddsType": "QIN", "leg": {"races": [self.no]},
                  "sellStatus": sell, "status": sell, "oddsLastUpdateTime": t.isoformat(), "oddsNodes": odds},
                 {"id": f"{MID}WIN{self.no}", "oddsType": "WIN", "leg": {"races": [self.no]},
                  "sellStatus": sell, "status": win, "oddsLastUpdateTime": t.isoformat(),
                  "oddsNodes": [{"combString": f"{i:02}", "oddsValue": 4 + i}
                                for i in range(1, self.field + 1) if i not in self.scratched] if nodes else []}]
        return race, pools


def card(n=3, per_race=None):
    return [FakeRace(i, P1 + M(30 * (i - 1)), **(per_race or {}).get(i, {})) for i in range(1, n + 1)]


def meeting_at(races, t):
    data = [r.snapshot(t) for r in races]
    return ({"id": MID, "date": DAY, "venueCode": "HV", "races": [d[0] for d in data]},
            [p for d in data for p in d[1]])


def simulate(races, start, end, recorder=None, step=8):
    recorder = recorder or rec.Recorder()
    published, t = {}, start
    while t <= end:
        meeting, pools = meeting_at(races, t)
        recorder.observe(meeting, pools, t)
        for n in sorted(recorder.state):
            if recorder.ready(n, t):
                published[n] = (t, recorder.record(n, DAY, "HV", MID))
                recorder.state[n]["published"] = "sim"
        t += timedelta(seconds=step)
    return recorder, published


def obs(record, name):
    point = record["points"][name]
    return point and datetime.fromisoformat(point["observed_at"])


class SnapshotPoints(unittest.TestCase):
    def test_normal_meeting_r2_has_six_points_at_the_right_times(self):
        _, pub = simulate(card(), P1 - M(45), P1 + M(65))
        t, r2 = pub[2]
        self.assertEqual(r2["missing"], {})
        self.assertEqual(r2["win_missing"], {})
        for name in rec.POINTS:
            self.assertEqual(r2["win_points"][name]["observed_at"], r2["points"][name]["observed_at"])
            self.assertEqual(len(r2["win_points"][name]["odds"]), 12)
        off1, post2 = P1, P1 + M(30)
        self.assertTrue(off1 <= obs(r2, "before_rollover") <= off1 + rec.WINDOW)
        paid1 = datetime.fromisoformat(pub[1][1]["events"]["win_payout"] or r2["target_times"]["after_rollover"])
        self.assertEqual(r2["points"]["after_rollover"]["anchor"], "prev_win_payout_plus_2min")
        self.assertTrue(off1 + M(11) <= obs(r2, "after_rollover") <= off1 + M(11) + rec.WINDOW)
        self.assertTrue(post2 - M(5) <= obs(r2, "t5") <= post2 - M(5) + rec.WINDOW)
        self.assertTrue(post2 - M(3) <= obs(r2, "t3") <= post2 - M(3) + rec.WINDOW)
        self.assertTrue(post2 - M(2) <= obs(r2, "t2") <= post2 - M(2) + rec.WINDOW)
        changes = r2["combinations"][0]["drop_pct"]
        self.assertIn("t3_to_t2", changes)
        self.assertIn("t2_to_after_start", changes)
        self.assertIn("t3_to_after_start", changes)
        self.assertEqual(len(r2["win_runners"]), 12)
        win_changes = r2["win_runners"][0]["drop_pct"]
        self.assertIn("t3_to_t2", win_changes)
        self.assertIn("t2_to_after_start", win_changes)
        self.assertIn("t3_to_after_start", win_changes)
        self.assertTrue(post2 <= obs(r2, "after_start") <= post2 + rec.WINDOW)
        self.assertEqual(r2["points"]["after_start"]["basis"], "closed_board_after_stop_sell")
        self.assertEqual(r2["points"]["after_start"]["sell_status"], "STOP_SELL")
        self.assertTrue(post2 <= t <= post2 + M(1), "R2 archived right after its off, not before")
        self.assertEqual(len(r2["combinations"]), 66)
        self.assertLess(paid1, post2)

    def test_first_race_has_only_four_points(self):
        _, pub = simulate(card(), P1 - M(45), P1 + M(5))
        r1 = pub[1][1]
        self.assertEqual(r1["missing"], {"before_rollover": "first_race", "after_rollover": "first_race"})
        self.assertTrue(all(r1["points"][k] for k in ("t5", "t3", "t2", "after_start")))


class StatusAndTiming(unittest.TestCase):
    def test_odds_withdrawn_after_close_uses_labelled_fallback(self):
        races = card(2, {2: {"nodes_after_close": False}})
        _, pub = simulate(races, P1 - M(45), P1 + M(35))
        point = pub[2][1]["points"]["after_start"]
        self.assertTrue(point["basis"].startswith("FALLBACK_"))
        self.assertLessEqual(point["fallback_age_seconds"], 60)

    def test_race_status_never_closed_uses_stop_sell_as_off(self):
        races = card(2, {1: {"closed_status": False}, 2: {"closed_status": False}})
        _, pub = simulate(races, P1 - M(45), P1 + M(35))
        r2 = pub[2][1]
        self.assertEqual(r2["events"]["off_anchor"], "qin_stop_sell")
        self.assertEqual(r2["points"]["after_start"]["basis"], "closed_board_after_stop_sell")

    def test_temporary_suspension_does_not_publish_early(self):
        post2 = P1 + M(30)
        races = card(3, {2: {"suspend": (post2 - M(10), post2 - M(8))}})
        _, pub = simulate(races, P1 - M(45), P1 + M(65))
        t, r2 = pub[2]
        self.assertGreaterEqual(t, post2)
        self.assertEqual(r2["missing"], {})
        r3 = pub[3][1]
        self.assertTrue(post2 <= obs(r3, "before_rollover") <= post2 + rec.WINDOW)

    def test_suspension_just_before_post_is_undone_when_selling_resumes(self):
        post2 = P1 + M(30)
        races = card(3, {2: {"suspend": (post2 - M(1), post2 - timedelta(seconds=20)), "delay": 2}})
        _, pub = simulate(races, P1 - M(45), P1 + M(70))
        r2, r3 = pub[2][1], pub[3][1]
        self.assertEqual(len(r2["suspensions"]), 1)
        self.assertTrue(post2 + M(2) <= obs(r2, "after_start") <= post2 + M(2) + rec.WINDOW)
        self.assertTrue(post2 + M(2) <= obs(r3, "before_rollover"), "R3 rollover re-taken at the real off")

    def test_no_payout_seen_falls_back_to_result_plus_10_and_says_so(self):
        races = card(2, {1: {"payout": 999}})
        _, pub = simulate(races, P1 - M(45), P1 + M(35))
        point = pub[2][1]["points"]["after_rollover"]
        self.assertEqual(point["anchor"], "FALLBACK_prev_result_plus_10min")
        self.assertTrue(P1 + M(16) <= datetime.fromisoformat(point["observed_at"]) <= P1 + M(16) + rec.WINDOW)

    def test_after_rollover_colliding_with_t5_is_left_blank_with_reason(self):
        races = card(2, {1: {"delay": 15}})
        _, pub = simulate(races, P1 - M(45), P1 + M(35))
        r2 = pub[2][1]
        self.assertEqual(r2["missing"], {"after_rollover": "collides_with_t5"})

    def test_post_time_delay_retakes_all_countdown_points(self):
        post2 = P1 + M(30)
        moved = lambda t: post2 + M(6) if t >= post2 - M(1) else post2
        races = card(2, {2: {"delay": 6, "post_shown": moved}})
        _, pub = simulate(races, P1 - M(45), P1 + M(45))
        r2 = pub[2][1]
        self.assertTrue(post2 + M(1) <= obs(r2, "t5") <= post2 + M(1) + rec.WINDOW)
        self.assertTrue(post2 + M(3) <= obs(r2, "t3") <= post2 + M(3) + rec.WINDOW)
        self.assertTrue(post2 + M(4) <= obs(r2, "t2") <= post2 + M(4) + rec.WINDOW)
        self.assertEqual({s["point"] for s in r2["superseded"]}, {"t5", "t3", "t2"})

    def test_scratched_horse_board_still_accepted(self):
        races = card(2, {2: {"scratched": [7]}})
        _, pub = simulate(races, P1 - M(45), P1 + M(35))
        r2 = pub[2][1]
        self.assertEqual(r2["missing"], {})
        self.assertEqual(len(r2["combinations"]), 55)
        self.assertEqual(r2["points"]["t3"]["field_check"], "matches_declared_runners")

    def test_void_race_is_archived_and_does_not_block(self):
        races = card(3, {2: {"void": True}})
        _, pub = simulate(races, P1 - M(45), P1 + M(65))
        self.assertEqual(set(pub), {1, 2, 3})
        self.assertIn("voided", pub[2][1]["missing"]["t5"])


class AbandonedRace(unittest.TestCase):
    """2026-11-14 Sha Tin R6: selling stopped 34 min before the post time, the pools were refunded 21 min later
    and the race status only then became ABANDONED. R7 must take its rollover points from R5, the last race run."""

    def test_rollover_points_follow_the_last_race_that_was_run(self):
        races = card(4, {2: {"abandon": (P1 - M(4), P1 + M(8), P1 + M(8) + timedelta(seconds=48))}})
        recorder, pub = simulate(races, P1 - M(45), P1 + M(95))
        r2, r3 = pub[2][1], pub[3][1]
        self.assertTrue(all(reason == "race abandoned" for reason in r2["missing"].values()))
        self.assertIsNone(r2["events"]["stop_sell"], "an abandoned race has no stop-sell at its unused post time")
        self.assertIsNone(r2["events"]["off"])
        self.assertIsNone(r2["events"]["win_payout"], "a refund is not a payout")
        self.assertEqual(r3["rollover_from_race"], 1)
        after = r3["points"]["after_rollover"]
        self.assertEqual(after["anchor"], "prev_win_payout_plus_2min")
        self.assertEqual(rec.stamp(after["target_at"]), recorder.state[1]["paid"] + M(2))
        # R2 was only known to be abandoned after R1's off, so R3's before_rollover target had already passed.
        self.assertEqual(r3["missing"], {"before_rollover": "race_in_between_abandoned_after_this_target_had_passed"})
        self.assertEqual(pub[4][1]["rollover_from_race"], 3)
        self.assertEqual(pub[4][1]["missing"], {})

    def test_race_known_abandoned_before_the_previous_off_gets_both_rollover_points(self):
        races = card(3, {2: {"abandon": (P1 - M(30), P1 - M(20), P1 - M(19))}})
        recorder, pub = simulate(races, P1 - M(45), P1 + M(65))
        r3 = pub[3][1]
        self.assertEqual(r3["missing"], {})
        self.assertEqual(obs(r3, "before_rollover"), recorder.state[1]["close"])
        self.assertLess(obs(r3, "before_rollover"), obs(r3, "after_rollover"))

    def test_points_already_timed_from_a_race_later_abandoned_are_withdrawn(self):
        # Abandoned at the start: selling stops 1 min before the post time and the status changes 20 min later.
        races = card(3, {2: {"abandon": (P1 + M(29), P1 + M(49), P1 + M(50))}})
        recorder, pub = simulate(races, P1 - M(45), P1 + M(65))
        r3 = pub[3][1]
        self.assertEqual(r3["rollover_from_race"], 1)
        self.assertIsNone(r3["points"]["before_rollover"])
        self.assertIn({"point": "before_rollover", "reason": "previous race abandoned"}, r3["superseded"])


class Restarts(unittest.TestCase):
    def test_late_start_never_labels_old_boards_as_after_start(self):
        _, pub = simulate(card(), P1 + M(50), P1 + M(65))
        for n in (1, 2):
            record = pub[n][1]
            self.assertTrue(all(p is None for p in record["points"].values()))
            self.assertEqual(record["missing"]["after_start"], "recorder_not_running_before_race_off")
        self.assertIsNotNone(pub[3][1]["points"]["t5"])

    def test_hand_over_state_round_trip_keeps_points(self):
        races = card()
        recorder, pub = simulate(races, P1 - M(45), P1 + M(15))
        saved = json.loads(json.dumps(recorder.dump()))
        resumed, pub2 = simulate(races, P1 + M(16), P1 + M(65), recorder=rec.Recorder.load(saved))
        self.assertEqual(set(pub), {1})
        self.assertEqual(pub2[2][1]["missing"], {})
        self.assertEqual(pub2[3][1]["missing"], {})


class FakeArchive:
    files = {}

    def __init__(self):
        self.run, self.ok_once = os.environ.get("GITHUB_RUN_ID", "1") + "-1", True

    def listing(self, folder):
        return [p.rsplit("/", 1)[1] for p in self.files if p.rsplit("/", 1)[0] == folder]

    def read(self, path):
        return json.loads(self.files[path])

    def put(self, path, payload, message):
        self.files[path] = json.dumps(payload)
        return True


class MainLoop(unittest.TestCase):
    dbl_source = staticmethod(lambda races, t: [])     # Double pools served by the fake source

    def run_main(self, races, start, run_id, limit=None):
        clock = {"t": start}
        rec.now = lambda: clock["t"]
        rec.time.sleep = lambda s: clock.__setitem__("t", clock["t"] + timedelta(seconds=s))
        rec.time.monotonic = lambda: clock["t"].timestamp()
        rec.calendar = lambda day: [meeting_at(races, clock["t"])[0]]
        rec.odds_pools = lambda day, venue, kinds=("QIN", "WIN"): [{"pmPools": (
            self.dbl_source(races, clock["t"]) if tuple(kinds) == ("DBL",) else meeting_at(races, clock["t"])[1])}]
        rec.Archive = FakeArchive
        os.environ.update(GITHUB_RUN_ID=run_id, PRIVATE_DATA_REPO="x/y", PRIVATE_DATA_TOKEN="z")
        if limit:
            rec.SOFT_HANDOFF, rec.HARD_HANDOFF = limit, limit + M(15)
        rec.main()
        return clock["t"]

    def setUp(self):
        self.saved = (rec.now, rec.time.sleep, rec.time.monotonic, rec.calendar, rec.odds_pools, rec.Archive,
                      rec.SOFT_HANDOFF, rec.HARD_HANDOFF)
        FakeArchive.files = {}

    def tearDown(self):
        (rec.now, rec.time.sleep, rec.time.monotonic, rec.calendar, rec.odds_pools, rec.Archive,
         rec.SOFT_HANDOFF, rec.HARD_HANDOFF) = self.saved

    def races(self):
        return sorted(p for p in FakeArchive.files if p.startswith("qin-history/") and "/race-" in p)

    def test_full_meeting_then_queued_run_exits_without_duplicates(self):
        races = card(9)
        end = self.run_main(races, P1 - M(48), "100")
        self.assertEqual(len(self.races()), 9)
        self.assertLess(end, P1 + M(30 * 8 + 2))
        self.run_main(races, end + M(1), "101")
        self.assertEqual(len(self.races()), 9, "queued run must not re-archive")
        for path in self.races():
            if not path.endswith("race-01-100-1.json"):
                self.assertEqual(json.loads(FakeArchive.files[path])["missing"], {}, path)
        for path in self.races():
            record = json.loads(FakeArchive.files[path])
            for name in ("t5", "t3", "t2", "after_rollover"):
                point = record["points"][name]
                if point:
                    late = datetime.fromisoformat(point["observed_at"]) - datetime.fromisoformat(point["target_at"])
                    self.assertTrue(timedelta(0) <= late <= timedelta(seconds=2), f"{path} {name} {late}")

    def test_long_meeting_hands_over_and_next_run_completes_all_six_points(self):
        races = card(9)
        end = self.run_main(races, P1 - M(48), "200", limit=M(130))
        for run_id in range(201, 206):
            if len(self.races()) == 9:
                break
            end = self.run_main(races, end + M(1), str(run_id), limit=M(130))
        handoffs = [p for p in FakeArchive.files if p.startswith("qin-handoff/")]
        self.assertGreaterEqual(len(handoffs), 2)
        self.assertEqual(len(self.races()), 9)
        for path in self.races():
            if "race-01-" not in path:
                self.assertEqual(json.loads(FakeArchive.files[path])["missing"], {}, path)

    def test_no_meeting_today_exits_quietly(self):
        races = card(2)
        self.run_main(races, P1 - M(24 * 60), "300")
        self.assertEqual(FakeArchive.files, {})

    def test_a_run_started_hours_early_waits_and_records_the_whole_meeting(self):
        # GitHub fired the schedule only twice a day: an early run must not exit and hope for a later trigger.
        end = self.run_main(card(3), P1 - M(170), "310")
        self.assertEqual(len(self.races()), 3)
        for path in self.races():
            expected = {"before_rollover": "first_race", "after_rollover": "first_race"} if "race-01-" in path else {}
            self.assertEqual(json.loads(FakeArchive.files[path])["missing"], expected, path)

    def test_after_a_long_wait_a_fresh_run_is_queued_for_the_full_time_budget(self):
        queued, saved = [], rec.dispatch_successor
        rec.dispatch_successor = lambda why: queued.append(why) or True
        try:
            end = self.run_main(card(3), P1 - M(170), "311")
            self.assertEqual(len(queued), 1)
            self.assertEqual(self.races(), [])
            self.assertTrue(P1 - rec.START_LEAD <= end <= P1 - rec.START_LEAD + M(1))
            self.run_main(card(3), end + M(1), "312")           # the queued run
            self.assertEqual(len(queued), 1)
            self.assertEqual(len(self.races()), 3)
        finally:
            rec.dispatch_successor = saved

    def test_a_wait_longer_than_one_job_is_passed_on(self):
        queued, saved = [], rec.dispatch_successor
        rec.dispatch_successor = lambda why: queued.append(why) or True
        try:
            end = self.run_main(card(3), P1 - M(460), "313")
            self.assertEqual(queued, ["still waiting for the meeting"])
            self.assertEqual(end, P1 - M(460) + rec.WAIT_LIMIT)
        finally:
            rec.dispatch_successor = saved

    def test_hand_over_queues_the_next_run_itself(self):
        queued, saved = [], rec.dispatch_successor
        rec.dispatch_successor = lambda why: queued.append(why) or True
        try:
            self.run_main(card(9), P1 - M(48), "320", limit=M(130))
            self.assertEqual(queued, ["hand-over"])
        finally:
            rec.dispatch_successor = saved


if __name__ == "__main__":
    unittest.main()
