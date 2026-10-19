from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ashare_vp.cli import main
from ashare_vp.datasource import DataFetcher
from ashare_vp.models import Asset

from helpers import make_bars

ETF = Asset("159999", "测试创新药ETF", "测试ETF", "etf", "SZ", "0.159999", "sz159999", "sz159999")
INDEX = Asset("000999", "测试宽基指数", "测试指数", "index", "SH", "1.000999", "sh000999", "sh000999")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.out = self.root / "reports"
        self.config_path = self.root / "assets.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "settings": {
                        "start_date": "2025-01-01",
                        "min_bars": 30,
                        "source_order": ["tencent", "sina"],
                    },
                    "groups": [
                        {
                            "name": "测试ETF",
                            "kind": "etf",
                            "assets": [
                                {
                                    "code": "159999",
                                    "name": "测试创新药ETF",
                                    "exchange": "SZ",
                                    "secid": "0.159999",
                                    "tencent": "sz159999",
                                    "sina": "sz159999",
                                }
                            ],
                        },
                        {
                            "name": "测试指数",
                            "kind": "index",
                            "assets": [
                                {
                                    "code": "000999",
                                    "name": "测试宽基指数",
                                    "exchange": "SH",
                                    "secid": "1.000999",
                                    "tencent": "sh000999",
                                    "sina": "sh000999",
                                }
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        fetcher = DataFetcher(self.cache, start_date="2025-01-01", delay=0)
        etf_bars = make_bars([1.0 + i * 0.002 for i in range(80)], [100000] * 80, start="2025-01-01")
        index_bars = make_bars([3000 + i * 5 for i in range(80)], [500000] * 80, start="2025-01-01")
        fetcher._save_cache(ETF, etf_bars, "test")
        fetcher._save_cache(INDEX, index_bars, "test")
        self.last_date = etf_bars[-1].date

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *extra):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(
                [
                    "--config",
                    str(self.config_path),
                    "--cache-dir",
                    str(self.cache),
                    "--output-dir",
                    str(self.out),
                    "--snapshot-dir",
                    str(self.root / "snapshots"),
                    "--offline",
                    "--date",
                    self.last_date,
                    "--format",
                    "md,json,csv",
                    "--quiet",
                    *extra,
                ]
            )
        return code, buffer.getvalue()

    def test_offline_report_generation(self):
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("vp_report.md", output)
        directory = self.out / self.last_date
        self.assertTrue((directory / "vp_report.md").exists())
        self.assertTrue((directory / "vp_report.json").exists())
        self.assertTrue((directory / "vp_report.csv").exists())

        payload = json.loads((directory / "vp_report.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["meta"]["as_of"], self.last_date)
        self.assertEqual(len(payload["assets"]), 2)
        self.assertEqual(payload["market"]["count"], 2)

        markdown = (directory / "vp_report.md").read_text(encoding="utf-8")
        self.assertIn("测试创新药ETF", markdown)
        self.assertIn("测试宽基指数", markdown)
        self.assertIn("分组明细", markdown)

    def test_filter_by_code(self):
        code, _ = self.run_cli("--code", "159999")
        self.assertEqual(code, 0)
        payload = json.loads(
            (self.out / self.last_date / "vp_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(payload["assets"]), 1)
        self.assertEqual(payload["assets"][0]["code"], "159999")

    def test_offline_missing_cache_fails(self):
        missing = [self.cache / "sz159999.json", self.cache / "sh000999.json"]
        backups = {path: path.read_text(encoding="utf-8") for path in missing}
        try:
            for path in missing:
                path.unlink()
            code, _ = self.run_cli()
            self.assertEqual(code, 2)
        finally:
            for path, content in backups.items():
                path.write_text(content, encoding="utf-8")

    def test_list_mode(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--config", str(self.config_path), "--list"])
        self.assertEqual(code, 0)
        self.assertIn("测试ETF", buffer.getvalue())
        self.assertIn("159999", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
