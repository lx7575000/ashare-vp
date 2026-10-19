"""数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Asset:
    """一个可分析的标的。"""

    code: str
    name: str
    group: str
    kind: str  # etf / index
    exchange: str  # SH / SZ / BJ
    secid: str  # 东方财富 secid
    tencent: Optional[str] = None
    sina: Optional[str] = None

    @property
    def symbol(self) -> str:
        return self.tencent or self.sina or self.secid

    @property
    def is_etf(self) -> bool:
        return self.kind == "etf"


@dataclass
class Bar:
    """日线行情。volume 统一为“手”，amount 单位为元。"""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None
    turnover: Optional[float] = None

    def to_list(self) -> list:
        return [
            self.date,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.amount,
            self.turnover,
        ]

    @classmethod
    def from_list(cls, row: list) -> "Bar":
        def _opt(value):
            return None if value is None or value == "" else float(value)

        return cls(
            date=str(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            amount=_opt(row[6]) if len(row) > 6 else None,
            turnover=_opt(row[7]) if len(row) > 7 else None,
        )


@dataclass
class FetchResult:
    asset: Asset
    bars: list[Bar]
    source: str
    cached: bool = False
    warning: Optional[str] = None


@dataclass
class Config:
    groups: list  # list[Group]
    settings: dict = field(default_factory=dict)

    @property
    def assets(self) -> list[Asset]:
        return [asset for group in self.groups for asset in group.assets]


@dataclass
class Group:
    name: str
    kind: str
    assets: list[Asset]
