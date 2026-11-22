"""Archive.read must handle files the contents API does not inline (over 1 MB): 2026-11-22's 1.6 MB hand-over file read as nothing,
the next run started without its state and R9 / R10 lost their boards. Run: python3 -m unittest discover -s tests -v"""
import base64
import importlib.util
import json
import os
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("base", Path(__file__).resolve().parent / "test_recorder.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
rec = base.rec


def make_archive():
    os.environ.setdefault("PRIVATE_DATA_REPO", "owner/private")
    os.environ.setdefault("PRIVATE_DATA_TOKEN", "x")
    return rec.Archive()


class ArchiveRead(unittest.TestCase):
    def setUp(self):
        self.archive = make_archive()
        self.original_request = rec.request
        self.requested = []

    def tearDown(self):
        rec.request = self.original_request

    def test_small_file_is_read_from_the_contents_reply(self):
        payload = {"saved_at": "x", "state": {"1": {}}}
        self.archive._call = lambda method, path, body=None: {"content": base64.b64encode(json.dumps(payload).encode()).decode(), "sha": "s"}
        rec.request = lambda *a, **k: self.fail("a small file needs no blob request")
        self.assertEqual(self.archive.read("a/b.json"), payload)

    def test_file_over_1mb_comes_back_empty_and_is_read_as_a_blob(self):
        payload = {"saved_at": "x", "state": {str(i): {"k": "v" * 40} for i in range(30000)}}   # about 1.6 MB
        self.archive._call = lambda method, path, body=None: {"content": "", "sha": "abc123", "size": 1654411}

        def fake_request(url, headers, data=None, method=None, timeout=10):
            self.requested.append(url)
            return {"content": base64.encodebytes(json.dumps(payload).encode()).decode(), "encoding": "base64"}

        rec.request = fake_request
        self.assertEqual(self.archive.read("qin-handoff/d/state.json"), payload)
        self.assertEqual(self.requested, ["https://api.github.com/repos/owner/private/git/blobs/abc123"])

    def test_empty_content_without_a_blob_is_an_error_not_an_empty_state(self):
        self.archive._call = lambda method, path, body=None: {"content": "", "sha": "abc123"}
        rec.request = lambda *a, **k: {"content": ""}
        with self.assertRaises(ValueError):
            self.archive.read("p.json")
        self.archive._call = lambda method, path, body=None: {"content": ""}
        with self.assertRaises(ValueError):
            self.archive.read("p.json")


if __name__ == "__main__":
    unittest.main()
