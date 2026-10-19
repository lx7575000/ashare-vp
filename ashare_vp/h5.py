"""H5 可视化报告生成。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional, Sequence

from .analysis import AssetAnalysis
from .config import PROJECT_ROOT
from .snapshot import list_snapshots

TEMPLATE_PATH = PROJECT_ROOT / "templates" / "h5.html"


def build_payload(
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    advice: dict,
    series: Optional[dict] = None,
    history: Optional[list] = None,
) -> dict:
    assets = []
    for analysis in analyses:
        payload = analysis.to_dict()
        payload["advice"] = (advice.get("items") or {}).get(analysis.asset.code)
        payload["series"] = (series or {}).get(analysis.asset.code)
        assets.append(payload)

    return {
        "meta": meta,
        "market": market,
        "assets": assets,
        "advice": advice,
        "history": history or [],
    }


def render_h5(payload: dict, template_path: Optional[str | Path] = None) -> str:
    path = Path(template_path) if template_path else TEMPLATE_PATH
    if not path.exists():
        raise FileNotFoundError(f"H5 模板不存在: {path}")
    template = path.read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")
    title = f"{payload.get('meta', {}).get('as_of', '')} {payload.get('meta', {}).get('session_label', '')}"
    return template.replace("__PAYLOAD__", data).replace("__TITLE__", _escape_html(title))


def write_h5(
    output_dir: str | Path,
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    advice: dict,
    *,
    series: Optional[dict] = None,
    history: Optional[list] = None,
    template_path: Optional[str | Path] = None,
) -> list[Path]:
    h5_dir = Path(output_dir) / "h5"
    h5_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(meta, market, analyses, advice, series, history)
    html = render_h5(payload, template_path=template_path)

    session = meta.get("session", "close")
    day = meta.get("as_of", "latest")
    target = h5_dir / f"{day}_{session}.html"
    target.write_text(html, encoding="utf-8")
    latest = h5_dir / "latest.html"
    latest.write_text(html, encoding="utf-8")
    _write_index(h5_dir, meta, history or [])
    return [target, latest]


def _write_index(h5_dir: Path, meta: dict, history: list) -> None:
    rows = []
    for item in history[:60]:
        filename = f"{item.get('date')}_{item.get('session')}.html"
        rows.append(
            f'<li><a href="{_escape_attr(filename)}">{_escape_html(str(item.get("date", "")))} '
            f'{_escape_html(str(item.get("session_label", "")))}</a>'
            f'<span>{_escape_html(str(item.get("regime", "")))} · 评分均值 '
            f'{_escape_html(str(item.get("avg_score", "")))}</span></li>'
        )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>历史快照</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;background:#f4f6fb;color:#101828;margin:0;padding:24px}}
main{{max-width:760px;margin:0 auto;background:#fff;border:1px solid #e6eaf2;border-radius:16px;padding:22px}}
h1{{font-size:20px;margin:0 0 6px}}p{{color:#667085;font-size:12px;margin:0 0 18px}}
ul{{list-style:none;padding:0;margin:0}}li{{display:flex;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid #eef2f7;font-size:13px}}
a{{color:#2563eb;text-decoration:none;font-weight:600}}span{{color:#98a2b3;font-size:11px}}
</style></head><body><main>
<h1>历史快照</h1><p>当前：{_escape_html(str(meta.get("as_of", "")))} {_escape_html(str(meta.get("session_label", "")))}</p>
<ul>{''.join(rows) or '<li>暂无历史快照</li>'}</ul>
</main></body></html>"""
    (h5_dir / "index.html").write_text(html, encoding="utf-8")


def _escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _escape_attr(value: str) -> str:
    return _escape_html(value).replace("'", "&#39;")


def copy_latest_to(source: str | Path, destination: str | Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target
