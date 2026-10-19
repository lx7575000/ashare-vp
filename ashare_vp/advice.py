"""近高/近低监测、条件化量价建议与跨时段连贯性分析。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import fmean
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from .analysis import AssetAnalysis

TZ = ZoneInfo("Asia/Shanghai")
NEAR_THRESHOLD_PCT = 1.5

LEVEL_LABELS = {
    "A": "积极关注",
    "B": "谨慎参与",
    "C": "观察等待",
    "D": "风险回避",
}

POSITION_CAPS = {
    "偏强": {"A": "30%-40%", "B": "20%-30%", "C": "10%-20%", "D": "0%-10%"},
    "震荡": {"A": "20%-30%", "B": "10%-20%", "C": "0%-15%", "D": "0%-10%"},
    "偏弱": {"A": "10%-20%", "B": "5%-15%", "C": "0%-10%", "D": "0%-5%"},
}


@dataclass
class NearInfo:
    dist_high_pct: Optional[float]
    dist_low_pct: Optional[float]
    near_high: bool
    near_low: bool

    @property
    def label(self) -> str:
        if self.near_high and self.near_low:
            return "both"
        if self.near_high:
            return "high"
        if self.near_low:
            return "low"
        return "none"


def near_info(analysis: AssetAnalysis, threshold: float = NEAR_THRESHOLD_PCT) -> NearInfo:
    high20 = analysis.high20
    low20 = analysis.low20
    dist_high = (
        (analysis.close / high20 - 1.0) * 100.0 if high20 and high20 > 0 else None
    )
    dist_low = (analysis.close / low20 - 1.0) * 100.0 if low20 and low20 > 0 else None
    near_high = analysis.new_high20 or (
        dist_high is not None and 0 <= dist_high <= threshold
    )
    near_low = analysis.new_low20 or (
        dist_low is not None and 0 <= dist_low <= threshold
    )
    return NearInfo(dist_high, dist_low, near_high, near_low)


def generate_advice(
    analyses: Sequence[AssetAnalysis],
    market: dict,
    *,
    session: str = "close",
    previous_snapshot: Optional[dict] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """根据量价状态生成条件化建议、近高近低清单和连贯性对比。"""

    generated_at = generated_at or datetime.now(TZ).isoformat(timespec="seconds")
    regime = market.get("regime", "震荡")
    items = {}
    near_high = []
    near_low = []

    for analysis in analyses:
        info = near_info(analysis)
        item = _advice_for(analysis, regime, info)
        items[analysis.asset.code] = item
        if info.near_high:
            near_high.append(_near_brief(analysis, info, item, side="high"))
        if info.near_low:
            near_low.append(_near_brief(analysis, info, item, side="low"))

    near_high.sort(key=lambda x: (x["dist_high_pct"] is None, x["dist_high_pct"] or 0))
    near_low.sort(key=lambda x: (x["dist_low_pct"] is None, x["dist_low_pct"] or 0))

    return {
        "generated_at": generated_at,
        "session": session,
        "market": _market_advice(market, near_high, near_low),
        "items": items,
        "near_high": near_high,
        "near_low": near_low,
        "continuity": _continuity(analyses, market, previous_snapshot),
        "disclaimer": (
            "以上为基于公开行情与规则化量价模型的量化参考，不构成投资建议或收益承诺。"
            "A股波动较大，请结合自身风险承受能力、仓位管理与止损纪律独立决策。"
        ),
    }


def _advice_for(analysis: AssetAnalysis, regime: str, info: NearInfo) -> dict:
    ratio = analysis.vol_ratio_5
    score = analysis.score
    change = analysis.change_pct
    atr = analysis.atr14 or analysis.close * 0.02
    stop_1atr = analysis.close - 1.5 * atr
    ma20_stop = analysis.ma20 if analysis.ma20 and analysis.ma20 < analysis.close else None
    stop_price = min(stop_1atr, ma20_stop) if ma20_stop else stop_1atr
    near_low_stop = analysis.low20 if analysis.low20 else analysis.close * 0.95
    high_break = analysis.high20 or analysis.close

    level = "C"
    title = "中性观察"
    action = "量价未给出明确方向，等待放量突破或缩量回踩确认。"
    trigger = "放量站上 MA20，或回踩 MA20 缩量企稳"
    risk = "趋势与量能均未确认，避免频繁交易。"

    if info.near_low and ((ratio is not None and ratio >= 1.3) or score < 30):
        level = "D"
        title = "破位风险，优先回避"
        action = (
            "价格逼近/跌破 20 日低点且量能放大，说明抛压仍在释放。"
            "不建议逆势抄底，已有仓位优先控制回撤。"
        )
        trigger = "出现放量阳线并站回 MA20，或连续 2-3 日缩量止跌后再评估"
        risk = f"跌破近低 {near_low_stop:.3f} 后可能加速下行。"
    elif info.near_low:
        level = "C"
        title = "缩量近低，等待企稳"
        action = (
            "已接近 20 日低点，但量能未明显放大，属于“弱平衡”状态。"
            "可观察，不宜急于左侧抄底；等待放量止跌或底部结构确认。"
        )
        trigger = "放量收复 5 日线/MA20，且量比回升至 1.2 以上"
        risk = f"若放量跌破近低 {near_low_stop:.3f}，弱势可能延续。"
    elif info.near_high and ratio is not None and ratio >= 1.3 and score >= 50:
        level = "A" if score >= 65 else "B"
        title = "放量近高，突破确认"
        action = (
            "价格接近/突破 20 日高点且量能配合，属于量价共振。"
            "不追高，优先等回踩突破位不破后分批参与。"
        )
        trigger = f"回踩 {high_break:.3f} 附近缩量企稳，或次日继续放量站上"
        risk = f"跌回 {high_break:.3f} 下方则突破失效。"
    elif info.near_high:
        level = "C"
        title = "缩量近高，警惕背离"
        action = (
            "价格接近 20 日高点，但量能不足，突破持续性存疑。"
            "持有者可上移止盈，空仓者不宜追高。"
        )
        trigger = "放量突破前高并站稳 2 个交易日"
        risk = "缩量新高容易出现假突破或量价顶背离。"
    elif (
        analysis.ma20
        and analysis.trend != "空头排列"
        and -2.5 <= (analysis.dist_ma20_pct or -99) <= 1.5
        and ratio is not None
        and ratio <= 1.0
        and score >= 45
    ):
        level = "B"
        title = "回踩支撑，关注低吸"
        action = (
            "中期均线未破，价格回踩 MA20 且量能收缩，属于良性回踩。"
            "可小仓位试探，等待止跌信号确认后再加。"
        )
        trigger = f"MA20（{analysis.ma20:.3f}）附近止跌，量比回升"
        risk = f"收盘跌破 MA20 则回踩逻辑失效。"
        stop_price = analysis.ma20 * 0.985
    elif score >= 65 and analysis.ma20 and analysis.close > analysis.ma20:
        level = "B"
        title = "趋势偏强，持有为主"
        action = (
            "价格在 MA20 上方且趋势评分偏强，量价结构健康。"
            "以持有为主，回踩 MA5/MA10 再考虑加仓，不追高。"
        )
        trigger = "回踩 5/10 日线缩量企稳"
        risk = "若放量跌破 MA20，趋势转弱。"
    elif score <= 30:
        level = "D"
        title = "弱势，观望"
        action = "趋势与量能均偏弱，缺少可交易的量价信号，优先观望。"
        trigger = "放量收复 MA20 并形成更高低点"
        risk = "弱势反弹持续性通常较差。"

    position = POSITION_CAPS.get(regime, POSITION_CAPS["震荡"])[level]
    if analysis.risk_flags:
        risk = risk + " 风险标签：" + "、".join(analysis.risk_flags) + "。"

    return {
        "code": analysis.asset.code,
        "name": analysis.asset.name,
        "group": analysis.asset.group,
        "level": level,
        "level_label": LEVEL_LABELS[level],
        "title": title,
        "action": action,
        "trigger": trigger,
        "stop": f"{stop_price:.3f}（参考止损，约收盘价下方 1.5×ATR）",
        "position": position,
        "risk": risk,
        "score": score,
        "rating": analysis.rating,
        "signal": analysis.signal,
        "near": info.label,
        "change_pct": round(change, 4) if change is not None else None,
        "vol_ratio_5": round(ratio, 4) if ratio is not None else None,
    }


def _near_brief(analysis: AssetAnalysis, info: NearInfo, advice: dict, *, side: str) -> dict:
    return {
        "code": analysis.asset.code,
        "name": analysis.asset.name,
        "group": analysis.asset.group,
        "price": round(analysis.close, 4),
        "high20": round(analysis.high20, 4) if analysis.high20 else None,
        "low20": round(analysis.low20, 4) if analysis.low20 else None,
        "dist_high_pct": round(info.dist_high_pct, 2) if info.dist_high_pct is not None else None,
        "dist_low_pct": round(info.dist_low_pct, 2) if info.dist_low_pct is not None else None,
        "vol_ratio_5": round(analysis.vol_ratio_5, 2) if analysis.vol_ratio_5 is not None else None,
        "score": analysis.score,
        "signal": analysis.signal,
        "level": advice["level"],
        "level_label": advice["level_label"],
        "title": advice["title"],
        "side": side,
    }


def _market_advice(market: dict, near_high: list, near_low: list) -> dict:
    regime = market.get("regime", "震荡")
    breadth = market.get("above_ma20_ratio", 0)
    median_ratio = market.get("median_vol_ratio_5")
    groups = market.get("groups") or []
    best_group = max(groups, key=lambda g: g.get("avg_change_pct") or -99, default=None)
    worst_group = min(groups, key=lambda g: g.get("avg_change_pct") or 99, default=None)

    if regime == "偏强":
        level = "进攻"
        position = "40%-60%"
        summary = "市场广度偏强，量价结构支持顺势参与，但仍以回踩确认后的分批操作为主。"
    elif regime == "偏弱":
        level = "防守"
        position = "0%-20%"
        summary = "多数标的位于 20 日线下方，量价结构偏弱，优先控制回撤，等待放量收复关键均线。"
    else:
        level = "均衡"
        position = "20%-40%"
        summary = "市场多空交织，适合轻仓观察与结构性机会，避免在缩量反弹中追高。"

    bullets = [
        f"20 日线之上 {market.get('above_ma20', 0)}/{market.get('count', 0)}"
        f"（{breadth:.1f}%），中位量比 {market.get('median_vol_ratio_5', '-')}。",
        f"近高标的 {len(near_high)} 个，近低标的 {len(near_low)} 个；"
        "近高看量能确认，近低看止跌信号。",
    ]
    if best_group:
        bullets.append(
            f"相对强势分组：{best_group['name']}（平均 {best_group.get('avg_change_pct', 0):+.2f}%）。"
        )
    if worst_group and worst_group is not best_group:
        bullets.append(
            f"相对弱势分组：{worst_group['name']}（平均 {worst_group.get('avg_change_pct', 0):+.2f}%）。"
        )
    if median_ratio is not None and median_ratio < 0.9:
        bullets.append("全市场中位量能低于 1，反弹若持续缩量，需降低预期。")

    return {
        "level": level,
        "position": position,
        "summary": summary,
        "bullets": bullets,
        "risk": (
            "规则化信号存在滞后与假突破风险；若指数放量跌破近低，应进一步降低仓位。"
        ),
    }


def _continuity(
    analyses: Sequence[AssetAnalysis], market: dict, previous: Optional[dict]
) -> dict:
    if not previous:
        return {
            "available": False,
            "summary": "首次留存快照，暂无上一时段对比；从下一次 11:00/14:00 分析开始可追踪信号变化。",
            "changes": [],
            "market": None,
        }

    previous_assets = {
        item.get("code"): item for item in (previous.get("assets") or []) if item.get("code")
    }
    changes = []
    upgraded = downgraded = 0
    for analysis in analyses:
        old = previous_assets.get(analysis.asset.code)
        if not old:
            continue
        old_score = old.get("score", 50)
        delta = analysis.score - old_score
        if delta >= 5:
            upgraded += 1
        elif delta <= -5:
            downgraded += 1
        old_price = old.get("close")
        price_change = (
            (analysis.close / old_price - 1.0) * 100.0
            if old_price and old_price > 0
            else None
        )
        old_signal = old.get("signal")
        if abs(delta) >= 5 or old_signal != analysis.signal:
            changes.append(
                {
                    "code": analysis.asset.code,
                    "name": analysis.asset.name,
                    "group": analysis.asset.group,
                    "score_delta": delta,
                    "price_change_pct": round(price_change, 2) if price_change is not None else None,
                    "old_signal": old_signal,
                    "new_signal": analysis.signal,
                }
            )
    changes.sort(key=lambda x: abs(x["score_delta"]), reverse=True)

    old_meta = previous.get("meta") or {}
    old_market = previous.get("market") or {}
    old_regime = old_market.get("regime")
    regime_text = (
        f"市场状态由 {old_regime} 变为 {market.get('regime')}"
        if old_regime and old_regime != market.get("regime")
        else f"市场状态维持 {market.get('regime')}"
    )
    summary = (
        f"较 {old_meta.get('as_of', '')} {old_meta.get('session_label', '上一时段')}，"
        f"{regime_text}；评分上调 {upgraded} 个、下调 {downgraded} 个。"
    )
    return {
        "available": True,
        "summary": summary,
        "previous": {
            "as_of": old_meta.get("as_of"),
            "session": old_meta.get("session"),
            "session_label": old_meta.get("session_label"),
            "generated_at": old_meta.get("generated_at"),
        },
        "market": {
            "old_regime": old_regime,
            "new_regime": market.get("regime"),
            "old_above_ma20_ratio": old_market.get("above_ma20_ratio"),
            "new_above_ma20_ratio": market.get("above_ma20_ratio"),
        },
        "changes": changes[:20],
    }
