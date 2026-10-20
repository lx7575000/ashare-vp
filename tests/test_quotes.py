from __future__ import annotations

import unittest
from datetime import datetime

from ashare_vp.quotes import (
    Quote,
    TZ,
    current_session_key,
    elapsed_fraction,
    quote_elapsed_fraction,
    session_elapsed_minutes,
    session_fraction,
    session_label,
)
from ashare_vp.session import session_is_replay
from ashare_vp.models import Asset

ETF = Asset("159999", "测试ETF", "测试", "etf", "SZ", "0.159999", "sz159999", "sz159999")
INDEX = Asset("000999", "测试指数", "测试", "index", "SH", "1.000999", "sh000999", "sh000999")


def quote_at(clock: str, volume=1000.0, amount=100000.0, turnover=2.0) -> Quote:
    return Quote(
        code="159999",
        name="测试ETF",
        price=1.05,
        prev_close=1.0,
        open=1.01,
        high=1.10,
        low=0.99,
        volume=volume,
        amount=amount,
        timestamp=f"20261016{clock}",
        turnover=turnover,
    )


class QuoteTests(unittest.TestCase):
    def test_session_fraction(self):
        self.assertAlmostEqual(session_fraction("1030"), 60 / 240)
        self.assertAlmostEqual(session_fraction("1100"), 90 / 240)
        self.assertAlmostEqual(session_fraction("1400"), 180 / 240)
        self.assertAlmostEqual(session_fraction("close"), 1.0)

    def test_quote_elapsed_fraction(self):
        self.assertAlmostEqual(quote_elapsed_fraction(quote_at("110000")), 90 / 240)
        self.assertAlmostEqual(quote_elapsed_fraction(quote_at("140000")), 180 / 240)
        self.assertAlmostEqual(quote_elapsed_fraction(quote_at("150000")), 1.0)
        self.assertAlmostEqual(quote_elapsed_fraction(quote_at("100000")), 30 / 240)

    def test_current_session_key(self):
        def at(hour, minute):
            return datetime(2026, 10, 16, hour, minute, tzinfo=TZ)

        self.assertEqual(current_session_key(at(10, 30)), "1030")
        self.assertEqual(current_session_key(at(10, 45)), "1030")
        self.assertEqual(current_session_key(at(11, 0)), "1100")
        self.assertEqual(current_session_key(at(14, 0)), "1400")
        self.assertEqual(current_session_key(at(15, 0)), "close")
        self.assertEqual(session_label("1030"), "10:30 盘中")

    def test_session_is_replay_when_clock_mismatches(self):
        def at(hour, minute):
            return datetime(2026, 10, 20, hour, minute, tzinfo=TZ)

        # 11:44 强制跑 14:00：数据是 11:44 的，应标记为回放。
        self.assertTrue(session_is_replay("1400", at(11, 44)))
        self.assertTrue(session_is_replay("close", at(11, 44)))
        self.assertFalse(session_is_replay("1100", at(11, 44)))
        # 真正 14:00 跑 14:00：不是回放。
        self.assertFalse(session_is_replay("1400", at(14, 0)))
        self.assertTrue(session_is_replay("close", at(14, 0)))
        # 收盘后跑收盘：不是回放。
        self.assertFalse(session_is_replay("close", at(15, 30)))
        self.assertTrue(session_is_replay("1400", at(15, 30)))

    def test_session_elapsed_minutes(self):
        morning = datetime(2026, 10, 16, 11, 0, tzinfo=TZ)
        afternoon = datetime(2026, 10, 16, 14, 0, tzinfo=TZ)
        close = datetime(2026, 10, 16, 15, 0, tzinfo=TZ)
        self.assertAlmostEqual(session_elapsed_minutes(morning), 90)
        self.assertAlmostEqual(session_elapsed_minutes(afternoon), 180)
        self.assertAlmostEqual(session_elapsed_minutes(close), 240)
        self.assertAlmostEqual(elapsed_fraction(morning), 90 / 240)

    def test_to_bar_projects_volume_and_amount(self):
        quote = quote_at("110000", volume=1000, amount=100000, turnover=2.0)
        bar = quote.to_bar(ETF, 0.5)
        self.assertAlmostEqual(bar.volume, 2000)
        self.assertAlmostEqual(bar.amount, 200000)
        self.assertAlmostEqual(bar.turnover, 4.0)
        self.assertEqual(bar.date, "2026-10-16")
        self.assertEqual(bar.close, 1.05)

    def test_index_turnover_not_projected(self):
        quote = quote_at("140000")
        bar = quote.to_bar(INDEX, 0.75)
        self.assertAlmostEqual(bar.volume, 1000 / 0.75)
        self.assertIsNone(bar.turnover)

    def test_quote_date_and_time(self):
        quote = quote_at("110000")
        self.assertEqual(quote.date, "2026-10-16")
        self.assertEqual(quote.time, "11:00:00")


if __name__ == "__main__":
    unittest.main()
