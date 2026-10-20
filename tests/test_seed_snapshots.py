from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "seed_snapshots.py"


class SeedSnapshotsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = self.root / "archive"
        self.snapshots = self.root / "snapshots"
        self.archive.mkdir()
        payload = {
            "meta": {
                "as_of": "2026-10-19",
                "session": "close",
                "generated_at": "2026-10-19T22:46:47",
            },
            "market": {"regime": "震荡"},
            "advice": {"items": {}},
            "assets": [{"code": "000001"}],
        }
        page = (
            "<html><script>\n"
            f"const DATA = {json.dumps(payload, ensure_ascii=False)};\n"
            "const ASSETS = [];\n"
            "</script></html>"
        )
        (self.archive / "2026-10-19_close.html").write_text(page, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_seed(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--archive-dir",
                str(self.archive),
                "--snapshot-dir",
                str(self.snapshots),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_snapshot_is_seeded(self):
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.snapshots / "2026-10-19" / "close.json"
        self.assertTrue(target.exists())
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["meta"]["session"], "close")
        self.assertEqual(data["assets"][0]["code"], "000001")

    def test_existing_snapshot_is_not_overwritten(self):
        target = self.snapshots / "2026-10-19" / "close.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"keep": true}', encoding="utf-8")
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"keep": true}')


if __name__ == "__main__":
    unittest.main()
