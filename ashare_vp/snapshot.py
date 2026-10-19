"""分析快照留存、索引与历史读取。"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date as Date
from pathlib import Path
from statistics import fmean
from typing import Optional, Sequence

from .analysis import AssetAnalysis
from .models import Bar

SESSION_ORDER = {"1030": 0, "1100": 1, "1400": 2, "close": 3}


def build_series(bars: Sequence[Bar], limit: int = 60) -> dict:
    closes = [bar.close for bar in bars]
    ma20 = []
    total = 0.0
    for i, value in enumerate(closes):
        total += value
        if i >= 20:
            total -= closes[i - 20]
        ma20.append(round(total / 20.0, 4) if i >= 19 else None)
    sample = bars[-limit:]
    offset = max(0, len(bars) - limit)
    return {
        "dates": [bar.date for bar in sample],
        "close": [round(bar.close, 4) for bar in sample],
        "volume": [round(bar.volume, 2) for bar in sample],
        "ma20": ma20[offset:],
    }


def build_series_map(analyses: Sequence[AssetAnalysis], bars_by_code: dict) -> dict:
    return {
        analysis.asset.code: build_series(bars_by_code.get(analysis.asset.code, []))
        for analysis in analyses
    }


def snapshot_key(meta: dict) -> str:
    return f"{meta.get('as_of', '')}-{meta.get('session', 'close')}"


def save_snapshot(
    snapshot_dir: str | Path,
    meta: dict,
    market: dict,
    analyses: Sequence[AssetAnalysis],
    advice: dict,
    *,
    series: Optional[dict] = None,
    retain_days: int = 180,
) -> Path:
    root = Path(snapshot_dir)
    day = meta.get("as_of") or Date.today().isoformat()
    session = meta.get("session") or "close"
    directory = root / day
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session}.json"

    assets = []
    for analysis in analyses:
        payload = analysis.to_dict()
        payload["advice"] = (advice.get("items") or {}).get(analysis.asset.code)
        payload["series"] = (series or {}).get(analysis.asset.code)
        assets.append(payload)

    snapshot = {
        "version": 1,
        "meta": meta,
        "market": market,
        "advice": advice,
        "assets": assets,
    }
    _write_json(path, snapshot)
    # 先清理过期快照，再重建索引：避免索引里残留已删除文件的条目。
    _prune(root, retain_days, keep=day)
    _update_index(root, meta, market, advice, path)
    return path


def load_snapshot(path: str | Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_latest_snapshot(
    snapshot_dir: str | Path, *, before_key: Optional[str] = None
) -> Optional[dict]:
    """读取 ``before_key`` 之前最新的一份快照。

    索引可能因手工删除、清理或异常退出而指向不存在的文件，因此按时间倒序
    逐个尝试，而不是只信任索引里的第一条。
    """
    root = Path(snapshot_dir)
    entries = _all_entries(root)
    candidates = []
    for entry in entries:
        key = entry.get("key") or f"{entry.get('date')}-{entry.get('session')}"
        if before_key and key >= before_key:
            continue
        candidates.append((key, entry))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, entry in candidates:
        snapshot = _load_entry(root, entry)
        if snapshot:
            return snapshot
    return None


def list_snapshots(snapshot_dir: str | Path, limit: int = 50) -> list[dict]:
    entries = _all_entries(Path(snapshot_dir))
    entries.sort(key=lambda item: item.get("key", ""), reverse=True)
    return entries[:limit]


def _update_index(root: Path, meta: dict, market: dict, advice: dict, path: Path) -> None:
    index_path = root / "index.json"
    entries = _all_entries(root)
    key = snapshot_key(meta)
    entry = {
        "key": key,
        "date": meta.get("as_of"),
        "session": meta.get("session", "close"),
        "session_label": meta.get("session_label", meta.get("session", "close")),
        "generated_at": meta.get("generated_at"),
        "regime": market.get("regime"),
        "up": market.get("up"),
        "down": market.get("down"),
        "above_ma20_ratio": market.get("above_ma20_ratio"),
        "avg_score": round(fmean([item.get("score", 0) for item in (advice.get("items") or {}).values()]), 2)
        if advice.get("items")
        else None,
        "near_high": len(advice.get("near_high") or []),
        "near_low": len(advice.get("near_low") or []),
        "path": str(path),
    }
    entries = [
        item
        for item in entries
        if item.get("key") != key and _entry_path(root, item) is not None
    ]
    entries.append(entry)
    entries.sort(key=lambda item: item.get("key", ""))
    _write_json(index_path, {"version": 1, "snapshots": entries[-500:]})


def _read_index(root: Path) -> list[dict]:
    path = root / "index.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    snapshots = payload.get("snapshots") if isinstance(payload, dict) else None
    return list(snapshots or [])


def _scan_entries(root: Path) -> list[dict]:
    entries = []
    if not root.exists():
        return entries
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            Date.fromisoformat(directory.name)
        except ValueError:
            continue
        for path in directory.glob("*.json"):
            session = path.stem
            entries.append(
                {
                    "key": f"{directory.name}-{session}",
                    "date": directory.name,
                    "session": session,
                    "path": str(path),
                }
            )
    return entries


def _entry_path(root: Path, entry: dict) -> Optional[Path]:
    """返回索引条目的有效文件路径；文件不存在时返回 None。"""
    raw = entry.get("path")
    if raw:
        path = Path(raw)
        if path.exists():
            return path
    day = entry.get("date")
    session = entry.get("session")
    if day and session:
        path = root / str(day) / f"{session}.json"
        if path.exists():
            return path
    return None


def _valid_entries(root: Path, entries: Sequence[dict]) -> list[dict]:
    return [entry for entry in entries if _entry_path(root, entry) is not None]


def _all_entries(root: Path) -> list[dict]:
    """合并索引与磁盘扫描结果，索引缺失/损坏时也能发现已有快照。"""
    merged: dict[str, dict] = {}
    for entry in _valid_entries(root, _read_index(root)):
        key = entry.get("key") or f"{entry.get('date')}-{entry.get('session')}"
        merged[key] = entry
    for entry in _scan_entries(root):
        merged.setdefault(entry["key"], entry)
    return list(merged.values())


def _load_entry(root: Path, entry: dict) -> Optional[dict]:
    path = _entry_path(root, entry)
    return load_snapshot(path) if path else None


def _prune(root: Path, retain_days: int, *, keep: Optional[str] = None) -> None:
    """删除相对“最新快照日期”超过保留天数的快照。

    以快照目录中的最新日期为基准，而不是系统当前日期，避免回放/补录历史
    数据时刚写入的快照被立即清理。``keep`` 指定的日期永不删除。
    """
    if retain_days <= 0:
        return
    days = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            days.append(Date.fromisoformat(directory.name))
        except ValueError:
            continue
    if keep:
        try:
            days.append(Date.fromisoformat(keep))
        except ValueError:
            pass
    if not days:
        return
    cutoff = max(days).toordinal() - retain_days
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            day = Date.fromisoformat(directory.name)
        except ValueError:
            continue
        if day.toordinal() >= cutoff or directory.name == keep:
            continue
        for path in directory.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
