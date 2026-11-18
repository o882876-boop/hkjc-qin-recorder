import json
import unittest

import recorder as rec
import windrop_summary
from tests import test_recorder as base
from tests.test_windrop import WindropInMainLoop as _Base  # noqa: F401  (reuse the main-loop fixtures)

M, P1 = base.M, base.P1


class SummaryInMainLoop(unittest.TestCase):
    run_main, setUp, tearDown = base.MainLoop.run_main, base.MainLoop.setUp, base.MainLoop.tearDown
    dbl_source = staticmethod(lambda races, t: [])

    def text(self):
        return base.FakeArchive.files["predictions/2026-11-11_HV/summary.md"]

    def test_the_summary_is_written_with_horse_names_every_race_and_the_after_race_column(self):
        self.run_main(base.card(3), P1 - M(45), "700")
        text = self.text()
        self.assertTrue(text.startswith("# windrop 預測摘要"))
        for n in (1, 2, 3):
            self.assertIn(f"### 第{n}場", text)
        self.assertIn("今日標出總表", text)
        self.assertIn("賽後 收盤(縮短)", text)
        self.assertIn("HKT", text)
        self.assertEqual(sum(1 for p in base.FakeArchive.files if p.endswith("summary.md")), 1)

    def test_empty_or_error_state_gives_no_summary_and_never_raises(self):
        self.assertEqual(windrop_summary.build_summary("2026-11-11", "HV", {}), "")
        self.assertEqual(windrop_summary.build_summary("2026-11-11", "HV", {1: {"windrop_t2": {"error": "x"}}}), "")

    def test_names_come_from_the_meeting_and_survive_a_hand_over(self):
        recorder = rec.Recorder()
        meeting, pools = base.meeting_at(base.card(2), P1 - M(20))
        recorder.observe(meeting, pools, P1 - M(20))
        names = recorder.state[1].get("names")
        self.assertTrue(names)
        again = rec.Recorder.load(json.loads(json.dumps(recorder.dump())))
        self.assertEqual(again.state[1]["names"], names)


if __name__ == "__main__":
    unittest.main()
