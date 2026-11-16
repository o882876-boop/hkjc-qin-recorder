"""Offline tests for the in-meeting 66888 recorder. Run: python3 -m unittest discover -s tests -v"""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import indices_recorder as ir  # noqa: E402

HK = ZoneInfo("Asia/Hong_Kong")
POST = datetime(2026, 11, 18, 18, 40, tzinfo=HK)

HTML = """<table id="tb-rank-wp-q">
<tr data-horse-no="1"><td class="horse-name">愛馬</td><td class="rank-index-win-value">78</td><td class="rank-index-place-value">80.5</td></tr>
<tr data-horse-no="2"><td class="horse-name">快馬</td><td class="rank-index-win-value">--</td><td class="rank-index-place-value">--</td></tr>
<tr data-horse-no="3"><td class="horse-name">新馬</td><td class="rank-index-win-value">86</td><td class="rank-index-place-value"></td></tr>
</table>"""


class Parse(unittest.TestCase):
    def test_numeric_rows_only(self):
        rows = ir.parse_indices(HTML)
        self.assertEqual(sorted(rows), ["1", "3"])
        self.assertEqual(rows["1"], {"name": "愛馬", "win_index": 78.0, "place_index": 80.5})
        self.assertIsNone(rows["3"]["place_index"])

    def test_blank_table_gives_nothing(self):
        self.assertEqual(ir.parse_indices(HTML.replace("78", "--").replace("80.5", "--").replace("86", "--")), {})


class Schedule(unittest.TestCase):
    def test_targets(self):
        t = ir.targets(POST)
        self.assertEqual(t["t10"], POST - timedelta(minutes=10))
        self.assertEqual(t["t2"], POST - timedelta(minutes=2))
        self.assertEqual(t["after_start"], POST + timedelta(minutes=1))

    def test_nothing_due_early(self):
        state = {1: {"points": {}, "post": POST}}
        due, future = ir.next_point(state, POST - timedelta(minutes=30))
        self.assertIsNone(due)
        self.assertEqual(future, POST - timedelta(minutes=10))

    def test_due_within_window_then_missed(self):
        state = {1: {"points": {}, "post": POST}}
        at = POST - timedelta(minutes=10) + timedelta(seconds=20)
        due, _ = ir.next_point(state, at)
        self.assertEqual(due[1:], (1, "t10"))
        late = POST - timedelta(minutes=10) + ir.LATE + timedelta(seconds=1)
        ir.next_point(state, late)
        self.assertEqual(state[1]["points"]["t10"]["status"], "missed")

    def test_taken_point_not_due_again(self):
        state = {1: {"points": {"t10": {"status": "ok"}}, "post": POST}}
        due, future = ir.next_point(state, POST - timedelta(minutes=10) + timedelta(seconds=5))
        self.assertIsNone(due)
        self.assertEqual(future, POST - timedelta(minutes=5))

    def test_postponed_race_moves_targets(self):
        state = {1: {"points": {}, "post": POST}}
        state[1]["post"] = POST + timedelta(minutes=20)           # calendar refresh
        due, future = ir.next_point(state, POST - timedelta(minutes=10) + timedelta(seconds=5))
        self.assertIsNone(due)
        self.assertEqual(future, POST + timedelta(minutes=10))

    def test_over_race_is_skipped(self):
        state = {1: {"points": {}, "post": POST, "over": True}}
        self.assertEqual(ir.next_point(state, POST), (None, None))

    def test_complete_and_over(self):
        s = {"points": {k: {"status": "ok"} for k in ir.POINTS}, "post": POST}
        self.assertTrue(ir.race_complete(s))
        s2 = {"points": {}, "post": POST}
        self.assertFalse(ir.race_is_over(s2, POST + timedelta(minutes=29)))
        self.assertTrue(ir.race_is_over(s2, POST + timedelta(minutes=31)))

    def test_record_keeps_missing_status(self):
        s = {"points": {"t10": {"status": "missed"}, "t5": {"status": "ok", "rows": []}}, "post": POST}
        rec = ir.build_record("2026-11-18", "HV", "MTG_20261118_0001", 3, s)
        self.assertEqual(rec["points"]["t10"]["status"], "missed")
        self.assertEqual(rec["race"], 3)
        self.assertEqual(rec["phase"], "in_meeting")


if __name__ == "__main__":
    unittest.main()
