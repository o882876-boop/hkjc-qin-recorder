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
                 suspend=None, scratched=(), void=False, post_shown=None, field=12):
        self.no, self.post, self.off = no, post, post + M(delay)
        self.result, self.payout, self.closed_status = result, payout, closed_status
        self.nodes_after_close, self.suspend, self.scratched = nodes_after_close, suspend, set(scratched)
        self.void, self.post_shown, self.field = void, post_shown, field

    def at(self, t):
        shown = self.post_shown(t) if self.post_shown else self.post
        if self.void:
            return "VOIDED", "STOP_SELL", "STOP_SELL", shown, True
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
                  "sellStatus": sell, "status": win, "oddsNodes": []}]
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


class FivePoints(unittest.TestCase):
    def test_normal_meeting_r2_has_five_points_at_the_right_times(self):
        _, pub = simulate(card(), P1 - M(45), P1 + M(65))
        t, r2 = pub[2]
        self.assertEqual(r2["missing"], {})
        off1, post2 = P1, P1 + M(30)
        self.assertTrue(off1 <= obs(r2, "before_rollover") <= off1 + rec.WINDOW)
        paid1 = datetime.fromisoformat(pub[1][1]["events"]["win_payout"] or r2["target_times"]["after_rollover"])
        self.assertEqual(r2["points"]["after_rollover"]["anchor"], "prev_win_payout_plus_2min")
        self.assertTrue(off1 + M(11) <= obs(r2, "after_rollover") <= off1 + M(11) + rec.WINDOW)
        self.assertTrue(post2 - M(5) <= obs(r2, "t5") <= post2 - M(5) + rec.WINDOW)
        self.assertTrue(post2 - M(3) <= obs(r2, "t3") <= post2 - M(3) + rec.WINDOW)
        self.assertTrue(post2 <= obs(r2, "after_start") <= post2 + rec.WINDOW)
        self.assertEqual(r2["points"]["after_start"]["basis"], "closed_board_after_stop_sell")
        self.assertEqual(r2["points"]["after_start"]["sell_status"], "STOP_SELL")
        self.assertTrue(post2 <= t <= post2 + M(1), "R2 archived right after its off, not before")
        self.assertEqual(len(r2["combinations"]), 66)
        self.assertLess(paid1, post2)

    def test_first_race_has_only_three_points(self):
        _, pub = simulate(card(), P1 - M(45), P1 + M(5))
        r1 = pub[1][1]
        self.assertEqual(r1["missing"], {"before_rollover": "first_race", "after_rollover": "first_race"})
        self.assertTrue(all(r1["points"][k] for k in ("t5", "t3", "after_start")))


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

    def test_post_time_delay_retakes_t5_and_t3(self):
        post2 = P1 + M(30)
        moved = lambda t: post2 + M(6) if t >= post2 - M(2) else post2
        races = card(2, {2: {"delay": 6, "post_shown": moved}})
        _, pub = simulate(races, P1 - M(45), P1 + M(45))
        r2 = pub[2][1]
        self.assertTrue(post2 + M(1) <= obs(r2, "t5") <= post2 + M(1) + rec.WINDOW)
        self.assertTrue(post2 + M(3) <= obs(r2, "t3") <= post2 + M(3) + rec.WINDOW)
        self.assertEqual({s["point"] for s in r2["superseded"]}, {"t5", "t3"})

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
    def run_main(self, races, start, run_id, limit=None):
        clock = {"t": start}
        rec.now = lambda: clock["t"]
        rec.time.sleep = lambda s: clock.__setitem__("t", clock["t"] + timedelta(seconds=s))
        rec.time.monotonic = lambda: clock["t"].timestamp()
        rec.calendar = lambda day: [meeting_at(races, clock["t"])[0]]
        rec.odds_pools = lambda day, venue: [{"pmPools": meeting_at(races, clock["t"])[1]}]
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
        return sorted(p for p in FakeArchive.files if "/race-" in p)

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

    def test_long_meeting_hands_over_and_next_run_completes_all_five_points(self):
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


if __name__ == "__main__":
    unittest.main()
