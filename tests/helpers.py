"""测试辅助。"""

from __future__ import annotations

from datetime import date, timedelta

from ashare_vp.models import Bar


def make_bars(closes, volumes=None, start="2025-01-01", amount=None):
    """根据收盘价序列构造连续日线。"""
    if volumes is None:
        volumes = [1000.0] * len(closes)
    current = date.fromisoformat(start)
    bars = []
    prev_close = closes[0]
    for i, close in enumerate(closes):
        open_price = prev_close if i else close
        high = max(open_price, close) * 1.005
        low = min(open_price, close) * 0.995
        bars.append(
            Bar(
                date=(current + timedelta(days=i)).isoformat(),
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close, 4),
                volume=float(volumes[i]),
                amount=amount,
            )
        )
        prev_close = close
    return bars
