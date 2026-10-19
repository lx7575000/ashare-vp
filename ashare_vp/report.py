"""日报渲染：Markdown / JSON / CSV / 控制台。"""

from __future__ import annotations

import csv
import json
import unicodedata
from pathlib import Path
from typing import Optional, Sequence

from .analysis import AssetAnalysis
from .models import Config


# --------------------------------------------------------------------- format
def fmt_num(value, digits: int = 2, dash: str = "-") -> str:
    if value is None:
        return dash
    return f"{value:.{digits}f}"


def fmt_pct(value, digits: int = 2, signed: bool = True) -> str:
    if value is None:
        return "-"
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def fmt_price(value, asset) -> str:
    if value is None:
        return "-"
    digits = 3 if asset.is_etf and value < 10 else 2
    return f"{value:.{digits}f}"


def fmt_volume(volume_lots) -> str:
    if volume_lots is None:
        return "-"
    if volume_lots >= 1e8:
        return f"{volume_lots / 1e8:.2f}亿手"
    if volume_lots >= 1e4:
        return f"{volume_lots / 1e4:.1f}万手"
    return f"{volume_lots:.0f}手"


def fmt_amount(amount_yuan, estimated: bool = False) -> str:
    if amount_yuan is None:
        return "-"
    prefix = "~" if estimated else ""
    if amount_yuan >= 1e8:
        return f"{prefix}{amount_yuan / 1e8:.2f}亿"
    if amount_yuan >= 1e4:
        return f"{prefix}{amount_yuan / 1e4:.1f}万"
    return f"{prefix}{amount_yuan:.0f}"


def fmt_score_breakdown(breakdown: dict) -> str:
    labels = [("trend", "趋势"), ("volume", "量能"), ("obv", "OBV"), ("momentum", "动量"), ("position", "位置")]
    parts = []
    for key, label in labels:
        value = breakdown.get(key, 0)
        parts.append(f"{label}{value:+d}")
    return " ".join(parts)


def display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def pad(text: str, width: int, align: str = "left") -> str:
    padding = max(0, width - display_width(text))
    if align == "right":
        return " " * padding + text
    if align == "center":
        left = padding // 2
        return " " * left + text + " " * (padding - left)
    return text + " " * padding


def table(headers: Sequence[str], rows: Sequence[Sequence], aligns: Optional[Sequence[str]] = None) -> str:
    aligns = list(aligns or ["left"] * len(headers))
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "|" + "|".join("---:" if a == "right" else "---" for a in aligns) + "|",
    ]
    for row in rows:
        cells = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ------------------------------------------------------------------- markdown
