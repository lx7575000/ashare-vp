from __future__ import annotations

import unittest

from ashare_vp.advice import generate_advice, near_info
from ashare_vp.analysis import analyze_asset, summarize_market
from ashare_vp.models import Asset

from helpers import make_bars

ASSET = Asset("159999", "测试ETF", "测试组", "etf", "SZ", "0.159999", "sz159999", "sz159999")


def analysis_for(closes, volumes):
    bars = make_bars(closes, volumes)
    return analyze_asset(ASSET, bars, as_of=bars[-1].date), bars


class AdviceTests(unittest.TestCase):
    def test_near_high_breakout_advice(self):
        closes = [100.0] * 45 + [101, 102, 103, 104, 105, 106, 107, 108, 109, 110.5]
        volumes = [1000.0] * 54 + [3000.0]
        analysis, _ = analysis_for(closes, volumes)
        info = near_info(analysis)
        self.assertTrue(info.near_high)
        market = summarize_market([analysis])
        advice = generate_advice([analysis], market)
        item = advice["items"][ASSET.code]
        self.assertIn(item["level"], {"A", "B"})
        self.assertEqual(advice["near_high"][0]["code"], ASSET.code)
        self.assertIn("突破", item["title"])

    def test_near_low_breakdown_advice(self):
        closes = [100.0] * 45 + [99, 98, 97, 96, 95, 94, 93, 92, 91, 89]
        volumes = [1000.0] * 54 + [3500.0]
        analysis, _ = analysis_for(closes, volumes)
        info = near_info(analysis)
        self.assertTrue(info.near_low)
        market = summarize_market([analysis])
        advice = generate_advice([analysis], market)
        item = advice["items"][ASSET.code]
        self.assertEqual(item["level"], "D")
        self.assertEqual(advice["near_low"][0]["code"], ASSET.code)
        self.assertIn("破位", item["title"])

    def test_market_advice_contains_position(self):
        closes = [100.0] * 60
        analysis, _ = analysis_for(closes, [1000.0] * 60)
        market = summarize_market([analysis])
        advice = generate_advice([analysis], market)
        self.assertIn("level", advice["market"])
        self.assertIn("position", advice["market"])
        self.assertTrue(advice["disclaimer"])

    def test_continuity_from_previous_snapshot(self):
        closes = [100.0] * 45 + [101, 102, 103, 104, 105, 106, 107, 108, 109, 110.5]
        analysis, _ = analysis_for(closes, [1000.0] * 54 + [3000.0])
        market = summarize_market([analysis])
        previous_asset = analysis.to_dict()
        previous_asset["score"] = max(0, analysis.score - 12)
        previous_asset["signal"] = "温和上涨"
        previous = {
            "meta": {
                "as_of": "2026-10-16",
                "session": "1100",
                "session_label": "11:00 盘中",
                "generated_at": "2026-10-16T11:00:00+08:00",
            },
            "market": {"regime": "震荡", "above_ma20_ratio": 40},
            "assets": [previous_asset],
        }
        advice = generate_advice([analysis], market, previous_snapshot=previous)
        continuity = advice["continuity"]
        self.assertTrue(continuity["available"])
        self.assertTrue(continuity["changes"])
        self.assertGreater(continuity["changes"][0]["score_delta"], 0)

    def test_first_snapshot_continuity(self):
        analysis, _ = analysis_for([100.0] * 60, [1000.0] * 60)
        market = summarize_market([analysis])
        advice = generate_advice([analysis], market, previous_snapshot=None)
        self.assertFalse(advice["continuity"]["available"])


if __name__ == "__main__":
    unittest.main()
