"""量价分析、信号识别与评分。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from statistics import fmean, median
from typing import Optional, Sequence

from . import indicators as ind
from .models import Asset, Bar


@dataclass
class AssetAnalysis:
    asset: Asset
    date: str
    bars_count: int
    close: float
    change_pct: Optional[float]
    change_5d_pct: Optional[float]
    change_20d_pct: Optional[float]
    open: float
    high: float
    low: float
    amplitude_pct: Optional[float]
    volume: float
    volume_ma5: Optional[float]
    volume_ma20: Optional[float]
    vol_ratio_5: Optional[float]
    vol_ratio_20: Optional[float]
    volume_percentile_60: Optional[float]
    amount: Optional[float]
    amount_estimated: bool
    turnover: Optional[float]
    ma5: Optional[float]
    ma10: Optional[float]
    ma20: Optional[float]
    ma60: Optional[float]
    ma20_slope_5: Optional[float]
    trend: str
    dist_ma20_pct: Optional[float]
    dist_ma60_pct: Optional[float]
    high20: Optional[float]
    low20: Optional[float]
    pos20: Optional[float]
    new_high20: bool
    new_low20: bool
    rsi14: Optional[float]
    mfi14: Optional[float]
    atr14: Optional[float]
    atr_pct: Optional[float]
    vwap20: Optional[float]
    dist_vwap20_pct: Optional[float]
    pv_corr20: Optional[float]
    obv: Optional[float]
    obv_ma20: Optional[float]
    obv_trend: str
    obv_new_high20: bool
    obv_new_low20: bool
    obv_slope_5: Optional[float]
    signal: str
    tags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    score: int = 50
    rating: str = "中性"
    score_breakdown: dict = field(default_factory=dict)
    source: str = ""
    cached: bool = False
    warning: Optional[str] = None

    def to_dict(self) -> dict:
        def r(value, digits=4):
            return None if value is None else round(value, digits)

        return {
            "code": self.asset.code,
            "name": self.asset.name,
            "group": self.asset.group,
            "kind": self.asset.kind,
            "date": self.date,
            "bars_count": self.bars_count,
            "close": r(self.close, 4),
            "change_pct": r(self.change_pct),
            "change_5d_pct": r(self.change_5d_pct),
            "change_20d_pct": r(self.change_20d_pct),
            "open": r(self.open, 4),
            "high": r(self.high, 4),
            "low": r(self.low, 4),
            "amplitude_pct": r(self.amplitude_pct),
            "volume": r(self.volume, 2),
            "volume_ma5": r(self.volume_ma5, 2),
            "volume_ma20": r(self.volume_ma20, 2),
            "vol_ratio_5": r(self.vol_ratio_5),
            "vol_ratio_20": r(self.vol_ratio_20),
            "volume_percentile_60": r(self.volume_percentile_60),
            "amount": r(self.amount, 2),
            "amount_estimated": self.amount_estimated,
            "turnover": r(self.turnover),
            "ma5": r(self.ma5, 4),
            "ma10": r(self.ma10, 4),
            "ma20": r(self.ma20, 4),
            "ma60": r(self.ma60, 4),
            "ma20_slope_5": r(self.ma20_slope_5),
            "trend": self.trend,
            "dist_ma20_pct": r(self.dist_ma20_pct),
            "dist_ma60_pct": r(self.dist_ma60_pct),
            "high20": r(self.high20, 4),
            "low20": r(self.low20, 4),
            "pos20": r(self.pos20),
            "new_high20": self.new_high20,
            "new_low20": self.new_low20,
            "rsi14": r(self.rsi14),
            "mfi14": r(self.mfi14),
            "atr14": r(self.atr14, 4),
            "atr_pct": r(self.atr_pct),
            "vwap20": r(self.vwap20, 4),
            "dist_vwap20_pct": r(self.dist_vwap20_pct),
            "pv_corr20": r(self.pv_corr20),
            "obv": r(self.obv, 2),
            "obv_ma20": r(self.obv_ma20, 2),
            "obv_trend": self.obv_trend,
            "obv_new_high20": self.obv_new_high20,
            "obv_new_low20": self.obv_new_low20,
            "obv_slope_5": r(self.obv_slope_5),
            "signal": self.signal,
            "tags": self.tags,
            "risk_flags": self.risk_flags,
            "score": self.score,
            "rating": self.rating,
            "score_breakdown": self.score_breakdown,
            "source": self.source,
            "cached": self.cached,
            "warning": self.warning,
        }


def analyze_asset(
    asset: Asset,
    bars: Sequence[Bar],
    as_of: Optional[str] = None,
    min_bars: int = 30,
    source: str = "",
    cached: bool = False,
    warning: Optional[str] = None,
) -> Optional[AssetAnalysis]:
    """计算单个标的截至 as_of 的量价指标。数据不足时返回 None。"""

    eligible = [bar for bar in bars if as_of is None or bar.date <= as_of]
    if len(eligible) < min_bars:
        return None
    eligible = sorted(eligible, key=lambda bar: bar.date)
    last = eligible[-1]
    prev = eligible[-2]

    closes = [bar.close for bar in eligible]
    volumes = [bar.volume for bar in eligible]
    highs = [bar.high for bar in eligible]
    lows = [bar.low for bar in eligible]

    change_pct = ind.pct_change(last.close, prev.close)
    change_5d_pct = ind.pct_change(last.close, closes[-6]) if len(closes) >= 6 else None
    change_20d_pct = ind.pct_change(last.close, closes[-21]) if len(closes) >= 21 else None
    amplitude_pct = (
        ind.safe_div(last.high - last.low, prev.close) * 100.0
        if ind.safe_div(last.high - last.low, prev.close) is not None
        else None
    )

    volume_ma5 = ind.sma_last(volumes, 5)
    volume_ma20 = ind.sma_last(volumes, 20)
    vol_ratio_5 = ind.volume_ratio(volumes, 5)
    vol_ratio_20 = ind.volume_ratio(volumes, 20)
    volume_percentile_60 = ind.percentile_rank(volumes, 60)

    amount = last.amount
    amount_estimated = False
    if amount is None and asset.is_etf:
        typical = (last.high + last.low + last.close) / 3.0
        amount = last.volume * 100.0 * typical
        amount_estimated = True

    ma5 = ind.sma_last(closes, 5)
    ma10 = ind.sma_last(closes, 10)
    ma20 = ind.sma_last(closes, 20)
    ma60 = ind.sma_last(closes, 60)

    ma20_series = ind.sma_series(closes, 20)
    ma20_slope_5 = None
    if len(ma20_series) >= 6 and ma20_series[-1] is not None and ma20_series[-6] is not None:
        ma20_slope_5 = ind.pct_change(ma20_series[-1], ma20_series[-6])

    trend = _trend_label(ma5, ma10, ma20, last.close)

    dist_ma20_pct = (
        ind.pct_change(last.close, ma20) if ma20 is not None else None
    )
    dist_ma60_pct = (
        ind.pct_change(last.close, ma60) if ma60 is not None else None
    )

    prev_window = eligible[-21:-1] if len(eligible) >= 21 else []
    high20 = max((bar.high for bar in prev_window), default=None)
    low20 = min((bar.low for bar in prev_window), default=None)
    new_high20 = high20 is not None and last.close > high20
    new_low20 = low20 is not None and last.close < low20

    window20 = eligible[-20:]
    range_high = max(bar.high for bar in window20)
    range_low = min(bar.low for bar in window20)
    pos20 = (
        (last.close - range_low) / (range_high - range_low) * 100.0
        if range_high > range_low
        else None
    )

    rsi14 = ind.rsi(closes, 14)
    mfi14 = ind.mfi(eligible, 14)
    atr14 = ind.atr(eligible, 14)
    atr_pct = (
        ind.safe_div(atr14, last.close) * 100.0
        if atr14 is not None and ind.safe_div(atr14, last.close) is not None
        else None
    )

    vwap20 = ind.vwap(eligible, 20)
    dist_vwap20_pct = (
        ind.pct_change(last.close, vwap20) if vwap20 is not None else None
    )
    pv_corr20 = ind.price_volume_correlation(eligible, 20)

    obv_values = ind.obv_series(eligible)
    obv = obv_values[-1] if obv_values else None
    obv_ma20 = ind.sma_last(obv_values, 20)
    obv_slope_5 = ind.normalized_slope(obv_values, 5)
    if len(obv_values) >= 6:
        obv_up = obv_values[-1] > obv_values[-6]
    else:
        obv_up = False
    if obv_ma20 is None:
        obv_trend = "数据不足"
    elif obv > obv_ma20 and obv_up:
        obv_trend = "上升"
    elif obv < obv_ma20 and not obv_up:
        obv_trend = "下降"
    else:
        obv_trend = "走平"

    obv_new_high20 = (
        len(obv_values) >= 21 and obv_values[-1] > max(obv_values[-21:-1])
    )
    obv_new_low20 = (
        len(obv_values) >= 21 and obv_values[-1] < min(obv_values[-21:-1])
    )

    tags, risk_flags = _signals(
        change_pct=change_pct,
        vol_ratio_5=vol_ratio_5,
        vol_ratio_20=vol_ratio_20,
        new_high20=new_high20,
        new_low20=new_low20,
        obv_new_high20=obv_new_high20,
        obv_new_low20=obv_new_low20,
        rsi14=rsi14,
        mfi14=mfi14,
        pos20=pos20,
    )

    breakdown = _score(
        close=last.close,
        change_pct=change_pct,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        ma60=ma60,
        ma20_slope_5=ma20_slope_5,
        vol_ratio_5=vol_ratio_5,
        vol_ratio_20=vol_ratio_20,
        new_high20=new_high20,
        new_low20=new_low20,
        obv=obv,
        obv_ma20=obv_ma20,
        obv_trend=obv_trend,
        obv_new_high20=obv_new_high20,
        rsi14=rsi14,
        mfi14=mfi14,
        pos20=pos20,
        risk_flags=risk_flags,
    )
    score = max(0, min(100, 50 + sum(breakdown.values())))
    rating = _rating(score)

    return AssetAnalysis(
        asset=asset,
        date=last.date,
        bars_count=len(eligible),
        close=last.close,
        change_pct=change_pct,
        change_5d_pct=change_5d_pct,
        change_20d_pct=change_20d_pct,
        open=last.open,
        high=last.high,
        low=last.low,
        amplitude_pct=amplitude_pct,
        volume=last.volume,
        volume_ma5=volume_ma5,
        volume_ma20=volume_ma20,
        vol_ratio_5=vol_ratio_5,
        vol_ratio_20=vol_ratio_20,
        volume_percentile_60=volume_percentile_60,
        amount=amount,
        amount_estimated=amount_estimated,
        turnover=last.turnover,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        ma60=ma60,
        ma20_slope_5=ma20_slope_5,
        trend=trend,
        dist_ma20_pct=dist_ma20_pct,
        dist_ma60_pct=dist_ma60_pct,
        high20=high20,
        low20=low20,
        pos20=pos20,
        new_high20=new_high20,
        new_low20=new_low20,
        rsi14=rsi14,
        mfi14=mfi14,
        atr14=atr14,
        atr_pct=atr_pct,
        vwap20=vwap20,
        dist_vwap20_pct=dist_vwap20_pct,
        pv_corr20=pv_corr20,
        obv=obv,
        obv_ma20=obv_ma20,
        obv_trend=obv_trend,
        obv_new_high20=obv_new_high20,
        obv_new_low20=obv_new_low20,
        obv_slope_5=obv_slope_5,
        signal="、".join(tags[:2] + risk_flags[:2]) if (tags or risk_flags) else "无",
        tags=tags,
        risk_flags=risk_flags,
        score=score,
        rating=rating,
        score_breakdown=breakdown,
        source=source,
        cached=cached,
        warning=warning,
    )


def _trend_label(ma5, ma10, ma20, close) -> str:
    if ma5 is None or ma10 is None or ma20 is None:
        return "数据不足"
    if ma5 > ma10 > ma20 and close > ma20:
        return "多头排列"
    if ma5 < ma10 < ma20 and close < ma20:
        return "空头排列"
    if close > ma20:
        return "均线交织偏强"
    if close < ma20:
        return "均线交织偏弱"
    return "均线交织"


def _signals(
    *,
    change_pct,
    vol_ratio_5,
    vol_ratio_20,
    new_high20,
    new_low20,
    obv_new_high20,
    obv_new_low20,
    rsi14,
    mfi14,
    pos20,
):
    tags: list[str] = []
    risks: list[str] = []

    ratio = vol_ratio_5
    if new_high20:
        if ratio is not None and ratio >= 1.3 and (change_pct or 0) > 0:
            tags.append("放量突破")
        elif ratio is not None and ratio < 0.8:
            tags.append("缩量新高")
        else:
            tags.append("收盘新高")
    elif new_low20:
        if ratio is not None and ratio >= 1.3 and (change_pct or 0) < 0:
            tags.append("放量破位")
        elif ratio is not None and ratio < 0.8:
            tags.append("缩量新低")
        else:
            tags.append("收盘新低")
    elif change_pct is not None and change_pct >= 1.0 and ratio is not None and ratio >= 1.5:
        tags.append("放量上涨")
    elif change_pct is not None and change_pct >= 1.0 and ratio is not None and ratio <= 0.7:
        tags.append("缩量上涨")
    elif change_pct is not None and change_pct <= -1.0 and ratio is not None and ratio >= 1.5:
        tags.append("放量下跌")
    elif change_pct is not None and change_pct < 0 and ratio is not None and ratio <= 0.7:
        tags.append("缩量回调")
    elif change_pct is not None and abs(change_pct) < 0.5 and ratio is not None and ratio >= 2.0:
        tags.append("放量滞涨")
    elif change_pct is not None and change_pct > 0:
        tags.append("温和上涨")
    elif change_pct is not None and change_pct < 0:
        tags.append("温和回调")
    else:
        tags.append("横盘")

    if new_high20 and not obv_new_high20 and ratio is not None and ratio < 1.0:
        risks.append("量价顶背离")
    if new_low20 and not obv_new_low20 and ratio is not None and ratio < 1.0:
        risks.append("量价底背离")
    if vol_ratio_20 is not None and vol_ratio_20 >= 2.5:
        risks.append("天量")
    if vol_ratio_20 is not None and vol_ratio_20 <= 0.5:
        risks.append("地量")
    if (rsi14 is not None and rsi14 >= 75) or (mfi14 is not None and mfi14 >= 85):
        risks.append("超买")
    if (rsi14 is not None and rsi14 <= 25) or (mfi14 is not None and mfi14 <= 15):
        risks.append("超卖")
    if pos20 is not None and pos20 >= 90 and ratio is not None and ratio >= 1.8:
        risks.append("高位放量")

    return _dedupe(tags), _dedupe(risks)


def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _score(
    *,
    close,
    change_pct,
    ma5,
    ma10,
    ma20,
    ma60,
    ma20_slope_5,
    vol_ratio_5,
    vol_ratio_20,
    new_high20,
    new_low20,
    obv,
    obv_ma20,
    obv_trend,
    obv_new_high20,
    rsi14,
    mfi14,
    pos20,
    risk_flags,
) -> dict:
    """返回各维度加减分（基准 50 分）。"""

    trend = 0
    if ma20 is not None:
        trend += 8 if close > ma20 else -8
    if None not in (ma5, ma10, ma20):
        if ma5 > ma10 > ma20:
            trend += 7
        elif ma5 < ma10 < ma20:
            trend -= 7
    if ma20_slope_5 is not None:
        if ma20_slope_5 > 0.3:
            trend += 5
        elif ma20_slope_5 < -0.3:
            trend -= 5
    if ma60 is not None:
        trend += 5 if close > ma60 else -5
    trend = max(-25, min(25, trend))

    volume = 0
    ratio = vol_ratio_5
    if change_pct is not None and ratio is not None:
        if change_pct > 0.05:
            if ratio >= 1.3:
                volume += 10
            elif ratio >= 1.0:
                volume += 6
            elif ratio >= 0.7:
                volume += 2
            else:
                volume -= 2
        elif change_pct < -0.05:
            if ratio <= 0.7:
                volume += 8
            elif ratio <= 1.0:
                volume += 4
            elif ratio >= 1.5:
                volume -= 8
            else:
                volume -= 2
    if new_high20 and ratio is not None:
        if ratio >= 1.3:
            volume += 7
        elif ratio < 0.8:
            volume -= 6
        else:
            volume += 2
    if new_low20 and ratio is not None:
        volume -= 8 if ratio >= 1.3 else 2
    if vol_ratio_20 is not None and vol_ratio_20 >= 2.5 and (change_pct or 0) < 0:
        volume -= 3
    volume = max(-15, min(20, volume))

    obv_score = 0
    if obv is not None and obv_ma20 is not None:
        obv_score += 6 if obv > obv_ma20 else -6
    if obv_trend == "上升":
        obv_score += 5
    elif obv_trend == "下降":
        obv_score -= 5
    if obv_new_high20:
        obv_score += 4
    if "量价顶背离" in risk_flags:
        obv_score -= 6
    if "量价底背离" in risk_flags:
        obv_score += 4
    obv_score = max(-15, min(20, obv_score))

    momentum = 0
    if rsi14 is not None:
        if 50 <= rsi14 < 70:
            momentum += 5
        elif 70 <= rsi14 < 80:
            momentum += 2
        elif rsi14 >= 80:
            momentum -= 4
        elif 30 <= rsi14 < 50:
            momentum += 2
        else:
            momentum -= 2
    if mfi14 is not None:
        if 50 <= mfi14 < 80:
            momentum += 5
        elif 80 <= mfi14 < 90:
            momentum += 0
        elif mfi14 >= 90:
            momentum -= 4
        elif 20 <= mfi14 < 50:
            momentum += 2
        else:
            momentum += 2
    momentum = max(-8, min(10, momentum))

    position = 0
    if pos20 is not None:
        if 50 <= pos20 <= 90:
            position += 3
        elif pos20 > 95:
            position -= 2
        elif pos20 < 20:
            position += 1
        else:
            position += 1

    return {
        "trend": trend,
        "volume": volume,
        "obv": obv_score,
        "momentum": momentum,
        "position": position,
    }


def _rating(score: int) -> str:
    if score >= 78:
        return "强势"
    if score >= 62:
        return "偏强"
    if score >= 45:
        return "中性"
    if score >= 30:
        return "偏弱"
    return "弱势"


def summarize_market(analyses: Sequence[AssetAnalysis], top_n: int = 5) -> dict:
    if not analyses:
        return {}

    changes = [a.change_pct for a in analyses if a.change_pct is not None]
    ratios = [a.vol_ratio_5 for a in analyses if a.vol_ratio_5 is not None]
    up = sum(1 for c in changes if c > 0.05)
    down = sum(1 for c in changes if c < -0.05)
    flat = len(changes) - up - down
    above_ma20 = sum(1 for a in analyses if a.ma20 is not None and a.close > a.ma20)
    above_pct = above_ma20 / len(analyses) * 100.0
    median_change = median(changes) if changes else None
    median_ratio = median(ratios) if ratios else None

    if above_pct >= 65 and (median_change or 0) > 0:
        regime = "偏强"
    elif above_pct <= 35 and (median_change or 0) < 0:
        regime = "偏弱"
    else:
        regime = "震荡"

    group_names = []
    for analysis in analyses:
        if analysis.asset.group not in group_names:
            group_names.append(analysis.asset.group)

    groups = []
    for name in group_names:
        members = [a for a in analyses if a.asset.group == name]
        member_changes = [a.change_pct for a in members if a.change_pct is not None]
        member_ratios = [a.vol_ratio_5 for a in members if a.vol_ratio_5 is not None]
        member_up = sum(1 for c in member_changes if c > 0.05)
        member_above = sum(1 for a in members if a.ma20 is not None and a.close > a.ma20)
        groups.append(
            {
                "name": name,
                "count": len(members),
                "avg_change_pct": round(fmean(member_changes), 4) if member_changes else None,
                "up_ratio": round(member_up / len(members) * 100.0, 2),
                "above_ma20_ratio": round(member_above / len(members) * 100.0, 2),
                "median_vol_ratio_5": round(median(member_ratios), 4) if member_ratios else None,
                "avg_score": round(fmean(a.score for a in members), 2),
            }
        )

    ranked = sorted(analyses, key=lambda a: (a.score, a.change_pct or 0), reverse=True)
    top = ranked[:top_n]
    bottom = sorted(analyses, key=lambda a: (a.score, a.change_pct or 0))[:top_n]
    volume_alerts = [
        a
        for a in analyses
        if (a.vol_ratio_5 is not None and a.vol_ratio_5 >= 1.5)
        or (a.vol_ratio_20 is not None and a.vol_ratio_20 >= 1.8)
    ]
    volume_alerts.sort(key=lambda a: max(a.vol_ratio_5 or 0, a.vol_ratio_20 or 0), reverse=True)
    divergences = [
        a for a in analyses if any(flag in a.risk_flags for flag in ("量价顶背离", "量价底背离"))
    ]

    def brief(a: AssetAnalysis) -> dict:
        return {
            "code": a.asset.code,
            "name": a.asset.name,
            "group": a.asset.group,
            "change_pct": round(a.change_pct, 4) if a.change_pct is not None else None,
            "vol_ratio_5": round(a.vol_ratio_5, 4) if a.vol_ratio_5 is not None else None,
            "score": a.score,
            "rating": a.rating,
            "signal": a.signal,
        }

    return {
        "count": len(analyses),
        "up": up,
        "down": down,
        "flat": flat,
        "up_ratio": round(up / len(analyses) * 100.0, 2),
        "above_ma20": above_ma20,
        "above_ma20_ratio": round(above_pct, 2),
        "median_change_pct": round(median_change, 4) if median_change is not None else None,
        "avg_change_pct": round(fmean(changes), 4) if changes else None,
        "median_vol_ratio_5": round(median_ratio, 4) if median_ratio is not None else None,
        "regime": regime,
        "groups": groups,
        "top": [brief(a) for a in top],
        "bottom": [brief(a) for a in bottom],
        "volume_alerts": [brief(a) for a in volume_alerts],
        "divergences": [brief(a) for a in divergences],
    }


def trade_date_gap(bar_date: str, as_of: str) -> int:
    """标的最新日期与目标日期相差的自然日。"""
    try:
        return (Date.fromisoformat(as_of) - Date.fromisoformat(bar_date)).days
    except ValueError:
        return 0
