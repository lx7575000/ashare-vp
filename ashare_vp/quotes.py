"""实时行情快照（腾讯财经）与盘中合成日线。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as Time
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from .datasource import FetchError, _http_text, ssl_warnings
from .models import Asset, Bar

TZ = ZoneInfo("Asia/Shanghai")
TRADING_MINUTES = 240.0

SESSION_LABELS = {
    "1030": "10:30 盘中",
    "1100": "11:00 盘中",
    "1400": "14:00 盘中",
    "close": "收盘",
}

# 10:30 / 11:00 / 14:00 / 收盘对应的已交易时长比例
SESSION_FRACTIONS = {
    "1030": 60.0 / TRADING_MINUTES,
    "1100": 90.0 / TRADING_MINUTES,
    "1400": 180.0 / TRADING_MINUTES,
    "close": 1.0,
}


@dataclass
class Quote:
    code: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float  # 手
    amount: Optional[float]  # 元
    timestamp: str  # YYYYMMDDHHMMSS
    change_pct: Optional[float] = None
    turnover: Optional[float] = None
    volume_ratio: Optional[float] = None
    avg_price: Optional[float] = None

    @property
    def date(self) -> str:
        if len(self.timestamp) >= 8:
            return f"{self.timestamp[:4]}-{self.timestamp[4:6]}-{self.timestamp[6:8]}"
        return ""

    @property
    def time(self) -> str:
        if len(self.timestamp) >= 14:
            return f"{self.timestamp[8:10]}:{self.timestamp[10:12]}:{self.timestamp[12:14]}"
        if len(self.timestamp) >= 12:
            return f"{self.timestamp[8:10]}:{self.timestamp[10:12]}"
        return ""

    def to_bar(self, asset: Asset, elapsed_fraction: float = 1.0) -> Bar:
        """把快照转换为“按当前进度折算的全天等效日线”。"""
        fraction = max(0.05, min(1.0, elapsed_fraction))
        volume = self.volume / fraction
        amount = self.amount / fraction if self.amount is not None else None
        turnover = self.turnover / fraction if self.turnover is not None and asset.is_etf else None
        open_price = self.open if self.open > 0 else self.price
        high = max(self.high, open_price, self.price, self.low)
        low = min(self.low, open_price, self.price, self.high)
        return Bar(
            date=self.date,
            open=open_price,
            high=high,
            low=low,
            close=self.price,
            volume=volume,
            amount=amount,
            turnover=turnover,
        )


def _symbol(asset: Asset) -> Optional[str]:
    if asset.tencent:
        return asset.tencent
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(asset.exchange)
    return f"{prefix}{asset.code}" if prefix else None


def fetch_quotes(
    assets: Sequence[Asset], *, timeout: float = 10
) -> tuple[dict[str, Quote], list[str]]:
    """批量抓取实时快照，返回 {code: Quote} 与提示信息。"""
    symbols = []
    wanted = {}
    for asset in assets:
        symbol = _symbol(asset)
        if symbol:
            symbols.append(symbol)
            wanted[asset.code] = asset

    quotes: dict[str, Quote] = {}
    errors: list[str] = []
    for start in range(0, len(symbols), 50):
        chunk = symbols[start : start + 50]
        url = "https://qt.gtimg.cn/q=" + ",".join(chunk)
        try:
            text = _http_text(
                url,
                encoding="gbk",
                headers={"Referer": "https://finance.qq.com/"},
                timeout=timeout,
            )
        except FetchError as exc:
            errors.append(str(exc))
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("v_") or '="' not in line:
                continue
            body = line.split('="', 1)[1].rsplit('"', 1)[0]
            fields = body.split("~")
            if len(fields) < 35:
                continue
            try:
                code = fields[2]
                if code not in wanted:
                    continue
                price = float(fields[3])
                prev_close = float(fields[4])
                open_price = float(fields[5])
                volume = float(fields[6])
                high = float(fields[33])
                low = float(fields[34])
                if (
                    price <= 0
                    or prev_close <= 0
                    or open_price <= 0
                    or volume < 0
                    or high <= 0
                    or low <= 0
                ):
                    continue
                amount = _parse_amount(fields)
                timestamp = fields[30].strip() if len(fields) > 30 else ""
                change_pct = _to_float(fields[32]) if len(fields) > 32 else None
                turnover = _to_float(fields[38]) if len(fields) > 38 else None
                volume_ratio = _to_float(fields[49]) if len(fields) > 49 else None
                avg_price = _to_float(fields[51]) if len(fields) > 51 else None
                quotes[code] = Quote(
                    code=code,
                    name=fields[1] or wanted[code].name,
                    price=price,
                    prev_close=prev_close,
                    open=open_price,
                    high=high,
                    low=low,
                    volume=volume,
                    amount=amount,
                    timestamp=timestamp,
                    change_pct=change_pct,
                    turnover=turnover,
                    volume_ratio=volume_ratio,
                    avg_price=avg_price,
                )
            except (TypeError, ValueError, IndexError):
                continue

    warnings = ssl_warnings()
    warnings.extend(errors)
    return quotes, warnings


def _parse_amount(fields: Sequence[str]) -> Optional[float]:
    # fields[35] = 价格/成交量/成交额（元），比 fields[37]（万元）更精确
    if len(fields) > 35 and "/" in fields[35]:
        parts = fields[35].split("/")
        if len(parts) >= 3:
            value = _to_float(parts[2])
            if value:
                return value
    if len(fields) > 37:
        value = _to_float(fields[37])
        if value:
            return value * 10000.0
    return None


def _to_float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def session_fraction(session: str, now: Optional[datetime] = None) -> float:
    if session in SESSION_FRACTIONS:
        return SESSION_FRACTIONS[session]
    return elapsed_fraction(now)


def quote_elapsed_fraction(quote: Quote) -> float:
    """按快照时间计算已交易比例，避免用收盘快照重复外推成交量。"""
    if len(quote.timestamp) >= 12:
        try:
            hour = int(quote.timestamp[8:10])
            minute = int(quote.timestamp[10:12])
        except ValueError:
            return session_fraction("close")
        clock = hour * 60 + minute
        if clock < 9 * 60 + 30:
            minutes = 5.0
        elif clock <= 11 * 60 + 30:
            minutes = clock - (9 * 60 + 30)
        elif clock < 13 * 60:
            minutes = 120.0
        elif clock <= 15 * 60:
            minutes = 120.0 + clock - 13 * 60
        else:
            minutes = TRADING_MINUTES
        return max(5.0, min(TRADING_MINUTES, minutes)) / TRADING_MINUTES
    return session_fraction("close")


def session_elapsed_minutes(now: Optional[datetime] = None) -> float:
    """当前时点已交易的分钟数（9:30-11:30，13:00-15:00）。"""
    current = now.astimezone(TZ) if now else datetime.now(TZ)
    clock = current.time()
    if clock < Time(9, 30):
        return 0.0
    if clock <= Time(11, 30):
        return (current.hour * 60 + current.minute) - (9 * 60 + 30)
    if clock < Time(13, 0):
        return 120.0
    if clock <= Time(15, 0):
        return 120.0 + (current.hour * 60 + current.minute) - (13 * 60)
    return TRADING_MINUTES


def elapsed_fraction(now: Optional[datetime] = None) -> float:
    """已交易时长占全天 240 分钟的比例，用于成交量外推。"""
    minutes = session_elapsed_minutes(now)
    return max(5.0, min(TRADING_MINUTES, minutes)) / TRADING_MINUTES


def is_quote_current(quote: Quote, now: Optional[datetime] = None) -> bool:
    current = now.astimezone(TZ) if now else datetime.now(TZ)
    return quote.date == current.date().isoformat()


def current_session_key(now: Optional[datetime] = None) -> str:
    """根据当前时间推断会话标签，主要用于手动运行。"""
    current = now.astimezone(TZ) if now else datetime.now(TZ)
    minutes = current.hour * 60 + current.minute
    if minutes < 11 * 60:
        return "1030"
    if minutes < 11 * 60 + 30:
        return "1100"
    if minutes < 13 * 60:
        return "1100"
    if minutes < 15 * 60:
        return "1400"
    return "close"


def session_label(session: str) -> str:
    return SESSION_LABELS.get(session, session)
