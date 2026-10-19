"""10:30 / 14:00 定时任务调度器（仅工作日，自动识别非交易日）。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date as Date
from datetime import datetime, time as Time, timedelta
from pathlib import Path
from typing import Optional, Sequence

from .config import (
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    ConfigError,
    load_config,
    select_assets,
)
from .quotes import TZ, current_session_key
from .session import run_session, session_label


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ashare-vp-scheduler",
        description="工作日 10:30 / 14:00 自动生成盘中量价分析与 H5",
    )
    parser.add_argument("--at", default="10:30,14:00", help="运行时间，逗号分隔，默认 10:30,14:00")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--group", action="append", default=[])
    parser.add_argument("--code", action="append", default=[])
    parser.add_argument("--source", choices=["auto", "tencent", "sina", "eastmoney"], default="auto")
    parser.add_argument("--cache-dir", default=str(PROJECT_ROOT / "data" / "cache"))
    parser.add_argument("--snapshot-dir", default=str(PROJECT_ROOT / "data" / "snapshots"))
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"))
    parser.add_argument("--start-date")
    parser.add_argument("--min-bars", type=int)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force", action="store_true", help="忽略交易日判断与已有状态，立即执行")
    parser.add_argument("--once", action="store_true", help="立即执行一次后退出")
    parser.add_argument("--dry-run", action="store_true", help="只打印未来任务时间，不执行")
    parser.add_argument(
        "--max-lag-minutes",
        type=int,
        default=30,
        help="系统休眠后错过任务超过该分钟数则跳过，0 表示不限制（默认 30）",
    )
    parser.add_argument("--state-file", default=str(PROJECT_ROOT / "data" / "scheduler_state.json"))
    parser.add_argument("--holiday-file", help="可选 JSON 文件，数组格式的休市日期 YYYY-MM-DD")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        times = parse_times(args.at)
    except ValueError as exc:
        print(f"时间格式错误: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        now = datetime.now(TZ)
        for _ in range(6):
            now = next_run(now, times)
            print(now.strftime("%Y-%m-%d %H:%M %A"))
        return 0

    if args.once:
        return _execute(args, datetime.now(TZ), require_current=not args.force)

    print(f"调度器启动：{', '.join(t.strftime('%H:%M') for t in times)}（Asia/Shanghai）")
    print("按 Ctrl+C 停止。")
    while True:
        now = datetime.now(TZ)
        target = next_run(now, times)
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] 下一次任务：{target.strftime('%Y-%m-%d %H:%M')}")
        try:
            while True:
                remaining = (target - datetime.now(TZ)).total_seconds()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 30))
        except KeyboardInterrupt:
            print("\n已停止。")
            return 0
        actual = datetime.now(TZ)
        if _missed(target, actual, args.max_lag_minutes):
            lag = (actual - target).total_seconds() / 60.0
            print(
                f"[{actual.strftime('%H:%M:%S')}] 已错过 {target.strftime('%H:%M')} "
                f"约 {lag:.0f} 分钟（上限 {args.max_lag_minutes}），跳过本次。"
            )
            continue
        code = _execute(args, actual, require_current=not args.force)
        if code not in (0, 3):
            print(f"任务失败，退出码 {code}", file=sys.stderr)
        time.sleep(5)


def _execute(args, now: datetime, *, require_current: bool) -> int:
    session = current_session_key(now)
    key = f"{now.date().isoformat()}-{session}"
    if not args.force and _already_ran(args.state_file, key):
        print(f"[{now.strftime('%H:%M:%S')}] {key} 已执行，跳过。")
        return 3

    holiday = _is_holiday(now.date(), args.holiday_file)
    if holiday and not args.force:
        print(f"[{now.strftime('%H:%M:%S')}] {now.date()} 在休市列表中，跳过。")
        return 3

    if not _is_trading_day(now) and not args.force:
        print(f"[{now.strftime('%H:%M:%S')}] 周末休市，跳过。")
        return 3

    try:
        config = load_config(args.config)
        assets = select_assets(config, args.group, args.code)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    min_bars = args.min_bars or int(config.settings.get("min_bars", 30))
    timeout = args.timeout or float(config.settings.get("timeout", 10))
    source_order = (
        [args.source]
        if args.source != "auto"
        else list(config.settings.get("source_order") or ["tencent", "sina", "eastmoney"])
    )
    print(f"[{now.strftime('%H:%M:%S')}] 执行 {session_label(session)} 分析...")
    code = run_session(
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
        refresh=False,
        top_n=args.top,
        force=args.force,
        no_quote=False,
        require_current=require_current and not args.offline,
        quiet=args.quiet,
    )
    if code == 0 and not args.force:
        _mark_ran(args.state_file, key)
    return code


def _is_trading_day(now: datetime) -> bool:
    """周末直接跳过；节假日由 run_session 的 require_current 用实时快照确认。

    这样定时任务只需抓取一次实时快照，避免原先“先探测指数、再抓全部标的”
    的重复请求。
    """
    return now.weekday() < 5


def _missed(target: datetime, actual: datetime, max_lag_minutes: int) -> bool:
    """系统休眠/阻塞后，判断是否已明显错过计划时间。"""
    if max_lag_minutes <= 0:
        return False
    return (actual - target).total_seconds() > max_lag_minutes * 60


def parse_times(value: str) -> list[Time]:
    times = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            hour, minute = part.split(":")
            times.append(Time(int(hour), int(minute)))
        except (ValueError, TypeError) as exc:
            raise ValueError(part) from exc
    if not times:
        raise ValueError("至少需要一个时间")
    return sorted(set(times))


def next_run(now: datetime, times: Sequence[Time], *, include_today: bool = True) -> datetime:
    base = now.astimezone(TZ)
    for offset in range(0, 8):
        day = base.date() + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for clock in times:
            candidate = datetime.combine(day, clock, tzinfo=TZ)
            if offset == 0 and candidate <= base:
                continue
            if offset > 0 or include_today:
                return candidate
    return datetime.combine(base.date() + timedelta(days=7), times[0], tzinfo=TZ)


def _already_ran(state_file: str | Path, key: str) -> bool:
    try:
        payload = json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return key in (payload.get("runs") or {})


def _mark_ran(state_file: str | Path, key: str) -> None:
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    runs = payload.get("runs") or {}
    runs[key] = datetime.now(TZ).isoformat(timespec="seconds")
    payload["runs"] = runs
    payload["updated_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_holiday(day: Date, holiday_file: Optional[str]) -> bool:
    if not holiday_file:
        return False
    try:
        data = json.loads(Path(holiday_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    values = data if isinstance(data, list) else data.get("holidays", [])
    return day.isoformat() in values


if __name__ == "__main__":
    raise SystemExit(main())
