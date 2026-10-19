from __future__ import annotations

import unittest

from ashare_vp import indicators as ind
from ashare_vp.models import Bar

from helpers import make_bars


class IndicatorTests(unittest.TestCase):
    def test_sma_series(self):
        values = [1, 2, 3, 4, 5]
        self.assertEqual(ind.sma_series(values, 3), [None, None, 2.0, 3.0, 4.0])
        self.assertEqual(ind.sma_last(values, 2), 4.5)
        self.assertIsNone(ind.sma_last(values, 10))

    def test_pct_change_and_safe_div(self):
        self.assertAlmostEqual(ind.pct_change(110, 100), 10.0)
        self.assertIsNone(ind.pct_change(1, 0))
        self.assertIsNone(ind.safe_div(1, 0))

    def test_volume_ratio_excludes_current(self):
        volumes = [100, 100, 100, 100, 100, 200]
        self.assertAlmostEqual(ind.volume_ratio(volumes, 5), 2.0)
        self.assertAlmostEqual(ind.volume_ratio(volumes, 3), 2.0)

    def test_obv_direction(self):
        bars = make_bars([10, 11, 10, 10, 12], [100, 200, 300, 400, 500])
        obv = ind.obv_series(bars)
        self.assertEqual(obv, [0.0, 200.0, -100.0, -100.0, 400.0])

    def test_rsi_all_gains(self):
        closes = list(range(1, 30))
        self.assertAlmostEqual(ind.rsi(closes, 14), 100.0)

    def test_mfi_bounds(self):
        bars = make_bars([10 + i * 0.1 for i in range(30)], [1000] * 30)
        value = ind.mfi(bars, 14)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 0)
        self.assertLessEqual(value, 100)

    def test_atr_positive(self):
        bars = make_bars([10 + (i % 3) for i in range(30)], [1000] * 30)
        value = ind.atr(bars, 14)
        self.assertIsNotNone(value)
        self.assertGreater(value, 0)

    def test_vwap_and_correlation(self):
        bars = make_bars([10, 11, 12, 13, 14], [100, 100, 100, 100, 100])
        vwap = ind.vwap(bars, 5)
        self.assertIsNotNone(vwap)
        self.assertGreater(vwap, 10)
        corr = ind.price_volume_correlation(
            make_bars([100, 101, 103.02, 106.1106, 110.354, 115.872], [100, 110, 132, 171.6, 240.24, 360.36]), 5
        )
        self.assertAlmostEqual(corr, 1.0, places=5)

    def test_percentile_rank(self):
        self.assertAlmostEqual(ind.percentile_rank([1, 2, 3, 4, 5], 5), 100.0)
        self.assertAlmostEqual(ind.percentile_rank([5, 4, 3, 2, 1], 5), 20.0)


if __name__ == "__main__":
    unittest.main()
