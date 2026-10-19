"""纯函数形式的量价指标。"""

from __future__ import annotations

import math
from statistics import fmean
from typing import Optional, Sequence

from .models import Bar


Number = Optional[float]


def safe_div(numerator: float, denominator: float) -> Number:
    if denominator == 0 or not math.isfinite(denominator):
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def pct_change(current: float, previous: float) -> Number:
    if previous == 0:
        return None
    return (current / previous - 1.0) * 100.0


def sma_series(values: Sequence[float], window: int) -> list[Number]:
    if window <= 0:
        raise ValueError("window 必须大于 0")
    out: list[Number] = [None] * len(values)
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        if i >= window - 1:
            out[i] = total / window
    return out


def sma_last(values: Sequence[float], window: int) -> Number:
    if len(values) < window or window <= 0:
        return None
    return fmean(values[-window:])


def ema_series(values: Sequence[float], window: int) -> list[Number]:
    if window <= 0:
        raise ValueError("window 必须大于 0")
    out: list[Number] = [None] * len(values)
    if not values:
        return out
    alpha = 2.0 / (window + 1.0)
    ema = values[0]
    out[0] = ema
    for i in range(1, len(values)):
        ema = alpha * values[i] + (1 - alpha) * ema
        out[i] = ema
    return out


def rolling_std(values: Sequence[float], window: int) -> Number:
    if len(values) < window or window < 2:
        return None
    sample = values[-window:]
    mean = fmean(sample)
    variance = sum((x - mean) ** 2 for x in sample) / (window - 1)
    return math.sqrt(variance)


def correlation(xs: Sequence[float], ys: Sequence[float]) -> Number:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    n = len(xs)
    mx = fmean(xs)
    my = fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    value = cov / math.sqrt(vx * vy)
    return max(-1.0, min(1.0, value))


def rsi(closes: Sequence[float], window: int = 14) -> Number:
    """Wilder RSI。"""
    if len(closes) < window + 1:
        return None

    gains = 0.0
    losses = 0.0
    for i in range(1, window + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta

    avg_gain = gains / window
    avg_loss = losses / window

    for i in range(window + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    ranges: list[float] = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return ranges


def atr(bars: Sequence[Bar], window: int = 14) -> Number:
    ranges = true_ranges(bars)
    if len(ranges) < window:
        return None
    value = fmean(ranges[:window])
    for tr in ranges[window:]:
        value = (value * (window - 1) + tr) / window
    return value


def obv_series(bars: Sequence[Bar]) -> list[float]:
    if not bars:
        return []
    out = [0.0]
    for i in range(1, len(bars)):
        if bars[i].close > bars[i - 1].close:
            out.append(out[-1] + bars[i].volume)
        elif bars[i].close < bars[i - 1].close:
            out.append(out[-1] - bars[i].volume)
        else:
            out.append(out[-1])
    return out


def mfi(bars: Sequence[Bar], window: int = 14) -> Number:
    """Money Flow Index。"""
    if len(bars) < window + 1:
        return None

    typical = [(b.high + b.low + b.close) / 3.0 for b in bars]
    positive = 0.0
    negative = 0.0
    start = len(bars) - window
    for i in range(start, len(bars)):
        flow = typical[i] * bars[i].volume
        if typical[i] > typical[i - 1]:
            positive += flow
        elif typical[i] < typical[i - 1]:
            negative += flow

    if negative == 0:
        return 100.0
    ratio = positive / negative
    return 100.0 - 100.0 / (1.0 + ratio)


def vwap(bars: Sequence[Bar], window: int = 20) -> Number:
    if len(bars) < window or window <= 0:
        return None
    total_volume = 0.0
    total_value = 0.0
    for bar in bars[-window:]:
        typical = (bar.high + bar.low + bar.close) / 3.0
        total_volume += bar.volume
        total_value += typical * bar.volume
    return safe_div(total_value, total_volume)


def volume_ratio(volumes: Sequence[float], window: int) -> Number:
    """当日成交量 / 前 window 日均量（不含当日）。"""
    if len(volumes) < window + 1:
        return None
    base = fmean(volumes[-(window + 1) : -1])
    return safe_div(volumes[-1], base)


def percentile_rank(values: Sequence[float], window: int = 60) -> Number:
    """当前值在最近 window 个值中的分位（0-100）。"""
    if not values:
        return None
    sample = values[-window:]
    current = sample[-1]
    count = sum(1 for value in sample if value <= current)
    return count / len(sample) * 100.0


def price_volume_correlation(bars: Sequence[Bar], window: int = 20) -> Number:
    """近 window 日“收益率变化”与“成交量变化率”的相关系数。"""
    if len(bars) < window + 1:
        return None
    price_changes: list[float] = []
    volume_changes: list[float] = []
    for i in range(len(bars) - window, len(bars)):
        prev_close = bars[i - 1].close
        prev_volume = bars[i - 1].volume
        if prev_close == 0 or prev_volume == 0:
            continue
        price_changes.append((bars[i].close - prev_close) / prev_close)
        volume_changes.append((bars[i].volume - prev_volume) / prev_volume)
    return correlation(price_changes, volume_changes)


def slope_pct(values: Sequence[float], window: int = 5) -> Number:
    """近 window 个有效值的累计变化率（%）。"""
    if len(values) < window:
        return None
    start = values[-window]
    end = values[-1]
    if start == 0:
        return None
    return (end / start - 1.0) * 100.0


def normalized_slope(values: Sequence[float], window: int = 5) -> Number:
    """用均值归一化的区间斜率，适合 OBV 等无固定量纲的序列。"""
    if len(values) < window:
        return None
    sample = values[-window:]
    mean = fmean(sample)
    if mean == 0:
        return None
    return (sample[-1] - sample[0]) / abs(mean)
