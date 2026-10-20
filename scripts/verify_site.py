#!/usr/bin/env python3
"""校验线上 ``data/latest.json`` 是否就是本次构建的版本。

部署后 Cloudflare 可能仍返回边缘缓存中的旧版本。workflow 会先把线上
JSON 下载到本地，再用本脚本比对 ``meta.generated_at``、``meta.as_of``
和标的数量；三者任一不一致就以非零状态退出，让 Actions 明确失败，
而不是把旧页面当成部署成功。

用法：

    python3 scripts/verify_site.py /tmp/live-latest.json \
        --generated-at 2026-10-19T23:52:10 \
        --as-of 2026-10-19 \
        --asset-count 25

退出码：0 一致；1 不一致；2 输入文件缺失或不是合法 JSON。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验线上 latest.json 与本次构建是否一致")
    parser.add_argument("path", help="线上 latest.json 的本地副本")
    parser.add_argument("--generated-at", required=True, help="本次构建的 meta.generated_at")
    parser.add_argument("--as-of", required=True, help="本次构建的 meta.as_of")
    parser.add_argument("--asset-count", required=True, type=int, help="本次构建的标的数量")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"校验失败：文件不存在 {path}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"校验失败：无法读取 {path}：{exc}", file=sys.stderr)
        return 2

    if not isinstance(data, dict):
        print("校验失败：latest.json 不是 JSON 对象", file=sys.stderr)
        return 2

    meta = data.get("meta") or {}
    assets = data.get("assets") or []
    actual = {
        "generated_at": meta.get("generated_at"),
        "as_of": meta.get("as_of"),
        "asset_count": len(assets) if isinstance(assets, list) else None,
    }
    expected = {
        "generated_at": args.generated_at,
        "as_of": args.as_of,
        "asset_count": args.asset_count,
    }

    errors = [key for key in expected if actual.get(key) != expected[key]]
    if errors:
        print("线上版本与本次构建不一致：", file=sys.stderr)
        for key in errors:
            print(f"  - {key}: 期望 {expected[key]!r}，实际 {actual.get(key)!r}", file=sys.stderr)
        return 1

    print(
        "线上版本校验通过："
        f"generated_at={actual['generated_at']} "
        f"as_of={actual['as_of']} "
        f"assets={actual['asset_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
