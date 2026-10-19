from __future__ import annotations

import io
import json
import re
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import urlopen

from ashare_vp import cli, session
from ashare_vp.config import load_config
from ashare_vp.datasource import DataFetcher
from ashare_vp.quotes import Quote
from ashare_vp.server import Handler
from helpers import make_bars


def build_fixture(root: Path):
    cache = root / "cache"
    output = root / "reports"
    snapshots = root / "snapshots"
    config_path = root / "assets.json"
    today = date.today()
    start = (today - timedelta(days=79)).isoformat()
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "settings": {
                    "start_date": start,
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
                                "name": "测试ETF",
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
                                "name": "测试指数",
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
    config = load_config(config_path)
    etf, index = config.assets
    fetcher = DataFetcher(cache, start_date=start, delay=0)
    etf_bars = make_bars([1.0 + i * 0.002 for i in range(80)], [100_000.0] * 80, start=start)
    index_bars = make_bars([3000 + i * 5 for i in range(80)], [500_000.0] * 80, start=start)
    fetcher._save_cache(etf, etf_bars, "test")
    fetcher._save_cache(index, index_bars, "test")
    return {
        "root": root,
        "cache": cache,
        "output": output,
        "snapshots": snapshots,
        "config_path": config_path,
        "config": config,
        "assets": [etf, index],
        "bars": {etf.code: etf_bars, index.code: index_bars},
        "today": today.isoformat(),
    }


def make_quote(asset, bars, clock: str, fraction: float) -> Quote:
    last = bars[-1]
    prev = bars[-2]
    price = round(last.close * 1.005, 4)
    return Quote(
        code=asset.code,
        name=asset.name,
        price=price,
        prev_close=prev.close,
        open=last.open,
        high=max(last.high, price),
        low=min(last.low, price),
        volume=last.volume * fraction,
        amount=last.volume * fraction * 100.0 * price,
        timestamp=f"{bars[-1].date.replace('-', '')}{clock}",
        change_pct=round((price / prev.close - 1.0) * 100.0, 4),
        turnover=1.0,
    )


def run_close(fixture):
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
        code = cli.main(
            [
                "--config",
                str(fixture["config_path"]),
                "--cache-dir",
                str(fixture["cache"]),
                "--output-dir",
                str(fixture["output"]),
                "--snapshot-dir",
                str(fixture["snapshots"]),
                "--offline",
                "--date",
                fixture["today"],
                "--quiet",
            ]
        )
    return code, buffer.getvalue()


def run_intraday(fixture, session_key: str, quotes):
    with mock.patch.object(session, "fetch_quotes", return_value=(quotes, [])):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return session.run_session(
                session=session_key,
                config=fixture["config"],
                assets=fixture["assets"],
                cache_dir=fixture["cache"],
                snapshot_dir=fixture["snapshots"],
                output_dir=fixture["output"],
                source_order=["tencent"],
                start_date=fixture["config"].settings["start_date"],
                min_bars=30,
                timeout=5,
                require_current=True,
                quiet=True,
            )


class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fixture = build_fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_close_report_exposes_advice_everywhere(self):
        code, output = run_close(self.fixture)
        self.assertEqual(code, 0)
        self.assertIn("vp_report.md", output)

        day = self.fixture["today"]
        report_dir = self.fixture["output"] / day
        payload = json.loads((report_dir / "vp_report.json").read_text(encoding="utf-8"))
        self.assertIn("advice", payload)
        self.assertEqual(len(payload["advice"]["items"]), 2)
        self.assertEqual(len(payload["assets"]), 2)
        self.assertIsNotNone(payload["assets"][0]["advice"])

        markdown = (report_dir / "vp_report.md").read_text(encoding="utf-8")
        self.assertIn("### 操作建议", markdown)
        self.assertIn("参考仓位", markdown)

        csv_header = (
            (report_dir / "vp_report.csv").read_text(encoding="utf-8-sig").splitlines()[0]
        )
        self.assertIn("advice_level", csv_header)
        self.assertIn("advice_position", csv_header)

        snapshot = json.loads(
            (self.fixture["snapshots"] / day / "close.json").read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot["meta"]["session"], "close")
        self.assertEqual(snapshot["meta"]["data_mode"], "daily")
        self.assertIn("advice", snapshot)

        h5_path = self.fixture["output"] / "h5" / f"{day}_close.html"
        self.assertTrue(h5_path.exists())
        html = h5_path.read_text(encoding="utf-8")
        self.assertNotIn("__PAYLOAD__", html)
        match = re.search(r"const DATA = (.*?);\nconst ASSETS", html, re.S)
        self.assertIsNotNone(match)
        h5_payload = json.loads(match.group(1))
        self.assertEqual(len(h5_payload["assets"]), 2)
        self.assertIn("advice", h5_payload)

    def test_intraday_sessions_then_close_continuity(self):
        day = self.fixture["today"]
        etf, index = self.fixture["assets"]

        quotes_1030 = {
            etf.code: make_quote(etf, self.fixture["bars"][etf.code], "103000", 60 / 240),
            index.code: make_quote(index, self.fixture["bars"][index.code], "103000", 60 / 240),
        }
        self.assertEqual(run_intraday(self.fixture, "1030", quotes_1030), 0)
        snap_1030 = json.loads(
            (self.fixture["snapshots"] / day / "1030.json").read_text(encoding="utf-8")
        )
        self.assertTrue(snap_1030["meta"]["intraday"])
        self.assertEqual(snap_1030["meta"]["quote_count"], 2)
        self.assertEqual(snap_1030["meta"]["data_mode"], "intraday")
        self.assertEqual(snap_1030["meta"]["quote_time"], "10:30:00")
        self.assertEqual(snap_1030["meta"]["session"], "1030")

        quotes_1100 = {
            etf.code: make_quote(etf, self.fixture["bars"][etf.code], "110000", 90 / 240),
            index.code: make_quote(index, self.fixture["bars"][index.code], "110000", 90 / 240),
        }
        self.assertEqual(run_intraday(self.fixture, "1100", quotes_1100), 0)
        snap_1100 = json.loads(
            (self.fixture["snapshots"] / day / "1100.json").read_text(encoding="utf-8")
        )
        self.assertTrue(snap_1100["meta"]["intraday"])
        self.assertEqual(snap_1100["meta"]["quote_count"], 2)
        self.assertEqual(snap_1100["meta"]["data_mode"], "intraday")
        self.assertEqual(snap_1100["meta"]["quote_time"], "11:00:00")

        quotes_1400 = {
            etf.code: make_quote(etf, self.fixture["bars"][etf.code], "140000", 180 / 240),
            index.code: make_quote(index, self.fixture["bars"][index.code], "140000", 180 / 240),
        }
        self.assertEqual(run_intraday(self.fixture, "1400", quotes_1400), 0)
        snap_1400 = json.loads(
            (self.fixture["snapshots"] / day / "1400.json").read_text(encoding="utf-8")
        )
        continuity = snap_1400["advice"]["continuity"]
        self.assertTrue(continuity["available"])
        self.assertEqual(continuity["previous"]["session"], "1100")

        self.assertEqual(run_close(self.fixture)[0], 0)
        snap_close = json.loads(
            (self.fixture["snapshots"] / day / "close.json").read_text(encoding="utf-8")
        )
        self.assertTrue(snap_close["advice"]["continuity"]["available"])
        self.assertEqual(
            snap_close["advice"]["continuity"]["previous"]["session"], "1400"
        )

        index_html = (self.fixture["output"] / "h5" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"{day}_1030.html", index_html)
        self.assertIn(f"{day}_1100.html", index_html)
        self.assertIn(f"{day}_1400.html", index_html)
        self.assertIn(f"{day}_close.html", index_html)

    def test_require_current_skips_before_daily_fetch(self):
        with mock.patch.object(session, "fetch_quotes", return_value=({}, [])):
            with mock.patch.object(
                session.DataFetcher, "fetch_many", side_effect=AssertionError("不应抓取日线")
            ):
                with redirect_stderr(io.StringIO()):
                    code = session.run_session(
                        session="1100",
                        config=self.fixture["config"],
                        assets=self.fixture["assets"],
                        cache_dir=self.fixture["cache"],
                        snapshot_dir=self.fixture["snapshots"],
                        output_dir=self.fixture["output"],
                        source_order=["tencent"],
                        start_date=self.fixture["config"].settings["start_date"],
                        timeout=5,
                        require_current=True,
                        quiet=True,
                    )
        self.assertEqual(code, 3)


class QuietHandler(Handler):
    def log_message(self, fmt, *args):
        pass


class ServerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fixture = build_fixture(self.root)
        self.assertEqual(run_close(self.fixture)[0], 0)
        self.old_h5 = Handler.h5_dir
        self.old_snapshot = Handler.snapshot_dir
        Handler.h5_dir = self.fixture["output"] / "h5"
        Handler.snapshot_dir = self.fixture["snapshots"]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        Handler.h5_dir = self.old_h5
        Handler.snapshot_dir = self.old_snapshot
        self.tmp.cleanup()

    def fetch(self, path):
        try:
            with urlopen(self.base + path, timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_endpoints_and_path_traversal(self):
        status, _, body = self.fetch("/health")
        self.assertEqual(status, 200)
        health = json.loads(body)
        self.assertEqual(health["status"], "ok")
        self.assertTrue(health["h5"])
        self.assertGreaterEqual(health["snapshots"], 1)
        self.assertTrue(health["latest"])

        status, _, body = self.fetch("/api/snapshots")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(json.loads(body)), 1)

        status, _, body = self.fetch("/api/latest")
        self.assertEqual(status, 200)
        latest = json.loads(body)
        self.assertEqual(latest["meta"]["as_of"], self.fixture["today"])
        self.assertIn("advice", latest)

        status, headers, body = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type"))
        self.assertIn("A股量价监控", body.decode("utf-8"))

        status, _, body = self.fetch("/h5/index.html")
        self.assertEqual(status, 200)
        self.assertIn("历史快照", body.decode("utf-8"))

        status, _, body = self.fetch(f"/snapshots/{self.fixture['today']}/close.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["meta"]["session"], "close")

        status, _, _ = self.fetch("/h5/%2e%2e/snapshots/index.json")
        self.assertEqual(status, 403)
        status, _, _ = self.fetch("/missing")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
