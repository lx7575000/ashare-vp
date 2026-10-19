#!/usr/bin/env python3
"""把 ashare_vp 生成的 H5 日报整理成可以直接部署的静态站点。

做四件事：
1. 收集 ``reports/h5/YYYY-MM-DD_{1100,1400,close}.html``，复制到 ``site/archive/``；
2. 选最新一期作为 ``site/index.html``，并生成 ``site/history.html`` 历史入口；
3. 维护 ``site/history.json``，记录日期、时段、市场状态和评分均值；
4. 脱敏本机绝对路径、清理过期归档。

只依赖标准库。用法：

    python3 scripts/build_site.py
    python3 scripts/build_site.py --prune-days 120
    python3 scripts/build_site.py --require-date 2026-10-19 --min-assets 20

退出码：0 成功；3 最新报告日期与 --require-date 不符（节假日/数据未更新）；
4 标的数量不足 --min-assets（数据源异常）。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
PAGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(1030|1100|1400|close)\.html$")
PAYLOAD_RE = re.compile(r"const\s+DATA\s*=\s*(\{.*?\});\s*\n", re.S)
SESSION_RANK = {"1030": 0, "1100": 1, "1400": 2, "close": 3}
SESSION_LABEL = {"1030": "10:30 盘中", "1100": "11:00 盘中", "1400": "14:00 盘中", "close": "收盘"}
NAV_MARK = 'id="vp-site-nav"'
NAV_RE = re.compile(r'<(a|div) id="vp-site-nav".*?</\1>', re.S)


# --------------------------------------------------------------------------- #
# 读取与脱敏
# --------------------------------------------------------------------------- #
def sanitize(text: str, root: Path) -> str:
    """去掉本机绝对路径，避免把用户名/目录结构发布到公网。"""
    text = text.replace(str(root) + "/", "")
    text = text.replace(str(root), ".")
    return text


def extract_payload(text: str) -> dict[str, Any] | None:
    match = PAYLOAD_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace("<\\/", "</")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_page(path: Path, text: str) -> dict[str, Any]:
    """从文件名和页面内嵌数据里提取历史列表需要的字段。"""
    match = PAGE_RE.match(path.name)
    if not match:
        raise ValueError(f"不是可归档的报告文件: {path.name}")
    day, session = match.group(1), match.group(2)
    payload = extract_payload(text) or {}
    meta = payload.get("meta") or {}
    market = payload.get("market") or {}
    assets = payload.get("assets") or []

    scores = [
        item.get("score")
        for item in assets
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float))
    ]
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    # 工具自己写入的 history 里已经有 avg_score，优先采用，避免口径差异。
    for item in payload.get("history") or []:
        if isinstance(item, dict) and item.get("date") == day and item.get("session") == session:
            if isinstance(item.get("avg_score"), (int, float)):
                avg_score = round(float(item["avg_score"]), 2)
            break

    return {
        "date": day,
        "session": session,
        "session_label": str(meta.get("session_label") or SESSION_LABEL[session]),
        "regime": str(market.get("regime") or ""),
        "avg_score": avg_score,
        "asset_count": int(meta.get("asset_count") or len(assets) or 0),
        "generated_at": str(meta.get("generated_at") or ""),
        "file": f"{day}_{session}.html",
    }


# --------------------------------------------------------------------------- #
# 页面加工
# --------------------------------------------------------------------------- #
def decorate(page: str, *, is_latest: bool) -> str:
    """加 noindex 和顶部站内导航，重复执行不会重复插入。"""
    if 'name="robots"' not in page:
        page = page.replace(
            '<meta charset="utf-8">',
            '<meta charset="utf-8">\n<meta name="robots" content="noindex,nofollow">',
            1,
        )

    # 先去掉旧导航，保证同一份页面既能作为首页（history.html），
    # 也能作为归档页（../index.html），不会把链接指错。
    page = NAV_RE.sub("", page)
    if NAV_MARK in page:
        return page

    if is_latest:
        href, label = "history.html", "历史报告 →"
    else:
        href, label = "../index.html", "← 最新报告"

    nav = (
        f'<div {NAV_MARK} style="display:flex;justify-content:flex-end;margin:0 0 10px">'
        f'<a href="{href}" style="display:inline-flex;align-items:center;gap:4px;'
        "padding:6px 11px;border-radius:999px;background:#fff;border:1px solid #dbe3ef;"
        "color:#344054;font-size:12px;font-weight:600;text-decoration:none;"
        'box-shadow:0 2px 8px rgba(15,23,42,.06)">'
        f"{label}</a></div>"
    )
    if '<div class="wrap">' in page:
        return page.replace('<div class="wrap">', '<div class="wrap">' + nav, 1)
    if "</body>" in page:
        return page.replace("</body>", nav + "\n</body>", 1)
    return page + nav


def render_history(items: list[dict[str, Any]], *, keep_days: int) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(
        items,
        key=lambda value: (value["date"], SESSION_RANK.get(value["session"], 0)),
        reverse=True,
    ):
        groups.setdefault(item["date"], []).append(item)

    rows: list[str] = []
    for day, sessions in groups.items():
        chips = []
        for item in sorted(
            sessions, key=lambda value: SESSION_RANK.get(value["session"], 0), reverse=True
        ):
            chips.append(
                '<a class="chip" href="archive/{file}">{label}</a>'.format(
                    file=html.escape(item["file"]),
                    label=html.escape(item["session_label"]),
                )
            )
        latest = sessions[0]
        regime = html.escape(latest.get("regime") or "—")
        score = latest.get("avg_score")
        score_text = f"{score:g}" if isinstance(score, (int, float)) else "—"
        rows.append(
            '<li><div class="date">{day}<span class="meta">{regime} · 均分 {score}</span></div>'
            '<div class="chips">{chips}</div></li>'.format(
                day=html.escape(day),
                regime=regime,
                score=html.escape(score_text),
                chips="".join(chips),
            )
        )

    body = "".join(rows) or '<li class="empty">还没有历史报告</li>'
    total = len(items)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b1220">
<meta name="robots" content="noindex,nofollow">
<title>历史报告 · A股量价监控</title>
<style>
  *{{box-sizing:border-box}}
  body{{margin:0;padding:20px 16px 48px;background:#f4f6fb;color:#101828;
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
    -webkit-font-smoothing:antialiased}}
  main{{max-width:760px;margin:0 auto}}
  .top{{background:#0b1220;color:#fff;border-radius:20px;padding:22px 20px;
    background-image:radial-gradient(600px 200px at 90% -30%,#3b82f655,transparent 60%)}}
  .top h1{{margin:0 0 6px;font-size:22px}}
  .top p{{margin:0;color:#cbd5e1;font-size:12px}}
  .top a{{display:inline-block;margin-top:14px;padding:9px 14px;border-radius:999px;
    background:#fff;color:#0b1220;font-size:13px;font-weight:700;text-decoration:none}}
  ul{{list-style:none;padding:0;margin:16px 0 0}}
  li{{background:#fff;border:1px solid #e6eaf2;border-radius:14px;padding:14px 16px;
    margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;
    gap:12px;flex-wrap:wrap}}
  .date{{font-size:15px;font-weight:700;letter-spacing:.2px}}
  .date .meta{{display:block;margin-top:3px;color:#667085;font-size:11px;font-weight:500}}
  .chips{{display:flex;gap:8px;flex-wrap:wrap}}
  .chip{{display:inline-block;padding:6px 11px;border-radius:999px;background:#eff6ff;
    color:#2563eb;font-size:12px;font-weight:600;text-decoration:none}}
  .chip:active{{background:#dbeafe}}
  .empty{{color:#667085;justify-content:center;font-size:13px}}
  .foot{{margin-top:18px;color:#98a2b3;font-size:11px;line-height:1.7;text-align:center}}
  @media (max-width:420px){{li{{align-items:flex-start;flex-direction:column}}}}
</style>
</head>
<body><main>
  <section class="top">
    <h1>历史报告</h1>
    <p>最近 {keep_days} 天 · 共 {total} 期 · 数据为生成时固化</p>
    <a href="index.html">查看最新报告 →</a>
  </section>
  <ul>{body}</ul>
  <p class="foot">仅用于量化研究与学习，不构成任何投资建议。</p>
</main></body>
</html>
"""


