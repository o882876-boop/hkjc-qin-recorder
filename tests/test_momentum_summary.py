"""momentum.md page tests. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pred", HERE / "test_prediction.py")
pred = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pred)
rec, base, ms = pred.rec, pred.base, __import__("momentum_summary")
HORSES = pred.HORSES
NAMES = {h: f"馬{h}" for h in HORSES}


def race_state(done=True):
    flat = {h: 0.0 for h in HORSES}
    t3 = {"1": 20, "2": 18, "3": 8, "4": 0, "5": 0, "6": -4, "7": -8, "8": 12}
    t2 = {h: t3[h] + (10 if h in ("1", "5") else 0) for h in HORSES}
    total = {h: t2[h] + (30 if h in ("5", "1") else 0) for h in HORSES}
    pts = {"t5": pred.board(flat), "t3": pred.board(t3), "t2": pred.board(t2),
           "after_start": pred.board(total) if done else None}
    pts["t3"]["observed_at"], pts["t2"]["observed_at"] = "2026-11-22T12:27:00+08:00", "2026-11-22T12:28:00+08:00"
    wpts = {"t5": pred.win(flat), "t3": pred.win(t3), "t2": pred.win(t2), "after_start": pred.win(total) if done else None}
    s = {"points": pts, "win_points": wpts, "names": NAMES, "post": datetime(2026, 11, 22, 12, 30)}
    s["t3_prediction"], s["t2_prediction"] = rec.predict_at(s, "t3"), rec.predict_at(s, "t2")
    return s


class Page(unittest.TestCase):
    def test_nothing_predicted_gives_an_empty_page(self):
        self.assertEqual(ms.build_momentum("2026-11-22", "ST", {}, rec.predict_outcome), "")
        self.assertEqual(ms.build_momentum("2026-11-22", "ST", {1: {"t3_prediction": {"error": "x"}}}, rec.predict_outcome), "")

    def test_newest_race_is_listed_first(self):
        text = ms.build_momentum("2026-11-22", "ST", {1: race_state(), 2: race_state(), 3: race_state()}, rec.predict_outcome)
        self.assertLess(text.index("### 第3場"), text.index("### 第2場"))
        self.assertLess(text.index("### 第2場"), text.index("### 第1場"))

    def test_finished_race_shows_names_stars_and_the_check_against_what_happened(self):
        text = ms.build_momentum("2026-11-22", "ST", {1: race_state()}, rec.predict_outcome)
        self.assertIn("# 動量預測　2026-11-22　ST", text)
        self.assertIn("### 第1場　開跑 12:30", text)
        self.assertIn("已完成", text)
        self.assertIn("馬1", text)
        self.assertRegex(text, r"\| 1 \| 馬1 \| ★\d \| ★\d \|")                 # top picks are starred
        self.assertIn("命中 **", text)
        self.assertIn("今日累計命中", text)
        self.assertNotIn("未完成", text)
        self.assertIn("唔係預測邊匹贏", text)

    def test_unfinished_race_has_no_after_race_numbers(self):
        text = ms.build_momentum("2026-11-22", "ST", {1: race_state(done=False)}, rec.predict_outcome)
        self.assertIn("未完成", text)
        self.assertNotIn("命中 **", text)
        self.assertIn("未有完成場次", text)

    def test_a_failing_outcome_never_blanks_the_page(self):
        text = ms.build_momentum("2026-11-22", "ST", {1: race_state()}, lambda *a: (_ for _ in ()).throw(KeyError("x")))
        self.assertIn("### 第1場", text)
        self.assertIn("未完成", text)

    def test_only_t3_is_enough(self):
        s = race_state()
        del s["t2_prediction"]
        text = ms.build_momentum("2026-11-22", "ST", {1: s}, rec.predict_outcome)
        self.assertIn("### 第1場", text)
        self.assertIn("t3 預測", text)


class FakeArchive:
    def __init__(self, ok=True):
        self.files, self.ok, self.writes = {}, ok, 0

    def put_text(self, path, text, message):
        self.writes += 1
        if self.ok:
            self.files[path] = text
        return self.ok


class Publish(unittest.TestCase):
    def setUp(self):
        self.recorder = rec.Recorder({1: race_state()})
        self.saved = rec.now
        rec.now = lambda: datetime(2026, 11, 22, 12, 40, tzinfo=rec.HK)

    def tearDown(self):
        rec.now = self.saved

    def test_writes_momentum_md_and_skips_an_unchanged_page(self):
        archive = FakeArchive()
        rec.publish_momentum(self.recorder, archive, "2026-11-22", "ST")
        self.assertIn("predictions/2026-11-22_ST/momentum.md", archive.files)
        self.assertIn("更新：", archive.files["predictions/2026-11-22_ST/momentum.md"])
        rec.publish_momentum(self.recorder, archive, "2026-11-22", "ST", force=True)
        self.assertEqual(archive.writes, 1)

    def test_a_failed_write_or_a_bug_never_raises(self):
        rec.publish_momentum(self.recorder, FakeArchive(ok=False), "2026-11-22", "ST")
        saved = rec.momentum_summary.build_momentum
        rec.momentum_summary.build_momentum = lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("boom"))
        try:
            rec.publish_momentum(self.recorder, FakeArchive(), "2026-11-22", "ST")
        finally:
            rec.momentum_summary.build_momentum = saved


class InMainLoop(unittest.TestCase):
    run_main, setUp, tearDown = base.MainLoop.run_main, base.MainLoop.setUp, base.MainLoop.tearDown
    dbl_source = staticmethod(lambda races, t: [])

    def test_the_page_is_kept_up_to_date_through_a_race_day(self):
        self.run_main(base.card(3), base.P1 - base.M(45), "600")
        text = base.FakeArchive.files["predictions/2026-11-11_HV/momentum.md"]
        for n in (1, 2, 3):
            self.assertIn(f"### 第{n}場", text)
        self.assertNotIn("未完成", text)                  # final write happens after every race is archived
        self.assertIn("今日累計命中", text)


if __name__ == "__main__":
    unittest.main()
