from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from ashare_vp.advice import generate_advice
from ashare_vp.analysis import analyze_asset, summarize_market
from ashare_vp.h5 import write_h5
from ashare_vp.models import Asset
from ashare_vp.snapshot import (
    build_series,
    list_snapshots,
    load_latest_snapshot,
    save_snapshot,
)

from helpers import make_bars

ASSET = Asset("159999", "测试ETF", "测试组", "etf", "SZ", "0.159999", "sz159999", "sz159999")


def make_data():
    bars = make_bars([1.0 + i * 0.002 for i in range(80)], [1000.0] * 80)
    analysis = analyze_asset(ASSET, bars, as_of=bars[-1].date)
    market = summarize_market([analysis])
    meta = {
        "as_of": bars[-1].date,
        "session": "1100",
        "session_label": "11:00 盘中",
        "generated_at": "2026-10-16T11:00:00+08:00",
        "asset_count": 1,
        "warnings": [],
    }
    advice = generate_advice([analysis], market, session="1100")
    series = {ASSET.code: build_series(bars)}
    return bars, analysis, market, meta, advice, series


class SnapshotH5Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_roundtrip(self):
        _, analysis, market, meta, advice, series = make_data()
        path = save_snapshot(
            self.root / "snapshots",
            meta,
            market,
            [analysis],
            advice,
            series=series,
            retain_days=0,
        )
        self.assertTrue(path.exists())
        loaded = load_latest_snapshot(self.root / "snapshots")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["meta"]["session"], "1100")
        self.assertEqual(len(loaded["assets"]), 1)
        self.assertIn("series", loaded["assets"][0])
        self.assertTrue((self.root / "snapshots" / "index.json").exists())

    def test_previous_snapshot_selection(self):
        _, analysis, market, meta, advice, series = make_data()
        save_snapshot(
            self.root / "snapshots", meta, market, [analysis], advice, series=series, retain_days=0
        )
        meta2 = dict(meta, session="1400", session_label="14:00 盘中")
        save_snapshot(
            self.root / "snapshots", meta2, market, [analysis], advice, series=series, retain_days=0
        )
        previous = load_latest_snapshot(
            self.root / "snapshots", before_key=f"{meta['as_of']}-1400"
        )
        self.assertIsNotNone(previous)
        self.assertEqual(previous["meta"]["session"], "1100")
        latest = load_latest_snapshot(self.root / "snapshots")
        self.assertEqual(latest["meta"]["session"], "1400")

    def test_h5_contains_embedded_data(self):
        _, analysis, market, meta, advice, series = make_data()
        paths = write_h5(
            self.root / "reports",
            meta,
            market,
            [analysis],
            advice,
            series=series,
            history=[],
        )
        html = paths[0].read_text(encoding="utf-8")
        self.assertNotIn("__PAYLOAD__", html)
        self.assertNotIn("__TITLE__", html)
        self.assertIn("A股量价监控", html)
        match = re.search(r"const DATA = (.*?);\nconst ASSETS", html, re.S)
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertEqual(len(data["assets"]), 1)
        self.assertEqual(data["assets"][0]["code"], ASSET.code)
        self.assertIn("series", data["assets"][0])
        self.assertTrue((self.root / "reports" / "h5" / "index.html").exists())


    def test_stale_index_entry_falls_back_to_previous(self):
        _, analysis, market, meta, advice, series = make_data()
        save_snapshot(
            self.root / "snapshots", meta, market, [analysis], advice, series=series, retain_days=0
        )
        meta2 = dict(meta, session="1400", session_label="14:00 盘中")
        save_snapshot(
            self.root / "snapshots", meta2, market, [analysis], advice, series=series, retain_days=0
        )
        index_path = self.root / "snapshots" / "index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["snapshots"].append(
            {
                "key": f"{meta['as_of']}-close",
                "date": meta["as_of"],
                "session": "close",
                "path": str(self.root / "snapshots" / meta["as_of"] / "missing.json"),
            }
        )
        index_path.write_text(json.dumps(payload), encoding="utf-8")

        latest = load_latest_snapshot(self.root / "snapshots")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["meta"]["session"], "1400")

    def test_old_snapshot_saved_alone_is_not_pruned(self):
        _, analysis, market, meta, advice, series = make_data()
        old_meta = dict(meta, as_of="2020-01-02", session="close", session_label="收盘")
        path = save_snapshot(
            self.root / "snapshots",
            old_meta,
            market,
            [analysis],
            advice,
            series=series,
            retain_days=180,
        )
        self.assertTrue(path.exists())
        keys = [entry["key"] for entry in list_snapshots(self.root / "snapshots")]
        self.assertIn("2020-01-02-close", keys)

    def test_prune_removes_old_snapshot_and_index_entry(self):
        _, analysis, market, meta, advice, series = make_data()
        old_meta = dict(meta, as_of="2020-01-02", session="close", session_label="收盘")
        old_path = save_snapshot(
            self.root / "snapshots",
            old_meta,
            market,
            [analysis],
            advice,
            series=series,
            retain_days=0,
        )
        new_meta = dict(meta, as_of="2026-10-16", session="close", session_label="收盘")
        save_snapshot(
            self.root / "snapshots",
            new_meta,
            market,
            [analysis],
            advice,
            series=series,
            retain_days=180,
        )
        self.assertFalse(old_path.exists())
        keys = [entry["key"] for entry in list_snapshots(self.root / "snapshots")]
        self.assertNotIn("2020-01-02-close", keys)
        self.assertIn("2026-10-16-close", keys)


if __name__ == "__main__":
    unittest.main()
