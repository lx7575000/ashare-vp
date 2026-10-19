from __future__ import annotations

import json
import unittest

from ashare_vp.analysis import analyze_asset, summarize_market
from ashare_vp.models import Asset

from helpers import make_bars

ASSET_ETF = Asset(
    code="159999",
    name="测试ETF",
    group="测试组",
    kind="etf",
    exchange="SZ",
    secid="0.159999",
    tencent="sz159999",
    sina="sz159999",
)

ASSET_INDEX = Asset(
    code="000999",
    name="测试指数",
    group="测试组",
    kind="index",
    exchange="SH",
    secid="1.000999",
    tencent="sh000999",
    sina="sh000999",
)


class AnalysisTests(unittest.TestCase):
    def test_volume_breakout(self):
        closes = [100.0] * 45 + [101, 102, 103, 104, 105, 106, 107, 108, 109, 112]
        volumes = [1000.0] * 54 + [3000.0]
        bars = make_bars(closes, volumes)
        result = analyze_asset(ASSET_ETF, bars, as_of=bars[-1].date)
        self.assertIsNotNone(result)
        self.assertTrue(result.new_high20)
        self.assertIn("放量突破", result.tags)
        self.assertGreater(result.score, 60)
        self.assertGreater(result.vol_ratio_5, 2.5)
        self.assertEqual(result.rating, "强势")

    def test_shrinking_pullback(self):
        closes = [100.0] * 45 + [101, 102, 103, 104, 105, 106, 107, 108, 109, 108.5]
        volumes = [1000.0] * 54 + [450.0]
        bars = make_bars(closes, volumes)
        result = analyze_asset(ASSET_ETF, bars, as_of=bars[-1].date)
        self.assertIsNotNone(result)
        self.assertIn("缩量回调", result.tags)
        self.assertLess(result.vol_ratio_5, 0.7)

    def test_top_divergence(self):
        closes = [100.0] * 40 + [95.0] + [96, 97, 98, 99, 101]
        volumes = [1000.0] * 40 + [10000.0] + [100.0] * 5
        bars = make_bars(closes, volumes)
        result = analyze_asset(ASSET_ETF, bars, as_of=bars[-1].date)
        self.assertIsNotNone(result)
        self.assertTrue(result.new_high20)
        self.assertFalse(result.obv_new_high20)
        self.assertIn("量价顶背离", result.risk_flags)
        self.assertIn("缩量新高", result.tags)

    def test_insufficient_data(self):
        bars = make_bars([100.0] * 10, [1000.0] * 10)
        self.assertIsNone(analyze_asset(ASSET_ETF, bars, as_of=bars[-1].date, min_bars=30))

    def test_as_of_filters_future_bars(self):
        bars = make_bars([100.0] * 40 + [200.0], [1000.0] * 41)
        cutoff = bars[-2].date
        result = analyze_asset(ASSET_ETF, bars, as_of=cutoff)
        self.assertIsNotNone(result)
        self.assertEqual(result.date, cutoff)
        self.assertLess(result.close, 150)

    def test_index_amount_not_estimated(self):
        bars = make_bars([3000.0] * 40, [100000.0] * 40)
        result = analyze_asset(ASSET_INDEX, bars, as_of=bars[-1].date)
        self.assertIsNotNone(result)
        self.assertIsNone(result.amount)
        self.assertFalse(result.amount_estimated)

    def test_etf_amount_estimated(self):
        bars = make_bars([1.0] * 40, [100000.0] * 40)
        result = analyze_asset(ASSET_ETF, bars, as_of=bars[-1].date)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.amount)
        self.assertTrue(result.amount_estimated)

    def test_to_dict_is_json_serializable(self):
        bars = make_bars([100.0 + i * 0.2 for i in range(60)], [1000.0] * 60)
        result = analyze_asset(ASSET_ETF, bars, as_of=bars[-1].date)
        payload = result.to_dict()
        json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["code"], ASSET_ETF.code)
        self.assertIn("score_breakdown", payload)

    def test_summarize_market(self):
        bars_up = make_bars([100.0] * 39 + [105.0], [2000.0] * 40)
        bars_down = make_bars([100.0] * 39 + [95.0], [2000.0] * 40)
        bars_flat = make_bars([100.0] * 40, [1000.0] * 40)
        analyses = [
            analyze_asset(ASSET_ETF, bars_up, as_of=bars_up[-1].date),
            analyze_asset(ASSET_INDEX, bars_down, as_of=bars_down[-1].date),
            analyze_asset(
                Asset("000998", "横盘指数", "测试组", "index", "SH", "1.000998", "sh000998", "sh000998"),
                bars_flat,
                as_of=bars_flat[-1].date,
            ),
        ]
        summary = summarize_market(analyses)
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["up"], 1)
        self.assertEqual(summary["down"], 1)
        self.assertIn("regime", summary)
        self.assertEqual(summary["groups"][0]["count"], 3)


if __name__ == "__main__":
    unittest.main()