def render_markdown(
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    config: Config,
    *,
    top_n: int = 5,
    detail: bool = False,
    advice: Optional[dict] = None,
) -> str:
    as_of = meta["as_of"]
    lines: list[str] = []
    lines.append(f"# A股量价日报 · {as_of}")
    lines.append("")
    lines.append(
        f"> 生成时间：{meta['generated_at']}　｜　数据源：{_sources_text(meta.get('sources'))}"
        f"　｜　标的数：{len(analyses)}"
    )
    if meta.get("requested_date") and meta["requested_date"] != as_of:
        lines.append(
            f"> 请求日期 {meta['requested_date']} 非交易日或行情未更新，已使用最近交易日 {as_of}。"
        )
    if meta.get("offline"):
        lines.append("> 当前为离线模式，全部数据来自本地缓存。")
    lines.append("")

    if meta.get("warnings"):
        lines.append("> **数据提示**：" + "；".join(meta["warnings"]))
        lines.append("")
    if meta.get("failures"):
        failed = "、".join(f"{item['name']}({item['code']})" for item in meta["failures"][:6])
        lines.append(f"> **未纳入分析**：{failed}")
        lines.append("")

    # 一、市场概览
    lines.append("## 一、市场概览")
    lines.append("")
    if market:
        etf_count = sum(1 for a in analyses if a.asset.is_etf)
        index_count = len(analyses) - etf_count
        lines.append(
            f"- **标的构成**：{len(analyses)} 个（ETF {etf_count} 个、宽基指数 {index_count} 个）"
        )
        lines.append(
            f"- **涨跌分布**：上涨 {market['up']} 家、下跌 {market['down']} 家、平盘 {market['flat']} 家，"
            f"上涨占比 {market['up_ratio']:.1f}%"
        )
        lines.append(
            f"- **20日线之上**：{market['above_ma20']}/{market['count']} "
            f"（{market['above_ma20_ratio']:.1f}%）"
        )
        lines.append(
            f"- **中位涨跌幅**：{fmt_pct(market['median_change_pct'])}　｜　"
            f"**中位量比(5日)**：{fmt_num(market['median_vol_ratio_5'])}"
        )
        lines.append(f"- **市场状态**：**{market['regime']}**（{_regime_text(market['regime'])}）")
        lines.append("")

        if market.get("groups"):
            lines.append("### 分组表现")
            lines.append("")
            rows = []
            for group in market["groups"]:
                rows.append(
                    [
                        group["name"],
                        group["count"],
                        fmt_pct(group["avg_change_pct"]),
                        f"{group['up_ratio']:.1f}%",
                        f"{group['above_ma20_ratio']:.1f}%",
                        fmt_num(group["median_vol_ratio_5"]),
                        fmt_num(group["avg_score"], 1),
                    ]
                )
            lines.append(
                table(
                    ["分组", "数量", "平均涨跌", "上涨占比", "MA20上方", "中位量比5", "平均评分"],
                    rows,
                    ["left", "right", "right", "right", "right", "right", "right"],
                )
            )
            lines.append("")

    if advice:
        lines.extend(_render_advice(advice, analyses))

    # 二、重点信号
    lines.append("## 二、重点信号")
    lines.append("")
    lines.append(f"### 相对强势榜 Top {top_n}")
    lines.append("")
    lines.append(_brief_table(market.get("top", []), "排名"))
    lines.append("")
    lines.append(f"### 相对弱势榜 Bottom {top_n}")
    lines.append("")
    lines.append(_brief_table(market.get("bottom", []), "排名"))
    lines.append("")

    lines.append("### 放量异动")
    lines.append("")
    if market.get("volume_alerts"):
        rows = [
            [
                item["code"],
                item["name"],
                item["group"],
                fmt_pct(item["change_pct"]),
                fmt_num(item["vol_ratio_5"]),
                f"{item['score']}",
                item["signal"],
            ]
            for item in market["volume_alerts"][:top_n]
        ]
        lines.append(
            table(
                ["代码", "名称", "分组", "涨跌%", "量比5", "评分", "信号"],
                rows,
                ["left", "left", "left", "right", "right", "right", "left"],
            )
        )
    else:
        lines.append("暂无显著放量异动。")
    lines.append("")

    lines.append("### 量价背离")
    lines.append("")
    if market.get("divergences"):
        rows = [
            [
                item["code"],
                item["name"],
                item["group"],
                fmt_pct(item["change_pct"]),
                fmt_num(item["vol_ratio_5"]),
                item["signal"],
            ]
            for item in market["divergences"][:top_n]
        ]
        lines.append(
            table(
                ["代码", "名称", "分组", "涨跌%", "量比5", "信号"],
                rows,
                ["left", "left", "left", "right", "right", "left"],
            )
        )
    else:
        lines.append("暂未识别到量价背离。")
    lines.append("")

    # 三、分组明细
    lines.append("## 三、分组明细")
    lines.append("")
    by_code = {a.asset.code: a for a in analyses}
    for group in config.groups:
        members = [by_code[asset.code] for asset in group.assets if asset.code in by_code]
        if not members:
            continue
        lines.append(f"### {group.name}（{len(members)}）")
        lines.append("")
        rows = []
        for item in members:
            rows.append(
                [
                    item.asset.code,
                    item.asset.name,
                    fmt_price(item.close, item.asset),
                    fmt_pct(item.change_pct),
                    fmt_pct(item.change_5d_pct),
                    fmt_num(item.vol_ratio_5),
                    fmt_num(item.vol_ratio_20),
                    fmt_amount(item.amount, item.amount_estimated),
                    fmt_pct(item.dist_ma20_pct),
                    f"{item.score}",
                    item.rating,
                    item.signal,
                ]
            )
        lines.append(
            table(
                ["代码", "名称", "收盘", "涨跌%", "5日%", "量比5", "量比20", "成交额", "MA20偏离", "评分", "评级", "信号"],
                rows,
                ["left", "left", "right", "right", "right", "right", "right", "right", "right", "right", "center", "left"],
            )
        )
        lines.append("")

    # 四、全量评分排序
    lines.append("## 四、全量评分排序")
    lines.append("")
    ranked = sorted(analyses, key=lambda a: (a.score, a.change_pct or 0), reverse=True)
    advice_items = (advice or {}).get("items") or {}
    rows = []
    for rank, item in enumerate(ranked, 1):
        row = [
            rank,
            item.asset.code,
            item.asset.name,
            item.asset.group,
            fmt_price(item.close, item.asset),
            fmt_pct(item.change_pct),
            fmt_pct(item.change_5d_pct),
            fmt_num(item.vol_ratio_5),
            f"{item.score}",
            item.rating,
            item.signal,
        ]
        if advice is not None:
            row.append((advice_items.get(item.asset.code) or {}).get("level_label", "-"))
        rows.append(row)
    headers = ["排名", "代码", "名称", "分组", "收盘", "涨跌%", "5日%", "量比5", "评分", "评级", "信号"]
    aligns = ["right", "left", "left", "left", "right", "right", "right", "right", "right", "center", "left"]
    if advice is not None:
        headers.append("建议")
        aligns.append("center")
    lines.append(table(headers, rows, aligns))
    lines.append("")

    # 五、指标明细
    if detail:
        lines.append("## 五、指标明细")
        lines.append("")
        rows = []
        for item in analyses:
            rows.append(
                [
                    item.asset.code,
                    item.asset.name,
                    fmt_price(item.ma5, item.asset),
                    fmt_price(item.ma10, item.asset),
                    fmt_price(item.ma20, item.asset),
                    fmt_price(item.ma60, item.asset),
                    fmt_num(item.rsi14, 1),
                    fmt_num(item.mfi14, 1),
                    fmt_pct(item.atr_pct, signed=False),
                    fmt_pct(item.dist_vwap20_pct),
                    fmt_num(item.pv_corr20),
                    fmt_num(item.obv_slope_5, 3),
                    fmt_score_breakdown(item.score_breakdown),
                ]
            )
        lines.append(
            table(
                ["代码", "名称", "MA5", "MA10", "MA20", "MA60", "RSI14", "MFI14", "ATR%", "VWAP20偏离", "量价相关", "OBV5", "评分拆解"],
                rows,
                ["left", "left", "right", "right", "right", "right", "right", "right", "right", "right", "right", "right", "left"],
            )
        )
        lines.append("")

    # 说明
    lines.append("## 指标说明")
    lines.append("")
    lines.append("- **量比5/20**：当日成交量 ÷ 前 5/20 个交易日均量（不含当日），衡量放量/缩量程度。")
    lines.append("- **MA20偏离**：收盘价相对 20 日均线的偏离百分比；正值表示在均线上方。")
    lines.append("- **OBV**：能量潮，按涨跌方向累加/扣减成交量；OBV 与价格背离常被视为资金流向的警示。")
    lines.append("- **MFI14**：资金流量指标，结合价格与成交量，>80 偏热、<20 偏冷。")
    lines.append("- **量价相关**：近 20 日收益率变化与成交量变化率的相关系数，正值表示涨跌与量能同向。")
    lines.append("- **评分**：以 50 分为基准，综合趋势、量能、OBV、动量、位置五个维度，范围 0–100；仅为量化打分，不构成买卖建议。")
    lines.append("- **信号**：放量突破、缩量新高、放量下跌、缩量回调、量价顶/底背离、天量/地量、超买/超卖等规则组合。")
    lines.append("")
    lines.append("## 数据说明")
    lines.append("")
    lines.append("- 日线数据来自腾讯财经/新浪财经/东方财富公开行情接口，成交量统一换算为“手”。")
    lines.append("- ETF 成交额在数据源未提供时按“成交量 × 100 × 当日均价”估算，并以 `~` 标注；指数不估算成交额。")
    lines.append("- 行情接口可能存在延迟、停牌或复权差异，请以交易所及基金公司公告为准。")
    lines.append("")
    lines.append("> 免责声明：本报告仅用于量化研究与学习，不构成任何投资建议。市场有风险，投资需谨慎。")
    lines.append("")
    return "\n".join(lines)


