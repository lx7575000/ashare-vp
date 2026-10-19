"""资产池配置加载与校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .models import Asset, Config, Group

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "assets.json"

DEFAULT_SETTINGS = {
    "start_date": "2024-01-01",
    "min_bars": 30,
    "source_order": ["tencent", "sina", "eastmoney"],
    "timeout": 10,
}

VALID_SOURCES = {"tencent", "sina", "eastmoney"}
VALID_KINDS = {"etf", "index"}


class ConfigError(ValueError):
    """配置文件错误。"""


def load_config(path: Optional[str | Path] = None) -> Config:
    """加载 JSON 资产池配置。"""

    config_path = Path(path).expanduser().resolve() if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 JSON: {config_path} ({exc})") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("groups"), list):
        raise ConfigError("配置文件缺少 groups 数组")

    settings = dict(DEFAULT_SETTINGS)
    settings.update(raw.get("settings") or {})
    _validate_settings(settings)

    groups: list[Group] = []
    seen_codes: set[str] = set()
    seen_groups: set[str] = set()

    for item in raw["groups"]:
        if not isinstance(item, dict):
            raise ConfigError("groups 中的每一项必须是对象")
        name = str(item.get("name", "")).strip()
        if not name:
            raise ConfigError("分组缺少 name")
        if name in seen_groups:
            raise ConfigError(f"分组重复: {name}")
        seen_groups.add(name)

        group_kind = str(item.get("kind", "etf")).strip().lower()
        if group_kind not in VALID_KINDS:
            raise ConfigError(f"分组 {name} 的 kind 非法: {group_kind}")

        assets: list[Asset] = []
        for entry in item.get("assets") or []:
            asset = _parse_asset(entry, group=name, default_kind=group_kind)
            if asset.code in seen_codes:
                raise ConfigError(f"标的代码重复: {asset.code}")
            seen_codes.add(asset.code)
            assets.append(asset)

        if not assets:
            raise ConfigError(f"分组 {name} 没有标的")
        groups.append(Group(name=name, kind=group_kind, assets=assets))

    if not groups:
        raise ConfigError("配置文件中没有分组")

    return Config(groups=groups, settings=settings)


def _validate_settings(settings: dict) -> None:
    source_order = settings.get("source_order")
    if not isinstance(source_order, list) or not source_order:
        raise ConfigError("settings.source_order 必须是非空数组")
    for source in source_order:
        if source not in VALID_SOURCES:
            raise ConfigError(f"未知数据源: {source}")

    try:
        min_bars = int(settings.get("min_bars", 30))
    except (TypeError, ValueError) as exc:
        raise ConfigError("settings.min_bars 必须是整数") from exc
    if min_bars < 20:
        raise ConfigError("settings.min_bars 不能小于 20")
    settings["min_bars"] = min_bars

    try:
        timeout = float(settings.get("timeout", 10))
    except (TypeError, ValueError) as exc:
        raise ConfigError("settings.timeout 必须是数字") from exc
    if timeout <= 0:
        raise ConfigError("settings.timeout 必须大于 0")
    settings["timeout"] = timeout

    start_date = str(settings.get("start_date", "2024-01-01"))
    _parse_date(start_date, field_name="settings.start_date")
    settings["start_date"] = start_date


def _parse_asset(entry: dict, group: str, default_kind: str) -> Asset:
    if not isinstance(entry, dict):
        raise ConfigError(f"分组 {group} 中的标的必须是对象")

    code = str(entry.get("code", "")).strip()
    name = str(entry.get("name", "")).strip()
    if not code or not name:
        raise ConfigError(f"分组 {group} 中存在缺少 code/name 的标的")

    kind = str(entry.get("kind", default_kind)).strip().lower()
    if kind not in VALID_KINDS:
        raise ConfigError(f"标的 {code} 的 kind 非法: {kind}")

    exchange = str(entry.get("exchange", "")).strip().upper()
    if not exchange:
        exchange = "SH" if code.startswith(("0", "5", "6", "9")) else "SZ"
    if exchange not in {"SH", "SZ", "BJ"}:
        raise ConfigError(f"标的 {code} 的 exchange 非法: {exchange}")

    secid = str(entry.get("secid", "")).strip()
    if not secid:
        market = "1" if exchange == "SH" else "0"
        secid = f"{market}.{code}"

    tencent = entry.get("tencent")
    sina = entry.get("sina")
    tencent = str(tencent).strip() if tencent else None
    sina = str(sina).strip() if sina else None
    if not tencent and not sina and not secid:
        raise ConfigError(f"标的 {code} 至少需要配置一个数据源代码")

    return Asset(
        code=code,
        name=name,
        group=group,
        kind=kind,
        exchange=exchange,
        secid=secid,
        tencent=tencent,
        sina=sina,
    )


def _parse_date(value: str, field_name: str):
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"{field_name} 不是 YYYY-MM-DD 格式: {value}") from exc


def select_assets(config: Config, groups: Optional[list[str]], codes: Optional[list[str]]):
    """按分组/代码筛选标的。分组支持包含匹配。"""

    selected = []
    group_filters = [g.strip() for g in (groups or []) if g.strip()]
    code_filters = {c.strip() for c in (codes or []) if c.strip()}

    for group in config.groups:
        group_match = not group_filters or any(
            f.lower() in group.name.lower() for f in group_filters
        )
        for asset in group.assets:
            if code_filters and asset.code not in code_filters:
                continue
            if group_filters and not group_match:
                continue
            selected.append(asset)

    if not selected:
        raise ConfigError("筛选后没有可分析的标的，请检查 --group/--code")
    return selected
