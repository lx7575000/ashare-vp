"""多数据源日线抓取与本地缓存。

数据源优先级：腾讯财经 -> 新浪财经 -> 东方财富。
腾讯/新浪用于日线 OHLCV；东方财富可额外提供成交额与换手率。
所有成交量统一换算为“手”。
"""

from __future__ import annotations

import json
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from .models import Asset, Bar, FetchResult

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_SSL_CONTEXT: Optional[ssl.SSLContext] = None
_SSL_WARNINGS: list[str] = []


class FetchError(RuntimeError):
    def __init__(self, message: str, *, network: bool = False):
        super().__init__(message)
        self.network = network


@dataclass
class CachedSeries:
    bars: list[Bar]
    source: str
    fetched_at: str


def _ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT

    mode = os.environ.get("ASHARE_VP_VERIFY_SSL", "").strip().lower()
    if mode in {"0", "false", "no"}:
        _SSL_CONTEXT = ssl._create_unverified_context()
        _SSL_WARNINGS.append(
            "已按 ASHARE_VP_VERIFY_SSL=0 关闭 SSL 证书校验，请仅在可信网络使用"
        )
    else:
        _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def _fallback_ssl(exc: Exception) -> bool:
    """证书校验失败时，除非显式要求校验，否则降级为不校验。"""
    global _SSL_CONTEXT
    mode = os.environ.get("ASHARE_VP_VERIFY_SSL", "").strip().lower()
    if mode in {"1", "true", "yes"}:
        return False
    _SSL_CONTEXT = ssl._create_unverified_context()
    msg = "SSL 证书校验失败，已自动降级为不校验（代理/自签名证书环境）"
    if msg not in _SSL_WARNINGS:
        _SSL_WARNINGS.append(msg)
    return True


def _http_bytes(url: str, *, headers: Optional[dict] = None, timeout: float = 10) -> bytes:
    """带重试与 SSL 降级的原始 HTTP 请求。"""
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"}
    if headers:
        req_headers.update(headers)

    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                raw = resp.read()
            if not raw:
                raise FetchError("接口返回空内容", network=True)
            return raw
        except ssl.SSLCertVerificationError as exc:
            if not _fallback_ssl(exc):
                raise FetchError(f"SSL 证书校验失败: {exc}", network=True) from exc
            last_error = exc
            continue
        except urllib.error.HTTPError as exc:
            last_error = exc
            if 400 <= exc.code < 500:
                raise FetchError(f"HTTP {exc.code}", network=False) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                if not _fallback_ssl(exc.reason):
                    raise FetchError(f"SSL 证书校验失败: {exc.reason}", network=True) from exc
                last_error = exc
                continue
            last_error = exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc

        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))

    raise FetchError(f"网络请求失败: {last_error}", network=True)


