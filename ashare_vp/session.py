"""盘中 10:30 / 11:00 / 14:00 量价分析与 H5 发布。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from .analysis import analyze_asset, summarize_market, trade_date_gap
from .config import (
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    ConfigError,
    load_config,
    select_assets,
)
from .datasource import DataFetcher
from .models import Asset
from .publish import publish
from .quotes import (
    Quote,
    TZ,
    current_session_key,
    fetch_quotes,
    quote_elapsed_fraction,
    session_label,
)
from .report import render_console


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ashare-vp-session",
        description="A股量价盘中分析：10:30 / 11:00 / 14:00 快照、近高近低监测、条件化建议与 H5",
    )
    parser.add_argument("--session", choices=["auto", "1030", "1100", "1400", "close"], default="auto")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--group", action="append", default=[])
    parser.add_argument("--code", action="append", default=[])
    parser.add_argument(
        "--source",
        choices=["auto", "tencent", "sina", "eastmoney"],
        default="auto",
    )
    parser.add_argument("--cache-dir", default=str(PROJECT_ROOT / "data" / "cache"))
    parser.add_argument("--snapshot-dir", default=str(PROJECT_ROOT / "data" / "snapshots"))
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"))
    parser.add_argument("--start-date")
    parser.add_argument("--min-bars", type=int)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--force", action="store_true", help="快照日期不是今天时也使用最新快照（用于预览/回放）")
    parser.add_argument("--no-quote", action="store_true", help="不使用实时快照，只用日线缓存")
    parser.add_argument(
        "--require-current",
        action="store_true",
        help="没有当日实时快照时跳过（定时任务使用，避免节假日误生成）",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    try:
        assets = select_assets(config, args.group, args.code)
    except ConfigError as exc:
        print(f"筛选错误: {exc}", file=sys.stderr)
        return 2

    min_bars = args.min_bars or int(config.settings.get("min_bars", 30))
    timeout = args.timeout or float(config.settings.get("timeout", 10))
    if min_bars < 20 or timeout <= 0:
        print("min_bars 需 >=20，timeout 需 >0", file=sys.stderr)
        return 2
    source_order = (
        [args.source]
        if args.source != "auto"
        else list(config.settings.get("source_order") or ["tencent", "sina", "eastmoney"])
    )
    session = args.session
    if session == "auto":
        session = current_session_key()

    return run_session(
        session=session,
        config=config,
        assets=assets,
        cache_dir=args.cache_dir,
        snapshot_dir=args.snapshot_dir,
        output_dir=args.output_dir,
        source_order=source_order,
        start_date=args.start_date or config.settings.get("start_date", "2024-01-01"),
        min_bars=min_bars,
        timeout=timeout,
        offline=args.offline,
        refresh=args.refresh,
        top_n=args.top,
        force=args.force,
        no_quote=args.no_quote,
        require_current=args.require_current,
        quiet=args.quiet,
    )


def session_is_replay(session: str, now: Optional[datetime] = None) -> bool:
    """请求时段与当前时段不一致时视为回放。

    例如在 11:44 用 ``--session 1400 --force`` 生成报告，数据实际是
    11:44 的盘中快照；如果仍标成“14:00 盘中”，标题会误导。这里在
    生成时把这种同日跨时段运行标记为“回放”。
    """
    current = now.astimezone(TZ) if now else datetime.now(TZ)
    return session != current_session_key(current)


def run_session(
    *,
    session: str,
    config,
    assets: Sequence[Asset],
    cache_dir: str | Path,
    snapshot_dir: str | Path,
    output_dir: str | Path,
    source_order: Sequence[str],
    start_date: str,
    min_bars: int = 30,
    timeout: float = 10,
    offline: bool = False,
    refresh: bool = False,
    top_n: int = 5,
    force: bool = False,
    no_quote: bool = False,
    require_current: bool = False,
    quiet: bool = False,
) -> int:
    now = datetime.now(TZ)
    today = now.date().isoformat()
    label = session_label(session)
    warnings: list[str] = []
    quotes: dict[str, Quote] = {}

    if not offline and not no_quote:
        if not quiet:
            print(f"[{now.strftime('%H:%M:%S')}] 获取 {len(assets)} 个标的实时快照...", file=sys.stderr)
        quotes, quote_warnings = fetch_quotes(assets, timeout=timeout)
        warnings.extend(quote_warnings)
        if not quiet:
            print(f"  快照 {len(quotes)}/{len(assets)} 个", file=sys.stderr)

    if require_current:
        # 非交易日/休市时提前退出，避免继续抓取 20+ 个标的的日线数据。
        current = [q for q in quotes.values() if q.date == today and q.volume > 0]
        if not current:
            print(
                f"跳过：当前没有 {today} 的实时快照（可能为非交易日/休市），避免生成过期盘中报告。",
                file=sys.stderr,
            )
            return 3

    fetcher = DataFetcher(
        cache_dir=cache_dir,
        start_date=start_date,
        end_date=today,
        source_order=source_order,
        timeout=timeout,
        min_bars=min_bars,
        offline=offline,
        refresh=refresh,
    )
    results, fetch_failures = fetcher.fetch_many(assets)
    warnings.extend(fetcher.warnings)
    failures = [
        {"code": asset.code, "name": asset.name, "error": message}
        for asset, message in fetch_failures
    ]

    merged: dict[str, tuple[list, bool, Optional[str], object]] = {}
    last_dates: list[str] = []
    quote_used = 0
    quote_time = None
    quote_date = None
    replay = session_is_replay(session, now)
    for result in results:
        bars = list(result.bars)
        quote = quotes.get(result.asset.code)
        item_warning = result.warning
        used = False
        if quote and quote.volume > 0 and (quote.date == today or force):
            fraction = quote_elapsed_fraction(quote)
            synthetic = quote.to_bar(result.asset, fraction)
            bars = [bar for bar in bars if bar.date != synthetic.date]
            bars.append(synthetic)
            bars.sort(key=lambda bar: bar.date)
            used = True
            quote_used += 1
            quote_time = max(quote_time, quote.time) if quote_time else quote.time
            quote_date = quote.date
            if quote.date != today:
                replay = True
            warning_prefix = "回放快照" if quote.date != today else "盘中快照"
            item_warning = f"{warning_prefix} {quote.time}，成交量按 {fraction:.0%} 进度外推"
        elif quote and quote.date != today:
            warnings.append(
                f"{result.asset.name} 快照停留在 {quote.date}，本次使用最近收盘数据"
            )

        eligible = [bar for bar in bars if bar.date <= today]
        if not eligible:
            failures.append(
                {"code": result.asset.code, "name": result.asset.name, "error": "无可用日线"}
            )
            continue
        last_dates.append(eligible[-1].date)
        merged[result.asset.code] = (bars, used, item_warning, result)

    if not last_dates:
        print("没有可用行情，无法生成盘中分析。", file=sys.stderr)
        return 2

    report_date = max(last_dates)
    if require_current and quote_used == 0:
        print(
            f"跳过：当前没有 {today} 的实时快照（可能为非交易日/休市），避免生成过期盘中报告。",
            file=sys.stderr,
        )
        return 3

    analyses = []
    bars_by_code = {}
    for code, (bars, used, item_warning, result) in merged.items():
        eligible = [bar for bar in bars if bar.date <= report_date]
        if not eligible:
            continue
        gap = trade_date_gap(eligible[-1].date, report_date)
        if gap > 10:
            failures.append(
                {
                    "code": result.asset.code,
                    "name": result.asset.name,
                    "error": f"最新数据 {eligible[-1].date}，滞后 {gap} 天",
                }
            )
            continue
        if gap > 0:
            stale = f"{result.asset.name} 最新数据 {eligible[-1].date}，较报告日滞后 {gap} 天"
            warnings.append(stale)
            if not item_warning:
                item_warning = stale
        analysis = analyze_asset(
            result.asset,
            bars,
            as_of=report_date,
            min_bars=min_bars,
            source=result.source,
            cached=result.cached,
            warning=item_warning,
        )
        if analysis is None:
            failures.append(
                {
                    "code": result.asset.code,
                    "name": result.asset.name,
                    "error": f"有效日线不足 {min_bars} 条",
                }
            )
            continue
        analyses.append(analysis)
        bars_by_code[code] = eligible

    if not analyses:
        print("所有标的均因数据不足被跳过。", file=sys.stderr)
        return 2

    market = summarize_market(analyses, top_n=top_n)
    sources: dict[str, int] = {}
    for result in results:
        sources[result.source] = sources.get(result.source, 0) + 1
    meta = {
        "as_of": report_date,
        "requested_date": today,
        "generated_at": now.isoformat(timespec="seconds"),
        "session": session,
        "session_label": (label + " · 回放") if replay else label,
        "sources": sources,
        "cached_count": sum(1 for item in analyses if item.cached),
        "asset_count": len(analyses),
        "offline": bool(offline),
        "intraday": quote_used > 0,
        "quote_count": quote_used,
        "quote_time": quote_time,
        "quote_date": quote_date,
        "replay": replay,
        "data_mode": "intraday" if quote_used else "daily",
        "warnings": _dedupe(warnings),
        "failures": failures,
        "config": str(Path(getattr(config, "path", DEFAULT_CONFIG_PATH))),
        "source_order": list(source_order),
    }

    try:
        publication = publish(
            meta,
            market,
            analyses,
            bars_by_code,
            snapshot_dir=snapshot_dir,
            output_dir=output_dir,
            session=session,
        )
    except Exception as exc:  # noqa: BLE001 - 发布失败不应丢失分析结果
        print(f"发布 H5/快照失败: {exc}", file=sys.stderr)
        return 2

    if not quiet:
        print(render_console(meta, market, analyses, top_n=top_n))
        advice = publication["advice"]["market"]
        print()
        print(
            f" 盘中建议: {advice.get('level')} ｜ 参考仓位 {advice.get('position')} ｜ "
            f"近高 {len(publication['advice']['near_high'])} / 近低 {len(publication['advice']['near_low'])}"
        )
        print(f" {advice.get('summary')}")
        print()
    print("H5 报告:")
    for path in publication["h5"]:
        print(f"  {path}")
    print("快照:")
    print(f"  {publication['snapshot']}")
    return 0


def _dedupe(values):
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
