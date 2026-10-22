from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from ashare_vp.datasource import CachedSeries, DataFetcher, FetchError
from ashare_vp.models import Asset, Bar

from helpers import make_bars

ASSET = Asset(
    code="159999",
    name="测试ETF",
    group="测试组",
    kind="etf",
    exchange="SZ",
    secid="0.159999",
    tencent="sz159999",
    sina="sz159999",
)


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fetcher = DataFetcher(
            self.tmp.name,
            start_date="2026-01-01",
            end_date="2026-10-16",
            delay=0,
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch("ashare_vp.datasource._http_json")
    def test_tencent_parse(self, mock_http):
        mock_http.return_value = {
            "data": {
                "sz159999": {
                    "day": [
                        ["2026-10-15", "1.00", "1.10", "1.20", "0.90", "12345.000"],
                        ["2026-10-16", "1.10", "1.05", "1.15", "0.95", "23456.000"],
                    ]
                }
            }
        }
        bars = self.fetcher._fetch_tencent(ASSET)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[1].date, "2026-10-16")
        self.assertAlmostEqual(bars[1].open, 1.10)
        self.assertAlmostEqual(bars[1].close, 1.05)
        self.assertAlmostEqual(bars[1].high, 1.15)
        self.assertAlmostEqual(bars[1].low, 0.95)
        self.assertAlmostEqual(bars[1].volume, 23456.0)
        self.assertIsNone(bars[1].amount)

    @patch("ashare_vp.datasource._http_json")
    def test_sina_parse_converts_volume(self, mock_http):
        mock_http.return_value = [
            {
                "day": "2026-10-16",
                "open": "1.10",
                "high": "1.15",
                "low": "0.95",
                "close": "1.05",
                "volume": "2345600",
            }
        ]
        bars = self.fetcher._fetch_sina(ASSET)
        self.assertEqual(len(bars), 1)
        self.assertAlmostEqual(bars[0].volume, 23456.0)

    @patch("ashare_vp.datasource._http_json")
    def test_eastmoney_parse(self, mock_http):
        mock_http.return_value = {
            "data": {
                "klines": [
                    "2026-10-16,1.10,1.05,1.15,0.95,23456,9876543.0,1.2,1.0,-0.05,2.5"
                ]
            }
        }
        bars = self.fetcher._fetch_eastmoney(ASSET)
        self.assertEqual(len(bars), 1)
        self.assertAlmostEqual(bars[0].volume, 23456.0)
        self.assertAlmostEqual(bars[0].amount, 9876543.0)
        self.assertAlmostEqual(bars[0].turnover, 2.5)

    @patch("ashare_vp.datasource._http_json")
    def test_sina_null_raises(self, mock_http):
        mock_http.return_value = None
        with self.assertRaises(FetchError):
            self.fetcher._fetch_sina(ASSET)


class CacheAndNormalizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fetcher = DataFetcher(
            self.tmp.name,
            start_date="2025-01-01",
            end_date="2026-10-16",
            delay=0,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalize_deduplicates_and_fixes_ohlc(self):
        bars = [
            Bar("2026-10-16", 10, 9, 11, 10.5, 100),
            Bar("2026-10-15", 9, 9.5, 8.8, 9.2, 100),
            Bar("2026-10-16", 10, 10, 11, 10.5, 200),
            Bar("bad-date", 10, 10, 11, 10.5, 100),
        ]
        normalized = self.fetcher._normalize_bars(bars)
        self.assertEqual([bar.date for bar in normalized], ["2026-10-15", "2026-10-16"])
        self.assertEqual(normalized[1].volume, 200)
        self.assertGreaterEqual(normalized[0].high, max(normalized[0].open, normalized[0].close))

    def test_cache_roundtrip_and_fresh(self):
        bars = make_bars([100.0] * 40, [1000.0] * 40, start="2026-06-01")
        self.fetcher._save_cache(ASSET, bars, "test")
        cached = self.fetcher._load_cache(ASSET)
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached.bars), len(bars))
        self.assertEqual(cached.source, "test")
        self.assertTrue(self.fetcher._covers(cached, bars[-1].date))

    def test_fetch_falls_back_to_second_source(self):
        bars = make_bars([100.0] * 40, [1000.0] * 40, start="2026-06-01")
        calls = []

        def fake_source(source, asset):
            calls.append(source)
            if source == "tencent":
                raise FetchError("tencent down", network=True)
            return bars

        with patch.object(self.fetcher, "_fetch_source", side_effect=fake_source):
            result = self.fetcher.fetch(ASSET)
        self.assertEqual(calls, ["tencent", "sina"])
        self.assertEqual(result.source, "sina")
        self.assertFalse(result.cached)

    def test_offline_without_cache_raises(self):
        fetcher = DataFetcher(
            self.tmp.name,
            start_date="2025-01-01",
            end_date=date.today().isoformat(),
            offline=True,
            delay=0,
        )
        with self.assertRaises(FetchError):
            fetcher.fetch(ASSET)

    def test_stale_cache_fallback(self):
        bars = make_bars([100.0] * 40, [1000.0] * 40, start=(date.today() - timedelta(days=45)).isoformat())
        self.fetcher.end_date = date.today().isoformat()
        self.fetcher._save_cache(ASSET, bars, "test")
        # 手动把抓取时间改旧，使缓存不再“当日新鲜”
        path = self.fetcher._cache_path(ASSET)
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["fetched_at"] = "2020-01-01T00:00:00"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(
            self.fetcher, "_fetch_source", side_effect=FetchError("all down", network=True)
        ):
            result = self.fetcher.fetch(ASSET)
        self.assertTrue(result.cached)
        self.assertIsNotNone(result.warning)


if __name__ == "__main__":
    unittest.main()