def _http_json(url: str, *, headers: Optional[dict] = None, timeout: float = 10) -> object:
    raw = _http_bytes(url, headers=headers, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise FetchError(f"响应不是合法 JSON: {exc}", network=False) from exc


def _http_text(
    url: str,
    *,
    encoding: str = "utf-8",
    headers: Optional[dict] = None,
    timeout: float = 10,
) -> str:
    raw = _http_bytes(url, headers=headers, timeout=timeout)
    return raw.decode(encoding, "replace")


def ssl_warnings() -> list[str]:
    """返回本进程内出现过的 SSL 提示。"""
    return list(_SSL_WARNINGS)


class DataFetcher:
    def __init__(
        self,
        cache_dir: str | Path,
        *,
        start_date: str = "2024-01-01",
        end_date: Optional[str] = None,
        source_order: Optional[Sequence[str]] = None,
        timeout: float = 10,
        min_bars: int = 30,
        offline: bool = False,
        refresh: bool = False,
        delay: float = 0.08,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.start_date = start_date
        self.end_date = end_date or Date.today().isoformat()
        self.source_order = list(source_order or ["tencent", "sina", "eastmoney"])
        self.timeout = timeout
        self.min_bars = min_bars
        self.offline = offline
        self.refresh = refresh
        self.delay = delay
        self.warnings: list[str] = []
        self.used_sources: dict[str, int] = {}
        self._transport_failures: dict[str, int] = {}
        self._disabled_sources: set[str] = set()

    # ------------------------------------------------------------------ public
    def fetch_many(self, assets: Sequence[Asset]) -> tuple[list[FetchResult], list[tuple[Asset, str]]]:
        results: list[FetchResult] = []
        failures: list[tuple[Asset, str]] = []
        for asset in assets:
            try:
                results.append(self.fetch(asset))
            except FetchError as exc:
                failures.append((asset, str(exc)))
        if _SSL_WARNINGS:
            for msg in _SSL_WARNINGS:
                if msg not in self.warnings:
                    self.warnings.append(msg)
        return results, failures

    def fetch(self, asset: Asset) -> FetchResult:
        cached = self._load_cache(asset)
        target = self.end_date

        if self.offline:
            if cached and self._covers(cached, target):
                return FetchResult(asset, cached.bars, cached.source, cached=True)
            raise FetchError("离线模式且本地缓存不足")

        if cached and not self.refresh and self._cache_is_fresh(cached, target):
            return FetchResult(asset, cached.bars, cached.source, cached=True)

        errors: list[str] = []
        for source in self.source_order:
            if source in self._disabled_sources:
                continue
            if not self._supports(asset, source):
                continue
            try:
                bars = self._fetch_source(source, asset)
            except FetchError as exc:
                errors.append(f"{source}: {exc}")
                if exc.network:
                    self._note_transport_failure(source)
                continue

            bars = self._normalize_bars(bars)
            if len(bars) < self.min_bars:
                errors.append(f"{source}: 仅 {len(bars)} 条日线")
                continue

            self._save_cache(asset, bars, source)
            self.used_sources[source] = self.used_sources.get(source, 0) + 1
            if self.delay:
                time.sleep(self.delay)
            return FetchResult(asset, bars, source)

        if cached and self._covers(cached, target):
            warning = "实时抓取失败，使用本地缓存：" + "; ".join(errors[:2])
            return FetchResult(asset, cached.bars, cached.source, cached=True, warning=warning)

        raise FetchError("所有数据源均失败：" + "; ".join(errors[:3]))

    # ------------------------------------------------------------------ cache
    def _cache_path(self, asset: Asset) -> Path:
        return self.cache_dir / f"{asset.exchange.lower()}{asset.code}.json"

    def _load_cache(self, asset: Asset) -> Optional[CachedSeries]:
        path = self._cache_path(asset)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            bars = [Bar.from_list(row) for row in payload.get("bars") or []]
            bars = self._normalize_bars(bars)
            if not bars:
                return None
            return CachedSeries(
                bars=bars,
                source=str(payload.get("source") or "cache"),
                fetched_at=str(payload.get("fetched_at") or ""),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _save_cache(self, asset: Asset, bars: Sequence[Bar], source: str) -> None:
        payload = {
            "version": 1,
            "code": asset.code,
            "name": asset.name,
            "source": source,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "bars": [bar.to_list() for bar in bars],
        }
        path = self._cache_path(asset)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def _cache_is_fresh(self, cached: CachedSeries, target: str) -> bool:
        if not self._covers(cached, target):
            return False
        if target < Date.today().isoformat():
            return True
        fetched_date = cached.fetched_at[:10]
        return fetched_date == Date.today().isoformat()

    def _covers(self, cached: CachedSeries, target: str) -> bool:
        if not cached.bars:
            return False
        first = cached.bars[0].date
        last = cached.bars[-1].date
        if target < first:
            return False
        if cached.fetched_at[:10] == Date.today().isoformat():
            return True
        try:
            gap = (Date.fromisoformat(target) - Date.fromisoformat(last)).days
        except ValueError:
            return False
        return gap <= 10

    # ------------------------------------------------------------------ source
    def _supports(self, asset: Asset, source: str) -> bool:
        if source == "tencent":
            return bool(asset.tencent)
        if source == "sina":
            return bool(asset.sina)
        if source == "eastmoney":
            return bool(asset.secid)
        return False

    def _fetch_source(self, source: str, asset: Asset) -> list[Bar]:
        if source == "tencent":
            return self._fetch_tencent(asset)
        if source == "sina":
            return self._fetch_sina(asset)
        if source == "eastmoney":
            return self._fetch_eastmoney(asset)
        raise FetchError(f"未知数据源: {source}")

    def _fetch_tencent(self, asset: Asset) -> list[Bar]:
        symbol = asset.tencent
        if not symbol:
            raise FetchError("未配置腾讯代码")
        param = f"{symbol},day,{self.start_date},{self.end_date},1023,qfq"
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
            + urllib.parse.quote(param, safe=",")
        )
        payload = _http_json(url, timeout=self.timeout)
        if not isinstance(payload, dict):
            raise FetchError("腾讯接口返回格式异常")
        node = (payload.get("data") or {}).get(symbol) or {}
        rows = node.get("qfqday") or node.get("day") or []
        bars: list[Bar] = []
        for row in rows:
            if isinstance(row, dict):
                row = [
                    row.get("date"),
                    row.get("open"),
                    row.get("close"),
                    row.get("high"),
                    row.get("low"),
                    row.get("volume"),
                ]
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                # 腾讯顺序：日期, 开, 收, 高, 低, 量(手)
                bars.append(
                    Bar(
                        date=str(row[0]),
                        open=float(row[1]),
                        close=float(row[2]),
                        high=float(row[3]),
                        low=float(row[4]),
                        volume=float(row[5]),
                        amount=None,
                    )
                )
            except (TypeError, ValueError):
                continue
        return bars

    def _fetch_sina(self, asset: Asset) -> list[Bar]:
        symbol = asset.sina
        if not symbol:
            raise FetchError("未配置新浪代码")
        url = (
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={urllib.parse.quote(symbol)}"
            "&scale=240&ma=no&datalen=1023"
        )
        payload = _http_json(
            url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=self.timeout
        )
        if payload is None:
            raise FetchError("新浪接口无数据")
        if not isinstance(payload, list):
            raise FetchError("新浪接口返回格式异常")
        bars: list[Bar] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            try:
                # 新浪成交量单位为股，换算为手
                volume = float(row["volume"]) / 100.0
                bars.append(
                    Bar(
                        date=str(row["day"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=volume,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return bars

    def _fetch_eastmoney(self, asset: Asset) -> list[Bar]:
        query = {
            "secid": asset.secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "beg": self.start_date.replace("-", ""),
            "end": self.end_date.replace("-", ""),
        }
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            + urllib.parse.urlencode(query)
        )
        payload = _http_json(url, timeout=self.timeout)
        if not isinstance(payload, dict):
            raise FetchError("东方财富接口返回格式异常")
        rows = (payload.get("data") or {}).get("klines") or []
        bars: list[Bar] = []
        for row in rows:
            parts = str(row).split(",")
            if len(parts) < 7:
                continue
            try:
                # 东财顺序：日期, 开, 收, 高, 低, 量(手), 额(元), 振幅, 涨跌幅, 涨跌额, 换手率
                bars.append(
                    Bar(
                        date=parts[0],
                        open=float(parts[1]),
                        close=float(parts[2]),
                        high=float(parts[3]),
                        low=float(parts[4]),
                        volume=float(parts[5]),
                        amount=float(parts[6]) if _is_number(parts[6]) else None,
                        turnover=float(parts[10]) if len(parts) > 10 and _is_number(parts[10]) else None,
                    )
                )
            except (TypeError, ValueError):
                continue
        return bars

    # ------------------------------------------------------------------ helper
    def _normalize_bars(self, bars: Sequence[Bar]) -> list[Bar]:
        by_date: dict[str, Bar] = {}
        for bar in bars:
            try:
                if not bar.date or len(bar.date) != 10:
                    continue
                values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
                if any(value is None or not _is_finite(value) for value in values):
                    continue
                if bar.open <= 0 or bar.close <= 0 or bar.high <= 0 or bar.low <= 0:
                    continue
                if bar.volume < 0:
                    continue
                high = max(bar.high, bar.open, bar.close, bar.low)
                low = min(bar.low, bar.open, bar.close, bar.high)
                by_date[bar.date] = Bar(
                    date=bar.date,
                    open=bar.open,
                    high=high,
                    low=low,
                    close=bar.close,
                    volume=bar.volume,
                    amount=bar.amount,
                    turnover=bar.turnover,
                )
            except (TypeError, ValueError):
                continue
        return [by_date[key] for key in sorted(by_date)]

    def _note_transport_failure(self, source: str) -> None:
        count = self._transport_failures.get(source, 0) + 1
        self._transport_failures[source] = count
        if count >= 3:
            self._disabled_sources.add(source)
            self.warnings.append(f"数据源 {source} 连续失败 {count} 次，本次运行已跳过")

    def _covers_target(self, asset: Asset, target: str) -> bool:
        cached = self._load_cache(asset)
        return bool(cached and self._covers(cached, target))


def _is_number(value) -> bool:
    if value in (None, "", "-", "--"):
        return False
    try:
        return _is_finite(float(value))
    except (TypeError, ValueError):
        return False


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
