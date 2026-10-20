from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_site.py"


class VerifySiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "latest.json"
        self.path.write_text(
            json.dumps(
                {
                    "meta": {
                        "generated_at": "2026-10-19T23:52:10",
                        "as_of": "2026-10-19",
                    },
                    "assets": [{"code": "000001"}],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def run_verify(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.path),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_matching_version_passes(self):
        result = self.run_verify(
            "--generated-at", "2026-10-19T23:52:10",
            "--as-of", "2026-10-19",
            "--asset-count", "1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("校验通过", result.stdout)

    def test_mismatched_version_fails(self):
        result = self.run_verify(
            "--generated-at", "2026-10-19T22:46:47",
            "--as-of", "2026-10-19",
            "--asset-count", "1",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("不一致", result.stderr)
        self.assertIn("generated_at", result.stderr)

    def test_missing_file_fails(self):
        self.path.unlink()
        result = self.run_verify(
            "--generated-at", "2026-10-19T23:52:10",
            "--as-of", "2026-10-19",
            "--asset-count", "1",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("文件不存在", result.stderr)


if __name__ == "__main__":
    unittest.main()
