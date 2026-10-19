"""统一发布流程：建议生成 -> 快照留存 -> H5 输出。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from .advice import generate_advice
from .analysis import AssetAnalysis
from .h5 import write_h5
from .snapshot import (
    build_series_map,
    list_snapshots,
    load_latest_snapshot,
    save_snapshot,
    snapshot_key,
)


def build_advice(
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    *,
    snapshot_dir: str | Path,
    session: Optional[str] = None,
) -> dict:
    """生成操作建议；读取同一交易日上一时段快照用于连贯性对比。"""
    session = session or meta.get("session") or "close"
    key = snapshot_key({**meta, "session": session})
    previous = load_latest_snapshot(snapshot_dir, before_key=key)
    return generate_advice(
        analyses,
        market,
        session=session,
        previous_snapshot=previous,
        generated_at=meta.get("generated_at"),
    )


def publish(
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    bars_by_code: dict,
    *,
    snapshot_dir: str | Path,
    output_dir: str | Path,
    session: Optional[str] = None,
    history_limit: int = 50,
    make_h5: bool = True,
    make_snapshot: bool = True,
    advice: Optional[dict] = None,
) -> dict:
    session = session or meta.get("session") or "close"
    meta = dict(meta)
    meta["session"] = session
    meta.setdefault("session_label", session)
    if advice is None:
        advice = build_advice(
            meta,
            market,
            analyses,
            snapshot_dir=snapshot_dir,
            session=session,
        )
    series = build_series_map(analyses, bars_by_code)
    snapshot_path = None
    if make_snapshot:
        snapshot_path = save_snapshot(
            snapshot_dir,
            meta,
            market,
            analyses,
            advice,
            series=series,
        )
    history = list_snapshots(snapshot_dir, limit=history_limit)
    h5_paths = []
    if make_h5:
        h5_paths = write_h5(
            output_dir,
            meta,
            market,
            analyses,
            advice,
            series=series,
            history=history,
        )
    return {
        "meta": meta,
        "advice": advice,
        "series": series,
        "snapshot": snapshot_path,
        "h5": h5_paths,
        "history": history,
    }