def _render_advice(advice: dict, analyses: Sequence[AssetAnalysis]) -> list[str]:
    """把条件化建议压缩成日报中的一段，完整数据仍在 JSON/CSV。"""
    lines = ["### 操作建议", ""]
    market = advice.get("market") or {}
    if market:
        lines.append(
            f"- **市场判断**：{market.get('level', '-')}　｜　参考仓位 {market.get('position', '-')}"
        )
        if market.get("summary"):
            lines.append(f"- **结论**：{market['summary']}")
        for bullet in (market.get("bullets") or [])[:3]:
            lines.append(f"- {bullet}")

    near_high = advice.get("near_high") or []
    near_low = advice.get("near_low") or []
    lines.append(f"- **近高/近低**：{len(near_high)} / {len(near_low)} 个标的")
    continuity = advice.get("continuity") or {}
    if continuity.get("available") and continuity.get("summary"):
        lines.append(f"- **跨时段对比**：{continuity['summary']}")
    lines.append("")

    items = advice.get("items") or {}
    rows = []
    for item in sorted(analyses, key=lambda a: a.score, reverse=True):
        info = items.get(item.asset.code) or {}
        if info.get("level") not in {"A", "B", "D"}:
            continue
        stop = str(info.get("stop") or "-").split("（", 1)[0]
        rows.append(
            [
                info.get("level_label", "-"),
                item.asset.code,
                item.asset.name,
                info.get("title", "-"),
                info.get("trigger", "-"),
                stop,
                info.get("position", "-"),
            ]
        )
    if rows:
        lines.append(
            table(
                ["建议", "代码", "名称", "结论", "触发条件", "参考止损", "参考仓位"],
                rows[:10],
                ["center", "left", "left", "left", "left", "right", "center"],
            )
        )
        if len(rows) > 10:
            lines.append("")
            lines.append(f"其余 {len(rows) - 10} 条建议见 JSON / CSV。")
    else:
        lines.append("当前没有 A/B/D 级条件化建议，保持观察。")
    lines.append("")
    lines.append("> 以上为规则化量价建议，仅供研究参考，不构成投资建议。")
    lines.append("")
    return lines


