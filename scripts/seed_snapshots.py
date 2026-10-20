#!/usr/bin/env python3
"""从站点归档补齐 ``data/snapshots`` 中缺失的快照。

GitHub Actions 的 snapshot 缓存是跨运行保存的；第一次运行、缓存被清理或
缓存键失效时，上一交易日的快照可能缺失，导致连贯性对比显示“首次留存”。
``site/archive/`` 里的 H5 页面内嵌了完整的 ``DATA`` payload，因此可以从
归档恢复上一份快照，供下一次盘中/收盘分析对比。

默认不覆盖已有快照，避免用旧归档覆盖本次运行刚生成的快照。

用法：

    python3 scripts/seed_snapshots.py
    python3 scripts/seed_snapshots.py --archive-dir site/archive --snapshot-dir data/snapshots
    python3 scripts/seed_snapshots.py --overwrite

退出码：0 成功（包括没有可补齐的归档）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 直接运行 scripts/seed_snapshots.py 时，sys.path[0] 是 scripts/。
from build_site import PAGE_RE, extract_payload


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="从 site/archive 补齐缺失的 data/snapshots")
    parser.add_argument("--archive-dir", default=str(root / "site" / "archive"))
    parser.add_argument("--snapshot-dir", default=str(root / "data" / "snapshots"))
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的快照")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive_dir = Path(args.archive_dir)
    snapshot_dir = Path(args.snapshot_dir)
    if not archive_dir.exists():
        print(f"没有归档目录，跳过: {archive_dir}", file=sys.stderr)
        return 0

    seeded = skipped = invalid = 0
    for page in sorted(archive_dir.glob("*.html")):
        match = PAGE_RE.match(page.name)
        if not match:
            continue
        day, session = match.group(1), match.group(2)
        target = snapshot_dir / day / f"{session}.json"
        if target.exists() and not args.overwrite:
            skipped += 1
            continue
        try:
            payload = extract_payload(page.read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"读取失败 {page}: {exc}", file=sys.stderr)
            invalid += 1
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("meta"), dict):
            print(f"跳过非法归档 {page}: 缺少 DATA payload", file=sys.stderr)
            invalid += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        seeded += 1
        print(f"补齐快照: {target}")

    print(f"seed_snapshots: seeded={seeded} skipped={skipped} invalid={invalid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
