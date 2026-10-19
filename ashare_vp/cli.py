"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date as Date
from datetime import datetime
from pathlib import Path

from . import __version__
from .analysis import analyze_asset, summarize_market, trade_date_gap
from .config import (
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    ConfigError,
    load_config,
    select_assets,
)
from .datasource import DataFetcher
from .publish import build_advice, publish
from .report import render_console, write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ashare-vp",
        description="A股量价分析工具：创新药/军工/生物医药ETF + 宽基指数每日量价日报",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python3 -m ashare_vp\n"
            "  python3 -m ashare_vp --date 2026-10-16 --detail\n"
            "  python3 -m ashare_vp --group 创新药 --group 宽基\n"
            "  python3 -m ashare_vp --offline --format md,json\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="资产池 JSON 配置路径")
    parser.add_argument("--date", help="分析截止日期 YYYY-MM-DD，默认今天（非交易日自动取最近交易日）")
    parser.add_argument("--group", action="append", default=[], help="只分析指定分组，可重复；支持名称包含匹配")
    parser.add_argument("--code", action="append", default=[], help="只分析指定代码，可重复")
    parser.add_argument(
        "--source",
        choices=["auto", "tencent", "sina", "eastmoney"],
        default="auto",
        help="指定数据源，默认 auto（按配置顺序自动切换）",
    )
    parser.add_argument("--cache-dir", default=str(PROJECT_ROOT / "data" / "cache"), help="行情缓存目录")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"), help="报告输出目录")
    parser.add_argument(
        "--snapshot-dir", default=str(PROJECT_ROOT / "data" / "snapshots"), help="盘中快照留存目录"
    )
    parser.add_argument(
        "--h5", action=argparse.BooleanOptionalAction, default=True, help="生成 H5 可视化页面（默认开启）"
    )
    parser.add_argument(
        "--snapshot", action=argparse.BooleanOptionalAction, default=True, help="留存分析快照（默认开启）"
    )
    parser.add_argument("--start-date", help="抓取起始日期，默认读取配置")
    parser.add_argument("--min-bars", type=int, help="最少日线数量，默认读取配置")
    parser.add_argument("--timeout", type=float, help="单次请求超时秒数，默认读取配置")
    parser.add_argument("--offline", action="store_true", help="离线模式，只使用本地缓存")
    parser.add_argument("--refresh", action="store_true", help="忽略当日缓存，强制重新抓取")
    parser.add_argument(
        "--format",
        default="md,json,csv",
        help="输出格式，逗号分隔：md,json,csv（默认全部）",
    )
    parser.add_argument("--detail", action="store_true", help="在 Markdown 中附加完整指标明细")
    parser.add_argument("--top", type=int, default=5, help="强势/弱势榜数量，默认 5")
    parser.add_argument("--list", action="store_true", help="列出资产池后退出")
    parser.add_argument("--quiet", action="store_true", help="只输出报告文件路径")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    if args.list:
        print(f"资产池: {args.config}")
        for group in config.groups:
            print(f"\n[{group.name}] {len(group.assets)} 个")
            for asset in group.assets:
                print(f"  {asset.code}  {asset.name}  ({asset.kind}, {asset.exchange})")
        return 0

    try:
        assets = select_assets(config, args.group, args.code)
    except ConfigError as exc:
        print(f"筛选错误: {exc}", file=sys.stderr)
        return 2

    today = Date.today()
    target = today
    if args.date:
        try:
            target = Date.fromisoformat(args.date)
        except ValueError:
            print(f"日期格式错误: {args.date}，应为 YYYY-MM-DD", file=sys.stderr)
            return 2
    if target > today:
        print(f"日期不能晚于今天: {target}", file=sys.stderr)
        return 2

    start_date = args.start_date or config.settings.get("start_date", "2024-01-01")
    try:
        if target < Date.fromisoformat(start_date):
            print(
                f"分析日期 {target} 早于抓取起始日期 {start_date}，请用 --start-date 调整。",
                file=sys.stderr,
            )
            return 2
    except ValueError:
        print(f"起始日期格式错误: {start_date}", file=sys.stderr)
        return 2

    min_bars = args.min_bars or int(config.settings.get("min_bars", 30))
    timeout = args.timeout or float(config.settings.get("timeout", 10))
    source_order = (
        [args.source]
        if args.source != "auto"
        else list(config.settings.get("source_order") or ["tencent", "sina", "eastmoney"])
    )
    formats = [part.strip().lower() for part in args.format.split(",") if part.strip()]
    invalid = [fmt for fmt in formats if fmt not in {"md", "json", "csv"}]
    if invalid:
        print(f"不支持的输出格式: {', '.join(invalid)}", file=sys.stderr)
        return 2
    if not formats:
        print("至少需要一种输出格式", file=sys.stderr)
        return 2
    if args.top < 1:
        print("--top 必须大于 0", file=sys.stderr)
        return 2
    if args.min_bars is not None and args.min_bars < 20:
        print("--min-bars 不能小于 20", file=sys.stderr)
        return 2
    if args.timeout is not None and args.timeout <= 0:
        print("--timeout 必须大于 0", file=sys.stderr)
        return 2
    if min_bars < 20:
        print(f"min_bars 不能小于 20（当前 {min_bars}）", file=sys.stderr)
        return 2
    if timeout <= 0:
        print(f"timeout 必须大于 0（当前 {timeout}）", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"正在获取 {len(assets)} 个标的的日线数据（截止 {target}）...", file=sys.stderr)

    fetcher = DataFetcher(
        cache_dir=args.cache_dir,
        start_date=start_date,
        end_date=max(target, today).isoformat(),
        source_order=source_order,
        timeout=timeout,
        min_bars=min_bars,
        offline=args.offline,
        refresh=args.refresh,
    )
    results, fetch_failures = fetcher.fetch_many(assets)

    failures: list[dict] = [
        {"code": asset.code, "name": asset.name, "error": message}
        for asset, message in fetch_failures
    ]
    warnings: list[str] = list(fetcher.warnings)
    if fetch_failures and not args.quiet:
        for asset, message in fetch_failures:
            print(f"  跳过 {asset.code} {asset.name}: {message}", file=sys.stderr)

    # 先确定本次报告实际使用的交易日：所有可用标的中最新的日线日期。
    last_dates = []
    for result in results:
        eligible = [bar for bar in result.bars if bar.date <= target.isoformat()]
        if eligible:
            last_dates.append(eligible[-1].date)
    if not last_dates:
        print("没有可用的行情数据，请检查网络、代码或缓存。", file=sys.stderr)
        return 2
    report_date = max(last_dates)

    analyses = []
    for result in results:
        eligible = [bar for bar in result.bars if bar.date <= report_date]
        if not eligible:
            failures.append(
                {
                    "code": result.asset.code,
                    "name": result.asset.name,
                    "error": f"无 {report_date} 及之前的数据",
                }
            )
            continue
        gap = trade_date_gap(eligible[-1].date, report_date)
        item_warning = result.warning
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
            stale_msg = f"{result.asset.name} 最新数据 {eligible[-1].date}，较报告日滞后 {gap} 天"
            warnings.append(stale_msg)
            if not item_warning:
                item_warning = stale_msg

        analysis = analyze_asset(
            result.asset,
            result.bars,
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

    if not analyses:
        print("所有标的均因数据不足被跳过，无法生成报告。", file=sys.stderr)
        return 2

    market = summarize_market(analyses, top_n=args.top)
    sources: dict[str, int] = {}
    for result in results:
        sources[result.source] = sources.get(result.source, 0) + 1
    meta = {
        "as_of": report_date,
        "requested_date": target.isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": sources,
        "cached_count": sum(1 for item in analyses if item.cached),
        "asset_count": len(analyses),
        "offline": bool(args.offline),
        "warnings": _dedupe(warnings),
        "failures": failures,
        "config": str(Path(args.config).resolve()),
        "source_order": source_order,
        "session": "close",
        "session_label": "收盘",
        "intraday": False,
        "quote_count": 0,
        "data_mode": "daily",
    }

    try:
        advice = build_advice(
            meta,
            market,
            analyses,
            snapshot_dir=args.snapshot_dir,
            session="close",
        )
    except Exception as exc:  # noqa: BLE001 - 建议生成失败不影响基础报告
        print(f"操作建议生成失败: {exc}", file=sys.stderr)
        advice = None

    written = write_outputs(
        args.output_dir,
        meta,
        market,
        analyses,
        config,
        formats=formats,
        detail=args.detail,
        top_n=args.top,
        advice=advice,
    )

    publication = None
    if args.h5 or args.snapshot:
        bars_by_code = {}
        analysis_codes = {item.asset.code for item in analyses}
        for result in results:
            if result.asset.code in analysis_codes:
                bars_by_code[result.asset.code] = [
                    bar for bar in result.bars if bar.date <= report_date
                ]
        try:
            publication = publish(
                meta,
                market,
                analyses,
                bars_by_code,
                snapshot_dir=args.snapshot_dir,
                output_dir=args.output_dir,
                session="close",
                make_h5=args.h5,
                make_snapshot=args.snapshot,
                advice=advice,
            )
        except Exception as exc:  # noqa: BLE001 - H5 失败不影响 Markdown/JSON 报告
            print(f"H5/快照生成失败: {exc}", file=sys.stderr)

    if not args.quiet:
        print(render_console(meta, market, analyses, top_n=args.top))
        print()
    print("报告文件:")
    for path in written:
        print(f"  {path}")
    if publication:
        for path in publication.get("h5") or []:
            print(f"  {path}")
        if publication.get("snapshot"):
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