def _brief_table(items: Sequence[dict], rank_header: str = "排名") -> str:
    if not items:
        return "暂无数据。"
    rows = []
    for rank, item in enumerate(items, 1):
        rows.append(
            [
                rank,
                item["code"],
                item["name"],
                item["group"],
                fmt_pct(item["change_pct"]),
                fmt_num(item["vol_ratio_5"]),
                f"{item['score']}",
                item["rating"],
                item["signal"],
            ]
        )
    return table(
        [rank_header, "代码", "名称", "分组", "涨跌%", "量比5", "评分", "评级", "信号"],
        rows,
        ["right", "left", "left", "left", "right", "right", "right", "center", "left"],
    )


def _sources_text(sources: Optional[dict]) -> str:
    if not sources:
        return "本地缓存"
    names = {"tencent": "腾讯财经", "sina": "新浪财经", "eastmoney": "东方财富", "cache": "本地缓存"}
    return "、".join(f"{names.get(key, key)}×{value}" for key, value in sources.items())


def _regime_text(regime: str) -> str:
    if regime == "偏强":
        return "多数标的站上20日线，中位涨跌幅为正"
    if regime == "偏弱":
        return "多数标的位于20日线下方，中位涨跌幅为负"
    return "多空交织，趋势性不强"


# ----------------------------------------------------------------------- json
def build_json(
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    advice: Optional[dict] = None,
) -> dict:
    items = (advice or {}).get("items") or {}
    assets = []
    for item in analyses:
        payload = item.to_dict()
        if advice is not None:
            payload["advice"] = items.get(item.asset.code)
        assets.append(payload)
    result = {
        "meta": meta,
        "market": market,
        "assets": assets,
    }
    if advice is not None:
        result["advice"] = advice
    return result


# ------------------------------------------------------------------------ csv
CSV_FIELDS = [
    "date",
    "code",
    "name",
    "group",
    "kind",
    "close",
    "change_pct",
    "change_5d_pct",
    "change_20d_pct",
    "volume",
    "volume_ma5",
    "volume_ma20",
    "vol_ratio_5",
    "vol_ratio_20",
    "volume_percentile_60",
    "amount",
    "amount_estimated",
    "turnover",
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "ma20_slope_5",
    "trend",
    "dist_ma20_pct",
    "dist_ma60_pct",
    "high20",
    "low20",
    "pos20",
    "new_high20",
    "new_low20",
    "rsi14",
    "mfi14",
    "atr14",
    "atr_pct",
    "vwap20",
    "dist_vwap20_pct",
    "pv_corr20",
    "obv",
    "obv_ma20",
    "obv_trend",
    "obv_new_high20",
    "obv_new_low20",
    "obv_slope_5",
    "signal",
    "tags",
    "risk_flags",
    "score",
    "rating",
    "source",
    "cached",
    "warning",
    "advice_level",
    "advice_level_label",
    "advice_title",
    "advice_position",
    "advice_trigger",
    "advice_stop",
    "advice_near",
]