# --------------------------------------------------------------------------- #
# 构建
# --------------------------------------------------------------------------- #
def iter_pages(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and PAGE_RE.match(path.name)
    )


def load_history(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict) and item.get("date") and item.get("session"):
            result[f"{item['date']}-{item['session']}"] = item
    return result


def build(args: argparse.Namespace) -> int:
    reports_dir = Path(args.reports)
    site_dir = Path(args.site)
    archive_dir = site_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    history = load_history(site_dir / "history.json")
    pages: dict[str, dict[str, Any]] = {}

    # 先读已有归档，再用本次新生成的报告覆盖同名条目。
    for directory, is_fresh in ((archive_dir, False), (reports_dir / "h5", True)):
        for path in iter_pages(directory):
            text = sanitize(path.read_text(encoding="utf-8"), ROOT)
            try:
                info = parse_page(path, text)
            except ValueError:
                continue
            key = f"{info['date']}-{info['session']}"
            if not is_fresh and key in pages:
                continue
            # 同一天重复运行时，如果新报告缺了标的（数据源抖动），保留更完整的旧归档。
            if is_fresh and key in pages and info["asset_count"] < pages[key]["asset_count"]:
                print(
                    f"保留更完整的归档：{key}（{pages[key]['asset_count']} > "
                    f"{info['asset_count']}）",
                    file=sys.stderr,
                )
                continue
            info["_text"] = text
            pages[key] = info

    if not pages:
        print(f"没有找到可发布的报告：{reports_dir / 'h5'}", file=sys.stderr)
        return 2

    latest = max(
        pages.values(),
        key=lambda item: (item["date"], SESSION_RANK.get(item["session"], 0)),
    )

    if args.require_date and latest["date"] != args.require_date:
        print(
            f"跳过发布：最新交易日为 {latest['date']}，不是 {args.require_date}"
            "（可能是周末/休市或行情尚未更新）。",
            file=sys.stderr,
        )
        return 3

    if latest["asset_count"] < args.min_assets:
        print(
            f"拒绝发布：最新报告只有 {latest['asset_count']} 个标的，"
            f"低于阈值 {args.min_assets}。",
            file=sys.stderr,
        )
        return 4

    # 写出归档页；所有归档页都链接回站点根目录的最新报告。
    for key, info in pages.items():
        page = decorate(info.get("_text", ""), is_latest=False)
        (archive_dir / info["file"]).write_text(page, encoding="utf-8")
        history[key] = {
            "date": info["date"],
            "session": info["session"],
            "session_label": info["session_label"],
            "regime": info["regime"],
            "avg_score": info["avg_score"],
            "asset_count": info["asset_count"],
            "generated_at": info["generated_at"],
            "file": info["file"],
        }

    # 首页 = 最新一期。
    (site_dir / "index.html").write_text(
        decorate(latest["_text"], is_latest=True), encoding="utf-8"
    )

    # 只保留仍存在的归档条目，并按日期倒序。
    items = [
        item
        for item in history.values()
        if (archive_dir / item.get("file", "")).exists()
    ]
    items.sort(
        key=lambda item: (item["date"], SESSION_RANK.get(item["session"], 0)),
        reverse=True,
    )

    # 剪枝：以最新报告日期为基准，避免回放旧数据时误删。
    if args.prune_days > 0:
        reference = date.fromisoformat(latest["date"])
        cutoff = reference - timedelta(days=args.prune_days)
        kept = []
        for item in items:
            try:
                day = date.fromisoformat(item["date"])
            except ValueError:
                continue
            if day >= cutoff:
                kept.append(item)
            else:
                (archive_dir / item["file"]).unlink(missing_ok=True)
        items = kept

    # 清掉不在索引里的 HTML（例如手工拷贝进来的旧文件）。
    keep_files = {item["file"] for item in items}
    for path in iter_pages(archive_dir):
        if path.name not in keep_files:
            path.unlink(missing_ok=True)

    (site_dir / "history.json").write_text(
        json.dumps(
            {"version": 1, "updated_at": latest["generated_at"], "items": items},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (site_dir / "history.html").write_text(
        render_history(items, keep_days=args.prune_days), encoding="utf-8"
    )
    (site_dir / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n", encoding="utf-8"
    )

    # 可选：把最新快照 JSON 也发布出去，方便以后接小程序/脚本。
    if not args.no_json:
        snapshot = (
            Path(args.snapshots)
            / latest["date"]
            / f"{latest['session']}.json"
        )
        if snapshot.exists():
            data_dir = site_dir / "data"
            data_dir.mkdir(exist_ok=True)
            (data_dir / "latest.json").write_text(
                sanitize(snapshot.read_text(encoding="utf-8"), ROOT),
                encoding="utf-8",
            )

    total_bytes = sum(path.stat().st_size for path in site_dir.rglob("*") if path.is_file())
    print(f"站点已生成：{site_dir}")
    print(
        f"最新：{latest['date']} {latest['session_label']} · "
        f"{latest['regime'] or '—'} · {latest['asset_count']} 个标的"
    )
    print(f"归档：{len(items)} 期（保留 {args.prune_days} 天）")
    print(f"体积：{total_bytes / 1024 / 1024:.2f} MB")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 H5 日报整理成静态站点")
    parser.add_argument("--reports", default=str(ROOT / "reports"), help="报告目录")
    parser.add_argument("--site", default=str(ROOT / "site"), help="站点输出目录")
    parser.add_argument(
        "--snapshots", default=str(ROOT / "data" / "snapshots"), help="快照目录"
    )
    parser.add_argument(
        "--prune-days", type=int, default=120, help="归档保留天数，0 表示不清理"
    )
    parser.add_argument("--require-date", help="要求最新报告等于该日期 YYYY-MM-DD，否则跳过")
    parser.add_argument(
        "--min-assets", type=int, default=20, help="标的数量下限，低于该值拒绝发布"
    )
    parser.add_argument("--no-json", action="store_true", help="不发布 latest.json")
    args = parser.parse_args(argv)
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