def write_csv(
    path: Path,
    analyses: Sequence[AssetAnalysis],
    advice: Optional[dict] = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    items = (advice or {}).get("items") or {}
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in analyses:
            row = item.to_dict()
            row["tags"] = "、".join(item.tags)
            row["risk_flags"] = "、".join(item.risk_flags)
            if advice is not None:
                info = items.get(item.asset.code) or {}
                row.update(
                    {
                        "advice_level": info.get("level"),
                        "advice_level_label": info.get("level_label"),
                        "advice_title": info.get("title"),
                        "advice_position": info.get("position"),
                        "advice_trigger": info.get("trigger"),
                        "advice_stop": info.get("stop"),
                        "advice_near": info.get("near"),
                    }
                )
            writer.writerow(row)


# --------------------------------------------------------------------- output
def write_outputs(
    output_dir: str | Path,
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    config: Config,
    *,
    formats: Sequence[str] = ("md", "json", "csv"),
    detail: bool = False,
    top_n: int = 5,
    advice: Optional[dict] = None,
) -> list[Path]:
    directory = Path(output_dir) / meta["as_of"]
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for fmt in formats:
        fmt = fmt.lower().strip()
        if fmt == "md":
            path = directory / "vp_report.md"
            path.write_text(
                render_markdown(
                    meta,
                    market,
                    analyses,
                    config,
                    top_n=top_n,
                    detail=detail,
                    advice=advice,
                ),
                encoding="utf-8",
            )
            written.append(path)
        elif fmt == "json":
            path = directory / "vp_report.json"
            path.write_text(
                json.dumps(
                    build_json(meta, market, analyses, advice=advice),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            written.append(path)
        elif fmt == "csv":
            path = directory / "vp_report.csv"
            write_csv(path, analyses, advice=advice)
            written.append(path)
    return written


# -------------------------------------------------------------------- console
def render_console(
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    *,
    top_n: int = 5,
) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f" A股量价分析  |  {meta['as_of']}  |  标的 {len(analyses)}")
    lines.append("=" * 78)
    if market:
        lines.append(
            f" 涨跌: 上涨 {market['up']} / 下跌 {market['down']} / 平盘 {market['flat']}"
            f"    20日线上方: {market['above_ma20']}/{market['count']} ({market['above_ma20_ratio']:.0f}%)"
        )
        lines.append(
            f" 中位涨跌: {fmt_pct(market['median_change_pct'])}"
            f"    中位量比5: {fmt_num(market['median_vol_ratio_5'])}"
            f"    状态: {market['regime']}"
        )
        lines.append("")
        lines.append(" 相对强势榜")
        lines.extend(_console_table(market.get("top", []), top_n))
        lines.append("")
        lines.append(" 相对弱势榜")
        lines.extend(_console_table(market.get("bottom", []), top_n))
        if market.get("volume_alerts"):
            lines.append("")
            lines.append(" 放量异动")
            for item in market["volume_alerts"][:top_n]:
                lines.append(
                    f"   {item['code']} {pad(item['name'], 18)} "
                    f"{fmt_pct(item['change_pct']):>8}  量比 {fmt_num(item['vol_ratio_5']):>5}  {item['signal']}"
                )
    lines.append("")
    lines.append(f" 数据源: {_sources_text(meta.get('sources'))}")
    return "\n".join(lines)


def _console_table(items: Sequence[dict], limit: int) -> list[str]:
    if not items:
        return ["   暂无数据"]
    headers = ["排名", "代码", "名称", "涨跌%", "量比5", "评分", "评级", "信号"]
    rows = []
    for rank, item in enumerate(items[:limit], 1):
        rows.append(
            [
                str(rank),
                item["code"],
                item["name"],
                fmt_pct(item["change_pct"]),
                fmt_num(item["vol_ratio_5"]),
                str(item["score"]),
                item["rating"],
                item["signal"],
            ]
        )
    widths = [max(display_width(str(row[i])) for row in [headers] + rows) for i in range(len(headers))]
    out = ["   " + "  ".join(pad(headers[i], widths[i], "right" if i in (0, 3, 4, 5) else "left") for i in range(len(headers)))]
    out.append("   " + "  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        out.append(
            "   "
            + "  ".join(
                pad(str(row[i]), widths[i], "right" if i in (0, 3, 4, 5) else "left")
                for i in range(len(headers))
            )
        )
    return out
