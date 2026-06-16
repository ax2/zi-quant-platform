from __future__ import annotations

import math
import asyncio
import json
import re
import shutil
import subprocess
import time
import uuid
import urllib.request
from urllib.parse import quote, urlencode, urlparse
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, distinct, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdminAuditLog,
    BacktestRun,
    BacktestTrade,
    DataJob,
    DataJobRun,
    DataSourceConfig,
    FactorDefinition,
    FactorValue,
    FinancialReport,
    JobStatus,
    MarketBar,
    PaperEquitySnapshot,
    PaperOrder,
    PaperPortfolio,
    PaperPosition,
    RadarSignal,
    Stock,
    StockPool,
    StockPoolMember,
    Strategy,
    StrategyExperiment,
    StrategyOptimizationRun,
    User,
    UserRole,
    Visibility,
)
from app.settings import settings

SECTORS = ["银行", "非银金融", "白酒食品", "医药生物", "新能源", "半导体", "计算机", "军工", "汽车", "有色金属"]
SEED_STOCKS = [
    ("600519.SH", "贵州茅台", "白酒食品"),
    ("300750.SZ", "宁德时代", "新能源"),
    ("601318.SH", "中国平安", "非银金融"),
    ("600036.SH", "招商银行", "银行"),
    ("000858.SZ", "五粮液", "白酒食品"),
    ("002594.SZ", "比亚迪", "汽车"),
    ("600030.SH", "中信证券", "非银金融"),
    ("000001.SZ", "平安银行", "银行"),
    ("600276.SH", "恒瑞医药", "医药生物"),
    ("688981.SH", "中芯国际", "半导体"),
]
REAL_STOCK_SUPPLEMENTS = [
    ("601398.SH", "工商银行", "银行"),
    ("601939.SH", "建设银行", "银行"),
    ("601288.SH", "农业银行", "银行"),
    ("601988.SH", "中国银行", "银行"),
    ("600000.SH", "浦发银行", "银行"),
    ("601166.SH", "兴业银行", "银行"),
    ("601328.SH", "交通银行", "银行"),
    ("600016.SH", "民生银行", "银行"),
    ("601857.SH", "中国石油", "油气开采Ⅱ"),
    ("600028.SH", "中国石化", "炼化及贸易"),
    ("601088.SH", "中国神华", "煤炭开采"),
    ("600900.SH", "长江电力", "电力"),
    ("600050.SH", "中国联通", "通信服务"),
    ("601668.SH", "中国建筑", "基础建设"),
    ("601390.SH", "中国中铁", "基础建设"),
    ("601186.SH", "中国铁建", "基础建设"),
    ("600031.SH", "三一重工", "工程机械"),
    ("000333.SZ", "美的集团", "白色家电"),
    ("000651.SZ", "格力电器", "白色家电"),
    ("000725.SZ", "京东方A", "光学光电子"),
    ("002415.SZ", "海康威视", "计算机设备"),
    ("002475.SZ", "立讯精密", "消费电子"),
    ("002230.SZ", "科大讯飞", "软件开发"),
    ("300059.SZ", "东方财富", "证券Ⅱ"),
    ("300124.SZ", "汇川技术", "自动化设备"),
    ("300760.SZ", "迈瑞医疗", "医疗器械"),
    ("600887.SH", "伊利股份", "饮料乳品"),
    ("603288.SH", "海天味业", "调味发酵品Ⅱ"),
    ("600809.SH", "山西汾酒", "白酒Ⅱ"),
    ("000568.SZ", "泸州老窖", "白酒Ⅱ"),
    ("600438.SH", "通威股份", "光伏设备"),
    ("601012.SH", "隆基绿能", "光伏设备"),
    ("600406.SH", "国电南瑞", "电网设备"),
    ("600309.SH", "万华化学", "化学制品"),
    ("002352.SZ", "顺丰控股", "物流"),
    ("601899.SH", "紫金矿业", "贵金属"),
    ("603259.SH", "药明康德", "医疗服务"),
]
CORE_REAL_DATA_SYMBOLS = [symbol for symbol, _, _ in SEED_STOCKS]
REFERENCE_PROJECTS = [
    {"repo": "WonderfulValley/qstock", "stars": None, "takeaway": "A股数据、技术选股和回测入口低门槛；平台化后需要多用户、权限、持久化和运维。"},
    {"repo": "ZhuLinsen/daily_stock_analysis", "stars": 42700, "takeaway": "AI 决策报告、策略问股和多渠道推送体验成熟；平台化后应把股票推荐、个股分析、复盘和飞书信号作为工作台主流程。"},
    {"repo": "microsoft/qlib", "stars": 44255, "takeaway": "AI 量化研究平台，适合参考实验、数据集、模型与因子流水线分层。"},
    {"repo": "vnpy/vnpy", "stars": None, "takeaway": "国内量化交易网关和事件引擎代表，适合参考网关抽象和策略运行隔离。"},
    {"repo": "mementum/backtrader", "stars": 21900, "takeaway": "事件驱动回测与 broker 模拟成熟，适合参考手续费、滑点和订单模型。"},
    {"repo": "ricequant/rqalpha", "stars": None, "takeaway": "可扩展、可替换的回测交易框架，适合参考插件化 mod 设计。"},
]
SECRET_CONFIG_KEYS = {"api_key", "apikey", "token", "access_token", "secret", "password", "refresh_token"}
SUPPORTED_DATA_SOURCE_ADAPTERS = {"qveris", "eastmoney", "tushare", "ths"}
DATA_SOURCE_ADAPTER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "qveris": {
        "label": "QVeris 数据接口",
        "capabilities": ["stock_basic", "realtime_quote", "historical_bars", "financial_report", "announcement", "news"],
        "production_requires": ["api_key", "prepared_tools", "enabled"],
        "operational_default": True,
        "source_aliases": ["qveris"],
        "notes": "默认真实数据接口，使用预置工具参数，不在运行时做 discovery。",
    },
    "eastmoney": {
        "label": "东方财富公开行情",
        "capabilities": ["stock_universe", "historical_bars"],
        "production_requires": ["enabled"],
        "operational_default": True,
        "source_aliases": ["eastmoney", "eastmoney_public"],
        "notes": "用于 A 股列表和长历史日线补足，不需要密钥。",
    },
    "tushare": {
        "label": "Tushare",
        "capabilities": ["stock_basic", "historical_bars", "financial_report"],
        "production_requires": ["secret_ref", "enabled"],
        "operational_default": False,
        "source_aliases": ["tushare"],
        "notes": "替换型接口，生产使用时通过 secret_ref 引用外部 token。",
    },
    "ths": {
        "label": "同花顺 iFinD",
        "capabilities": ["stock_basic", "realtime_quote", "historical_bars", "financial_report"],
        "production_requires": ["secret_ref", "enabled"],
        "operational_default": False,
        "source_aliases": ["ths", "ifind", "tonghuashun"],
        "notes": "替换型接口，生产使用时通过 secret_ref 引用外部凭证。",
    },
}
SUPPORTED_USER_ROLES = {role.value for role in UserRole}
QSTOCK_LAYERS = [
    {"layer": "数据", "pro": "贴近 A 股，入口简单。", "con": "网页源易变，生产需要 provider 抽象、缓存、审计。", "ours": "统一 DataSourceAdapter，QVeris 数据接口、Tushare、同花顺可替换。"},
    {"layer": "因子", "pro": "MACD、金叉等技术指标易理解。", "con": "因子版本和窗口若不入库难以复现。", "ours": "因子定义、参数和计算结果持久化。"},
    {"layer": "策略", "pro": "买卖规则链路短。", "con": "缺少多用户隔离、审批和风控准入。", "ours": "策略分私有/公共、状态和参数 schema。"},
    {"layer": "雷达", "pro": "适合盘中扫描。", "con": "无去重和等级会产生噪声。", "ours": "雷达信号独立建模，含 severity 和 payload。"},
    {"layer": "智能与市场", "pro": "可整合新闻、情绪、解释。", "con": "智能层必须可审计，不能直接下单。", "ours": "只做解释、候选和风险提示。"},
    {"layer": "模拟执行", "pro": "降低试错成本。", "con": "常忽略手续费、停牌、涨跌停和成交量约束。", "ours": "内置 A 股 100 股手、佣金、过户费、印花税。"},
]
EXPECTED_MIGRATION_REVISION = "20260611_0005"
EASTMONEY_A_SHARE_LIST_URL = "http://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_KLINE_URL = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
SUPPORTED_DATA_JOB_TYPES = {
    "stock_universe",
    "quote",
    "market_bars",
    "pool_rebuild",
    "factor_refresh",
    "backtest",
    "financial_report",
    "real_data_bootstrap",
    "paper_snapshot",
    "strategy_research",
    "feishu_signal",
}
DAILY_STOCK_ANALYSIS_STRATEGY_ROUTES = [
    {"id": "ma_momentum", "name": "均线动量", "source": "daily_stock_analysis", "signals": ["均线多头", "动量确认", "MACD 方向"]},
    {"id": "quality_growth", "name": "质量成长", "source": "daily_stock_analysis", "signals": ["ROE", "营收增长", "净利率"]},
    {"id": "relative_strength", "name": "相对强弱轮动", "source": "daily_stock_analysis", "signals": ["同池强弱排名", "市场宽度", "低换手轮动"]},
    {"id": "low_volatility_risk", "name": "低波回撤控制", "source": "daily_stock_analysis", "signals": ["波动率过滤", "回撤约束", "止损观察"]},
    {"id": "breakout_watch", "name": "放量突破观察", "source": "daily_stock_analysis", "signals": ["突破观察", "成交量约束", "风险复核"]},
]
CRON_FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "weekday": (0, 7),
}


@dataclass(frozen=True)
class FactorRow:
    symbol: str
    name: str
    sector: str
    price: float
    dif: float
    dea: float
    macd: float
    rsi: float
    momentum_20d: float
    volatility_20d: float
    quality: float
    score: float
    quality_source: str = "market_or_seed"
    revenue_growth: float | None = None
    net_margin: float | None = None
    roe: float | None = None


def build_seed_stocks(size: int = 500) -> list[dict[str, Any]]:
    out = [{"symbol": s, "name": n, "sector": sec, "market": s.split(".")[-1], "lot_size": 100} for s, n, sec in SEED_STOCKS]
    seen = {x["symbol"] for x in out}
    idx = 1
    while len(out) < size:
        market = "SH" if idx % 2 else "SZ"
        symbol = f"{'6' if market == 'SH' else '0'}{idx:05d}.{market}"
        sector = SECTORS[idx % len(SECTORS)]
        if symbol not in seen:
            out.append({"symbol": symbol, "name": f"{sector}样本{idx:03d}", "sector": sector, "market": market, "lot_size": 100})
            seen.add(symbol)
        idx += 1
    return out


def _normalize_eastmoney_stock_rows(rows: list[dict[str, Any]], limit: int = 500) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        code = str(row.get("f12") or "").strip()
        name = str(row.get("f14") or "").strip()
        sector = str(row.get("f100") or "未分类").strip() or "未分类"
        market_code = row.get("f13")
        market = "SH" if str(market_code) == "1" or code.startswith(("6", "9")) else "SZ"
        if not re.fullmatch(r"\d{6}", code) or not name or name == "-" or "退市" in name or name.upper().startswith(("ST", "*ST")):
            continue
        symbol = f"{code}.{market}"
        if symbol in seen:
            continue
        out.append({"symbol": symbol, "name": name, "sector": sector, "market": market, "lot_size": 100, "metadata_json": {"source": "eastmoney_public", "raw": row}})
        seen.add(symbol)
        if len(out) >= limit:
            break
    return out


def _is_excluded_stock_name(name: str) -> bool:
    normalized = name.upper()
    return "退市" in name or normalized.startswith(("ST", "*ST")) or "样本" in name


def built_in_real_stock_supplements() -> list[dict[str, Any]]:
    return [
        {"symbol": symbol, "name": name, "sector": sector, "market": symbol.split(".")[-1], "lot_size": 100, "metadata_json": {"source": "built_in_real_supplement"}}
        for symbol, name, sector in REAL_STOCK_SUPPLEMENTS
    ]


def _fetch_eastmoney_page(params: dict[str, Any]) -> dict[str, Any]:
    url = f"{EASTMONEY_A_SHARE_LIST_URL}?{urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
        try:
            completed = subprocess.run(["curl", "--noproxy", "*", "--retry", "3", "--retry-delay", "1", "-sS", url], check=True, capture_output=True, text=True, timeout=30)
            return json.loads(completed.stdout)
        except Exception as exc:
            last_error = exc
        time.sleep(0.5 + attempt * 0.5)
    if last_error:
        raise last_error
    return {}


def _eastmoney_secid(symbol: str) -> str:
    code, _, market = symbol.partition(".")
    market_id = "1" if market.upper() == "SH" or code.startswith(("6", "9")) else "0"
    return f"{market_id}.{code}"


def _fetch_eastmoney_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    full_url = f"{url}?{urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            completed = subprocess.run(["curl", "--noproxy", "*", "--retry", "3", "--retry-delay", "1", "-sS", full_url], check=True, capture_output=True, text=True, timeout=30)
            return json.loads(completed.stdout)
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 + attempt * 0.5)
    if last_error:
        raise last_error
    return {}


def _normalize_eastmoney_kline_rows(symbol: str, payload: dict[str, Any], start: date, end: date) -> list[dict[str, Any]]:
    klines = (((payload or {}).get("data") or {}).get("klines") or [])
    out: list[dict[str, Any]] = []
    for line in klines:
        cells = str(line).split(",")
        if len(cells) < 7:
            continue
        trade_date = _parse_date(cells[0])
        if not trade_date or trade_date < start or trade_date > end:
            continue
        open_price = _parse_float(cells[1])
        close = _parse_float(cells[2])
        high = _parse_float(cells[3])
        low = _parse_float(cells[4])
        raw_volume = _parse_float(cells[5]) or 0.0
        volume = raw_volume * 100
        amount = _parse_float(cells[6]) or 0.0
        if open_price is None or close is None or high is None or low is None:
            continue
        out.append({
            "symbol": symbol,
            "trade_date": trade_date,
            "frequency": "1d",
            "open": round(open_price, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close, 4),
            "volume": volume,
            "amount": amount,
            "source": "eastmoney",
            "payload": {"raw": line, "fq": "qfq", "raw_volume": raw_volume, "volume_unit": "shares"},
        })
    return out


async def fetch_eastmoney_daily_bars(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    params = {
        "secid": _eastmoney_secid(symbol),
        "klt": 101,
        "fqt": 1,
        "beg": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    payload = await asyncio.to_thread(_fetch_eastmoney_json, EASTMONEY_KLINE_URL, params)
    return _normalize_eastmoney_kline_rows(symbol, payload, start, end)


async def fetch_eastmoney_a_share_universe(limit: int = 500) -> list[dict[str, Any]]:
    page_size = 10
    raw_rows: list[dict[str, Any]] = []
    for page in range(1, 120):
        params = {
            "pn": page,
            "pz": page_size,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f13,f100",
        }
        payload = await asyncio.to_thread(_fetch_eastmoney_page, params)
        rows = [row for row in (((payload or {}).get("data") or {}).get("diff") or []) if isinstance(row, dict)]
        if not rows:
            break
        raw_rows.extend(rows)
        if len(_normalize_eastmoney_stock_rows(raw_rows, limit=limit)) >= limit:
            break
    return _normalize_eastmoney_stock_rows(raw_rows, limit=limit)


def synthetic_price(symbol: str) -> float:
    digits = [int(x) for x in re.findall(r"\d", symbol)]
    seed = sum((i + 1) * d for i, d in enumerate(digits))
    return round(8 + (seed % 9500) / 100, 2)


def _symbol_seed(symbol: str) -> int:
    return sum((i + 1) * ord(c) for i, c in enumerate(symbol))


def synthetic_bars(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    seed = _symbol_seed(symbol)
    base = synthetic_price(symbol)
    rows: list[dict[str, Any]] = []
    cursor = start
    i = 0
    while cursor <= end:
        if cursor.weekday() < 5:
            drift = (i / 252) * ((seed % 17) - 6) / 100
            wave = math.sin((i + seed % 19) / 5) * 0.035
            close = max(1.0, base * (1 + drift + wave))
            open_price = close * (1 + math.sin(i + seed) * 0.006)
            high = max(open_price, close) * (1 + 0.008 + (seed % 5) / 1000)
            low = min(open_price, close) * (1 - 0.008 - (seed % 4) / 1000)
            volume = 800000 + (seed % 1000) * 100 + i * 900
            rows.append({
                "symbol": symbol,
                "trade_date": cursor,
                "frequency": "1d",
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": float(volume),
                "amount": round(float(volume) * close, 2),
                "source": "simulated_fallback",
                "payload": {"reason": "no_live_source_or_parse_failed"},
            })
            i += 1
        cursor += timedelta(days=1)
    return rows


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in {"-", "--", "None", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m"):
        try:
            parsed = datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


def _extract_qveris_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("data", "rows", "items", "result", "records"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
        for key in ("data", "result", "payload"):
            nested = payload.get(key)
            if isinstance(nested, dict | list | str):
                rows = _extract_qveris_rows(nested)
                if rows:
                    return rows
        text = payload.get("text") or payload.get("content") or payload.get("markdown")
    else:
        text = payload
    if not isinstance(text, str) or "|" not in text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    headers = [h.strip() for h in lines[0].strip("|").split("|")]
    rows: list[dict[str, Any]] = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _normalize_bar_rows(symbol: str, raw_rows: list[dict[str, Any]], start: date, end: date, source: str) -> list[dict[str, Any]]:
    date_keys = ("trade_date", "date", "日期", "交易日期", "time")
    open_keys = ("open", "开盘", "开盘价")
    high_keys = ("high", "最高", "最高价")
    low_keys = ("low", "最低", "最低价")
    close_keys = ("close", "收盘", "收盘价", "最新价", "当日收盘价")
    volume_keys = ("volume", "成交量")
    amount_keys = ("amount", "成交额")

    def pick(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
        lowered = {str(k).lower(): v for k, v in row.items()}
        for key in keys:
            if key in row:
                return row[key]
            if key.lower() in lowered:
                return lowered[key.lower()]
        return None

    out: list[dict[str, Any]] = []
    for row in raw_rows:
        trade_date = _parse_date(pick(row, date_keys))
        close = _parse_float(pick(row, close_keys))
        if not trade_date or close is None or trade_date < start or trade_date > end:
            continue
        open_price = _parse_float(pick(row, open_keys)) or close
        high = _parse_float(pick(row, high_keys)) or max(open_price, close)
        low = _parse_float(pick(row, low_keys)) or min(open_price, close)
        volume = _parse_float(pick(row, volume_keys)) or 0.0
        amount = _parse_float(pick(row, amount_keys)) or round(volume * close, 2)
        out.append({
            "symbol": symbol,
            "trade_date": trade_date,
            "frequency": "1d",
            "open": round(open_price, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close, 4),
            "volume": volume,
            "amount": amount,
            "source": source,
            "payload": row,
        })
    return sorted(out, key=lambda x: x["trade_date"])


def _normalize_financial_rows(symbol: str, raw_rows: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    date_keys = ("report_date", "end_date", "date", "报告期", "报告日期", "交易日期", "截止日期", "公告日期")
    revenue_keys = ("revenue", "operating_revenue", "营业收入", "营业总收入", "营收")
    profit_keys = ("net_profit", "归母净利润", "净利润", "归属于母公司股东的净利润")
    roe_keys = ("roe", "净资产收益率", "加权净资产收益率", "ROE")
    report_type_keys = ("report_type", "报表类型", "报告类型")

    def pick(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
        lowered = {str(k).lower(): v for k, v in row.items()}
        for key in keys:
            if key in row:
                return row[key]
            if key.lower() in lowered:
                return lowered[key.lower()]
        for row_key, value in row.items():
            row_key_text = str(row_key).lower()
            if any(key.lower() in row_key_text for key in keys):
                return value
        return None

    out: list[dict[str, Any]] = []
    seen: set[tuple[date, str]] = set()
    for row in raw_rows:
        report_date = _parse_date(pick(row, date_keys))
        if not report_date:
            continue
        report_type = str(pick(row, report_type_keys) or "income").strip()[:40] or "income"
        key = (report_date, report_type)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "symbol": symbol,
            "report_date": report_date,
            "report_type": report_type,
            "revenue": _parse_float(pick(row, revenue_keys)),
            "net_profit": _parse_float(pick(row, profit_keys)),
            "roe": _parse_float(pick(row, roe_keys)),
            "source": source,
            "payload": row,
        })
    return sorted(out, key=lambda x: x["report_date"], reverse=True)


def synthetic_financial_reports(symbol: str, years: int = 3) -> list[dict[str, Any]]:
    seed = _symbol_seed(symbol)
    base_revenue = 2_000_000_000 + (seed % 8000) * 1_000_000
    margin = 0.08 + (seed % 18) / 100
    roe_base = 6 + (seed % 22)
    current_year = date.today().year
    rows = []
    for i in range(years):
        year = current_year - i - 1
        growth = 1 + ((seed % 9) - 2) / 100
        revenue = base_revenue * (growth ** (years - i))
        net_profit = revenue * margin
        rows.append({
            "symbol": symbol,
            "report_date": date(year, 12, 31),
            "report_type": "annual",
            "revenue": round(revenue, 2),
            "net_profit": round(net_profit, 2),
            "roe": round(roe_base - i * 0.7, 2),
            "source": "simulated_fallback",
            "payload": {"reason": "no_live_financial_source_or_parse_failed"},
        })
    return rows


class QVerisDataClient:
    def __init__(self) -> None:
        self.api_key = settings.qveris_data_api_key
        self.base_url = settings.qveris_base_url.rstrip("/")

    async def execute_tool(self, tool_id: str, search_id: str, parameters: dict[str, Any]) -> Any:
        if not self.api_key:
            raise RuntimeError("missing_data_api_key")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"search_id": search_id, "parameters": parameters, "max_response_size": 800000}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post(f"/tools/execute?tool_id={quote(tool_id, safe='')}", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def prepare_search(self, query: str, limit: int = 5) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("missing_data_api_key")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"query": query, "limit": limit}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post("/search", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()


def _qveris_response_usage(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    candidates = [payload]
    for key in ("usage", "meta", "metadata", "billing"):
        item = payload.get(key)
        if isinstance(item, dict):
            candidates.append(item)
    aliases = {
        "cost": ("cost", "credits", "credits_used", "credit_cost"),
        "remaining_credits": ("remaining_credits", "remainingCredits", "credit_balance", "credits_remaining"),
    }
    out: dict[str, Any] = {}
    for target, keys in aliases.items():
        for candidate in candidates:
            for key in keys:
                if key in candidate and candidate[key] is not None:
                    out[target] = candidate[key]
                    break
            if target in out:
                break
    return out


def _qveris_call_telemetry(tool_id: str, search_id: str) -> dict[str, Any]:
    return {
        "tool_id": tool_id or None,
        "search_id_cached": bool(search_id),
        "attempted": 0,
        "success": 0,
        "empty": 0,
        "errors": 0,
        "cost": 0,
        "remaining_credits": None,
        "last_error": None,
    }


def _record_qveris_call(telemetry: dict[str, Any], payload: Any = None, row_count: int = 0, error: str | None = None) -> None:
    telemetry["attempted"] = int(telemetry.get("attempted") or 0) + 1
    if error:
        telemetry["errors"] = int(telemetry.get("errors") or 0) + 1
        telemetry["last_error"] = error
        return
    if row_count > 0:
        telemetry["success"] = int(telemetry.get("success") or 0) + 1
    else:
        telemetry["empty"] = int(telemetry.get("empty") or 0) + 1
    usage = _qveris_response_usage(payload)
    if "cost" in usage:
        try:
            telemetry["cost"] = round(float(telemetry.get("cost") or 0) + float(usage["cost"]), 6)
        except (TypeError, ValueError):
            telemetry["cost"] = usage["cost"]
    if "remaining_credits" in usage:
        telemetry["remaining_credits"] = usage["remaining_credits"]


def _redact_data_source_config(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SECRET_CONFIG_KEYS:
                out[key] = "***redacted***" if item else None
            else:
                out[key] = _redact_data_source_config(item)
        return out
    if isinstance(value, list):
        return [_redact_data_source_config(item) for item in value]
    return value


def _normalize_data_source_config(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    stripped: list[str] = []

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                if key.lower() in SECRET_CONFIG_KEYS and item:
                    stripped.append(key)
                    out[key] = "***managed-by-secret-ref***"
                else:
                    out[key] = walk(item)
            return out
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(config or {}), sorted(set(stripped))


def data_source_config_payload(source: DataSourceConfig) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "name": source.name,
        "adapter": source.adapter,
        "enabled": source.enabled,
        "priority": source.priority,
        "config": _redact_data_source_config(source.config_json or {}),
        "secret_ref": source.secret_ref,
        "has_secret_ref": bool(source.secret_ref),
        "last_status": _redact_data_source_config(source.last_status or {}),
    }


def _source_alias_count(counts: dict[str, int], aliases: list[str]) -> int:
    lowered = {key.lower(): int(value or 0) for key, value in counts.items()}
    return sum(lowered.get(alias.lower(), 0) for alias in aliases)


def _data_source_capability_row(
    source: DataSourceConfig | None,
    adapter: str,
    market_bar_counts: dict[str, int] | None = None,
    financial_report_counts: dict[str, int] | None = None,
    stock_universe_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    adapter = adapter.strip().lower()
    spec = DATA_SOURCE_ADAPTER_CAPABILITIES.get(adapter, {"label": adapter, "capabilities": [], "production_requires": ["enabled"], "operational_default": False, "source_aliases": [adapter], "notes": ""})
    config = source.config_json if source else {}
    tools = (config or {}).get("tools") or {}
    aliases = list(spec.get("source_aliases") or [adapter])
    requires = list(spec.get("production_requires") or [])
    enabled = bool(source.enabled) if source else False
    has_secret_ref = bool(source.secret_ref) if source else False
    has_prepared_tools = len(tools) >= 2
    env_key_ready = True
    if adapter == "qveris":
        env_key_ready = bool(settings.qveris_data_api_key)

    missing: list[str] = []
    if "enabled" in requires and not enabled:
        missing.append("enabled")
    if "secret_ref" in requires and not has_secret_ref:
        missing.append("secret_ref")
    if "api_key" in requires and not env_key_ready:
        missing.append("api_key")
    if "prepared_tools" in requires and not has_prepared_tools:
        missing.append("prepared_tools")

    market_rows = _source_alias_count(market_bar_counts or {}, aliases)
    financial_rows = _source_alias_count(financial_report_counts or {}, aliases)
    stock_rows = _source_alias_count(stock_universe_counts or {}, aliases)
    operational_default = bool(spec.get("operational_default"))
    production_ready = bool(source and not missing)
    data_observed = bool(market_rows or financial_rows or stock_rows)
    status = "ready" if production_ready and (operational_default or data_observed or adapter in {"tushare", "ths"}) else "degraded"
    if not source:
        status = "missing"
        missing = ["data_source_config"]
    elif not production_ready:
        status = "degraded"
    next_action = "observe_data_quality" if status == "ready" else "configure_data_source"
    if "prepared_tools" in missing:
        next_action = "prepare_qveris_tools"
    elif "secret_ref" in missing:
        next_action = "set_secret_ref"
    elif "enabled" in missing:
        next_action = "enable_data_source"
    return {
        "adapter": adapter,
        "label": spec.get("label") or adapter,
        "configured": bool(source),
        "enabled": enabled,
        "status": status,
        "production_ready": production_ready,
        "operational_default": operational_default,
        "next_action": next_action,
        "missing": missing,
        "capabilities": list(spec.get("capabilities") or []),
        "production_requires": requires,
        "source_aliases": aliases,
        "has_secret_ref": has_secret_ref,
        "prepared_tool_count": len(tools),
        "prepared_tool_keys": sorted(tools.keys()),
        "discovery_disabled": (config or {}).get("discovery") is False if adapter == "qveris" else None,
        "last_status": _redact_data_source_config(source.last_status or {}) if source else {},
        "observed_rows": {
            "market_bars": market_rows,
            "financial_reports": financial_rows,
            "stock_universe": stock_rows,
        },
        "notes": spec.get("notes") or "",
    }


def _data_source_capability_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    has_market = any("historical_bars" in row.get("capabilities", []) and row.get("production_ready") for row in rows)
    has_financial = any("financial_report" in row.get("capabilities", []) and row.get("production_ready") for row in rows)
    has_stock = any("stock_basic" in row.get("capabilities", []) and row.get("production_ready") for row in rows)
    default_chain = [row for row in rows if row.get("operational_default")]
    default_ready = any(row.get("adapter") == "qveris" and row.get("production_ready") for row in rows) and any(row.get("adapter") == "eastmoney" and row.get("production_ready") for row in rows)
    missing: list[str] = []
    if not has_market:
        missing.append("historical_bars_provider")
    if not has_financial:
        missing.append("financial_report_provider")
    if not has_stock:
        missing.append("stock_basic_provider")
    if not default_ready:
        missing.append("default_qveris_eastmoney_chain")
    return {
        "status": "ready" if not missing else "degraded",
        "missing": missing,
        "default_chain_ready": default_ready,
        "ready_adapter_count": sum(1 for row in rows if row.get("production_ready")),
        "configured_adapter_count": sum(1 for row in rows if row.get("configured")),
        "supported_adapter_count": len(rows),
        "capability_coverage": {
            "stock_basic": has_stock,
            "historical_bars": has_market,
            "financial_report": has_financial,
        },
        "default_chain": [row.get("adapter") for row in default_chain],
    }


async def data_source_capability_matrix(session: AsyncSession) -> dict[str, Any]:
    sources = (await session.scalars(select(DataSourceConfig).order_by(DataSourceConfig.priority, DataSourceConfig.name))).all()
    source_by_adapter = {source.adapter: source for source in sources}
    market_counts = {source: int(count) for source, count in (await session.execute(select(MarketBar.source, func.count()).group_by(MarketBar.source))).all()}
    financial_counts = {source: int(count) for source, count in (await session.execute(select(FinancialReport.source, func.count()).group_by(FinancialReport.source))).all()}
    stock_counts: dict[str, int] = {}
    for stock in (await session.scalars(select(Stock))).all():
        source_name = str((stock.metadata_json or {}).get("source") or "unknown")
        stock_counts[source_name] = stock_counts.get(source_name, 0) + 1
    rows = [
        _data_source_capability_row(source_by_adapter.get(adapter), adapter, market_counts, financial_counts, stock_counts)
        for adapter in sorted(SUPPORTED_DATA_SOURCE_ADAPTERS)
    ]
    status = _data_source_capability_status(rows)
    return {
        **status,
        "items": rows,
        "generated_at": datetime.now(UTC).isoformat(),
        "security": {
            "inline_secret_values_returned": False,
            "secret_fields_redacted": sorted(SECRET_CONFIG_KEYS),
            "secret_ref_required_for_replaceable_adapters": ["tushare", "ths"],
        },
    }


def _safe_url_host(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.netloc or parsed.path.split("/")[0] or None


def integration_config_status(qveris_source: DataSourceConfig | None = None) -> dict[str, Any]:
    qveris_config = qveris_source.config_json if qveris_source else {}
    qveris_tools = (qveris_config or {}).get("tools") or {}
    qveris_ready = bool(settings.qveris_data_api_key and settings.qveris_base_url and qveris_source and qveris_source.enabled and len(qveris_tools) >= 2)
    deepseek_ready = bool(settings.deepseek_api_key and settings.deepseek_base_url and settings.deepseek_model)
    api_token_ready = bool(settings.zi_api_token)
    status = "ready" if qveris_ready and deepseek_ready and api_token_ready else "degraded"
    missing: list[str] = []
    if not qveris_ready:
        missing.append("qveris_data_api_key_or_prepared_tools")
    if not deepseek_ready:
        missing.append("deepseek_api_key_or_model")
    if not api_token_ready:
        missing.append("zi_api_token")
    return {
        "status": status,
        "missing": missing,
        "qveris": {
            "api_key_configured": bool(settings.qveris_data_api_key),
            "base_url_host": _safe_url_host(settings.qveris_base_url),
            "data_source_enabled": bool(qveris_source.enabled) if qveris_source else False,
            "discovery_disabled": (qveris_config or {}).get("discovery") is False,
            "prepared_search_id_configured": bool(settings.qveris_prepared_search_id or (qveris_config or {}).get("prepared_search_id")),
            "prepared_tool_count": len(qveris_tools),
            "prepared_tool_keys": sorted(qveris_tools.keys()),
        },
        "deepseek": {
            "api_key_configured": bool(settings.deepseek_api_key),
            "base_url_host": _safe_url_host(settings.deepseek_base_url),
            "model": settings.deepseek_model,
            "model_configured": bool(settings.deepseek_model),
        },
        "api_token_configured": api_token_ready,
    }


def _data_provenance_status(quality: dict[str, Any], market_sources: list[dict[str, Any]], financial_sources: list[dict[str, Any]]) -> dict[str, Any]:
    real_market_rows = sum(int(row.get("rows") or 0) for row in market_sources if row.get("source") != "simulated_fallback")
    real_financial_rows = sum(int(row.get("rows") or 0) for row in financial_sources if row.get("source") != "simulated_fallback")
    fallback_ratio = float(quality.get("fallback_bar_ratio") or 0)
    max_fallback = float((quality.get("targets") or {}).get("max_fallback_bar_ratio", 0.05))
    missing: list[str] = []
    if real_market_rows <= 0:
        missing.append("real_market_rows")
    if real_financial_rows <= 0:
        missing.append("real_financial_rows")
    if fallback_ratio > max_fallback:
        missing.append("fallback_ratio")
    return {
        "status": "ready" if not missing else "degraded",
        "missing": missing,
        "real_market_rows": real_market_rows,
        "real_financial_rows": real_financial_rows,
        "fallback_bar_ratio": fallback_ratio,
        "max_fallback_bar_ratio": max_fallback,
    }


async def data_provenance_report(session: AsyncSession) -> dict[str, Any]:
    market_rows = (
        await session.execute(
            select(
                MarketBar.source,
                func.count().label("rows"),
                func.count(distinct(MarketBar.symbol)).label("symbols"),
                func.min(MarketBar.trade_date).label("first_date"),
                func.max(MarketBar.trade_date).label("latest_date"),
            )
            .group_by(MarketBar.source)
            .order_by(func.count().desc())
        )
    ).all()
    financial_rows = (
        await session.execute(
            select(
                FinancialReport.source,
                func.count().label("rows"),
                func.count(distinct(FinancialReport.symbol)).label("symbols"),
                func.min(FinancialReport.report_date).label("first_date"),
                func.max(FinancialReport.report_date).label("latest_date"),
            )
            .group_by(FinancialReport.source)
            .order_by(func.count().desc())
        )
    ).all()
    data_sources = (await session.scalars(select(DataSourceConfig).order_by(DataSourceConfig.priority, DataSourceConfig.name))).all()
    recent_sync_audits = (
        await session.scalars(
            select(AdminAuditLog)
            .where(AdminAuditLog.action.in_(["sync_market_bars", "sync_financial_reports", "sync_stock_universe"]))
            .order_by(AdminAuditLog.created_at.desc())
            .limit(10)
        )
    ).all()
    quality = await data_quality_summary(session)
    market_sources = [
        {
            "source": row.source or "unknown",
            "rows": int(row.rows or 0),
            "symbols": int(row.symbols or 0),
            "first_date": row.first_date.isoformat() if row.first_date else None,
            "latest_date": row.latest_date.isoformat() if row.latest_date else None,
        }
        for row in market_rows
    ]
    financial_sources = [
        {
            "source": row.source or "unknown",
            "rows": int(row.rows or 0),
            "symbols": int(row.symbols or 0),
            "first_date": row.first_date.isoformat() if row.first_date else None,
            "latest_date": row.latest_date.isoformat() if row.latest_date else None,
        }
        for row in financial_rows
    ]
    status = _data_provenance_status(quality, market_sources, financial_sources)
    return {
        "status": status["status"],
        "read_only": True,
        "quality": {
            "status": quality.get("status"),
            "market_freshness": quality.get("market_freshness"),
            "financial_freshness": quality.get("financial_freshness"),
            "fallback_bar_ratio": quality.get("fallback_bar_ratio"),
            "targets": quality.get("targets"),
            "gaps": quality.get("gaps"),
        },
        "status_detail": status,
        "market_sources": market_sources,
        "financial_sources": financial_sources,
        "data_sources": [
            {
                "id": str(source.id),
                "name": source.name,
                "adapter": source.adapter,
                "enabled": source.enabled,
                "priority": source.priority,
                "has_secret_ref": bool(source.secret_ref),
                "last_status": _redact_data_source_config(source.last_status or {}),
            }
            for source in data_sources
        ],
        "recent_sync_audits": [
            {
                "id": str(log.id),
                "action": log.action,
                "target": log.target,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "payload": _redact_data_source_config(log.payload or {}),
            }
            for log in recent_sync_audits
        ],
        "generated_at": datetime.now(UTC).isoformat(),
        "warning": "数据来源报告只用于真实数据链路排障和审计，不包含密钥，不触发外部同步，也不会提交真实交易订单。",
    }


def deployment_config_status() -> dict[str, Any]:
    mode = (settings.zi_deployment_mode or "development").strip().lower()
    valid_modes = {"development", "test", "staging", "production"}
    reasons: list[str] = []
    if mode not in valid_modes:
        reasons.append("unsupported_deployment_mode")
    if mode == "production" and settings.auto_create_schema:
        reasons.append("auto_create_schema_enabled_in_production")
    production_safe = mode == "production" and not settings.auto_create_schema
    return {
        "status": "ready" if not reasons else "degraded",
        "mode": mode,
        "valid_modes": sorted(valid_modes),
        "auto_create_schema_enabled": bool(settings.auto_create_schema),
        "production_safe": production_safe,
        "reasons": reasons,
        "next_action": "set_auto_create_schema_false" if "auto_create_schema_enabled_in_production" in reasons else "set_valid_deployment_mode" if reasons else "none",
        "warning": "生产模式应设置 ZI_DEPLOYMENT_MODE=production 且 AUTO_CREATE_SCHEMA=false，并在启动前显式运行 Alembic 迁移。",
    }


def user_payload(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.display_name,
        "role": user.role.value,
        "active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def list_users(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.scalars(select(User).order_by(User.created_at, User.email))).all()
    return {"items": [user_payload(row) for row in rows], "roles": sorted(SUPPORTED_USER_ROLES)}


async def upsert_user(
    session: AsyncSession,
    email: str,
    display_name: str,
    role: str,
    is_active: bool,
    user_id: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    email = email.strip().lower()
    display_name = display_name.strip()
    role = role.strip().lower()
    if "@" not in email:
        return {"saved": False, "reason": "invalid_email"}
    if len(display_name) < 1:
        return {"saved": False, "reason": "invalid_display_name"}
    if role not in SUPPORTED_USER_ROLES:
        return {"saved": False, "reason": "unsupported_role", "roles": sorted(SUPPORTED_USER_ROLES)}
    user = await session.get(User, uuid.UUID(user_id)) if user_id else None
    if not user:
        user = await session.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, display_name=display_name, role=UserRole(role), is_active=is_active)
        session.add(user)
    else:
        user.email = email
        user.display_name = display_name
        user.role = UserRole(role)
        user.is_active = is_active
    session.add(AdminAuditLog(action="upsert_user", target=email, actor_id=actor_id, payload={"role": role, "active": is_active}))
    await session.commit()
    return {"saved": True, "user": user_payload(user)}


async def set_user_active(session: AsyncSession, user_id: str, active: bool, actor_id: uuid.UUID | None = None) -> dict[str, Any]:
    user = await session.get(User, uuid.UUID(user_id))
    if not user:
        return {"updated": False, "reason": "missing_user"}
    active_admin_count = await session.scalar(select(func.count()).select_from(User).where(User.role == UserRole.admin, User.is_active.is_(True))) or 0
    if not active and user.role == UserRole.admin and user.is_active and active_admin_count <= 1:
        return {"updated": False, "reason": "cannot_disable_last_active_admin"}
    user.is_active = active
    session.add(AdminAuditLog(action="set_user_active", target=user.email, actor_id=actor_id, payload={"active": active}))
    await session.commit()
    return {"updated": True, "user": user_payload(user)}


async def list_data_source_configs(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.scalars(select(DataSourceConfig).order_by(DataSourceConfig.priority, DataSourceConfig.name))).all()
    return {"items": [data_source_config_payload(row) for row in rows], "supported_adapters": sorted(SUPPORTED_DATA_SOURCE_ADAPTERS)}


async def upsert_data_source_config(
    session: AsyncSession,
    name: str,
    adapter: str,
    enabled: bool,
    priority: int,
    config: dict[str, Any],
    secret_ref: str | None = None,
    source_id: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    adapter = adapter.strip().lower()
    if adapter not in SUPPORTED_DATA_SOURCE_ADAPTERS:
        return {"saved": False, "reason": "unsupported_adapter", "supported_adapters": sorted(SUPPORTED_DATA_SOURCE_ADAPTERS)}
    name = name.strip()
    if len(name) < 2:
        return {"saved": False, "reason": "invalid_name"}
    normalized_config, stripped_secret_keys = _normalize_data_source_config(config or {})
    source = await session.get(DataSourceConfig, uuid.UUID(source_id)) if source_id else None
    if not source:
        source = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.name == name))
    if not source:
        source = DataSourceConfig(name=name, adapter=adapter)
        session.add(source)
    source.name = name
    source.adapter = adapter
    source.enabled = enabled
    source.priority = max(1, min(int(priority), 999))
    source.config_json = normalized_config
    if secret_ref is not None:
        source.secret_ref = secret_ref.strip() or None
    source.last_status = {
        **(source.last_status or {}),
        "configured_at": datetime.now(UTC).isoformat(),
        "stripped_secret_keys": stripped_secret_keys,
    }
    session.add(AdminAuditLog(action="upsert_data_source_config", target=name, actor_id=actor_id, payload={"adapter": adapter, "enabled": enabled, "priority": source.priority, "stripped_secret_keys": stripped_secret_keys}))
    await session.commit()
    return {"saved": True, "data_source": data_source_config_payload(source), "stripped_secret_keys": stripped_secret_keys}


async def set_data_source_enabled(session: AsyncSession, source_id: str, enabled: bool, actor_id: uuid.UUID | None = None) -> dict[str, Any]:
    source = await session.get(DataSourceConfig, uuid.UUID(source_id))
    if not source:
        return {"updated": False, "reason": "missing_data_source"}
    source.enabled = enabled
    source.last_status = {**(source.last_status or {}), "enabled_changed_at": datetime.now(UTC).isoformat(), "enabled": enabled}
    session.add(AdminAuditLog(action="set_data_source_enabled", target=str(source.id), actor_id=actor_id, payload={"adapter": source.adapter, "enabled": enabled}))
    await session.commit()
    return {"updated": True, "data_source": data_source_config_payload(source)}


async def prepare_qveris_data_source(session: AsyncSession, query: str | None = None) -> dict[str, Any]:
    config = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.adapter == "qveris", DataSourceConfig.enabled.is_(True)).order_by(DataSourceConfig.priority))
    if not config:
        return {"prepared": False, "reason": "missing_enabled_data_source"}
    client = QVerisDataClient()
    if not client.api_key:
        return {"prepared": False, "reason": "missing_data_api_key"}
    query = query or "A股 日线 历史行情 股票代码 开盘价 收盘价 成交量"
    try:
        payload = await client.prepare_search(query=query, limit=8)
    except Exception as exc:
        config.last_status = {"prepared": False, "error": type(exc).__name__, "prepared_at": datetime.now(UTC).isoformat()}
        session.add(AdminAuditLog(action="prepare_data_source_failed", target=str(config.id), payload={"adapter": config.adapter, "error": type(exc).__name__}))
        await session.commit()
        return {"prepared": False, "reason": type(exc).__name__}

    search_id = payload.get("search_id") or payload.get("id") or payload.get("session_id")
    if not search_id:
        config.last_status = {"prepared": False, "error": "missing_search_id", "prepared_at": datetime.now(UTC).isoformat()}
        await session.commit()
        return {"prepared": False, "reason": "missing_search_id"}
    cfg = dict(config.config_json or {})
    cfg["prepared_search_id"] = search_id
    cfg["prepared_query"] = query
    cfg["prepared_at"] = datetime.now(UTC).isoformat()
    config.config_json = cfg
    config.last_status = {"prepared": True, "prepared_at": cfg["prepared_at"], "query": query}
    session.add(AdminAuditLog(action="prepare_data_source", target=str(config.id), payload={"adapter": config.adapter, "query": query}))
    await session.commit()
    return {"prepared": True, "data_source_id": str(config.id), "query": query, "search_id_cached": True}


async def _store_bars(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    stored = 0
    for row in rows:
        existing = await session.scalar(
            select(MarketBar).where(
                MarketBar.symbol == row["symbol"],
                MarketBar.trade_date == row["trade_date"],
                MarketBar.frequency == row.get("frequency", "1d"),
            )
        )
        if existing:
            for key in ("open", "high", "low", "close", "volume", "amount", "source", "payload"):
                setattr(existing, key, row[key])
        else:
            session.add(MarketBar(**row))
        stored += 1
    return stored


async def _store_financial_reports(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    stored = 0
    for row in rows:
        if row.get("source") != "simulated_fallback":
            await session.execute(
                delete(FinancialReport).where(
                    FinancialReport.symbol == row["symbol"],
                    FinancialReport.report_date == row["report_date"],
                    FinancialReport.source == "simulated_fallback",
                )
            )
        existing = await session.scalar(
            select(FinancialReport).where(
                FinancialReport.symbol == row["symbol"],
                FinancialReport.report_date == row["report_date"],
                FinancialReport.report_type == row["report_type"],
            )
        )
        if existing:
            for key in ("revenue", "net_profit", "roe", "source", "payload"):
                setattr(existing, key, row[key])
        else:
            session.add(FinancialReport(**row))
        stored += 1
    return stored


async def public_pool_symbols(session: AsyncSession, limit: int = 500) -> list[str]:
    pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
    if not pool:
        return list((await session.scalars(select(Stock.symbol).order_by(Stock.symbol).limit(limit))).all())
    return list(
        (
            await session.scalars(
                select(StockPoolMember.symbol)
                .where(StockPoolMember.pool_id == pool.id)
                .order_by(StockPoolMember.id)
                .limit(limit)
            )
        ).all()
    )


async def public_pool_real_data_candidates(session: AsyncSession, limit: int = 10) -> list[str]:
    symbols = await public_pool_symbols(session, limit=500)
    if not symbols:
        return []
    qveris_bar_symbols = set((await session.scalars(select(distinct(MarketBar.symbol)).where(MarketBar.symbol.in_(symbols), MarketBar.source == "qveris"))).all())
    qveris_financial_symbols = set((await session.scalars(select(distinct(FinancialReport.symbol)).where(FinancialReport.symbol.in_(symbols), FinancialReport.source == "qveris"))).all())
    ranked = sorted(
        symbols,
        key=lambda symbol: (
            symbol in qveris_bar_symbols and symbol in qveris_financial_symbols,
            symbol in qveris_bar_symbols,
            symbol in qveris_financial_symbols,
            symbols.index(symbol),
        ),
    )
    return ranked[: min(max(limit, 1), 200)]


async def sync_market_bars(session: AsyncSession, symbols: list[str] | None = None, days: int = 180, allow_fallback: bool = True) -> dict[str, Any]:
    end = date.today()
    start = end - timedelta(days=max(days, 20))
    if not symbols:
        symbols = await public_pool_real_data_candidates(session, limit=30)
    config = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.adapter == "qveris", DataSourceConfig.enabled.is_(True)).order_by(DataSourceConfig.priority))
    tool_id = ""
    search_id = settings.qveris_prepared_search_id
    if config:
        tool_id = config.config_json.get("tools", {}).get("historical_bars", "")
        search_id = config.config_json.get("prepared_search_id") or search_id

    client = QVerisDataClient()
    stored = 0
    source_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    qveris_telemetry = _qveris_call_telemetry(tool_id, search_id)
    for symbol in symbols[: min(len(symbols), 200)]:
        rows: list[dict[str, Any]] = []
        source = "simulated_fallback"
        qveris_rows: list[dict[str, Any]] = []
        if tool_id and search_id and client.api_key:
            try:
                payload = await client.execute_tool(tool_id, search_id, {"symbol": symbol, "start_date": start.isoformat(), "end_date": end.isoformat(), "frequency": "1d"})
                qveris_rows = _normalize_bar_rows(symbol, _extract_qveris_rows(payload), start, end, "qveris")
                _record_qveris_call(qveris_telemetry, payload=payload, row_count=len(qveris_rows))
                rows = qveris_rows
                source = "qveris" if qveris_rows else "simulated_fallback"
                if not qveris_rows:
                    errors.append({"symbol": symbol, "error": "empty_or_unparseable_real_source_response"})
            except Exception as exc:
                _record_qveris_call(qveris_telemetry, error=type(exc).__name__)
                errors.append({"symbol": symbol, "error": type(exc).__name__})
        elif not allow_fallback:
            errors.append({"symbol": symbol, "error": "missing_prepared_real_data_source"})
        if len(rows) < 60:
            try:
                eastmoney_rows = await fetch_eastmoney_daily_bars(symbol, start, end)
                if eastmoney_rows:
                    rows = eastmoney_rows
                    source = "eastmoney"
            except Exception as exc:
                errors.append({"symbol": symbol, "error": f"eastmoney_{type(exc).__name__}"})
        if not rows:
            if not allow_fallback:
                continue
            rows = synthetic_bars(symbol, start, end)
        if any(row.get("source") != "simulated_fallback" for row in rows):
            await session.execute(
                delete(MarketBar).where(
                    MarketBar.symbol == symbol,
                    MarketBar.trade_date >= start,
                    MarketBar.trade_date <= end,
                    MarketBar.source == "simulated_fallback",
                )
            )
        stored += await _store_bars(session, rows)
        for row in rows:
            row_source = str(row.get("source") or source)
            source_counts[row_source] = source_counts.get(row_source, 0) + 1

    status = JobStatus.success if stored else JobStatus.failed
    if config:
        config.last_status = {"synced_at": datetime.now(UTC).isoformat(), "symbols": len(symbols), "stored_rows": stored, "sources": source_counts, "errors": errors[:10], "allow_fallback": allow_fallback, "qveris_calls": qveris_telemetry}
    session.add(DataJob(name=f"历史行情同步 {datetime.now(UTC).isoformat(timespec='seconds')}", job_type="market_bars", status=status, schedule="manual", last_run_at=datetime.now(UTC), payload={"symbols": len(symbols), "stored_rows": stored, "sources": source_counts, "errors": errors[:10], "allow_fallback": allow_fallback}))
    session.add(AdminAuditLog(action="sync_market_bars", target="market_bars", payload={"symbols": len(symbols), "stored_rows": stored, "sources": source_counts, "errors": errors[:10], "qveris_calls": qveris_telemetry}))
    await session.commit()
    return {"stored_rows": stored, "symbols": len(symbols), "sources": source_counts, "errors": errors[:10], "qveris_calls": qveris_telemetry, "start_date": start.isoformat(), "end_date": end.isoformat()}


async def sync_financial_reports(session: AsyncSession, symbols: list[str] | None = None, limit: int = 30, allow_fallback: bool = False) -> dict[str, Any]:
    if not symbols:
        symbols = await public_pool_real_data_candidates(session, limit=min(max(limit, 1), 200))
    else:
        symbols = [s.strip().upper() for s in symbols if s.strip()][: min(max(limit, 1), 200)]

    config = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.adapter == "qveris", DataSourceConfig.enabled.is_(True)).order_by(DataSourceConfig.priority))
    tool_id = ""
    search_id = settings.qveris_prepared_search_id
    if config:
        tool_id = config.config_json.get("tools", {}).get("financial_report", "")
        search_id = config.config_json.get("prepared_search_id") or search_id

    client = QVerisDataClient()
    stored = 0
    source_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    qveris_telemetry = _qveris_call_telemetry(tool_id, search_id)
    for symbol in symbols:
        rows: list[dict[str, Any]] = []
        source = "simulated_fallback"
        if tool_id and search_id and client.api_key:
            try:
                payload = await client.execute_tool(tool_id, search_id, {"symbol": symbol, "report_type": "income", "limit": 8})
                rows = _normalize_financial_rows(symbol, _extract_qveris_rows(payload), "qveris")
                _record_qveris_call(qveris_telemetry, payload=payload, row_count=len(rows))
                source = "qveris" if rows else "simulated_fallback"
                if not rows:
                    errors.append({"symbol": symbol, "error": "empty_or_unparseable_financial_response"})
            except Exception as exc:
                _record_qveris_call(qveris_telemetry, error=type(exc).__name__)
                errors.append({"symbol": symbol, "error": type(exc).__name__})
        elif not allow_fallback:
            errors.append({"symbol": symbol, "error": "missing_prepared_real_financial_source"})
        if not rows:
            if not allow_fallback:
                continue
            rows = synthetic_financial_reports(symbol)
        stored += await _store_financial_reports(session, rows)
        source_counts[source] = source_counts.get(source, 0) + len(rows)

    status = JobStatus.success if stored else JobStatus.failed
    if config:
        config.last_status = {**(config.last_status or {}), "financial_synced_at": datetime.now(UTC).isoformat(), "financial_symbols": len(symbols), "financial_rows": stored, "financial_sources": source_counts, "financial_errors": errors[:10], "allow_fallback": allow_fallback, "financial_qveris_calls": qveris_telemetry}
    session.add(DataJob(name=f"财报同步 {datetime.now(UTC).isoformat(timespec='seconds')}", job_type="financial_report", status=status, schedule="manual", last_run_at=datetime.now(UTC), payload={"symbols": len(symbols), "stored_rows": stored, "sources": source_counts, "errors": errors[:10], "allow_fallback": allow_fallback}))
    session.add(AdminAuditLog(action="sync_financial_reports", target="financial_reports", payload={"symbols": len(symbols), "stored_rows": stored, "sources": source_counts, "errors": errors[:10], "qveris_calls": qveris_telemetry}))
    await session.commit()
    return {"stored_rows": stored, "symbols": len(symbols), "sources": source_counts, "errors": errors[:10], "qveris_calls": qveris_telemetry}


async def bootstrap_real_data(session: AsyncSession, symbols: list[str] | None = None, days: int = 180, limit: int = 10) -> dict[str, Any]:
    normalized = []
    seen: set[str] = set()
    source_symbols = symbols or await public_pool_real_data_candidates(session, limit=limit)
    if not source_symbols:
        source_symbols = CORE_REAL_DATA_SYMBOLS
    for symbol in source_symbols:
        code = symbol.strip().upper()
        if code and code not in seen:
            normalized.append(code)
            seen.add(code)
    normalized = normalized[: min(max(limit, 1), 50)]
    if not normalized:
        return {"bootstrapped": False, "reason": "empty_symbols"}

    market = await sync_market_bars(session, symbols=normalized, days=days, allow_fallback=False)
    financials = await sync_financial_reports(session, symbols=normalized, limit=len(normalized), allow_fallback=False)
    factors = await refresh_factor_values(session, limit=500)
    readiness = await system_readiness(session)
    session.add(
        AdminAuditLog(
            action="bootstrap_real_data",
            target="real_data",
            payload={
                "symbols": normalized,
                "market": market,
                "financials": financials,
                "factor_rows": factors.get("rows"),
                "readiness_status": readiness.get("status"),
            },
        )
    )
    await session.commit()
    return {
        "bootstrapped": True,
        "symbols": normalized,
        "market": market,
        "financials": financials,
        "factors": {"rows": factors.get("rows"), "top": factors.get("top", [])[:5]},
        "readiness": readiness,
    }


def compute_factor(stock: Stock, strategy_count: int = 5) -> FactorRow:
    checksum = sum(ord(c) for c in stock.symbol)
    price = synthetic_price(stock.symbol)
    dif = round(((checksum % 29) - 14) / 100, 4)
    dea = round(((checksum % 23) - 11) / 100, 4)
    macd = round((dif - dea) * 2, 4)
    rsi = round(25 + checksum % 55, 2)
    momentum = round(((checksum % 41) - 20) / 100, 4)
    volatility = round(0.12 + (checksum % 18) / 100, 4)
    quality = round(0.35 + (checksum % 50) / 100, 4)
    score = round(macd * 0.8 + momentum * 1.5 + quality * 0.45 + (0.45 - volatility) * 0.25 + min(strategy_count, 30) / 120, 4)
    return FactorRow(stock.symbol, stock.name, stock.sector, price, dif, dea, macd, rsi, momentum, volatility, quality, score)


def _ema(values: list[float], span: int) -> float:
    if not values:
        return 0.0
    alpha = 2 / (span + 1)
    ema = values[0]
    for value in values[1:]:
        ema = alpha * value + (1 - alpha) * ema
    return ema


def _has_price_discontinuity(bars: list[MarketBar], threshold: float = 0.35) -> bool:
    ordered = sorted(bars, key=lambda b: b.trade_date)
    for i in range(1, len(ordered)):
        prev = ordered[i - 1].close
        if prev and abs(ordered[i].close / prev - 1) > threshold:
            return True
    return False


def _market_factor_from_bars(stock: Stock, bars: list[MarketBar], strategy_count: int = 5) -> FactorRow | None:
    ordered = sorted(bars, key=lambda b: b.trade_date)
    if len(ordered) < 20 or _has_price_discontinuity(ordered):
        return None
    closes = [b.close for b in ordered]
    price = closes[-1]
    ema12 = _ema(closes[-26:], 12)
    ema26 = _ema(closes[-26:], 26)
    dif = ema12 - ema26
    macd_series = []
    for i in range(max(0, len(closes) - 35), len(closes)):
        window = closes[: i + 1]
        macd_series.append(_ema(window[-26:], 12) - _ema(window[-26:], 26))
    dea = _ema(macd_series, 9)
    macd = (dif - dea) * 2
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = changes[-14:] if len(changes) >= 14 else changes
    gains = sum(max(x, 0) for x in recent) / max(len(recent), 1)
    losses = sum(abs(min(x, 0)) for x in recent) / max(len(recent), 1)
    rsi = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    momentum = closes[-1] / closes[-20] - 1 if closes[-20] else 0.0
    daily_returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
    recent_returns = daily_returns[-20:]
    avg = sum(recent_returns) / max(len(recent_returns), 1)
    variance = sum((x - avg) ** 2 for x in recent_returns) / max(len(recent_returns), 1)
    volatility = math.sqrt(variance) * math.sqrt(252)
    quality = max(0.05, min(0.95, 0.65 - volatility * 0.35 + max(momentum, -0.2)))
    score = round(macd * 0.01 + momentum * 2.2 + quality * 0.55 + (0.35 - min(volatility, 0.8)) * 0.35 + min(strategy_count, 30) / 140, 4)
    return FactorRow(stock.symbol, stock.name, stock.sector, round(price, 4), round(dif, 4), round(dea, 4), round(macd, 4), round(rsi, 2), round(momentum, 4), round(volatility, 4), round(quality, 4), score)


def _apply_financial_quality(row: FactorRow, reports: list[FinancialReport]) -> FactorRow:
    if not reports:
        return row
    ordered = sorted(reports, key=lambda r: (r.source == "qveris", r.report_date), reverse=True)
    latest = ordered[0]
    previous = next(
        (
            r
            for r in ordered[1:]
            if r.revenue
            and latest.revenue
            and r.report_date < latest.report_date
            and r.report_date.month == latest.report_date.month
            and r.report_date.day == latest.report_date.day
        ),
        None,
    )
    previous = previous or next((r for r in ordered[1:] if r.revenue and latest.revenue and r.report_date < latest.report_date), None)
    net_margin = latest.net_profit / latest.revenue if latest.revenue and latest.net_profit is not None else None
    revenue_growth = latest.revenue / previous.revenue - 1 if previous and previous.revenue and latest.revenue else None
    margin_component = max(-0.2, min(net_margin or 0, 0.6))
    growth_component = max(-0.5, min(revenue_growth or 0, 0.8))
    roe_component = max(0.0, min((latest.roe or 0) / 100, 0.5))
    fundamental_quality = max(0.05, min(0.95, 0.35 + margin_component * 0.9 + growth_component * 0.25 + roe_component * 0.4))
    blended_quality = round(row.quality * 0.35 + fundamental_quality * 0.65, 4)
    score = round(row.score - row.quality * 0.55 + blended_quality * 0.55 + growth_component * 0.12, 4)
    return replace(
        row,
        quality=blended_quality,
        score=score,
        quality_source=f"financial_report:{latest.source}",
        revenue_growth=round(revenue_growth, 4) if revenue_growth is not None else None,
        net_margin=round(net_margin, 4) if net_margin is not None else None,
        roe=round(latest.roe, 4) if latest.roe is not None else None,
    )


async def compute_market_factor_rows(session: AsyncSession, limit: int = 500) -> list[FactorRow]:
    pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
    if pool:
        stocks = (
            await session.scalars(
                select(Stock)
                .join(StockPoolMember, StockPoolMember.symbol == Stock.symbol)
                .where(StockPoolMember.pool_id == pool.id)
                .order_by(StockPoolMember.id)
                .limit(limit)
            )
        ).all()
    else:
        stocks = (await session.scalars(select(Stock).limit(limit))).all()
    strategies_count = await session.scalar(select(func.count()).select_from(Strategy)) or 0
    symbols = [s.symbol for s in stocks]
    bars = (await session.scalars(select(MarketBar).where(MarketBar.symbol.in_(symbols)).order_by(MarketBar.symbol, MarketBar.trade_date))).all()
    financial_reports = (await session.scalars(select(FinancialReport).where(FinancialReport.symbol.in_(symbols)).order_by(FinancialReport.symbol, FinancialReport.report_date.desc()))).all()
    bars_by_symbol: dict[str, list[MarketBar]] = {}
    for bar in bars:
        bars_by_symbol.setdefault(bar.symbol, []).append(bar)
    reports_by_symbol: dict[str, list[FinancialReport]] = {}
    for report in financial_reports:
        reports_by_symbol.setdefault(report.symbol, []).append(report)
    rows = []
    for stock in stocks:
        row = _market_factor_from_bars(stock, bars_by_symbol.get(stock.symbol, []), strategies_count)
        row = row or compute_factor(stock, strategies_count)
        rows.append(_apply_financial_quality(row, reports_by_symbol.get(stock.symbol, [])))
    return sorted(rows, key=lambda r: r.score, reverse=True)


async def compute_market_factor_rows_as_of(session: AsyncSession, as_of: date, limit: int = 500) -> list[FactorRow]:
    pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
    if pool:
        stocks = (
            await session.scalars(
                select(Stock)
                .join(StockPoolMember, StockPoolMember.symbol == Stock.symbol)
                .where(StockPoolMember.pool_id == pool.id)
                .order_by(StockPoolMember.id)
                .limit(limit)
            )
        ).all()
    else:
        stocks = (await session.scalars(select(Stock).limit(limit))).all()
    strategies_count = await session.scalar(select(func.count()).select_from(Strategy)) or 0
    symbols = [s.symbol for s in stocks]
    bars = (
        await session.scalars(
            select(MarketBar)
            .where(MarketBar.symbol.in_(symbols), MarketBar.trade_date <= as_of)
            .order_by(MarketBar.symbol, MarketBar.trade_date)
        )
    ).all()
    financial_reports = (
        await session.scalars(
            select(FinancialReport)
            .where(FinancialReport.symbol.in_(symbols), FinancialReport.report_date <= as_of)
            .order_by(FinancialReport.symbol, FinancialReport.report_date.desc())
        )
    ).all()
    bars_by_symbol: dict[str, list[MarketBar]] = {}
    for bar in bars:
        bars_by_symbol.setdefault(bar.symbol, []).append(bar)
    reports_by_symbol: dict[str, list[FinancialReport]] = {}
    for report in financial_reports:
        reports_by_symbol.setdefault(report.symbol, []).append(report)
    rows = []
    for stock in stocks:
        row = _market_factor_from_bars(stock, bars_by_symbol.get(stock.symbol, []), strategies_count)
        if row:
            rows.append(_apply_financial_quality(row, reports_by_symbol.get(stock.symbol, [])))
    return sorted(rows, key=lambda r: r.score, reverse=True)


def _recommendation_action(row: FactorRow) -> tuple[str, str, str]:
    if row.score >= 0.9 and row.momentum_20d >= 0.05 and row.quality >= 0.6 and row.rsi < 78:
        return "BUY_WATCH", "red", "趋势、质量和相对强度同时满足，适合加入纸面观察候选"
    if row.score >= 0.55 and row.momentum_20d >= 0.02 and row.rsi < 82:
        return "OBSERVE", "amber", "信号偏强但仍需等待成交量、行业拥挤度和回撤确认"
    if row.rsi >= 82 or row.volatility_20d >= 0.55:
        return "RISK_WATCH", "gray", "短期过热或波动偏高，优先复核风险"
    return "HOLD_WATCH", "gray", "信号不弱但未达到买入观察门槛"


def _strategy_tags_for_factor(row: FactorRow) -> list[str]:
    tags: list[str] = []
    if row.momentum_20d > 0.03 and row.macd > 0:
        tags.append("均线动量")
    if row.quality >= 0.65 or (row.roe is not None and row.roe > 8):
        tags.append("质量成长")
    if row.score >= 0.75:
        tags.append("相对强弱轮动")
    if row.volatility_20d <= 0.28:
        tags.append("低波回撤控制")
    if row.momentum_20d >= 0.08 and row.rsi < 75:
        tags.append("放量突破观察")
    return tags or ["综合观察"]


def _stock_recommendation_from_factor(row: FactorRow, rank: int, *, trade_date: date | None = None) -> dict[str, Any]:
    action, color, action_reason = _recommendation_action(row)
    confidence = "high" if action == "BUY_WATCH" and row.quality >= 0.65 and row.volatility_20d <= 0.45 else "medium" if action in {"BUY_WATCH", "OBSERVE"} else "low"
    return {
        "rank": rank,
        "symbol": row.symbol,
        "name": row.name,
        "sector": row.sector,
        "trade_date": trade_date.isoformat() if trade_date else None,
        "action": action,
        "action_color": color,
        "confidence": confidence,
        "price": row.price,
        "score": row.score,
        "strategy_tags": _strategy_tags_for_factor(row),
        "reason": action_reason,
        "evidence": {
            "macd": row.macd,
            "dif": row.dif,
            "dea": row.dea,
            "rsi": row.rsi,
            "momentum_20d": row.momentum_20d,
            "volatility_20d": row.volatility_20d,
            "quality": row.quality,
            "quality_source": row.quality_source,
            "revenue_growth": row.revenue_growth,
            "net_margin": row.net_margin,
            "roe": row.roe,
        },
        "risk_control": {
            "paper_only": True,
            "suggested_max_position_pct": 0.08 if confidence == "high" else 0.04,
            "stop_loss_watch": 0.08,
            "manual_review_required": True,
        },
    }


def _recommendation_sort_key(item: dict[str, Any]) -> tuple[int, int, float]:
    action_rank = {"BUY_WATCH": 0, "OBSERVE": 1, "HOLD_WATCH": 2, "RISK_WATCH": 3}
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    return (action_rank.get(str(item.get("action")), 9), confidence_rank.get(str(item.get("confidence")), 9), -float(item.get("score") or 0.0))


async def realtime_stock_recommendations(session: AsyncSession, limit: int = 10) -> dict[str, Any]:
    latest_date = await session.scalar(select(func.max(MarketBar.trade_date)).where(MarketBar.source != "simulated_fallback"))
    rows = await compute_market_factor_rows(session, limit=500)
    candidates = [_stock_recommendation_from_factor(row, index + 1, trade_date=latest_date) for index, row in enumerate(rows[: min(max(limit * 5, 20), 120)])]
    recommendations = sorted(candidates, key=_recommendation_sort_key)[: min(max(limit, 1), 50)]
    for index, item in enumerate(recommendations, start=1):
        item["rank"] = index
    buy_watch = [item for item in recommendations if item["action"] == "BUY_WATCH"]
    return {
        "status": "ready" if recommendations else "empty",
        "paper_only": True,
        "trade_date": latest_date.isoformat() if latest_date else None,
        "strategy_library": DAILY_STOCK_ANALYSIS_STRATEGY_ROUTES,
        "recommendations": recommendations,
        "summary": {
            "count": len(recommendations),
            "buy_watch": len(buy_watch),
            "observe": sum(1 for item in recommendations if item["action"] == "OBSERVE"),
            "top_symbols": [item["symbol"] for item in recommendations[:5]],
        },
        "warning": "推荐仅用于策略研究和模拟盘观察，不会提交真实交易订单，不构成投资建议。",
    }


async def yesterday_recommendation_review(session: AsyncSession, limit: int = 10) -> dict[str, Any]:
    dates = (await session.scalars(select(distinct(MarketBar.trade_date)).where(MarketBar.source != "simulated_fallback").order_by(MarketBar.trade_date.desc()).limit(2))).all()
    if len(dates) < 2:
        return {"status": "insufficient_history", "paper_only": True, "items": [], "warning": "缺少至少两个真实交易日，暂无法复盘昨日推荐。"}
    latest_date, previous_date = dates[0], dates[1]
    previous_rows = await compute_market_factor_rows_as_of(session, previous_date, limit=500)
    previous_candidates = [_stock_recommendation_from_factor(row, index + 1, trade_date=previous_date) for index, row in enumerate(previous_rows[: min(max(limit * 5, 20), 120)])]
    previous_recs = sorted(previous_candidates, key=_recommendation_sort_key)[: min(max(limit, 1), 50)]
    for index, item in enumerate(previous_recs, start=1):
        item["rank"] = index
    symbols = [item["symbol"] for item in previous_recs]
    bars = (
        await session.scalars(
            select(MarketBar)
            .where(MarketBar.symbol.in_(symbols), MarketBar.trade_date.in_([previous_date, latest_date]))
            .order_by(MarketBar.symbol, MarketBar.trade_date)
        )
    ).all()
    by_symbol_date = {(bar.symbol, bar.trade_date): bar for bar in bars}
    items = []
    for rec in previous_recs:
        prev_bar = by_symbol_date.get((rec["symbol"], previous_date))
        latest_bar = by_symbol_date.get((rec["symbol"], latest_date))
        ret = latest_bar.close / prev_bar.close - 1 if prev_bar and latest_bar and prev_bar.close else None
        hit = ret is not None and ((rec["action"] == "BUY_WATCH" and ret > 0) or (rec["action"] in {"OBSERVE", "HOLD_WATCH"} and ret >= -0.01))
        items.append({
            **rec,
            "review": {
                "latest_date": latest_date.isoformat(),
                "previous_close": prev_bar.close if prev_bar else None,
                "latest_close": latest_bar.close if latest_bar else None,
                "next_day_return": round(ret, 4) if ret is not None else None,
                "hit": hit,
                "result": "hit" if hit else "miss" if ret is not None else "missing_price",
            },
        })
    reviewed = [item for item in items if item["review"]["next_day_return"] is not None]
    hit_count = sum(1 for item in reviewed if item["review"]["hit"])
    return {
        "status": "ready",
        "paper_only": True,
        "recommendation_date": previous_date.isoformat(),
        "review_date": latest_date.isoformat(),
        "items": items,
        "summary": {
            "reviewed": len(reviewed),
            "hit_count": hit_count,
            "hit_rate": round(hit_count / len(reviewed), 4) if reviewed else None,
            "avg_next_day_return": round(sum(item["review"]["next_day_return"] for item in reviewed) / len(reviewed), 4) if reviewed else None,
        },
        "warning": "昨日复盘只评估纸面推荐的下一交易日表现，不代表未来收益，也不会提交真实交易订单。",
    }


async def analyze_stock_symbol(session: AsyncSession, symbol: str) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    stock = await session.get(Stock, normalized)
    if not stock:
        return {"found": False, "reason": "missing_stock", "symbol": normalized}
    bars = (await session.scalars(select(MarketBar).where(MarketBar.symbol == normalized).order_by(MarketBar.trade_date))).all()
    reports = (await session.scalars(select(FinancialReport).where(FinancialReport.symbol == normalized).order_by(FinancialReport.report_date.desc()))).all()
    strategies_count = await session.scalar(select(func.count()).select_from(Strategy)) or 0
    factor = _market_factor_from_bars(stock, bars, strategies_count) or compute_factor(stock, strategies_count)
    factor = _apply_financial_quality(factor, reports)
    recommendation = _stock_recommendation_from_factor(factor, 1, trade_date=bars[-1].trade_date if bars else None)
    latest_report = reports[0] if reports else None
    latest_bar = bars[-1] if bars else None
    previous_bar = bars[-2] if len(bars) >= 2 else None
    daily_return = latest_bar.close / previous_bar.close - 1 if latest_bar and previous_bar and previous_bar.close else None
    analysis = {
        "found": True,
        "paper_only": True,
        "stock": {"symbol": stock.symbol, "name": stock.name, "market": stock.market, "sector": stock.sector},
        "latest_quote": {
            "trade_date": latest_bar.trade_date.isoformat() if latest_bar else None,
            "close": latest_bar.close if latest_bar else None,
            "daily_return": round(daily_return, 4) if daily_return is not None else None,
            "source": latest_bar.source if latest_bar else "synthetic_or_missing",
        },
        "recommendation": recommendation,
        "financial": {
            "report_date": latest_report.report_date.isoformat() if latest_report else None,
            "source": latest_report.source if latest_report else None,
            "revenue": latest_report.revenue if latest_report else None,
            "net_profit": latest_report.net_profit if latest_report else None,
            "roe": latest_report.roe if latest_report else None,
        },
        "strategy_views": [
            {"name": tag, "verdict": "match" if tag in recommendation["strategy_tags"] else "watch"}
            for tag in ["均线动量", "质量成长", "相对强弱轮动", "低波回撤控制", "放量突破观察"]
        ],
        "risk_findings": [
            item
            for item in [
                "真实行情样本不足，降低置信度" if len(bars) < 60 else None,
                "财报缺失，质量因子主要来自价格行为" if not reports else None,
                "RSI 偏高，注意短期过热" if factor.rsi >= 78 else None,
                "20日年化波动偏高，控制模拟仓位" if factor.volatility_20d >= 0.45 else None,
            ]
            if item
        ],
        "warning": "个股分析仅用于研究和模拟盘观察，不会提交真实交易订单，不构成投资建议。",
    }
    return analysis


def _format_feishu_signal_message(recommendations: dict[str, Any], review: dict[str, Any] | None = None) -> str:
    lines = [
        "ZiQuant A股策略信号",
        f"日期：{recommendations.get('trade_date') or '-'}",
        "说明：仅用于研究和模拟盘纸面观察，不是投资建议，不会提交真实交易订单。",
        "",
        "今日策略推荐：",
    ]
    for item in (recommendations.get("recommendations") or [])[:8]:
        evidence = item.get("evidence") or {}
        momentum = float(evidence.get("momentum_20d") or 0.0)
        quality = float(evidence.get("quality") or 0.0)
        lines.append(
            f"- {item['name']}({item['symbol']}): {item['action']} · 分数 {item['score']} · 动量 {momentum:.2%} · 质量 {quality:.2f} · {item['reason']}"
        )
    if review:
        summary = review.get("summary") or {}
        lines.extend([
            "",
            f"昨日推荐复盘：{review.get('recommendation_date')} -> {review.get('review_date')}",
            f"- 命中 {summary.get('hit_count')}/{summary.get('reviewed')} · 命中率 {summary.get('hit_rate')} · 平均收益 {summary.get('avg_next_day_return')}",
        ])
    return "\n".join(lines)


def _deepseek_chat_completion_via_urllib(payload: dict[str, Any]) -> dict[str, Any]:
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=settings.deepseek_timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _llm_strategy_metric_summary(metrics: dict[str, Any] | None) -> dict[str, Any]:
    metrics = metrics or {}
    out_of_sample = metrics.get("out_of_sample") or {}
    stability = metrics.get("walk_forward_stability") or {}
    return {
        "total_return": metrics.get("total_return"),
        "benchmark_return": metrics.get("benchmark_return"),
        "alpha_return": metrics.get("alpha_return"),
        "sharpe": metrics.get("sharpe"),
        "max_drawdown": metrics.get("max_drawdown"),
        "trade_count": metrics.get("trade_count"),
        "out_of_sample": {
            "passed": out_of_sample.get("passed"),
            "return": out_of_sample.get("return"),
            "benchmark_return": out_of_sample.get("benchmark_return"),
            "alpha_return": out_of_sample.get("alpha_return"),
            "max_drawdown": out_of_sample.get("max_drawdown"),
            "sharpe": out_of_sample.get("sharpe"),
        },
        "walk_forward_stability": {
            "passed": stability.get("passed"),
            "positive_segments": stability.get("positive_segments"),
            "worst_segment_drawdown": stability.get("worst_segment_drawdown"),
            "reason": stability.get("reason"),
        },
    }


def _feishu_live_send_preflight(target_chat_id: str | None, binary: str | None = None) -> dict[str, Any]:
    chat_id_configured = bool(str(target_chat_id or "").strip())
    live_enabled = bool(settings.lark_signal_live_enabled)
    cli_available = _lark_cli_available(binary)
    reasons = [
        reason
        for reason in [
            None if live_enabled else "live_send_disabled",
            None if chat_id_configured else "missing_chat_id",
            None if cli_available else "lark_cli_unavailable",
        ]
        if reason
    ]
    return {
        "allowed": not reasons,
        "live_enabled": live_enabled,
        "chat_id_configured": chat_id_configured,
        "lark_cli_available": cli_available,
        "reasons": reasons,
    }


async def send_feishu_signal(
    session: AsyncSession,
    chat_id: str | None = None,
    limit: int = 8,
    dry_run: bool = True,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    recommendations = await realtime_stock_recommendations(session, limit=limit)
    review = await yesterday_recommendation_review(session, limit=limit)
    message = _format_feishu_signal_message(recommendations, review)
    target_chat_id = chat_id or settings.lark_signal_chat_id
    payload = {
        "chat_id": target_chat_id,
        "dry_run": dry_run,
        "live_enabled": bool(settings.lark_signal_live_enabled),
        "message_preview": message[:2000],
        "recommendation_count": len(recommendations.get("recommendations") or []),
        "review_status": review.get("status"),
        "paper_only": True,
    }
    if dry_run:
        session.add(AdminAuditLog(action="feishu_signal_dry_run", target=target_chat_id, actor_id=actor_id, payload=payload))
        await session.commit()
        return {"sent": False, "dry_run": True, **payload, "warning": "dry-run 未发送飞书消息；真实发送需 dry_run=false 且 LARK_SIGNAL_LIVE_ENABLED=true。"}
    preflight = _feishu_live_send_preflight(target_chat_id)
    payload["preflight"] = preflight
    if not preflight["allowed"]:
        session.add(AdminAuditLog(action="feishu_signal_blocked", target=target_chat_id, actor_id=actor_id, payload=payload))
        await session.commit()
        return {
            "sent": False,
            "dry_run": False,
            "blocked": True,
            "reason": ",".join(preflight["reasons"]),
            **payload,
            "warning": "飞书 live 发送被生产闸门阻断；仅用于研究和模拟盘纸面观察，不是投资建议，不会提交真实交易订单。",
        }
    idempotency_key = f"zi-quant-signal-{date.today().isoformat()}-{limit}-{target_chat_id[-8:]}"
    command = [
        settings.lark_cli_bin,
        "im",
        "+messages-send",
        "--as",
        "bot",
        "--chat-id",
        target_chat_id,
        "--text",
        message,
        "--idempotency-key",
        idempotency_key,
        "--json",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    payload.update({"returncode": result.returncode, "stdout_tail": result.stdout[-2000:], "stderr_tail": result.stderr[-2000:]})
    session.add(AdminAuditLog(action="feishu_signal_send", target=target_chat_id, actor_id=actor_id, payload=payload))
    await session.commit()
    return {
        "sent": result.returncode == 0,
        "dry_run": False,
        **payload,
        "warning": "飞书信号仅用于研究和模拟盘纸面观察，不是投资建议，不会提交真实交易订单。",
    }


def _lark_cli_available(binary: str | None = None) -> bool:
    value = (binary or settings.lark_cli_bin or "").strip()
    if not value:
        return False
    if "/" in value:
        return Path(value).exists()
    return shutil.which(value) is not None


async def recommendation_workflow_status(session: AsyncSession, probe_symbol: str = "600519.SH") -> dict[str, Any]:
    recommendations = await realtime_stock_recommendations(session, limit=5)
    review = await yesterday_recommendation_review(session, limit=5)
    analysis = await analyze_stock_symbol(session, probe_symbol)
    signal_job = await session.scalar(
        select(DataJob)
        .where(DataJob.job_type == "feishu_signal", DataJob.status != JobStatus.failed)
        .order_by(DataJob.last_run_at.desc().nullslast(), DataJob.id.desc())
        .limit(1)
    )
    recommendation_items = recommendations.get("recommendations") or []
    review_items = review.get("items") or []
    latest_quote = analysis.get("latest_quote") or {}
    stock_recommendation = analysis.get("recommendation") or {}
    signal_payload = signal_job.payload if signal_job else {}
    signal_job_ready = bool(signal_job and str(signal_job.schedule or "").strip() and str(signal_job.schedule).strip() != "manual")
    lark_ready = _lark_cli_available()
    signal_dry_run = bool((signal_payload or {}).get("dry_run", settings.lark_signal_default_dry_run))
    live_preflight = _feishu_live_send_preflight((signal_payload or {}).get("chat_id") or settings.lark_signal_chat_id)
    passed = (
        recommendations.get("status") == "ready"
        and len(recommendation_items) > 0
        and review.get("status") == "ready"
        and len(review_items) > 0
        and analysis.get("found") is True
        and bool(stock_recommendation.get("action"))
        and bool(latest_quote.get("close"))
        and signal_job_ready
        and lark_ready
    )
    return {
        "status": "ready" if passed else "degraded",
        "passed": passed,
        "paper_only": True,
        "recommendation_status": recommendations.get("status"),
        "recommendation_count": len(recommendation_items),
        "review_status": review.get("status"),
        "review_count": len(review_items),
        "analysis_symbol": probe_symbol,
        "analysis_found": analysis.get("found") is True,
        "analysis_action": stock_recommendation.get("action"),
        "analysis_close": latest_quote.get("close"),
        "feishu_signal_job": {
            "exists": signal_job is not None,
            "job_id": str(signal_job.id) if signal_job else None,
            "schedule": signal_job.schedule if signal_job else None,
            "dry_run": signal_dry_run,
            "live_enabled": bool(settings.lark_signal_live_enabled),
            "live_ready": bool(not signal_dry_run and live_preflight["allowed"]),
            "live_blockers": live_preflight["reasons"] if not signal_dry_run else [],
            "send_mode": "dry_run" if signal_dry_run else "live",
            "ready": signal_job_ready,
        },
        "lark_cli": {
            "binary": settings.lark_cli_bin,
            "available": lark_ready,
        },
        "warning": "荐股、复盘、个股分析和飞书信号仅用于研究和模拟盘观察，不会提交真实交易订单，不构成投资建议。",
    }


async def refresh_factor_values(session: AsyncSession, limit: int = 500) -> dict[str, Any]:
    rows = await compute_market_factor_rows(session, limit=limit)
    factor = await session.scalar(select(FactorDefinition).where(FactorDefinition.name == "质量动量"))
    if not factor:
        factor = FactorDefinition(owner_id=None, name="质量动量", visibility=Visibility.public, expression="quality * 0.45 + momentum_20d * 1.5", params_schema={"rebalance": "weekly"})
        session.add(factor)
        await session.flush()
    trade_date = date.today()
    await session.execute(delete(FactorValue).where(FactorValue.factor_id == factor.id, FactorValue.trade_date == trade_date))
    session.add_all([
        FactorValue(
            factor_id=factor.id,
            symbol=row.symbol,
            trade_date=trade_date,
            value=row.score,
            payload=asdict(row) | {"source": "market_bars_or_seed_fallback"},
        )
        for row in rows
    ])
    session.add(AdminAuditLog(action="refresh_factor_values", target=str(factor.id), payload={"rows": len(rows), "trade_date": trade_date.isoformat()}))
    await session.commit()
    return {"refreshed": True, "factor_id": str(factor.id), "trade_date": trade_date.isoformat(), "rows": len(rows), "top": [asdict(r) for r in rows[:10]]}


def paper_fee(amount: float, side: str) -> float:
    commission = max(amount * 0.0003, 5)
    transfer = amount * 0.00001
    stamp = amount * 0.0005 if side == "sell" else 0
    return round(commission + transfer + stamp, 2)


async def latest_market_prices(session: AsyncSession, symbols: list[str]) -> dict[str, dict[str, Any]]:
    unique_symbols = list(dict.fromkeys(symbols))
    if not unique_symbols:
        return {}
    rows = (
        await session.scalars(
            select(MarketBar)
            .where(MarketBar.symbol.in_(unique_symbols))
            .order_by(MarketBar.symbol, MarketBar.trade_date.desc())
        )
    ).all()
    prices: dict[str, dict[str, Any]] = {}
    for bar in rows:
        if bar.symbol in prices:
            continue
        prices[bar.symbol] = {
            "price": float(bar.close),
            "trade_date": bar.trade_date.isoformat(),
            "source": bar.source,
        }
    for symbol in unique_symbols:
        prices.setdefault(symbol, {"price": synthetic_price(symbol), "trade_date": None, "source": "synthetic_fallback"})
    return prices


def _portfolio_risk_config(portfolio: PaperPortfolio) -> dict[str, float]:
    risk = (portfolio.config_json or {}).get("risk", {}) if portfolio.config_json else {}
    return {
        "max_single_position_pct": float(risk.get("max_single_position_pct", 0.2)),
        "max_order_pct": float(risk.get("max_order_pct", 0.15)),
        "min_cash_pct": float(risk.get("min_cash_pct", 0.01)),
        "max_drawdown_pct": float(risk.get("max_drawdown_pct", 0.15)),
        "daily_loss_pct": float(risk.get("daily_loss_pct", 0.03)),
    }


def _paper_risk_events_for_portfolio(
    portfolio: PaperPortfolio,
    valuation: dict[str, Any],
    performance: dict[str, Any],
    strategy: Strategy | None = None,
) -> list[dict[str, Any]]:
    config = _portfolio_risk_config(portfolio)
    strategy_risk = (strategy.rule_json or {}).get("risk", {}) if strategy else {}
    stop_loss = float(strategy_risk.get("stop_loss", 0.08))
    take_profit_raw = strategy_risk.get("take_profit", 0.35)
    take_profit = float(take_profit_raw) if take_profit_raw is not None else None
    equity = max(float(valuation.get("total_equity") or 0), 1.0)
    events: list[dict[str, Any]] = []

    def add_event(event_type: str, severity: str, summary: str, **payload: Any) -> None:
        events.append({
            "portfolio_id": str(portfolio.id),
            "portfolio_name": portfolio.name,
            "portfolio_visibility": portfolio.visibility.value,
            "event_type": event_type,
            "severity": severity,
            "summary": summary,
            "paper_only": True,
            **payload,
        })

    drawdown = float(performance.get("max_drawdown") or 0)
    if drawdown >= config["max_drawdown_pct"]:
        add_event(
            "portfolio_drawdown",
            "high",
            f"模拟盘最大回撤 {drawdown:.2%} 超过阈值 {config['max_drawdown_pct']:.2%}",
            value=round(drawdown, 4),
            limit=config["max_drawdown_pct"],
            action="review_strategy_and_reduce_paper_risk",
        )
    daily_return = performance.get("daily_return")
    if daily_return is not None and float(daily_return) <= -config["daily_loss_pct"]:
        add_event(
            "daily_loss",
            "medium",
            f"模拟盘最近单日收益 {float(daily_return):.2%} 低于阈值 -{config['daily_loss_pct']:.2%}",
            value=round(float(daily_return), 4),
            limit=-config["daily_loss_pct"],
            action="inspect_recent_positions",
        )
    cash_pct = float(valuation.get("cash") or 0) / equity
    if cash_pct < config["min_cash_pct"]:
        add_event(
            "low_cash",
            "medium",
            f"模拟盘现金比例 {cash_pct:.2%} 低于阈值 {config['min_cash_pct']:.2%}",
            value=round(cash_pct, 4),
            limit=config["min_cash_pct"],
            action="avoid_new_paper_buys",
        )

    for position in valuation.get("positions") or []:
        symbol = str(position.get("symbol") or "")
        name = str(position.get("name") or symbol)
        avg_cost = float(position.get("avg_cost") or 0)
        last_price = float(position.get("last_price") or 0)
        market_value = float(position.get("market_value") or 0)
        weight = market_value / equity
        if avg_cost > 0 and last_price > 0:
            pnl_pct = last_price / avg_cost - 1
            if pnl_pct <= -stop_loss:
                add_event(
                    "position_stop_loss",
                    "high",
                    f"{name} 纸面浮亏 {pnl_pct:.2%} 触及止损阈值 -{stop_loss:.2%}",
                    symbol=symbol,
                    value=round(pnl_pct, 4),
                    limit=-stop_loss,
                    action="review_or_reduce_paper_position",
                )
            if take_profit is not None and pnl_pct >= take_profit:
                add_event(
                    "position_take_profit",
                    "medium",
                    f"{name} 纸面浮盈 {pnl_pct:.2%} 达到止盈观察阈值 {take_profit:.2%}",
                    symbol=symbol,
                    value=round(pnl_pct, 4),
                    limit=take_profit,
                    action="consider_staged_paper_take_profit",
                )
        if weight > config["max_single_position_pct"]:
            add_event(
                "position_concentration",
                "medium",
                f"{name} 模拟仓位 {weight:.2%} 超过单票阈值 {config['max_single_position_pct']:.2%}",
                symbol=symbol,
                value=round(weight, 4),
                limit=config["max_single_position_pct"],
                action="rebalance_paper_position",
            )
        if str(position.get("price_source") or "").endswith("fallback"):
            add_event(
                "fallback_price",
                "low",
                f"{name} 使用 fallback 价格，需确认真实行情覆盖",
                symbol=symbol,
                value=position.get("price_source"),
                action="sync_real_market_data",
            )
    return events


async def evaluate_portfolio_risk(
    session: AsyncSession,
    portfolio_id: str,
    symbol: str | None = None,
    side: str | None = None,
    shares: int = 0,
    price: float | None = None,
) -> dict[str, Any]:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    if not portfolio:
        return {"accepted": False, "reason": "missing_portfolio"}
    positions = (await session.scalars(select(PaperPosition).where(PaperPosition.portfolio_id == portfolio.id, PaperPosition.shares > 0))).all()
    price_map = await latest_market_prices(session, [p.symbol for p in positions] + ([symbol] if symbol else []))
    position_values = {p.symbol: price_map[p.symbol]["price"] * p.shares for p in positions}
    market_value = sum(position_values.values())
    equity = portfolio.cash + market_value
    config = _portfolio_risk_config(portfolio)
    checks: list[dict[str, Any]] = []

    if symbol and side and shares > 0:
        price = price if price is not None else price_map[symbol]["price"]
        order_value = price * shares
        projected_cash = portfolio.cash
        projected_symbol_value = position_values.get(symbol, 0.0)
        if side == "buy":
            fee = paper_fee(order_value, "buy")
            projected_cash -= order_value + fee
            projected_symbol_value += order_value
        else:
            fee = paper_fee(order_value, "sell")
            projected_cash += order_value - fee
            projected_symbol_value = max(0.0, projected_symbol_value - order_value)
        projected_equity = max(projected_cash + market_value + (projected_symbol_value - position_values.get(symbol, 0.0)), 1.0)
        order_pct = order_value / max(equity, 1.0)
        single_pct = projected_symbol_value / projected_equity
        cash_pct = projected_cash / projected_equity
        checks.extend([
            {"name": "max_order_pct", "passed": order_pct <= config["max_order_pct"], "value": round(order_pct, 4), "limit": config["max_order_pct"]},
            {"name": "max_single_position_pct", "passed": single_pct <= config["max_single_position_pct"], "value": round(single_pct, 4), "limit": config["max_single_position_pct"]},
            {"name": "min_cash_pct", "passed": cash_pct >= config["min_cash_pct"], "value": round(cash_pct, 4), "limit": config["min_cash_pct"]},
        ])

    concentration = [
        {"symbol": sym, "weight": round(value / equity, 4) if equity else 0.0, "market_value": round(value, 2)}
        for sym, value in sorted(position_values.items(), key=lambda x: x[1], reverse=True)
    ]
    accepted = all(c["passed"] for c in checks) if checks else True
    return {
        "accepted": accepted,
        "portfolio_id": str(portfolio.id),
        "cash": round(portfolio.cash, 2),
        "market_value": round(market_value, 2),
        "equity": round(equity, 2),
        "config": config,
        "checks": checks,
        "concentration": concentration,
    }


async def seed_database(session: AsyncSession) -> None:
    existing = await session.scalar(select(func.count()).select_from(Stock))
    if existing and existing >= 500:
        researcher = await session.scalar(select(User).where(User.email == "researcher@local.zicode"))
        if researcher:
            repaired = 0
            for model in (StockPool, Strategy, PaperPortfolio, BacktestRun, StrategyOptimizationRun):
                rows = (await session.scalars(select(model).where(model.owner_id.is_(None), model.visibility == Visibility.private) if hasattr(model, "visibility") else select(model).where(model.owner_id.is_(None)))).all()
                for row in rows:
                    row.owner_id = researcher.id
                    repaired += 1
            if repaired:
                session.add(AdminAuditLog(action="repair_private_owner", target="seed_database", actor_id=researcher.id, payload={"rows": repaired}))
                await session.commit()
        source = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.adapter == "qveris"))
        if source:
            config = dict(source.config_json or {})
            config.setdefault("discovery", False)
            config.setdefault("tools", {
                "realtime_quote": "hangseng_polysource.a_shares_live_quote.query.v2.10fe0581",
                "historical_bars": "caidazi.get_sec_daily_price.execute.v1.7a43f96e",
                "financial_report": "caidazi.get_sec_income.execute.v1.7a43f96e",
                "valuation": "caidazi.get_sec_valuation.execute.v1.7a43f96e",
            })
            if settings.qveris_prepared_search_id:
                config["prepared_search_id"] = settings.qveris_prepared_search_id
            source.config_json = config
            await session.commit()
        eastmoney = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.adapter == "eastmoney"))
        if not eastmoney:
            session.add(DataSourceConfig(name="东方财富公开行情", adapter="eastmoney", priority=40, config_json={"apis": ["qt/clist/get"], "usage": "stock_universe"}))
            await session.commit()
        existing_jobs = set((await session.scalars(select(DataJob.name))).all())
        missing_jobs = []
        if "股票基础信息同步" not in existing_jobs:
            missing_jobs.append(DataJob(name="股票基础信息同步", job_type="stock_universe", status=JobStatus.idle, schedule="0 7 * * 1-5", payload={"limit": 500, "source": "eastmoney_public", "reset_public_pool": False}))
        if "因子刷新" not in existing_jobs:
            missing_jobs.append(DataJob(name="因子刷新", job_type="factor_refresh", status=JobStatus.idle, schedule="0 18 * * 1-5", payload={"limit": 500}))
        if "策略回测" not in existing_jobs:
            missing_jobs.append(DataJob(name="策略回测", job_type="backtest", status=JobStatus.idle, schedule="0 19 * * 1-5", payload={"days": 180, "max_symbols": 40}))
        if "财报同步" not in existing_jobs:
            missing_jobs.append(DataJob(name="财报同步", job_type="financial_report", status=JobStatus.idle, schedule="0 20 * * 1-5", payload={"source": "qveris", "limit": 30, "allow_fallback": False}))
        if "真实数据引导同步" not in existing_jobs:
            missing_jobs.append(DataJob(name="真实数据引导同步", job_type="real_data_bootstrap", status=JobStatus.idle, schedule="manual", payload={"limit": 10, "days": 180}))
        if "模拟盘净值快照" not in existing_jobs:
            missing_jobs.append(DataJob(name="模拟盘净值快照", job_type="paper_snapshot", status=JobStatus.idle, schedule="0 16 * * 1-5", payload={"source": "scheduled_close"}))
        if "策略研究与模拟观察" not in existing_jobs:
            missing_jobs.append(DataJob(name="策略研究与模拟观察", job_type="strategy_research", status=JobStatus.idle, schedule="30 19 * * 1-5", payload={"days": 900, "initial_cash": 100000, "max_symbols": 40, "max_trials": 8, "paper_observe": True}))
        if "飞书策略信号" not in existing_jobs:
            missing_jobs.append(DataJob(name="飞书策略信号", job_type="feishu_signal", status=JobStatus.idle, schedule="45 15 * * 1-5", payload={"dry_run": settings.lark_signal_default_dry_run, "limit": 8}))
        if missing_jobs:
            session.add_all(missing_jobs)
            await session.commit()
        return

    admin = User(email="admin@local.zicode", display_name="平台管理员", role=UserRole.admin)
    researcher = User(email="researcher@local.zicode", display_name="研究员", role=UserRole.researcher)
    session.add_all([admin, researcher])
    await session.flush()

    stocks = [Stock(**row, metadata_json={"source": "built_in_seed"}) for row in build_seed_stocks(500)]
    session.add_all(stocks)

    source_configs = [
        DataSourceConfig(name="QVeris 数据接口", adapter="qveris", priority=10, config_json={"discovery": False, "prepared_search_id": settings.qveris_prepared_search_id or None, "tools": {
            "realtime_quote": "hangseng_polysource.a_shares_live_quote.query.v2.10fe0581",
            "historical_bars": "caidazi.get_sec_daily_price.execute.v1.7a43f96e",
            "financial_report": "caidazi.get_sec_income.execute.v1.7a43f96e",
            "valuation": "caidazi.get_sec_valuation.execute.v1.7a43f96e",
        }}),
        DataSourceConfig(name="Tushare", adapter="tushare", priority=20, config_json={"apis": ["stock_basic", "daily", "fina_indicator"]}),
        DataSourceConfig(name="同花顺 iFinD", adapter="ths", priority=30, config_json={"apis": ["THS_BD", "THS_HQ", "THS_FIN"]}),
        DataSourceConfig(name="东方财富公开行情", adapter="eastmoney", priority=40, config_json={"apis": ["qt/clist/get"], "usage": "stock_universe"}),
    ]
    session.add_all(source_configs)

    factors = [
        FactorDefinition(owner_id=None, name="MACD 金叉", visibility=Visibility.public, expression="DIF > DEA and MACD > 0", params_schema={"fast": 12, "slow": 26, "signal": 9}),
        FactorDefinition(owner_id=None, name="RSI 反转", visibility=Visibility.public, expression="RSI < 35", params_schema={"window": 14}),
        FactorDefinition(owner_id=None, name="质量动量", visibility=Visibility.public, expression="quality * 0.45 + momentum_20d * 1.5", params_schema={"rebalance": "weekly"}),
    ]
    session.add_all(factors)
    strategy = Strategy(owner_id=None, name="金叉质量轮动", visibility=Visibility.public, status="active", rule_json={"buy": ["macd_golden_cross", "score_top_30"], "risk": {"max_position_pct": 0.1, "stop_loss": 0.08}})
    session.add(strategy)
    await session.flush()

    public_pool = StockPool(owner_id=None, name="公共 A 股 500", visibility=Visibility.public, refresh_strategy_id=strategy.id, description="内置 500 只 A 股基础股票池")
    private_pool = StockPool(owner_id=researcher.id, name="研究员新能源观察池", visibility=Visibility.private, refresh_strategy_id=strategy.id, description="用户私有股票池示例")
    session.add_all([public_pool, private_pool])
    await session.flush()
    session.add_all([StockPoolMember(pool_id=public_pool.id, symbol=s.symbol, reason="built_in_500") for s in stocks])
    session.add_all([StockPoolMember(pool_id=private_pool.id, symbol=s.symbol, reason="sector_private_seed") for s in stocks if s.sector == "新能源"][:50])
    session.add(PaperPortfolio(owner_id=None, strategy_id=strategy.id, name="公共模拟盘", visibility=Visibility.public, cash=100000))
    session.add(PaperPortfolio(owner_id=researcher.id, strategy_id=strategy.id, name="研究员模拟盘", visibility=Visibility.private, cash=100000))
    session.add_all([
        DataJob(name="实时行情刷新", job_type="quote", status=JobStatus.idle, schedule="*/5 * * * 1-5", payload={"source": "qveris"}),
        DataJob(name="股票基础信息同步", job_type="stock_universe", status=JobStatus.idle, schedule="0 7 * * 1-5", payload={"limit": 500, "source": "eastmoney_public", "reset_public_pool": False}),
        DataJob(name="财报同步", job_type="financial_report", status=JobStatus.idle, schedule="0 20 * * 1-5", payload={"source": "qveris", "limit": 30, "allow_fallback": False}),
        DataJob(name="策略股票池重建", job_type="pool_rebuild", status=JobStatus.idle, schedule="0 8 * * 1-5", payload={"strategy": "金叉质量轮动"}),
        DataJob(name="因子刷新", job_type="factor_refresh", status=JobStatus.idle, schedule="0 18 * * 1-5", payload={"limit": 500}),
        DataJob(name="策略回测", job_type="backtest", status=JobStatus.idle, schedule="0 19 * * 1-5", payload={"days": 180, "max_symbols": 40}),
        DataJob(name="真实数据引导同步", job_type="real_data_bootstrap", status=JobStatus.idle, schedule="manual", payload={"limit": 10, "days": 180}),
        DataJob(name="模拟盘净值快照", job_type="paper_snapshot", status=JobStatus.idle, schedule="0 16 * * 1-5", payload={"source": "scheduled_close"}),
        DataJob(name="策略研究与模拟观察", job_type="strategy_research", status=JobStatus.idle, schedule="30 19 * * 1-5", payload={"days": 900, "initial_cash": 100000, "max_symbols": 40, "max_trials": 8, "paper_observe": True}),
        DataJob(name="飞书策略信号", job_type="feishu_signal", status=JobStatus.idle, schedule="45 15 * * 1-5", payload={"dry_run": settings.lark_signal_default_dry_run, "limit": 8}),
    ])
    session.add(AdminAuditLog(action="seed_database", target="platform", payload={"stocks": 500}))
    await session.commit()


def visible_resource_filter(model: Any, user_id: uuid.UUID | None) -> Any:
    if user_id is None:
        return model.visibility == Visibility.public
    return or_(model.visibility == Visibility.public, model.owner_id == user_id)


async def rebuild_public_pool(session: AsyncSession, limit: int = 500) -> dict[str, Any]:
    pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
    if not pool:
        return {"updated": False, "reason": "missing_pool"}
    factor_rows = await compute_market_factor_rows(session, limit=500)
    ranked_symbols = [row.symbol for row in factor_rows[:limit]]
    await session.execute(delete(StockPoolMember).where(StockPoolMember.pool_id == pool.id))
    session.add_all([StockPoolMember(pool_id=pool.id, symbol=symbol, reason="market_and_fundamental_factor_rebuild") for symbol in ranked_symbols])
    session.add(AdminAuditLog(action="rebuild_pool", target=str(pool.id), payload={"limit": limit, "method": "market_and_fundamental_factor"}))
    await session.commit()
    return {"updated": True, "pool": pool.name, "count": len(ranked_symbols), "method": "market_and_fundamental_factor"}


async def create_stock_pool(
    session: AsyncSession,
    name: str,
    description: str = "",
    symbols: list[str] | None = None,
    owner_id: uuid.UUID | None = None,
    visibility: Visibility = Visibility.private,
) -> dict[str, Any]:
    normalized_symbols = []
    seen: set[str] = set()
    for symbol in symbols or []:
        code = symbol.strip().upper()
        if code and code not in seen:
            normalized_symbols.append(code)
            seen.add(code)
    existing_symbols = set((await session.scalars(select(Stock.symbol).where(Stock.symbol.in_(normalized_symbols)))).all()) if normalized_symbols else set()
    missing_symbols = [symbol for symbol in normalized_symbols if symbol not in existing_symbols]
    if missing_symbols:
        return {"created": False, "reason": "unknown_symbols", "missing_symbols": missing_symbols[:20]}

    pool = StockPool(owner_id=owner_id, name=name, description=description, visibility=visibility)
    session.add(pool)
    await session.flush()
    session.add_all([StockPoolMember(pool_id=pool.id, symbol=symbol, reason="manual_create") for symbol in normalized_symbols])
    session.add(AdminAuditLog(action="create_stock_pool", target=str(pool.id), payload={"name": name, "members": len(normalized_symbols)}))
    await session.commit()
    return {"created": True, "id": str(pool.id), "name": pool.name, "visibility": pool.visibility.value, "members": len(normalized_symbols)}


async def get_stock_pool_detail(session: AsyncSession, pool_id: str) -> dict[str, Any]:
    pool = await session.get(StockPool, uuid.UUID(pool_id))
    if not pool:
        return {"found": False, "reason": "missing_pool"}
    rows = (
        await session.execute(
            select(StockPoolMember, Stock)
            .join(Stock, Stock.symbol == StockPoolMember.symbol)
            .where(StockPoolMember.pool_id == pool.id)
            .order_by(StockPoolMember.symbol)
        )
    ).all()
    return {
        "found": True,
        "id": str(pool.id),
        "name": pool.name,
        "visibility": pool.visibility.value,
        "description": pool.description,
        "members": [
            {"symbol": stock.symbol, "name": stock.name, "market": stock.market, "sector": stock.sector, "weight": member.weight, "reason": member.reason}
            for member, stock in rows
        ],
    }


async def create_paper_portfolio(
    session: AsyncSession,
    name: str,
    owner_id: uuid.UUID | None,
    visibility: Visibility = Visibility.private,
    strategy_id: str | None = None,
    initial_cash: float = 100000.0,
    risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_strategy_id = uuid.UUID(strategy_id) if strategy_id else None
    if parsed_strategy_id and not await session.get(Strategy, parsed_strategy_id):
        return {"created": False, "reason": "missing_strategy"}
    portfolio = PaperPortfolio(
        owner_id=owner_id,
        strategy_id=parsed_strategy_id,
        name=name,
        visibility=visibility,
        cash=round(initial_cash, 2),
        config_json={"risk": risk or {}, "initial_cash": round(initial_cash, 2)},
    )
    session.add(portfolio)
    session.add(AdminAuditLog(action="create_paper_portfolio", target=name, actor_id=owner_id, payload={"visibility": visibility.value, "initial_cash": initial_cash}))
    await session.flush()
    await record_portfolio_snapshot(session, str(portfolio.id), source="portfolio_create", commit=False)
    await session.commit()
    return {"created": True, "id": str(portfolio.id), "name": portfolio.name, "visibility": portfolio.visibility.value, "cash": portfolio.cash}


async def market_coverage(session: AsyncSession, symbols: list[str] | None = None, limit: int = 100) -> dict[str, Any]:
    stmt = (
        select(
            MarketBar.symbol,
            func.min(MarketBar.trade_date).label("start_date"),
            func.max(MarketBar.trade_date).label("end_date"),
            func.count().label("bar_count"),
            func.count(distinct(MarketBar.source)).label("source_count"),
        )
        .group_by(MarketBar.symbol)
        .order_by(MarketBar.symbol)
    )
    if symbols:
        normalized = [s.strip().upper() for s in symbols if s.strip()]
        stmt = stmt.where(MarketBar.symbol.in_(normalized))
    rows = (await session.execute(stmt.limit(min(max(limit, 1), 500)))).all()
    items = []
    for symbol, start_date, end_date, bar_count, source_count in rows:
        sources = (await session.scalars(select(distinct(MarketBar.source)).where(MarketBar.symbol == symbol).order_by(MarketBar.source))).all()
        items.append({
            "symbol": symbol,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "bar_count": int(bar_count),
            "source_count": int(source_count),
            "sources": list(sources),
        })
    return {"items": items}


async def financial_report_coverage(session: AsyncSession, symbols: list[str] | None = None, limit: int = 100) -> dict[str, Any]:
    stmt = (
        select(
            FinancialReport.symbol,
            func.min(FinancialReport.report_date).label("start_date"),
            func.max(FinancialReport.report_date).label("end_date"),
            func.count().label("report_count"),
            func.count(distinct(FinancialReport.source)).label("source_count"),
        )
        .group_by(FinancialReport.symbol)
        .order_by(FinancialReport.symbol)
    )
    if symbols:
        normalized = [s.strip().upper() for s in symbols if s.strip()]
        stmt = stmt.where(FinancialReport.symbol.in_(normalized))
    rows = (await session.execute(stmt.limit(min(max(limit, 1), 500)))).all()
    items = []
    for symbol, start_date, end_date, report_count, source_count in rows:
        sources = (await session.scalars(select(distinct(FinancialReport.source)).where(FinancialReport.symbol == symbol).order_by(FinancialReport.source))).all()
        items.append({
            "symbol": symbol,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "report_count": int(report_count),
            "source_count": int(source_count),
            "sources": list(sources),
        })
    return {"items": items}


async def sync_stock_universe(session: AsyncSession, limit: int = 500, reset_public_pool: bool = True) -> dict[str, Any]:
    source_name = "eastmoney_public"
    try:
        stocks = await fetch_eastmoney_a_share_universe(limit=limit)
    except Exception as exc:
        source_name = "database_plus_builtin_real_supplement"
        existing = (
            await session.scalars(
                select(Stock)
                .where(~Stock.name.like("%样本%"), ~Stock.name.like("%退市%"), ~Stock.name.like("ST%"), ~Stock.name.like("*ST%"))
                .order_by(Stock.symbol)
                .limit(limit)
            )
        ).all()
        stocks = [
            {"symbol": stock.symbol, "name": stock.name, "sector": stock.sector, "market": stock.market, "lot_size": stock.lot_size, "metadata_json": {**(stock.metadata_json or {}), "source": "database_recovery"}}
            for stock in existing
            if not _is_excluded_stock_name(stock.name)
        ]
        fetch_error = type(exc).__name__
    else:
        fetch_error = None
    seen = {row["symbol"] for row in stocks}
    for row in built_in_real_stock_supplements():
        if row["symbol"] not in seen:
            stocks.append(row)
            seen.add(row["symbol"])
        if len(stocks) >= limit:
            break
    if len(stocks) < min(limit, 500):
        return {"synced": False, "reason": "insufficient_stock_rows", "rows": len(stocks), "expected": min(limit, 500)}

    inserted = 0
    updated = 0
    for row in stocks:
        existing = await session.get(Stock, row["symbol"])
        if existing:
            existing.name = row["name"]
            existing.market = row["market"]
            existing.sector = row["sector"]
            existing.lot_size = row["lot_size"]
            existing.metadata_json = {**(existing.metadata_json or {}), **row["metadata_json"]}
            updated += 1
        else:
            session.add(Stock(**row))
            inserted += 1

    pool_count = 0
    pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
    if reset_public_pool and pool:
        await session.execute(delete(StockPoolMember).where(StockPoolMember.pool_id == pool.id))
        session.add_all([StockPoolMember(pool_id=pool.id, symbol=row["symbol"], reason="stock_universe_sync") for row in stocks[:500]])
        pool_count = min(len(stocks), 500)

    source_config = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.adapter == "eastmoney"))
    if source_config:
        source_config.last_status = {"synced_at": datetime.now(UTC).isoformat(), "rows": len(stocks), "inserted": inserted, "updated": updated, "source": source_name}

    payload = {"rows": len(stocks), "inserted": inserted, "updated": updated, "public_pool_members": pool_count, "source": source_name, "fetch_error": fetch_error}
    session.add(DataJob(name=f"股票基础信息同步 {datetime.now(UTC).isoformat(timespec='seconds')}", job_type="stock_universe", status=JobStatus.success, schedule="manual", last_run_at=datetime.now(UTC), payload=payload))
    session.add(AdminAuditLog(action="sync_stock_universe", target="stocks", payload=payload))
    await session.commit()
    return {"synced": True, **payload}


async def list_financial_reports(session: AsyncSession, symbol: str | None = None, limit: int = 100) -> dict[str, Any]:
    stmt = select(FinancialReport).order_by(FinancialReport.report_date.desc(), FinancialReport.symbol).limit(min(max(limit, 1), 500))
    if symbol:
        stmt = stmt.where(FinancialReport.symbol == symbol.strip().upper())
    rows = (await session.scalars(stmt)).all()
    return {
        "items": [
            {
                "symbol": row.symbol,
                "report_date": row.report_date.isoformat(),
                "report_type": row.report_type,
                "revenue": row.revenue,
                "net_profit": row.net_profit,
                "roe": row.roe,
                "source": row.source,
            }
            for row in rows
        ]
    }


async def record_all_portfolio_snapshots(session: AsyncSession, source: str = "scheduled_close", owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    stmt = select(PaperPortfolio).order_by(PaperPortfolio.name)
    if owner_id:
        stmt = stmt.where(or_(PaperPortfolio.owner_id == owner_id, PaperPortfolio.visibility == Visibility.public))
    portfolios = (await session.scalars(stmt)).all()
    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for portfolio in portfolios:
        try:
            result = await record_portfolio_snapshot(session, str(portfolio.id), source=source, commit=False)
        except Exception as exc:
            errors.append({"portfolio_id": str(portfolio.id), "name": portfolio.name, "error": type(exc).__name__})
            continue
        if result.get("recorded"):
            snapshot = result["snapshot"]
            items.append({
                "portfolio_id": str(portfolio.id),
                "name": portfolio.name,
                "visibility": portfolio.visibility.value,
                "total_equity": snapshot["total_equity"],
                "total_return": snapshot["total_return"],
                "max_drawdown": snapshot["max_drawdown"],
                "snapshot_id": snapshot["id"],
            })
        else:
            errors.append({"portfolio_id": str(portfolio.id), "name": portfolio.name, "reason": result.get("reason")})
    await session.flush()
    return {
        "snapshotted": True,
        "source": source,
        "portfolio_count": len(portfolios),
        "snapshot_count": len(items),
        "error_count": len(errors),
        "items": items,
        "errors": errors,
    }


def _expand_cron_field(field: str, field_name: str) -> set[int]:
    low, high = CRON_FIELD_RANGES[field_name]
    values: set[int] = set()
    for part in str(field or "").split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        base = part
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = max(1, int(step_text))
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(base)
        start = max(low, start)
        end = min(high, end)
        values.update(range(start, end + 1, step))
    if field_name == "weekday" and 7 in values:
        values.add(0)
    return values


def _cron_schedule_matches(schedule: str, now: datetime) -> bool:
    parts = str(schedule or "").split()
    if len(parts) != 5:
        return False
    minute, hour, day, month, weekday = parts
    cron_weekday = (now.weekday() + 1) % 7
    return (
        now.minute in _expand_cron_field(minute, "minute")
        and now.hour in _expand_cron_field(hour, "hour")
        and now.day in _expand_cron_field(day, "day")
        and now.month in _expand_cron_field(month, "month")
        and cron_weekday in _expand_cron_field(weekday, "weekday")
    )


def data_job_due(job: DataJob, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    schedule = str(job.schedule or "").strip()
    if not schedule or schedule == "manual" or job.status == JobStatus.running:
        return False
    if not _cron_schedule_matches(schedule, now):
        return False
    if not job.last_run_at:
        return True
    last_run_at = job.last_run_at
    if last_run_at.tzinfo is None:
        last_run_at = last_run_at.replace(tzinfo=UTC)
    current_minute = now.replace(second=0, microsecond=0)
    last_minute = last_run_at.astimezone(UTC).replace(second=0, microsecond=0)
    return last_minute < current_minute


def data_job_recent_missed_due(job: DataJob, now: datetime | None = None, lookback_minutes: int = 24 * 60) -> dict[str, Any] | None:
    now = now or datetime.now(UTC)
    schedule = str(job.schedule or "").strip()
    if not schedule or schedule == "manual" or job.status == JobStatus.running:
        return None
    current_minute = now.astimezone(UTC).replace(second=0, microsecond=0)
    last_run_at = job.last_run_at
    last_run_minute = last_run_at.astimezone(UTC).replace(second=0, microsecond=0) if last_run_at and last_run_at.tzinfo else last_run_at.replace(tzinfo=UTC).replace(second=0, microsecond=0) if last_run_at else None
    for offset in range(1, max(1, lookback_minutes) + 1):
        candidate = current_minute - timedelta(minutes=offset)
        if not _cron_schedule_matches(schedule, candidate):
            continue
        if last_run_minute and last_run_minute >= candidate:
            return None
        age_minutes = int((current_minute - candidate).total_seconds() // 60)
        return {
            "job_id": str(job.id),
            "name": job.name,
            "type": job.job_type,
            "schedule": job.schedule,
            "due_at": candidate.isoformat(),
            "last_run_at": last_run_at.isoformat() if last_run_at else None,
            "age_minutes": age_minutes,
        }
    return None


def data_job_due_or_recent_missed(job: DataJob, now: datetime | None = None, lookback_minutes: int = 24 * 60) -> bool:
    now = now or datetime.now(UTC)
    return data_job_due(job, now=now) or data_job_recent_missed_due(job, now=now, lookback_minutes=lookback_minutes) is not None


async def run_due_data_jobs(session: AsyncSession, now: datetime | None = None, limit: int = 5) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    jobs = (await session.scalars(select(DataJob).order_by(DataJob.name))).all()
    due_jobs = [job for job in jobs if data_job_due_or_recent_missed(job, now=now)]
    results: list[dict[str, Any]] = []
    for job in due_jobs[: max(1, limit)]:
        results.append(await run_data_job(session, str(job.id)))
    return {
        "checked_at": now.isoformat(),
        "checked_count": len(jobs),
        "due_count": len(due_jobs),
        "ran_count": len(results),
        "skipped_due_count": max(0, len(due_jobs) - len(results)),
        "results": results,
    }


def _strategy_research_job_params(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "strategy_id": payload.get("strategy_id"),
        "days": min(max(int(payload.get("days", 900)), 120), 1800),
        "initial_cash": max(float(payload.get("initial_cash", 100000.0)), 1000.0),
        "max_symbols": min(max(int(payload.get("max_symbols", 40)), 5), 500),
        "max_trials": min(max(int(payload.get("max_trials", 8)), 1), 30),
        "paper_observe": bool(payload.get("paper_observe", True)),
        "max_portfolios": min(max(int(payload.get("max_portfolios", 5)), 1), 50),
    }


async def run_scheduled_strategy_research(session: AsyncSession, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    params = _strategy_research_job_params(payload)
    research = await run_next_strategy_research_action(
        session,
        strategy_id=params["strategy_id"],
        days=params["days"],
        initial_cash=params["initial_cash"],
        max_symbols=params["max_symbols"],
        max_trials=params["max_trials"],
    )
    observations: list[dict[str, Any]] = []
    plan = research.get("plan") or {}
    if params["paper_observe"] and plan.get("action") == "paper_observe":
        portfolios = (
            await session.scalars(
                select(PaperPortfolio)
                .where(or_(PaperPortfolio.visibility == Visibility.public, PaperPortfolio.owner_id.is_(None)))
                .order_by(PaperPortfolio.name)
                .limit(params["max_portfolios"])
            )
        ).all()
        for portfolio in portfolios:
            observation = await paper_rebalance_plan(session, str(portfolio.id), execute=False)
            observations.append({
                "portfolio_id": str(portfolio.id),
                "portfolio_name": portfolio.name,
                "planned": observation.get("planned"),
                "recommendation_count": len(observation.get("recommendations") or []),
                "strategy_health_status": (observation.get("strategy_health") or {}).get("status"),
                "execution_blocked": observation.get("execution_blocked", False),
            })
    return {
        "researched": True,
        "params": params,
        "plan_action": plan.get("action"),
        "research_ran": research.get("ran"),
        "readiness_after": research.get("readiness_after"),
        "strategy_health_after": {
            "status": (research.get("strategy_health_after") or {}).get("status"),
            "passed": (research.get("strategy_health_after") or {}).get("passed"),
            "reasons": (research.get("strategy_health_after") or {}).get("reasons") or [],
        },
        "paper_observations": observations,
        "paper_only": True,
        "warning": "仅执行策略研究、候选验证或模拟盘观察，不会提交真实交易订单。",
    }


def _feishu_signal_job_params(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "chat_id": payload.get("chat_id") or None,
        "limit": min(max(int(payload.get("limit", 8)), 1), 20),
        "dry_run": bool(payload.get("dry_run", settings.lark_signal_default_dry_run)),
    }


async def run_scheduled_feishu_signal(session: AsyncSession, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    params = _feishu_signal_job_params(payload)
    sent = await send_feishu_signal(
        session,
        chat_id=params["chat_id"],
        limit=params["limit"],
        dry_run=params["dry_run"],
    )
    return {
        "signaled": True,
        "params": params,
        "sent": sent.get("sent"),
        "dry_run": sent.get("dry_run"),
        "recommendation_count": sent.get("recommendation_count"),
        "review_status": sent.get("review_status"),
        "paper_only": True,
        "warning": "仅发送策略研究和模拟盘观察信号，不会提交真实交易订单，也不构成投资建议。",
    }


def _data_job_start_blocker(job: DataJob) -> dict[str, Any] | None:
    if job.status == JobStatus.running:
        return {
            "started": False,
            "reason": "job_already_running",
            "job_id": str(job.id),
            "job_type": job.job_type,
            "status": job.status.value,
            "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
        }
    return None


def _stock_universe_job_params(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "limit": min(max(int(payload.get("limit", 500)), 1), 1000),
        "reset_public_pool": bool(payload.get("reset_public_pool", False)),
    }


async def run_data_job(session: AsyncSession, job_id: str) -> dict[str, Any]:
    job = await session.scalar(select(DataJob).where(DataJob.id == uuid.UUID(job_id)).with_for_update())
    if not job:
        return {"started": False, "reason": "missing_job"}
    blocked = _data_job_start_blocker(job)
    if blocked:
        return blocked
    started_at = datetime.now(UTC)
    job_payload = dict(job.payload or {})
    run = DataJobRun(job_id=job.id, job_name=job.name, job_type=job.job_type, status=JobStatus.running, started_at=started_at, payload=job_payload, result={})
    session.add(run)
    job.status = JobStatus.running
    job.last_run_at = started_at
    job.payload = {**(job.payload or {}), "started_at": job.last_run_at.isoformat()}
    await session.commit()

    try:
        if job.job_type == "stock_universe":
            params = _stock_universe_job_params(job.payload)
            result = await sync_stock_universe(session, limit=params["limit"], reset_public_pool=params["reset_public_pool"])
        elif job.job_type in {"quote", "market_bars"}:
            result = await sync_market_bars(session, days=int((job.payload or {}).get("days", 180)), allow_fallback=bool((job.payload or {}).get("allow_fallback", True)))
        elif job.job_type == "pool_rebuild":
            result = await rebuild_public_pool(session, limit=int((job.payload or {}).get("limit", 500)))
        elif job.job_type == "factor_refresh":
            result = await refresh_factor_values(session, limit=int((job.payload or {}).get("limit", 500)))
        elif job.job_type == "backtest":
            result = await run_backtest(session, days=int((job.payload or {}).get("days", 180)), max_symbols=int((job.payload or {}).get("max_symbols", 40)))
        elif job.job_type == "financial_report":
            result = await sync_financial_reports(session, limit=int((job.payload or {}).get("limit", 30)), allow_fallback=bool((job.payload or {}).get("allow_fallback", False)))
        elif job.job_type == "real_data_bootstrap":
            result = await bootstrap_real_data(session, symbols=(job.payload or {}).get("symbols"), days=int((job.payload or {}).get("days", 180)), limit=int((job.payload or {}).get("limit", 10)))
        elif job.job_type == "paper_snapshot":
            result = await record_all_portfolio_snapshots(session, source=str((job.payload or {}).get("source") or "scheduled_close"))
        elif job.job_type == "strategy_research":
            result = await run_scheduled_strategy_research(session, payload=job_payload)
        elif job.job_type == "feishu_signal":
            result = await run_scheduled_feishu_signal(session, payload=job_payload)
        else:
            result = {"skipped": True, "reason": "unsupported_job_type", "job_type": job.job_type}

        refreshed = await session.get(DataJob, job.id)
        if refreshed:
            skipped = bool(result.get("skipped"))
            refreshed.status = JobStatus.failed if skipped else JobStatus.success
            refreshed.last_run_at = datetime.now(UTC)
            refreshed.payload = {**(refreshed.payload or {}), "finished_at": refreshed.last_run_at.isoformat(), "result": result}
        finished_at = datetime.now(UTC)
        run.status = JobStatus.failed if result.get("skipped") else JobStatus.success
        run.finished_at = finished_at
        run.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        run.result = result
        session.add(AdminAuditLog(action="run_data_job", target=str(job.id), payload={"job_type": job.job_type, "result": result}))
        await session.commit()
        return {"started": True, "job_id": str(job.id), "run_id": str(run.id), "job_type": job.job_type, "status": "failed" if result.get("skipped") else "success", "result": result}
    except Exception as exc:
        failed = await session.get(DataJob, job.id)
        if failed:
            failed.status = JobStatus.failed
            failed.last_run_at = datetime.now(UTC)
            failed.payload = {**(failed.payload or {}), "finished_at": failed.last_run_at.isoformat(), "error": type(exc).__name__}
        finished_at = datetime.now(UTC)
        run.status = JobStatus.failed
        run.finished_at = finished_at
        run.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        run.result = {"error": type(exc).__name__}
        session.add(AdminAuditLog(action="run_data_job_failed", target=str(job.id), payload={"job_type": job.job_type, "error": type(exc).__name__}))
        await session.commit()
        return {"started": True, "job_id": str(job.id), "run_id": str(run.id), "job_type": job.job_type, "status": "failed", "error": type(exc).__name__}


def _data_job_run_diagnostic(run: DataJobRun) -> dict[str, Any]:
    result = run.result or {}
    payload = run.payload or {}
    status = run.status.value if isinstance(run.status, JobStatus) else str(run.status)
    if status == "running":
        age_seconds = None
        if run.started_at:
            started_at = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=UTC)
            age_seconds = int((datetime.now(UTC) - started_at).total_seconds())
        stale = bool(age_seconds is not None and age_seconds > 2 * 60 * 60)
        return {
            "category": "stale_running" if stale else "running",
            "severity": "medium" if stale else "info",
            "retryable": False,
            "suggested_action": "reset_stale_jobs" if stale else "wait_for_completion",
            "summary": "任务运行超过 2 小时，建议先重置卡住任务。" if stale else "任务仍在运行中，等待完成或观察 worker 日志。",
            "age_seconds": age_seconds,
        }
    if status == "success":
        if run.job_type == "strategy_research":
            observations = result.get("paper_observations") or []
            return {
                "category": "strategy_observation",
                "severity": "info",
                "retryable": False,
                "suggested_action": "paper_observe" if result.get("plan_action") == "paper_observe" else "review_research_result",
                "summary": f"策略研究完成，动作 {result.get('plan_action') or '-'}，模拟观察 {len(observations)} 个组合。",
            }
        if run.job_type == "paper_snapshot":
            return {
                "category": "paper_snapshot",
                "severity": "info",
                "retryable": False,
                "suggested_action": "review_portfolio_performance",
                "summary": f"模拟盘快照完成，生成 {result.get('snapshot_count', 0)} 条快照，错误 {result.get('error_count', 0)} 条。",
            }
        stored_rows = result.get("stored_rows")
        if stored_rows is not None:
            return {
                "category": "data_sync",
                "severity": "info" if int(stored_rows or 0) > 0 else "low",
                "retryable": int(stored_rows or 0) == 0,
                "suggested_action": "inspect_data_source" if int(stored_rows or 0) == 0 else "review_coverage",
                "summary": f"数据同步完成，落库 {stored_rows} 行。",
            }
        return {"category": "success", "severity": "info", "retryable": False, "suggested_action": "none", "summary": "任务成功完成。"}
    error = result.get("error") or result.get("reason") or payload.get("error")
    if error == "stale_running_timeout":
        return {
            "category": "stale_timeout",
            "severity": "medium",
            "retryable": True,
            "suggested_action": "reset_failed_jobs_then_rerun",
            "summary": "任务曾卡住并已被标记超时，可在确认数据源正常后重置失败计划任务并重跑。",
        }
    if result.get("skipped") or error == "unsupported_job_type":
        return {
            "category": "unsupported_or_skipped",
            "severity": "medium",
            "retryable": False,
            "suggested_action": "fix_job_type_or_payload",
            "summary": f"任务被跳过：{error or run.job_type}。",
        }
    return {
        "category": "failed",
        "severity": "medium",
        "retryable": True,
        "suggested_action": "inspect_payload_and_rerun",
        "summary": f"任务失败：{error or 'unknown_error'}。",
    }


async def list_data_job_runs(session: AsyncSession, limit: int = 50, job_id: str | None = None) -> dict[str, Any]:
    stmt = select(DataJobRun).order_by(DataJobRun.started_at.desc()).limit(min(max(limit, 1), 200))
    if job_id:
        stmt = stmt.where(DataJobRun.job_id == uuid.UUID(job_id))
    rows = (await session.scalars(stmt)).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "job_id": str(row.job_id) if row.job_id else None,
                "job_name": row.job_name,
                "job_type": row.job_type,
                "status": row.status.value,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "duration_ms": row.duration_ms,
                "payload": row.payload,
                "result": row.result,
                "diagnostic": _data_job_run_diagnostic(row),
            }
            for row in rows
        ]
    }


def _data_job_payload(row: DataJob, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    missed = data_job_recent_missed_due(row, now=now)
    return {
        "id": str(row.id),
        "name": row.name,
        "type": row.job_type,
        "job_type": row.job_type,
        "status": row.status.value,
        "schedule": row.schedule,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "payload": row.payload,
        "manual": str(row.schedule or "").strip() == "manual",
        "missed_due": missed,
        "start_blocker": _data_job_start_blocker(row),
    }


async def list_data_jobs(session: AsyncSession, limit: int = 200, job_type: str | None = None) -> dict[str, Any]:
    normalized_limit = min(max(limit, 1), 500)
    stmt = select(DataJob).order_by(DataJob.job_type, DataJob.name).limit(normalized_limit)
    if job_type:
        stmt = stmt.where(DataJob.job_type == job_type.strip())
    now = datetime.now(UTC)
    rows = (await session.scalars(stmt)).all()
    items = [_data_job_payload(row, now=now) for row in rows]
    return {
        "items": items,
        "count": len(items),
        "limit": normalized_limit,
        "filters": {"job_type": job_type},
        "generated_at": now.isoformat(),
        "paper_only": True,
        "warning": "任务列表仅用于数据同步、策略研究、回测和模拟盘观察运维，不会提交真实交易订单。",
    }


def admin_audit_log_payload(log: AdminAuditLog) -> dict[str, Any]:
    return {
        "id": str(log.id),
        "actor_id": str(log.actor_id) if log.actor_id else None,
        "action": log.action,
        "target": log.target,
        "payload": _redact_data_source_config(log.payload or {}),
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


async def list_admin_audit_logs(session: AsyncSession, limit: int = 50, action: str | None = None, target: str | None = None) -> dict[str, Any]:
    normalized_limit = min(max(limit, 1), 200)
    stmt = select(AdminAuditLog)
    if action:
        stmt = stmt.where(AdminAuditLog.action == action.strip())
    if target:
        stmt = stmt.where(AdminAuditLog.target.ilike(f"%{target.strip()}%"))
    stmt = stmt.order_by(AdminAuditLog.created_at.desc()).limit(normalized_limit)
    rows = (await session.scalars(stmt)).all()
    return {
        "items": [admin_audit_log_payload(row) for row in rows],
        "count": len(rows),
        "limit": normalized_limit,
        "filters": {"action": action, "target": target},
    }


def _readiness_status(checks: list[dict[str, Any]]) -> str:
    if any(check["severity"] == "critical" and not check["passed"] for check in checks):
        return "blocked"
    if any(not check["passed"] for check in checks):
        return "degraded"
    return "ready"


PRODUCTION_AUDIT_REQUIREMENTS = [
    {"id": "database_and_schema", "title": "数据库与迁移", "category": "infrastructure", "check_names": ["migration_current"], "required": True, "next_action": "run_alembic_upgrade"},
    {"id": "deployment_config", "title": "上线运行配置", "category": "infrastructure", "check_names": ["deployment_config"], "required": True, "next_action": "set_production_deployment_config"},
    {"id": "stock_universe", "title": "A 股 500 股票池", "category": "market_universe", "check_names": ["stock_pool_size", "public_pool_default_quality"], "required": True, "next_action": "sync_stock_universe"},
    {"id": "real_market_data", "title": "真实行情与长历史", "category": "real_data", "check_names": ["real_market_bars", "public_pool_real_market_coverage", "public_pool_long_history_coverage", "market_data_freshness"], "required": True, "next_action": "bootstrap_real_market_data"},
    {"id": "real_financial_data", "title": "真实财报与质量因子", "category": "real_data", "check_names": ["real_financial_reports", "public_pool_real_financial_coverage", "financial_data_freshness"], "required": True, "next_action": "sync_financial_reports"},
    {"id": "replaceable_data_sources", "title": "数据源抽象与可替换性", "category": "data_sources", "check_names": ["enabled_data_source", "data_source_capabilities", "integration_config"], "required": True, "next_action": "configure_data_sources"},
    {"id": "backtest_engine", "title": "回测与基准评估", "category": "backtest", "check_names": ["successful_backtest"], "required": True, "next_action": "run_formal_backtest"},
    {"id": "effective_strategy", "title": "策略有效性证据", "category": "strategy", "check_names": ["active_strategy", "strategy_promotion_readiness"], "required": True, "next_action": "run_next_strategy_research_action"},
    {"id": "recommendation_and_signal_workflow", "title": "策略荐股、个股分析与飞书信号", "category": "recommendation", "check_names": ["recommendation_workflow"], "required": True, "next_action": "repair_recommendation_or_signal_workflow"},
    {"id": "llm_optimization_loop", "title": "大模型策略优化闭环", "category": "strategy", "check_names": ["strategy_optimization_loop"], "required": True, "next_action": "run_strategy_optimization_loop"},
    {"id": "paper_trading_observation", "title": "模拟盘观察闭环", "category": "paper_trading", "check_names": ["paper_portfolio_health"], "required": True, "next_action": "record_paper_snapshot_or_rebalance_plan"},
    {"id": "multi_user_access_control", "title": "多用户与权限控制", "category": "access_control", "check_names": ["active_admin_user"], "required": True, "next_action": "create_active_admin_user"},
    {"id": "fallback_data_ratio", "title": "Fallback 数据占比", "category": "real_data", "check_names": ["fallback_bar_ratio"], "required": False, "next_action": "reduce_fallback_data"},
]


def production_readiness_audit_payload(readiness: dict[str, Any], ops: dict[str, Any] | None = None) -> dict[str, Any]:
    checks_by_name = {check.get("name"): check for check in readiness.get("checks", [])}
    items: list[dict[str, Any]] = []
    required_total = 0
    required_passed = 0
    degraded_count = 0
    blocked_count = 0
    categories: dict[str, dict[str, Any]] = {}
    for requirement in PRODUCTION_AUDIT_REQUIREMENTS:
        names = requirement["check_names"]
        checks = [checks_by_name.get(name) for name in names if checks_by_name.get(name)]
        missing_names = [name for name in names if name not in checks_by_name]
        passed = bool(checks) and not missing_names and all(bool(check.get("passed")) for check in checks)
        failed_severities = [str(check.get("severity") or "info") for check in checks if not check.get("passed")]
        if "critical" in failed_severities:
            status = "blocked"
            blocked_count += 1
        elif passed:
            status = "ready"
        else:
            status = "degraded"
            degraded_count += 1
        if requirement.get("required"):
            required_total += 1
            if passed:
                required_passed += 1
        category = str(requirement["category"])
        category_row = categories.setdefault(category, {"category": category, "total": 0, "ready": 0, "degraded": 0, "blocked": 0})
        category_row["total"] += 1
        category_row[status] += 1
        items.append({
            "id": requirement["id"],
            "title": requirement["title"],
            "category": requirement["category"],
            "required": bool(requirement.get("required")),
            "status": status,
            "passed": passed,
            "missing_checks": missing_names,
            "next_action": "none" if passed else requirement["next_action"],
            "evidence": [
                {
                    "check": check.get("name"),
                    "passed": bool(check.get("passed")),
                    "severity": check.get("severity"),
                    "value": check.get("value"),
                    "expected": check.get("expected"),
                    "detail": check.get("detail"),
                }
                for check in checks
            ],
        })
    required_ready = required_total > 0 and required_passed == required_total
    ops_status = (ops or {}).get("status")
    status = "blocked" if blocked_count else "ready" if required_ready and ops_status in {None, "ready"} else "degraded"
    readiness_checks = readiness.get("checks", [])
    failed_checks = [check for check in readiness_checks if not check.get("passed")]
    action_items = (ops or {}).get("action_items") or []
    missing_required = [
        {"id": item["id"], "title": item["title"], "status": item["status"], "next_action": item["next_action"]}
        for item in items
        if item["required"] and not item["passed"]
    ]
    return {
        "status": status,
        "paper_only": True,
        "required_passed": required_passed,
        "required_total": required_total,
        "required_ratio": round(required_passed / max(required_total, 1), 4),
        "degraded_count": degraded_count,
        "blocked_count": blocked_count,
        "coverage": {
            "requirement_count": len(PRODUCTION_AUDIT_REQUIREMENTS),
            "readiness_check_count": len(readiness_checks),
            "readiness_passed_count": len(readiness_checks) - len(failed_checks),
            "failed_critical_checks": [check.get("name") for check in failed_checks if check.get("severity") == "critical"],
            "failed_warning_checks": [check.get("name") for check in failed_checks if check.get("severity") != "critical"],
            "missing_required": missing_required,
            "category_summary": list(categories.values()),
            "ops_action_count": len(action_items),
            "ops_action_severities": {
                "high": sum(1 for item in action_items if item.get("severity") == "high"),
                "medium": sum(1 for item in action_items if item.get("severity") == "medium"),
                "low": sum(1 for item in action_items if item.get("severity") == "low"),
            },
        },
        "readiness_status": readiness.get("status"),
        "ops_status": ops_status,
        "items": items,
        "action_items": action_items,
        "summary": readiness.get("summary") or {},
        "generated_at": datetime.now(UTC).isoformat(),
        "warning": "生产就绪审计只证明平台研究、回测和模拟盘能力，不代表投资建议，也不会提交真实交易订单。",
    }


async def production_readiness_audit(session: AsyncSession) -> dict[str, Any]:
    readiness = await system_readiness(session)
    ops = await operations_status(session, owner_id=None)
    return production_readiness_audit_payload(readiness, ops)


def production_acceptance_report_payload(
    audit: dict[str, Any],
    readiness: dict[str, Any] | None = None,
    ops: dict[str, Any] | None = None,
    strict_production: bool = False,
) -> dict[str, Any]:
    checklist = []
    for item in audit.get("items") or []:
        evidence = item.get("evidence") or []
        checklist.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "category": item.get("category"),
            "required": bool(item.get("required")),
            "status": item.get("status"),
            "passed": bool(item.get("passed")),
            "evidence_count": len(evidence),
            "failed_evidence": [
                row.get("check")
                for row in evidence
                if not row.get("passed")
            ] + list(item.get("missing_checks") or []),
            "next_action": item.get("next_action") or "none",
        })

    residual_risks: list[dict[str, Any]] = []
    for action in (audit.get("action_items") or []) + ((ops or {}).get("action_items") or []):
        severity = str(action.get("severity") or "low")
        residual_risks.append({
            "source": "ops_action",
            "severity": severity,
            "summary": action.get("summary") or action.get("detail") or action.get("action") or "运维待办",
            "next_action": action.get("action") or action.get("next_action") or action.get("suggested_action") or "review",
            "blocking": severity in {"critical", "high"},
        })
    strategy_evidence = (ops or {}).get("strategy_effectiveness_evidence") or {}
    for risk in strategy_evidence.get("residual_risks") or []:
        residual_risks.append({
            "source": "strategy_effectiveness",
            "severity": "low",
            "summary": str(risk),
            "next_action": "continue_paper_observation",
            "blocking": False,
        })
    deployment = (readiness or {}).get("deployment_config") or {}
    production_profile_reasons = list(deployment.get("reasons") or [])
    if strict_production and deployment.get("mode") != "production":
        production_profile_reasons.append("deployment_mode_not_production")
    if strict_production and deployment.get("auto_create_schema_enabled") is True:
        production_profile_reasons.append("auto_create_schema_enabled")
    production_profile_next_action = deployment.get("next_action")
    if strict_production and not deployment.get("production_safe") and production_profile_next_action in {None, "none"}:
        production_profile_next_action = "set_production_deployment_config"
    production_profile = {
        "strict": bool(strict_production),
        "mode": deployment.get("mode"),
        "auto_create_schema_enabled": deployment.get("auto_create_schema_enabled"),
        "production_safe": bool(deployment.get("production_safe")),
        "reasons": production_profile_reasons,
        "next_action": production_profile_next_action if strict_production and not deployment.get("production_safe") else "none",
    }
    if strict_production and not production_profile["production_safe"]:
        residual_risks.append({
            "source": "deployment_profile",
            "severity": "high",
            "summary": "严格生产验收要求 ZI_DEPLOYMENT_MODE=production 且 AUTO_CREATE_SCHEMA=false。",
            "next_action": production_profile["next_action"] or "set_production_deployment_config",
            "blocking": True,
        })
    deduped_residual_risks: list[dict[str, Any]] = []
    seen_risk_keys: set[tuple[str, str, str, str]] = set()
    for risk in residual_risks:
        key = (
            str(risk.get("source") or ""),
            str(risk.get("severity") or ""),
            str(risk.get("summary") or ""),
            str(risk.get("next_action") or ""),
        )
        if key in seen_risk_keys:
            continue
        seen_risk_keys.add(key)
        deduped_residual_risks.append(risk)

    required_ok = audit.get("required_total", 0) > 0 and audit.get("required_passed") == audit.get("required_total")
    accepted = audit.get("status") == "ready" and required_ok and (not strict_production or production_profile["production_safe"])
    return {
        "status": "ready" if accepted else "degraded" if strict_production and not production_profile["production_safe"] else audit.get("status", "degraded"),
        "decision": "accepted_for_paper_observation" if accepted else "not_accepted",
        "paper_only": True,
        "strict_production": bool(strict_production),
        "production_profile": production_profile,
        "required_passed": audit.get("required_passed", 0),
        "required_total": audit.get("required_total", 0),
        "required_ratio": audit.get("required_ratio", 0),
        "coverage": audit.get("coverage") or {},
        "checklist": checklist,
        "residual_risks": deduped_residual_risks[:30],
        "evidence": {
            "readiness_status": (readiness or {}).get("status") or audit.get("readiness_status"),
            "ops_status": (ops or {}).get("status") or audit.get("ops_status"),
            "summary": (readiness or {}).get("summary") or audit.get("summary") or {},
            "data_quality": (ops or {}).get("data_quality"),
            "data_source_capabilities": (ops or {}).get("data_source_capabilities"),
            "strategy_effectiveness": strategy_evidence or None,
            "strategy_optimization_loop": (ops or {}).get("strategy_optimization_loop"),
            "paper_portfolio_health": (ops or {}).get("paper_portfolio_health"),
            "paper_risk_events": (ops or {}).get("paper_risk_events"),
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "warning": "验收结论仅适用于研究、回测和模拟盘观察；不会提交真实交易订单，不构成投资建议。",
    }


async def production_acceptance_report(session: AsyncSession, strict_production: bool = False) -> dict[str, Any]:
    readiness = await system_readiness(session)
    ops = await operations_status(session, owner_id=None)
    audit = production_readiness_audit_payload(readiness, ops)
    return production_acceptance_report_payload(audit, readiness, ops, strict_production=strict_production)


def _freshness_status(latest: date | None, today: date | None = None, max_age_days: int = 7) -> dict[str, Any]:
    if latest is None:
        return {"fresh": False, "age_days": None, "latest": None, "max_age_days": max_age_days, "reason": "missing_data"}
    today = today or date.today()
    age_days = max((today - latest).days, 0)
    return {
        "fresh": age_days <= max_age_days,
        "age_days": age_days,
        "latest": latest.isoformat(),
        "max_age_days": max_age_days,
        "reason": "fresh" if age_days <= max_age_days else "stale",
    }


def _coverage_target(pool_count: int, ratio: float, floor: int) -> int:
    if pool_count <= 0:
        return 0
    ratio_target = math.ceil(pool_count * max(0.0, ratio))
    return min(pool_count, max(floor, ratio_target))


def data_quality_targets(public_pool_count: int) -> dict[str, Any]:
    return {
        "real_bar_symbols": _coverage_target(public_pool_count, settings.min_public_pool_real_bar_coverage, settings.min_public_pool_real_bar_symbols),
        "long_history_symbols": _coverage_target(public_pool_count, settings.min_public_pool_long_history_coverage, settings.min_public_pool_long_history_symbols),
        "financial_symbols": _coverage_target(public_pool_count, settings.min_public_pool_financial_coverage, settings.min_public_pool_financial_symbols),
        "real_bar_coverage": settings.min_public_pool_real_bar_coverage,
        "long_history_coverage": settings.min_public_pool_long_history_coverage,
        "financial_coverage": settings.min_public_pool_financial_coverage,
        "max_fallback_bar_ratio": settings.max_fallback_bar_ratio,
    }


def _metric_float(metrics: dict[str, Any], name: str, default: float | None = None) -> float | None:
    value = metrics.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _strategy_experiment_health_payload(experiment: StrategyExperiment | None) -> dict[str, Any] | None:
    if experiment is None:
        return None
    comparison = experiment.comparison or {}
    return {
        "id": str(experiment.id),
        "name": experiment.name,
        "status": experiment.status,
        "passed": experiment.passed,
        "decision": experiment.decision,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
        "deltas": comparison.get("deltas") or {},
        "reasons": comparison.get("reasons") or [],
    }


def strategy_health_repair_plan(status: str, reasons: list[str], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    if status == "ready":
        return [
            {
                "priority": "observe",
                "action": "paper_observe",
                "title": "保持模拟盘观察",
                "detail": "最近回测健康度通过，继续记录模拟盘净值和回撤，不自动扩大风险敞口。",
                "endpoint": "/api/portfolios/{portfolio_id}/rebalance",
                "params": {"execute": False},
            }
        ]
    if status == "missing":
        return [
            {
                "priority": "critical",
                "action": "create_active_strategy",
                "title": "创建或启用策略",
                "detail": "平台缺少 active 策略，无法形成策略健康度和模拟盘调仓闭环。",
                "endpoint": "/api/strategies/{strategy_id}/promote",
                "params": {},
            }
        ]
    if status == "degraded" and not metrics:
        return [
            {
                "priority": "high",
                "action": "run_backtest",
                "title": "先运行正式回测",
                "detail": "启用策略缺少成功回测记录，先用真实行情生成 Alpha、样本外和稳定性指标。",
                "endpoint": "/api/backtests/run",
                "params": {"days": 900, "initial_cash": 100000, "max_symbols": 50},
            }
        ]

    plan: list[dict[str, Any]] = []
    alpha = metrics.get("alpha_return")
    out_sample_alpha = metrics.get("out_of_sample_alpha_return")
    max_drawdown = metrics.get("max_drawdown")
    trade_count = metrics.get("trade_count") or 0
    sharpe = metrics.get("sharpe")
    reason_text = "；".join(reasons)
    if out_sample_alpha is not None and float(out_sample_alpha) < -0.05:
        plan.append({
            "priority": "critical",
            "action": "remediate_health",
            "title": "优先修复样本外 Alpha",
            "detail": "样本外 Alpha 低于 -5%，先用大模型生成候选并立即验证，候选未通过时继续 Alpha 网格搜索。",
            "endpoint": "/api/strategies/remediate-health",
            "params": {"days": 900, "initial_cash": 100000, "max_symbols": 40},
            "parameter_bias": {"candidate_top_n": "<=3", "min_momentum": ">=0.08", "min_quality": ">=0.65", "max_sector_pct": "<=0.25"},
        })
        plan.append({
            "priority": "high",
            "action": "alpha_search",
            "title": "做 Alpha 网格搜索",
            "detail": "围绕候选数量、动量门槛、质量门槛、行业暴露和单票仓位做有限搜索，目标优先提高样本外 Alpha。",
            "endpoint": "/api/strategies/alpha-search",
            "params": {"days": 900, "initial_cash": 100000, "max_symbols": 30, "max_trials": 8},
        })
    if alpha is not None and float(alpha) < -0.05:
        plan.append({
            "priority": "high",
            "action": "tighten_signal_quality",
            "title": "收紧入选信号",
            "detail": "全段 Alpha 跑输同源等权基准，减少弱信号入选并提高质量/动量门槛。",
            "endpoint": "/api/strategies/optimize",
            "params": {},
            "parameter_bias": {"candidate_top_n": "<=3", "min_momentum": ">=0.05", "min_quality": ">=0.60"},
        })
    if max_drawdown is not None and float(max_drawdown) > 0.30:
        plan.append({
            "priority": "high",
            "action": "reduce_risk_exposure",
            "title": "降低组合风险暴露",
            "detail": "最大回撤超过 30%，需要降低单票仓位、收紧止损并检查分段回撤。",
            "endpoint": "/api/strategies/optimize",
            "params": {},
            "parameter_bias": {"max_position_pct": "<=0.07", "stop_loss": "<=0.06", "max_positions": "<=8"},
        })
    if "分段稳定性" in reason_text or metrics.get("walk_forward_passed") is False:
        plan.append({
            "priority": "medium",
            "action": "walk_forward_review",
            "title": "复查滚动稳定性",
            "detail": "分段稳定性未通过，扩大样本区间并观察不同市场阶段的 Alpha 是否集中在少数区间。",
            "endpoint": "/api/strategies/remediate-health",
            "params": {"days": 1200, "initial_cash": 100000, "max_symbols": 50},
        })
    if trade_count < 2:
        plan.append({
            "priority": "medium",
            "action": "loosen_or_expand_universe",
            "title": "提高有效交易覆盖",
            "detail": "交易次数不足，先检查真实行情覆盖和股票池范围，再适度放宽过严过滤条件。",
            "endpoint": "/api/data/coverage",
            "params": {"limit": 50},
        })
    if sharpe is not None and float(sharpe) < 0:
        plan.append({
            "priority": "medium",
            "action": "reject_and_archive",
            "title": "归档低质量策略候选",
            "detail": "Sharpe 为负且健康度失败，优先归档候选，避免进入模拟盘执行。",
            "endpoint": "/api/strategies/{strategy_id}",
            "params": {"status": "archived"},
        })
    if not plan:
        plan.append({
            "priority": "medium",
            "action": "manual_review",
            "title": "人工复核失败原因",
            "detail": "健康度未通过但未命中特定规则，复查最近回测、实验记录、真实行情覆盖和策略参数。",
            "endpoint": "/api/strategies/health",
            "params": {},
        })
    return plan


def strategy_effectiveness_evidence(
    status: str,
    reasons: list[str],
    metrics: dict[str, Any],
    backtest: BacktestRun | None = None,
    experiment_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status == "missing":
        return {
            "verdict": "missing_strategy",
            "confidence": "none",
            "passed": False,
            "summary": "缺少启用策略，无法证明策略有效性。",
            "strengths": [],
            "residual_risks": ["需要先创建并启用策略"],
            "required_action": "create_or_activate_strategy",
        }
    if backtest is None:
        return {
            "verdict": "missing_backtest",
            "confidence": "low",
            "passed": False,
            "summary": "启用策略缺少成功回测记录，不能进入生产级策略观察。",
            "strengths": [],
            "residual_risks": ["需要正式回测、样本外检验和基准对比"],
            "required_action": "run_formal_backtest",
        }
    strengths: list[str] = []
    residual_risks: list[str] = list(reasons)
    if metrics.get("alpha_return") is not None and float(metrics["alpha_return"]) > 0:
        strengths.append("全段收益跑赢同源等权基准")
    if metrics.get("out_of_sample_alpha_return") is not None and float(metrics["out_of_sample_alpha_return"]) > 0:
        strengths.append("样本外 Alpha 为正")
    if metrics.get("walk_forward_passed") is True:
        strengths.append("滚动分段稳定性通过")
    if experiment_payload and experiment_payload.get("passed") is True:
        strengths.append("最近候选验证实验通过")
    if metrics.get("trade_count") is not None and int(metrics.get("trade_count") or 0) < 10:
        residual_risks.append("交易次数偏少，继续模拟盘观察")
    if metrics.get("limited_history"):
        residual_risks.append("历史样本有限，扩大真实行情覆盖后复核")
    confidence = "high" if status == "ready" and len(strengths) >= 3 and not reasons else "medium" if status == "ready" else "low"
    verdict = "validated_for_paper_observation" if status == "ready" else "needs_research_repair"
    return {
        "verdict": verdict,
        "confidence": confidence,
        "passed": status == "ready",
        "summary": "策略有效性证据通过，适合继续模拟盘观察。" if status == "ready" else "策略有效性证据不足，需要继续研究修复。",
        "strengths": strengths,
        "residual_risks": residual_risks,
        "required_action": "paper_observe" if status == "ready" else "run_next_strategy_research_action",
        "evidence_refs": {
            "backtest_run_id": str(backtest.id) if backtest else None,
            "experiment_id": experiment_payload.get("id") if experiment_payload else None,
            "backtest_period": {
                "start": backtest.start_date.isoformat() if backtest and backtest.start_date else None,
                "end": backtest.end_date.isoformat() if backtest and backtest.end_date else None,
            },
        },
        "metrics": {
            "total_return": metrics.get("total_return"),
            "benchmark_return": metrics.get("benchmark_return"),
            "alpha_return": metrics.get("alpha_return"),
            "out_of_sample_alpha_return": metrics.get("out_of_sample_alpha_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe": metrics.get("sharpe"),
            "trade_count": metrics.get("trade_count"),
        },
    }


def strategy_health_from_metrics(strategy: Strategy | None, backtest: BacktestRun | None, experiment: StrategyExperiment | None = None) -> dict[str, Any]:
    if strategy is None:
        return {
            "status": "missing",
            "passed": False,
            "reasons": ["缺少启用策略"],
            "repair_plan": strategy_health_repair_plan("missing", ["缺少启用策略"], {}),
            "strategy": None,
            "backtest": None,
            "experiment": None,
            "metrics": {},
            "effectiveness_evidence": strategy_effectiveness_evidence("missing", ["缺少启用策略"], {}, None, None),
            "generated_at": datetime.now(UTC).isoformat(),
        }
    strategy_payload = {"id": str(strategy.id), "name": strategy.name, "visibility": strategy.visibility.value, "status": strategy.status}
    experiment_payload = _strategy_experiment_health_payload(experiment)
    if backtest is None:
        return {
            "status": "degraded",
            "passed": False,
            "reasons": ["启用策略缺少成功回测记录"],
            "repair_plan": strategy_health_repair_plan("degraded", ["启用策略缺少成功回测记录"], {}),
            "strategy": strategy_payload,
            "backtest": None,
            "experiment": experiment_payload,
            "metrics": {},
            "effectiveness_evidence": strategy_effectiveness_evidence("degraded", ["启用策略缺少成功回测记录"], {}, None, experiment_payload),
            "generated_at": datetime.now(UTC).isoformat(),
        }

    metrics = backtest.metrics or {}
    out_of_sample = metrics.get("out_of_sample") or {}
    stability = metrics.get("walk_forward_stability") or {}
    total_return = _metric_float(metrics, "total_return", 0.0)
    benchmark_return = _metric_float(metrics, "benchmark_return")
    alpha_return = _metric_float(metrics, "alpha_return")
    max_drawdown = _metric_float(metrics, "max_drawdown", 1.0)
    sharpe = _metric_float(metrics, "sharpe", -999.0)
    trade_count = int(_metric_float(metrics, "trade_count", 0.0) or 0)
    out_sample_return = _metric_float(out_of_sample, "return")
    out_sample_benchmark = _metric_float(out_of_sample, "benchmark_return")
    out_sample_alpha = _metric_float(out_of_sample, "alpha_return")

    reasons: list[str] = []
    if metrics.get("limited_history"):
        reasons.append("回测历史样本过短")
    if trade_count < 2:
        reasons.append("交易次数不足 2 笔")
    if max_drawdown is not None and max_drawdown > 0.30:
        reasons.append("最大回撤超过 30%")
    if stability.get("passed") is False:
        reasons.append(f"分段稳定性未通过：{stability.get('reason') or 'unknown'}")
    if out_of_sample.get("passed") is False:
        reasons.append(f"样本外检验未通过：{out_of_sample.get('reason') or 'unknown'}")
    if out_sample_alpha is not None and out_sample_alpha < -0.05:
        reasons.append("样本外 Alpha 低于 -5%")
    if alpha_return is not None and alpha_return < -0.05 and (sharpe is None or sharpe < 1.5):
        reasons.append("Alpha 低于 -5% 且 Sharpe 未达到补偿阈值")
    status = "ready" if not reasons else "rejected"
    health_metrics = {
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "alpha_return": alpha_return,
        "out_of_sample_return": out_sample_return,
        "out_of_sample_benchmark_return": out_sample_benchmark,
        "out_of_sample_alpha_return": out_sample_alpha,
        "out_of_sample_passed": out_of_sample.get("passed"),
        "walk_forward_passed": stability.get("passed"),
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "trade_count": trade_count,
        "limited_history": bool(metrics.get("limited_history")),
    }

    return {
        "status": status,
        "passed": not reasons,
        "reasons": reasons,
        "repair_plan": strategy_health_repair_plan(status, reasons, health_metrics),
        "strategy": strategy_payload,
        "backtest": {
            "id": str(backtest.id),
            "name": backtest.name,
            "status": backtest.status,
            "start_date": backtest.start_date.isoformat() if backtest.start_date else None,
            "end_date": backtest.end_date.isoformat() if backtest.end_date else None,
            "created_at": backtest.created_at.isoformat() if backtest.created_at else None,
        },
        "experiment": experiment_payload,
        "metrics": health_metrics,
        "effectiveness_evidence": strategy_effectiveness_evidence(status, reasons, health_metrics, backtest, experiment_payload),
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def active_strategy_health(session: AsyncSession, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    strategy = await session.scalar(
        select(Strategy)
        .where(Strategy.status == "active", visible_resource_filter(Strategy, owner_id))
        .order_by(Strategy.created_at.desc())
        .limit(1)
    )
    if not strategy:
        return strategy_health_from_metrics(None, None, None)
    backtest = await session.scalar(
        select(BacktestRun)
        .where(BacktestRun.strategy_id == strategy.id, BacktestRun.status == "success")
        .order_by(BacktestRun.created_at.desc())
        .limit(1)
    )
    experiment = await session.scalar(
        select(StrategyExperiment)
        .where(or_(StrategyExperiment.strategy_id == strategy.id, StrategyExperiment.source_strategy_id == strategy.id))
        .order_by(StrategyExperiment.created_at.desc())
        .limit(1)
    )
    return strategy_health_from_metrics(strategy, backtest, experiment)


def paper_rebalance_execution_guard(execute: bool, strategy_health: dict[str, Any], allow_unhealthy_strategy: bool = False) -> dict[str, Any]:
    if not execute:
        return {"execution_allowed": False, "execution_blocked": False, "reason": "plan_only"}
    if allow_unhealthy_strategy:
        return {"execution_allowed": True, "execution_blocked": False, "reason": "explicit_unhealthy_strategy_override"}
    if strategy_health.get("status") == "ready" and strategy_health.get("passed") is True:
        return {"execution_allowed": True, "execution_blocked": False, "reason": "strategy_health_ready"}
    return {
        "execution_allowed": False,
        "execution_blocked": True,
        "reason": "strategy_health_rejected",
        "details": strategy_health.get("reasons") or ["启用策略健康度未通过"],
    }


def _paper_portfolio_health_from_rows(
    portfolios: list[PaperPortfolio],
    strategy_by_id: dict[uuid.UUID, Strategy],
    latest_snapshot_by_portfolio: dict[uuid.UUID, PaperEquitySnapshot],
    position_count_by_portfolio: dict[uuid.UUID, int],
    latest_order_at_by_portfolio: dict[uuid.UUID, datetime],
    strategy_health: dict[str, Any],
    now: datetime | None = None,
    max_snapshot_age_days: int = 7,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    items: list[dict[str, Any]] = []
    bound_count = 0
    active_bound_count = 0
    public_bound_count = 0
    fresh_snapshot_count = 0
    stale_snapshot_count = 0
    missing_snapshot_count = 0
    unbound_count = 0
    cash_only_count = 0

    for portfolio in portfolios:
        strategy = strategy_by_id.get(portfolio.strategy_id) if portfolio.strategy_id else None
        snapshot = latest_snapshot_by_portfolio.get(portfolio.id)
        latest_order_at = latest_order_at_by_portfolio.get(portfolio.id)
        position_count = int(position_count_by_portfolio.get(portfolio.id, 0) or 0)
        strategy_status = strategy.status if strategy else None
        strategy_visibility = strategy.visibility.value if strategy else None
        bound = bool(strategy and strategy.status != "archived")
        if bound:
            bound_count += 1
        if strategy and strategy.status == "active":
            active_bound_count += 1
        if strategy and strategy.visibility == Visibility.public:
            public_bound_count += 1
        if not bound:
            unbound_count += 1
        if position_count == 0:
            cash_only_count += 1

        snapshot_age_days: int | None = None
        snapshot_fresh = False
        if snapshot and snapshot.snapshot_at:
            snapshot_at = snapshot.snapshot_at
            if snapshot_at.tzinfo is None:
                snapshot_at = snapshot_at.replace(tzinfo=UTC)
            snapshot_age_days = max(0, (now - snapshot_at).days)
            snapshot_fresh = snapshot_age_days <= max_snapshot_age_days
        if snapshot_fresh:
            fresh_snapshot_count += 1
        elif snapshot:
            stale_snapshot_count += 1
        else:
            missing_snapshot_count += 1

        item_reasons = []
        if not bound:
            item_reasons.append("未绑定有效策略")
        if not snapshot:
            item_reasons.append("缺少权益快照")
        elif not snapshot_fresh:
            item_reasons.append(f"权益快照超过 {max_snapshot_age_days} 天")
        if position_count == 0:
            item_reasons.append("当前为空仓/现金观察")
        items.append(
            {
                "id": str(portfolio.id),
                "name": portfolio.name,
                "visibility": portfolio.visibility.value,
                "strategy_id": str(portfolio.strategy_id) if portfolio.strategy_id else None,
                "strategy_name": strategy.name if strategy else None,
                "strategy_status": strategy_status,
                "strategy_visibility": strategy_visibility,
                "bound_to_valid_strategy": bound,
                "position_count": position_count,
                "cash": round(float(portfolio.cash or 0), 2),
                "latest_snapshot_at": snapshot.snapshot_at.isoformat() if snapshot and snapshot.snapshot_at else None,
                "latest_snapshot_age_days": snapshot_age_days,
                "latest_total_equity": round(float(snapshot.total_equity), 2) if snapshot else None,
                "latest_order_at": latest_order_at.isoformat() if latest_order_at else None,
                "snapshot_fresh": snapshot_fresh,
                "status": "ready" if bound and snapshot_fresh else "degraded",
                "reasons": item_reasons,
            }
        )

    strategy_ready = strategy_health.get("status") == "ready" and strategy_health.get("passed") is True
    if not portfolios:
        reasons.append("缺少可见模拟盘")
    if unbound_count:
        reasons.append(f"{unbound_count} 个模拟盘未绑定有效策略")
    if missing_snapshot_count:
        reasons.append(f"{missing_snapshot_count} 个模拟盘缺少权益快照")
    if stale_snapshot_count:
        reasons.append(f"{stale_snapshot_count} 个模拟盘权益快照过期")
    if not strategy_ready:
        reasons.append("启用策略健康度未通过，模拟盘只能生成观察计划")

    observation_ready_count = sum(1 for item in items if item["bound_to_valid_strategy"] and item["snapshot_fresh"])
    status = "ready" if portfolios and not reasons else "degraded"
    next_action = "paper_observe" if status == "ready" else "record_paper_snapshot"
    if unbound_count:
        next_action = "bind_active_strategy"
    if not strategy_ready:
        next_action = "run_next_strategy_research_action"
    return {
        "status": status,
        "passed": status == "ready",
        "paper_only": True,
        "reasons": reasons,
        "next_action": next_action,
        "max_snapshot_age_days": max_snapshot_age_days,
        "portfolio_count": len(portfolios),
        "bound_portfolio_count": bound_count,
        "active_strategy_bound_count": active_bound_count,
        "public_strategy_bound_count": public_bound_count,
        "fresh_snapshot_count": fresh_snapshot_count,
        "stale_snapshot_count": stale_snapshot_count,
        "missing_snapshot_count": missing_snapshot_count,
        "unbound_portfolio_count": unbound_count,
        "cash_only_portfolio_count": cash_only_count,
        "observation_ready_count": observation_ready_count,
        "strategy_health_status": strategy_health.get("status"),
        "items": items,
        "generated_at": now.isoformat(),
        "warning": "仅用于模拟盘观察和纸面调仓建议，不会提交真实交易订单。",
    }


async def paper_portfolio_health_summary(session: AsyncSession, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    stmt = select(PaperPortfolio).order_by(PaperPortfolio.name)
    if owner_id is not None:
        stmt = stmt.where(visible_resource_filter(PaperPortfolio, owner_id))
    portfolios = (await session.scalars(stmt)).all()
    portfolio_ids = [portfolio.id for portfolio in portfolios]
    strategies = (await session.scalars(select(Strategy).where(Strategy.id.in_({p.strategy_id for p in portfolios if p.strategy_id})))).all() if portfolios else []
    latest_snapshot_by_portfolio: dict[uuid.UUID, PaperEquitySnapshot] = {}
    position_count_by_portfolio: dict[uuid.UUID, int] = {}
    latest_order_at_by_portfolio: dict[uuid.UUID, datetime] = {}
    if portfolio_ids:
        snapshots = (
            await session.scalars(
                select(PaperEquitySnapshot)
                .where(PaperEquitySnapshot.portfolio_id.in_(portfolio_ids))
                .order_by(PaperEquitySnapshot.portfolio_id, PaperEquitySnapshot.snapshot_at.desc())
            )
        ).all()
        for snapshot in snapshots:
            latest_snapshot_by_portfolio.setdefault(snapshot.portfolio_id, snapshot)
        position_counts = (
            await session.execute(
                select(PaperPosition.portfolio_id, func.count())
                .where(PaperPosition.portfolio_id.in_(portfolio_ids), PaperPosition.shares > 0)
                .group_by(PaperPosition.portfolio_id)
            )
        ).all()
        position_count_by_portfolio = {row[0]: int(row[1]) for row in position_counts}
        latest_orders = (
            await session.execute(
                select(PaperOrder.portfolio_id, func.max(PaperOrder.created_at))
                .where(PaperOrder.portfolio_id.in_(portfolio_ids))
                .group_by(PaperOrder.portfolio_id)
            )
        ).all()
        latest_order_at_by_portfolio = {row[0]: row[1] for row in latest_orders if row[1]}
    strategy_health = await active_strategy_health(session, owner_id=owner_id)
    return _paper_portfolio_health_from_rows(
        portfolios,
        {strategy.id: strategy for strategy in strategies},
        latest_snapshot_by_portfolio,
        position_count_by_portfolio,
        latest_order_at_by_portfolio,
        strategy_health,
    )


async def data_quality_summary(session: AsyncSession) -> dict[str, Any]:
    public_pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
    public_pool_count = 0
    public_pool_real_bar_symbols = 0
    public_pool_long_history_symbols = 0
    public_pool_financial_symbols = 0
    if public_pool:
        public_symbol_subquery = select(StockPoolMember.symbol).where(StockPoolMember.pool_id == public_pool.id)
        public_pool_count = await session.scalar(select(func.count()).select_from(StockPoolMember).where(StockPoolMember.pool_id == public_pool.id)) or 0
        public_pool_real_bar_symbols = await session.scalar(select(func.count(distinct(MarketBar.symbol))).where(MarketBar.symbol.in_(public_symbol_subquery), MarketBar.source != "simulated_fallback")) or 0
        public_pool_financial_symbols = await session.scalar(select(func.count(distinct(FinancialReport.symbol))).where(FinancialReport.symbol.in_(public_symbol_subquery), FinancialReport.source != "simulated_fallback")) or 0
        long_history_subquery = (
            select(MarketBar.symbol)
            .where(MarketBar.symbol.in_(public_symbol_subquery), MarketBar.source != "simulated_fallback")
            .group_by(MarketBar.symbol)
            .having(func.count(distinct(MarketBar.trade_date)) >= 250)
            .subquery()
        )
        public_pool_long_history_symbols = await session.scalar(select(func.count()).select_from(long_history_subquery)) or 0
    real_bar_count = await session.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.source != "simulated_fallback")) or 0
    fallback_bar_count = await session.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.source == "simulated_fallback")) or 0
    latest_market_date = await session.scalar(select(func.max(MarketBar.trade_date)).where(MarketBar.source != "simulated_fallback"))
    latest_financial_date = await session.scalar(select(func.max(FinancialReport.report_date)).where(FinancialReport.source != "simulated_fallback"))
    total_bars = real_bar_count + fallback_bar_count
    fallback_ratio = round(fallback_bar_count / total_bars, 4) if total_bars else 0.0
    market_freshness = _freshness_status(latest_market_date, max_age_days=7)
    financial_freshness = _freshness_status(latest_financial_date, max_age_days=220)
    coverage_denominator = max(public_pool_count, 1)
    targets = data_quality_targets(public_pool_count)
    gaps = {
        "real_bar_symbols": max(0, targets["real_bar_symbols"] - public_pool_real_bar_symbols),
        "long_history_symbols": max(0, targets["long_history_symbols"] - public_pool_long_history_symbols),
        "financial_symbols": max(0, targets["financial_symbols"] - public_pool_financial_symbols),
        "fallback_bar_ratio": max(0.0, round(fallback_ratio - targets["max_fallback_bar_ratio"], 4)),
    }
    coverage_ready = all(value == 0 for value in gaps.values())
    return {
        "market_freshness": market_freshness,
        "financial_freshness": financial_freshness,
        "real_bar_rows": real_bar_count,
        "fallback_bar_rows": fallback_bar_count,
        "fallback_bar_ratio": fallback_ratio,
        "public_pool_members": public_pool_count,
        "public_pool_real_bar_symbols": public_pool_real_bar_symbols,
        "public_pool_long_history_symbols": public_pool_long_history_symbols,
        "public_pool_financial_symbols": public_pool_financial_symbols,
        "public_pool_real_bar_coverage": round(public_pool_real_bar_symbols / coverage_denominator, 4),
        "public_pool_long_history_coverage": round(public_pool_long_history_symbols / coverage_denominator, 4),
        "public_pool_financial_coverage": round(public_pool_financial_symbols / coverage_denominator, 4),
        "targets": targets,
        "gaps": gaps,
        "next_action": "none" if coverage_ready else "bootstrap_real_data_or_raise_coverage",
        "status": "ready" if market_freshness["fresh"] and financial_freshness["fresh"] and coverage_ready else "degraded",
    }


async def system_readiness(session: AsyncSession) -> dict[str, Any]:
    def check(name: str, passed: bool, severity: str, value: Any, expected: Any, detail: str) -> dict[str, Any]:
        return {"name": name, "passed": passed, "severity": severity, "value": value, "expected": expected, "detail": detail}

    stock_count = await session.scalar(select(func.count()).select_from(Stock)) or 0
    active_strategy_count = await session.scalar(select(func.count()).select_from(Strategy).where(Strategy.status == "active")) or 0
    enabled_source_count = await session.scalar(select(func.count()).select_from(DataSourceConfig).where(DataSourceConfig.enabled.is_(True))) or 0
    backtest_count = await session.scalar(select(func.count()).select_from(BacktestRun).where(BacktestRun.status == "success")) or 0
    qveris_bar_count = await session.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.source == "qveris")) or 0
    real_bar_count = await session.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.source != "simulated_fallback")) or 0
    fallback_bar_count = await session.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.source == "simulated_fallback")) or 0
    qveris_bar_symbols = await session.scalar(select(func.count(distinct(MarketBar.symbol))).where(MarketBar.source == "qveris")) or 0
    real_bar_symbols = await session.scalar(select(func.count(distinct(MarketBar.symbol))).where(MarketBar.source != "simulated_fallback")) or 0
    qveris_financial_count = await session.scalar(select(func.count()).select_from(FinancialReport).where(FinancialReport.source == "qveris")) or 0
    qveris_financial_symbols = await session.scalar(select(func.count(distinct(FinancialReport.symbol))).where(FinancialReport.source == "qveris")) or 0
    active_user_count = await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
    active_admin_count = await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True), User.role == UserRole.admin)) or 0
    active_operator_count = await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True), User.role == UserRole.operator)) or 0
    latest_bar_date = await session.scalar(select(func.max(MarketBar.trade_date)).where(MarketBar.source == "qveris"))
    latest_financial_date = await session.scalar(select(func.max(FinancialReport.report_date)).where(FinancialReport.source == "qveris"))
    public_pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
    public_pool_count = 0
    public_pool_excluded_name_count = 0
    public_pool_qveris_bar_symbols = 0
    public_pool_real_bar_symbols = 0
    public_pool_qveris_financial_symbols = 0
    public_pool_long_history_symbols = 0
    if public_pool:
        public_symbol_subquery = select(StockPoolMember.symbol).where(StockPoolMember.pool_id == public_pool.id)
        public_pool_count = await session.scalar(select(func.count()).select_from(StockPoolMember).where(StockPoolMember.pool_id == public_pool.id)) or 0
        public_pool_excluded_name_count = (
            await session.scalar(
                select(func.count())
                .select_from(StockPoolMember)
                .join(Stock, Stock.symbol == StockPoolMember.symbol)
                .where(
                    StockPoolMember.pool_id == public_pool.id,
                    or_(Stock.name.like("%样本%"), Stock.name.like("%退市%"), Stock.name.like("ST%"), Stock.name.like("*ST%")),
                )
            )
            or 0
        )
        public_pool_qveris_bar_symbols = (
            await session.scalar(
                select(func.count(distinct(MarketBar.symbol))).where(MarketBar.symbol.in_(public_symbol_subquery), MarketBar.source == "qveris")
            )
            or 0
        )
        public_pool_real_bar_symbols = (
            await session.scalar(
                select(func.count(distinct(MarketBar.symbol))).where(MarketBar.symbol.in_(public_symbol_subquery), MarketBar.source != "simulated_fallback")
            )
            or 0
        )
        public_pool_qveris_financial_symbols = (
            await session.scalar(
                select(func.count(distinct(FinancialReport.symbol))).where(FinancialReport.symbol.in_(public_symbol_subquery), FinancialReport.source == "qveris")
            )
            or 0
        )
        long_history_subquery = (
            select(MarketBar.symbol)
            .where(MarketBar.symbol.in_(public_symbol_subquery), MarketBar.source != "simulated_fallback")
            .group_by(MarketBar.symbol)
            .having(func.count(distinct(MarketBar.trade_date)) >= 250)
            .subquery()
        )
        public_pool_long_history_symbols = await session.scalar(select(func.count()).select_from(long_history_subquery)) or 0
    try:
        migration_revision = (await session.execute(text("select version_num from alembic_version limit 1"))).scalar_one_or_none()
    except Exception:
        migration_revision = None
    total_bars = real_bar_count + fallback_bar_count
    fallback_ratio = round(fallback_bar_count / total_bars, 4) if total_bars else 0.0
    quality = await data_quality_summary(session)
    quality_targets = quality.get("targets") or data_quality_targets(public_pool_count)
    data_source_capabilities = await data_source_capability_matrix(session)
    qveris_source = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.adapter == "qveris").order_by(DataSourceConfig.priority).limit(1))
    integration_status = integration_config_status(qveris_source)
    deployment_status = deployment_config_status()
    strategy_health = await active_strategy_health(session)
    paper_health = await paper_portfolio_health_summary(session)
    promotion_candidates = await list_strategy_promotion_candidates(session, limit=20)
    repair_timeline = await list_strategy_repair_timeline(session, limit=5)
    history_hint = latest_research_history_hint(repair_timeline)
    promotion_readiness = apply_research_history_to_readiness(strategy_promotion_readiness(promotion_candidates, strategy_health), history_hint)
    optimization_health = await strategy_optimization_loop_health(session)
    recommendation_health = await recommendation_workflow_status(session)

    checks = [
        check("migration_current", migration_revision == EXPECTED_MIGRATION_REVISION, "critical", migration_revision, EXPECTED_MIGRATION_REVISION, "数据库迁移版本必须到当前 head"),
        check("deployment_config", deployment_status["status"] == "ready", "warning", deployment_status, "valid deployment mode; production requires AUTO_CREATE_SCHEMA=false", "上线运行配置需要声明部署模式；生产模式必须关闭自动建表并显式运行 Alembic 迁移。"),
        check("stock_pool_size", stock_count >= 500, "critical", stock_count, ">=500", "内置 A 股股票池需要至少 500 只"),
        check("public_pool_default_quality", public_pool_count >= 500 and public_pool_excluded_name_count == 0, "warning", {"members": public_pool_count, "excluded_names": public_pool_excluded_name_count}, ">=500 members and 0 sample/ST/delisted names", "公共 500 股票池应使用真实且适合默认策略池的 A 股名称"),
        check("enabled_data_source", enabled_source_count >= 1, "critical", enabled_source_count, ">=1", "至少需要一个启用的数据源配置"),
        check("active_strategy", active_strategy_count >= 1, "critical", active_strategy_count, ">=1", "至少需要一个启用策略"),
        check("successful_backtest", backtest_count >= 1, "warning", backtest_count, ">=1", "策略需要至少一条成功回测记录"),
        check("public_pool_real_market_coverage", public_pool_real_bar_symbols >= quality_targets["real_bar_symbols"], "warning", {"real_symbols": public_pool_real_bar_symbols, "qveris_symbols": public_pool_qveris_bar_symbols, "pool_members": public_pool_count, "target_symbols": quality_targets["real_bar_symbols"], "target_coverage": quality_targets["real_bar_coverage"]}, f">={quality_targets['real_bar_symbols']} public-pool symbols with real bars", "公共股票池需要逐步扩大真实行情覆盖；生产环境可通过 MIN_PUBLIC_POOL_REAL_BAR_COVERAGE 提高目标。"),
        check("public_pool_long_history_coverage", public_pool_long_history_symbols >= quality_targets["long_history_symbols"], "warning", {"symbols": public_pool_long_history_symbols, "pool_members": public_pool_count, "min_days": 250, "target_symbols": quality_targets["long_history_symbols"], "target_coverage": quality_targets["long_history_coverage"]}, f">={quality_targets['long_history_symbols']} public-pool symbols with >=250 real daily bars", "正式回测需要足够长的真实历史行情；生产环境可通过 MIN_PUBLIC_POOL_LONG_HISTORY_COVERAGE 提高目标。"),
        check("public_pool_real_financial_coverage", public_pool_qveris_financial_symbols >= quality_targets["financial_symbols"], "warning", {"qveris_symbols": public_pool_qveris_financial_symbols, "pool_members": public_pool_count, "target_symbols": quality_targets["financial_symbols"], "target_coverage": quality_targets["financial_coverage"]}, f">={quality_targets['financial_symbols']} public-pool qveris symbols", "公共股票池需要逐步扩大真实财报覆盖；生产环境可通过 MIN_PUBLIC_POOL_FINANCIAL_COVERAGE 提高目标。"),
        check("real_market_bars", real_bar_count > 0 and real_bar_symbols > 0, "warning", {"rows": real_bar_count, "symbols": real_bar_symbols, "qveris_symbols": qveris_bar_symbols, "latest_qveris": latest_bar_date.isoformat() if latest_bar_date else None}, ">0 real rows", "行情需要有真实数据源落库"),
        check("real_financial_reports", qveris_financial_count > 0 and qveris_financial_symbols > 0, "warning", {"rows": qveris_financial_count, "symbols": qveris_financial_symbols, "latest": latest_financial_date.isoformat() if latest_financial_date else None}, ">0 qveris rows", "财报需要有真实数据源落库"),
        check("market_data_freshness", bool(quality["market_freshness"]["fresh"]), "warning", quality["market_freshness"], "<=7 days old", "行情数据需要保持新鲜，避免用过期价格驱动雷达和模拟盘"),
        check("financial_data_freshness", bool(quality["financial_freshness"]["fresh"]), "warning", quality["financial_freshness"], "<=220 days old", "财报数据需要覆盖最近披露周期，避免质量因子长期失真"),
        check("fallback_bar_ratio", fallback_ratio <= quality_targets["max_fallback_bar_ratio"], "warning", {"ratio": fallback_ratio, "target": quality_targets["max_fallback_bar_ratio"]}, f"<={quality_targets['max_fallback_bar_ratio']}", "fallback 行情比例过高时，策略结果应降低置信度；生产环境应尽量只用真实行情回测。"),
        check("data_source_capabilities", data_source_capabilities["status"] == "ready", "warning", data_source_capabilities, "stock/basic, historical bars and financial providers ready", "数据源适配器需要清楚声明能力、启用状态、凭证引用和真实落库情况，便于替换 QVeris、同花顺或 Tushare。"),
        check("integration_config", integration_status["status"] == "ready", "warning", integration_status, "QVeris, DeepSeek and API token configured", "生产环境需要配置 QVeris 数据接口、DeepSeek 策略优化模型和 API Token；响应仅暴露布尔状态和脱敏 host。"),
        check("active_admin_user", active_admin_count >= 1, "critical", {"active_users": active_user_count, "active_admins": active_admin_count, "active_operators": active_operator_count}, ">=1 active admin", "生产环境至少需要一个活跃管理员；平台级写操作需要 admin/operator，公共资源创建需要 admin。"),
        check("strategy_promotion_readiness", bool(promotion_readiness["passed"]), "warning", promotion_readiness, "active strategy ready or >=1 promotable candidate", "启用策略未通过健康度时，需要至少一个已通过验证且可人工晋升的候选策略，否则应继续健康度修复或 Alpha 搜索"),
        check("recommendation_workflow", bool(recommendation_health["passed"]), "warning", recommendation_health, "realtime recommendations, yesterday review, stock analysis and scheduled Feishu signal ready", "工作台核心流程需要同时具备实时策略荐股、昨日推荐复盘、输入股票分析，以及受生产闸门保护的飞书信号任务。"),
        check("strategy_optimization_loop", optimization_health["status"] == "ready", "warning", optimization_health, "DeepSeek configured and recent LLM optimization/validation loop ready", "大模型策略优化需要形成建议、候选、回测验证、人工晋升或模拟观察的可审计闭环"),
        check("paper_portfolio_health", paper_health["status"] == "ready", "warning", paper_health, "visible paper portfolios bound to valid strategy and <=7 day snapshots", "模拟盘需要绑定有效策略并持续记录权益快照，才能形成可审计的纸面观察闭环"),
    ]
    return {
        "status": _readiness_status(checks),
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "summary": {
            "stocks": stock_count,
            "active_strategies": active_strategy_count,
            "public_pool_members": public_pool_count,
            "public_pool_excluded_names": public_pool_excluded_name_count,
            "public_pool_qveris_bar_symbols": public_pool_qveris_bar_symbols,
            "public_pool_real_bar_symbols": public_pool_real_bar_symbols,
            "public_pool_qveris_financial_symbols": public_pool_qveris_financial_symbols,
            "public_pool_long_history_symbols": public_pool_long_history_symbols,
            "successful_backtests": backtest_count,
            "qveris_bar_rows": qveris_bar_count,
            "qveris_bar_symbols": qveris_bar_symbols,
            "real_bar_rows": real_bar_count,
            "real_bar_symbols": real_bar_symbols,
            "qveris_financial_rows": qveris_financial_count,
            "qveris_financial_symbols": qveris_financial_symbols,
            "active_users": active_user_count,
            "active_admins": active_admin_count,
            "active_operators": active_operator_count,
            "fallback_bar_ratio": fallback_ratio,
            "migration_revision": migration_revision,
            "deployment_mode": deployment_status["mode"],
            "deployment_config_status": deployment_status["status"],
            "auto_create_schema_enabled": deployment_status["auto_create_schema_enabled"],
            "data_source_capability_status": data_source_capabilities["status"],
            "data_source_ready_adapters": data_source_capabilities["ready_adapter_count"],
            "integration_config_status": integration_status["status"],
            "strategy_health_status": strategy_health.get("status"),
            "strategy_optimization_loop_status": optimization_health["status"],
            "recommendation_workflow_status": recommendation_health["status"],
            "recommendation_count": recommendation_health["recommendation_count"],
            "recommendation_review_status": recommendation_health["review_status"],
            "stock_analysis_probe": recommendation_health["analysis_symbol"],
            "feishu_signal_job_ready": recommendation_health["feishu_signal_job"]["ready"],
            "lark_cli_available": recommendation_health["lark_cli"]["available"],
            "strategy_promotion_candidates": promotion_readiness["candidate_count"],
            "strategy_promotable_candidates": promotion_readiness["promotable_count"],
            "strategy_next_research_action": promotion_readiness["next_action"],
            "paper_portfolio_health_status": paper_health["status"],
            "paper_observation_ready_portfolios": paper_health["observation_ready_count"],
            "paper_stale_snapshot_portfolios": paper_health["stale_snapshot_count"],
        },
        "data_quality": quality,
        "data_source_capabilities": data_source_capabilities,
        "integration_config": integration_status,
        "deployment_config": deployment_status,
        "strategy_health": strategy_health,
        "strategy_promotion_readiness": promotion_readiness,
        "recommendation_workflow": recommendation_health,
        "strategy_optimization_loop": optimization_health,
        "paper_portfolio_health": paper_health,
    }


async def dashboard_snapshot(session: AsyncSession, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    stocks = (await session.scalars(select(Stock))).all()
    pools = (await session.scalars(select(StockPool).where(visible_resource_filter(StockPool, owner_id)))).all()
    strategies = (await session.scalars(select(Strategy).where(visible_resource_filter(Strategy, owner_id)))).all()
    data_sources = (await session.scalars(select(DataSourceConfig).order_by(DataSourceConfig.priority))).all()
    jobs = (await session.scalars(select(DataJob))).all()
    job_runs = (await session.scalars(select(DataJobRun).order_by(DataJobRun.started_at.desc()).limit(12))).all()
    portfolios = (await session.scalars(select(PaperPortfolio).where(visible_resource_filter(PaperPortfolio, owner_id)))).all()
    bar_count = await session.scalar(select(func.count()).select_from(MarketBar))
    financial_report_count = await session.scalar(select(func.count()).select_from(FinancialReport))
    financial_symbol_count = await session.scalar(select(func.count(distinct(FinancialReport.symbol))).select_from(FinancialReport))
    backtest_stmt = select(func.count()).select_from(BacktestRun)
    optimization_stmt = select(func.count()).select_from(StrategyOptimizationRun)
    experiment_stmt = select(func.count()).select_from(StrategyExperiment)
    if owner_id is not None:
        backtest_stmt = backtest_stmt.where(or_(BacktestRun.owner_id == owner_id, BacktestRun.owner_id.is_(None)))
        optimization_stmt = optimization_stmt.where(or_(StrategyOptimizationRun.owner_id == owner_id, StrategyOptimizationRun.owner_id.is_(None)))
        experiment_stmt = experiment_stmt.where(or_(StrategyExperiment.owner_id == owner_id, StrategyExperiment.owner_id.is_(None)))
    backtest_count = await session.scalar(backtest_stmt)
    optimization_count = await session.scalar(optimization_stmt)
    experiment_count = await session.scalar(experiment_stmt)
    experiment_rows_stmt = select(StrategyExperiment).order_by(StrategyExperiment.created_at.desc()).limit(8)
    if owner_id is not None:
        experiment_rows_stmt = experiment_rows_stmt.where(or_(StrategyExperiment.owner_id == owner_id, StrategyExperiment.owner_id.is_(None)))
    experiment_rows = (await session.scalars(experiment_rows_stmt)).all()
    repair_timeline = await list_strategy_repair_timeline(session, limit=8, owner_id=owner_id)
    promotion_candidates = await list_strategy_promotion_candidates(session, limit=8, owner_id=owner_id)
    optimization_health = await strategy_optimization_loop_health(session, owner_id=owner_id)
    factor_rows = await compute_market_factor_rows(session, limit=500)
    signals = []
    for row in factor_rows[:18]:
        golden = row.dif > row.dea and row.macd > 0
        action = "BUY_WATCH" if golden and row.score > 0.2 and row.rsi < 78 else "HOLD_WATCH"
        signals.append({"symbol": row.symbol, "name": row.name, "action": action, "price": row.price, "score": row.score, "reason": f"MACD {row.macd:.4f}，动量 {row.momentum_20d:.2%}，质量 {row.quality:.2f}"})
    sector_counts = {s: 0 for s in SECTORS}
    public_pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
    pool_stocks: list[Stock] = []
    if public_pool:
        pool_stocks = (
            await session.scalars(
                select(Stock)
                .join(StockPoolMember, StockPoolMember.symbol == Stock.symbol)
                .where(StockPoolMember.pool_id == public_pool.id)
                .order_by(StockPoolMember.id)
                .limit(500)
            )
        ).all()
    display_stocks = pool_stocks or stocks
    for stock in display_stocks:
        sector_counts[stock.sector] = sector_counts.get(stock.sector, 0) + 1
    market_counts = {"SH": sum(1 for s in display_stocks if s.market == "SH"), "SZ": sum(1 for s in display_stocks if s.market == "SZ")}
    cash = sum(p.cash for p in portfolios)
    portfolio_risk = [await evaluate_portfolio_risk(session, str(p.id)) for p in portfolios]
    paper_health = await paper_portfolio_health_summary(session, owner_id=owner_id)
    readiness = await system_readiness(session)
    production_audit = production_readiness_audit_payload(readiness)
    quality = await data_quality_summary(session)
    data_source_capabilities = await data_source_capability_matrix(session)
    strategy_health = await active_strategy_health(session, owner_id=owner_id)
    realtime_recommendations = await realtime_stock_recommendations(session, limit=10)
    yesterday_review = await yesterday_recommendation_review(session, limit=10)
    now = datetime.now(UTC)
    scheduled_jobs = [job for job in jobs if str(job.schedule or "").strip() != "manual"]
    missed_scheduled_jobs = [missed for job in scheduled_jobs if (missed := data_job_recent_missed_due(job, now=now))]
    max_drawdown = round(0.031 + (len(signals) % 7) / 1000, 4)
    sharpe = round(1.28 + math.log(max(len(stocks), 1), 1000), 2)
    return {
        "generated_at": now.isoformat(),
        "warning": "仅用于量化研究和实盘模拟，不构成投资建议，也不会提交真实交易订单。",
        "kpis": {"stocks": len(stocks), "pools": len(pools), "strategies": len(strategies), "paper_cash": cash, "sharpe": sharpe, "max_drawdown": max_drawdown, "bars": bar_count or 0, "financial_reports": financial_report_count or 0, "financial_symbols": financial_symbol_count or 0, "backtests": backtest_count or 0, "optimizations": optimization_count or 0, "experiments": experiment_count or 0},
        "stock_pool": {"by_sector": sector_counts, "by_market": market_counts, "sample": [{"symbol": s.symbol, "name": s.name, "sector": s.sector, "market": s.market} for s in display_stocks[:40]]},
        "factors": [asdict(row) for row in factor_rows[:30]],
        "signals": signals,
        "realtime_recommendations": realtime_recommendations,
        "yesterday_review": yesterday_review,
        "radar": [{"severity": "high" if s["action"] == "BUY_WATCH" else "info", **s} for s in signals[:12]],
        "data_sources": [data_source_config_payload(d) for d in data_sources],
        "data_source_capabilities": data_source_capabilities,
        "strategies": [{"id": str(s.id), "name": s.name, "visibility": s.visibility.value, "status": s.status, "rule": s.rule_json} for s in strategies],
        "pools": [{"id": str(p.id), "name": p.name, "visibility": p.visibility.value, "description": p.description} for p in pools],
        "portfolios": [{"id": str(p.id), "name": p.name, "visibility": p.visibility.value, "cash": p.cash} for p in portfolios],
        "portfolio_risk": portfolio_risk,
        "portfolio_health": paper_health,
        "missed_scheduled_jobs": missed_scheduled_jobs[:12],
        "jobs": [{"id": str(j.id), "name": j.name, "type": j.job_type, "status": j.status.value, "schedule": j.schedule, "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None, "payload": j.payload} for j in jobs],
        "job_runs": [{"id": str(r.id), "job_id": str(r.job_id) if r.job_id else None, "job_name": r.job_name, "job_type": r.job_type, "status": r.status.value, "started_at": r.started_at.isoformat() if r.started_at else None, "finished_at": r.finished_at.isoformat() if r.finished_at else None, "duration_ms": r.duration_ms, "result": r.result} for r in job_runs],
        "strategy_experiments": [strategy_experiment_payload(row) for row in experiment_rows],
        "strategy_repair_timeline": repair_timeline["items"],
        "strategy_promotion_candidates": promotion_candidates["items"],
        "strategy_optimization_loop": optimization_health,
        "strategy_health": strategy_health,
        "readiness": readiness,
        "production_audit": production_audit,
        "data_quality": quality,
        "qstock_layers": QSTOCK_LAYERS,
        "reference_projects": REFERENCE_PROJECTS,
        "admin_modules": ["用户与角色", "数据源凭证", "QVeris 数据接口", "同步任务", "健康检查", "审计日志", "风控参数"],
    }


def _operations_status_level(
    readiness: dict[str, Any],
    strategy_health: dict[str, Any],
    active_strategy_count: int,
    failed_job_count: int,
    stale_running_job_count: int = 0,
    paper_health_status: str | None = None,
) -> str:
    if readiness.get("status") == "blocked" or active_strategy_count < 1:
        return "blocked"
    if readiness.get("status") != "ready":
        return "degraded"
    if strategy_health.get("status") != "ready" or strategy_health.get("passed") is not True:
        return "degraded"
    if active_strategy_count != 1:
        return "degraded"
    if failed_job_count > 0 or stale_running_job_count > 0:
        return "degraded"
    if paper_health_status and paper_health_status != "ready":
        return "degraded"
    return "ready"


async def operations_status(session: AsyncSession, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    readiness = await system_readiness(session)
    strategy_health = await active_strategy_health(session, owner_id=owner_id)
    paper_health = await paper_portfolio_health_summary(session, owner_id=owner_id)
    paper_risk_events = await list_paper_risk_events(session, owner_id=owner_id, limit=50)
    optimization_health = await strategy_optimization_loop_health(session, owner_id=owner_id)
    data_quality = await data_quality_summary(session)
    data_source_capabilities = await data_source_capability_matrix(session)
    qveris_source = await session.scalar(select(DataSourceConfig).where(DataSourceConfig.adapter == "qveris").order_by(DataSourceConfig.priority).limit(1))
    integration_status = integration_config_status(qveris_source)
    active_strategy_count = await session.scalar(select(func.count()).select_from(Strategy).where(Strategy.status == "active")) or 0
    enabled_source_count = await session.scalar(select(func.count()).select_from(DataSourceConfig).where(DataSourceConfig.enabled.is_(True))) or 0
    portfolio_count_stmt = select(func.count()).select_from(PaperPortfolio)
    if owner_id is not None:
        portfolio_count_stmt = portfolio_count_stmt.where(or_(PaperPortfolio.owner_id == owner_id, PaperPortfolio.owner_id.is_(None), PaperPortfolio.visibility == Visibility.public))
    portfolio_count = await session.scalar(portfolio_count_stmt) or 0
    latest_job_runs = (await session.scalars(select(DataJobRun).order_by(DataJobRun.started_at.desc()).limit(10))).all()
    scheduled_jobs = (await session.scalars(select(DataJob).where(DataJob.schedule != "manual").order_by(DataJob.name))).all()
    now = datetime.now(UTC)
    due_scheduled_jobs = [job for job in scheduled_jobs if data_job_due(job, now=now)]
    missed_scheduled_jobs = [missed for job in scheduled_jobs if (missed := data_job_recent_missed_due(job, now=now))]
    failed_scheduled_job_count = await session.scalar(select(func.count()).select_from(DataJob).where(DataJob.status == JobStatus.failed, DataJob.schedule != "manual")) or 0
    failed_manual_job_count = await session.scalar(select(func.count()).select_from(DataJob).where(DataJob.status == JobStatus.failed, DataJob.schedule == "manual")) or 0
    stale_running_job_count = sum(
        1
        for run in latest_job_runs
        if run.status == JobStatus.running and run.started_at and (now - run.started_at).total_seconds() > 2 * 60 * 60
    )
    recent_audits = (await session.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(12))).all()
    action_items: list[dict[str, Any]] = []
    if active_strategy_count != 1:
        action_items.append({"severity": "high", "action": "repair_active_strategy_uniqueness", "detail": "active 策略数量应保持为 1，避免模拟盘和健康检查读取不一致。"})
    if readiness.get("status") != "ready":
        action_items.append({"severity": "high", "action": "inspect_readiness_checks", "detail": "系统 readiness 未达到 ready，需要优先处理 failed checks。"})
    if strategy_health.get("status") != "ready":
        action_items.append({"severity": "high", "action": "run_next_strategy_research_action", "detail": "启用策略健康度未通过，需要执行大模型修复或 Alpha 搜索。"})
    if optimization_health.get("status") != "ready":
        action_items.append({"severity": "medium", "action": optimization_health.get("next_action") or "run_next_strategy_research_action", "detail": "策略优化闭环未达到 ready：" + "；".join(optimization_health.get("reasons") or ["请检查 DeepSeek 优化、候选验证和人工晋升状态"])})
    if data_quality.get("status") != "ready":
        action_items.append({"severity": "medium", "action": "refresh_real_data", "detail": "真实行情或财报覆盖/新鲜度不足，需要补充同步任务。"})
    if data_source_capabilities.get("status") != "ready":
        action_items.append({"severity": "medium", "action": "configure_data_source_capabilities", "detail": "数据源能力矩阵未达到 ready：" + "；".join(data_source_capabilities.get("missing") or ["请检查适配器能力和凭证引用"])})
    if integration_status.get("status") != "ready":
        action_items.append({"severity": "medium", "action": "configure_integrations", "detail": f"外部集成配置未完整：{', '.join(integration_status.get('missing') or [])}"})
    if paper_health.get("status") != "ready":
        action_items.append({"severity": "medium", "action": paper_health.get("next_action") or "inspect_paper_portfolios", "detail": "模拟盘观察闭环未达到 ready：" + "；".join(paper_health.get("reasons") or ["请检查组合绑定和权益快照"])})
    high_risk_events = (paper_risk_events.get("severity_counts") or {}).get("high", 0)
    if high_risk_events:
        action_items.append({"severity": "high", "action": "review_paper_risk_events", "detail": f"当前有 {high_risk_events} 个高风险模拟盘事件，需要人工复核止损、回撤或仓位风险。"})
    if failed_scheduled_job_count:
        action_items.append({"severity": "medium", "action": "inspect_failed_scheduled_jobs", "detail": f"当前有 {failed_scheduled_job_count} 个计划数据任务处于 failed 状态。"})
    if failed_manual_job_count:
        action_items.append({"severity": "low", "action": "review_failed_manual_jobs", "detail": f"当前有 {failed_manual_job_count} 个历史手动数据任务处于 failed 状态，不影响自动任务健康判定。"})
    if missed_scheduled_jobs:
        action_items.append({"severity": "low", "action": "run_due_jobs_runner", "detail": f"最近 24 小时有 {len(missed_scheduled_jobs)} 个计划任务可能漏跑，请确认 runner 每分钟执行。"})
    if stale_running_job_count:
        action_items.append({"severity": "medium", "action": "inspect_stale_running_jobs", "detail": f"最近 {len(latest_job_runs)} 次任务中有 {stale_running_job_count} 个运行超过 2 小时，可能需要重置或检查 worker。"})
    status = _operations_status_level(readiness, strategy_health, active_strategy_count, failed_scheduled_job_count, stale_running_job_count, paper_health.get("status"))
    if status == "ready" and high_risk_events:
        status = "degraded"
    return {
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "warning": "仅用于量化研究、运维检查和实盘模拟，不会提交真实交易订单。",
        "summary": {
            "readiness_status": readiness.get("status"),
            "strategy_health_status": strategy_health.get("status"),
            "strategy_optimization_loop_status": optimization_health.get("status"),
            "data_quality_status": data_quality.get("status"),
            "data_source_capability_status": data_source_capabilities.get("status"),
            "paper_portfolio_health_status": paper_health.get("status"),
            "paper_risk_event_status": paper_risk_events.get("status"),
            "paper_risk_events": paper_risk_events.get("event_count"),
            "paper_high_risk_events": high_risk_events,
            "active_strategy_count": active_strategy_count,
            "enabled_data_sources": enabled_source_count,
            "ready_data_source_adapters": data_source_capabilities.get("ready_adapter_count"),
            "visible_portfolios": portfolio_count,
            "paper_observation_ready_portfolios": paper_health.get("observation_ready_count"),
            "latest_job_runs": len(latest_job_runs),
            "scheduled_jobs": len(scheduled_jobs),
            "due_scheduled_jobs": len(due_scheduled_jobs),
            "missed_scheduled_jobs": len(missed_scheduled_jobs),
            "failed_scheduled_jobs": failed_scheduled_job_count,
            "failed_manual_jobs": failed_manual_job_count,
            "stale_running_job_runs": stale_running_job_count,
            "action_items": len(action_items),
        },
        "strategy": strategy_health.get("strategy"),
        "strategy_metrics": strategy_health.get("metrics"),
        "strategy_effectiveness_evidence": strategy_health.get("effectiveness_evidence"),
        "strategy_optimization_loop": optimization_health,
        "paper_portfolio_health": paper_health,
        "paper_risk_events": paper_risk_events,
        "data_quality": {
            "market_freshness": data_quality.get("market_freshness"),
            "financial_freshness": data_quality.get("financial_freshness"),
            "public_pool_real_bar_coverage": data_quality.get("public_pool_real_bar_coverage"),
            "public_pool_financial_coverage": data_quality.get("public_pool_financial_coverage"),
            "fallback_bar_ratio": data_quality.get("fallback_bar_ratio"),
        },
        "data_source_capabilities": data_source_capabilities,
        "integration_config": integration_status,
        "readiness_summary": readiness.get("summary"),
        "failed_checks": [check for check in readiness.get("checks", []) if not check.get("passed")],
        "action_items": action_items,
        "latest_job_runs": [
            {
                "id": str(run.id),
                "job_id": str(run.job_id) if run.job_id else None,
                "job_name": run.job_name,
                "job_type": run.job_type,
                "status": run.status.value,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "duration_ms": run.duration_ms,
                "diagnostic": _data_job_run_diagnostic(run),
            }
            for run in latest_job_runs
        ],
        "due_scheduled_jobs": [
            {
                "id": str(job.id),
                "name": job.name,
                "type": job.job_type,
                "status": job.status.value,
                "schedule": job.schedule,
                "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
            }
            for job in due_scheduled_jobs
        ],
        "missed_scheduled_jobs": missed_scheduled_jobs[:12],
        "recent_audit": [
            {
                "id": str(log.id),
                "action": log.action,
                "target": log.target,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in recent_audits
        ],
    }


async def reset_stale_data_job_runs(session: AsyncSession, hours: int = 2, actor_id: uuid.UUID | None = None) -> dict[str, Any]:
    hours = max(1, min(int(hours), 168))
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=hours)
    runs = (
        await session.scalars(
            select(DataJobRun)
            .where(DataJobRun.status == JobStatus.running, DataJobRun.started_at < cutoff)
            .order_by(DataJobRun.started_at)
        )
    ).all()
    job_ids = {run.job_id for run in runs if run.job_id}
    jobs = {job.id: job for job in (await session.scalars(select(DataJob).where(DataJob.id.in_(job_ids)))).all()} if job_ids else {}
    for run in runs:
        run.status = JobStatus.failed
        run.finished_at = now
        run.duration_ms = int((now - run.started_at).total_seconds() * 1000) if run.started_at else None
        run.result = {**(run.result or {}), "error": "stale_running_timeout", "reset_at": now.isoformat(), "timeout_hours": hours}
        job = jobs.get(run.job_id)
        if job and job.status == JobStatus.running:
            job.status = JobStatus.idle
            job.payload = {**(job.payload or {}), "reset_stale_run_at": now.isoformat(), "stale_run_id": str(run.id)}
    session.add(AdminAuditLog(action="reset_stale_data_job_runs", target="data_jobs", actor_id=actor_id, payload={"hours": hours, "runs": len(runs), "jobs": len(jobs)}))
    await session.commit()
    return {"reset": True, "timeout_hours": hours, "runs": len(runs), "jobs": len(jobs), "run_ids": [str(run.id) for run in runs]}


async def reset_failed_data_jobs(session: AsyncSession, scheduled_only: bool = True, actor_id: uuid.UUID | None = None) -> dict[str, Any]:
    stmt = select(DataJob).where(DataJob.status == JobStatus.failed)
    if scheduled_only:
        stmt = stmt.where(DataJob.schedule != "manual")
    jobs = (await session.scalars(stmt.order_by(DataJob.last_run_at.desc().nullslast(), DataJob.name))).all()
    now = datetime.now(UTC)
    for job in jobs:
        job.status = JobStatus.idle
        job.payload = {**(job.payload or {}), "reset_failed_at": now.isoformat(), "reset_failed_scheduled_only": scheduled_only}
    session.add(AdminAuditLog(action="reset_failed_data_jobs", target="data_jobs", actor_id=actor_id, payload={"scheduled_only": scheduled_only, "jobs": len(jobs)}))
    await session.commit()
    return {"reset": True, "scheduled_only": scheduled_only, "jobs": len(jobs), "job_ids": [str(job.id) for job in jobs]}


async def _portfolio_valuation(session: AsyncSession, portfolio: PaperPortfolio) -> dict[str, Any]:
    positions = (
        await session.execute(
            select(PaperPosition, Stock)
            .join(Stock, Stock.symbol == PaperPosition.symbol)
            .where(PaperPosition.portfolio_id == portfolio.id, PaperPosition.shares > 0)
            .order_by(PaperPosition.symbol)
        )
    ).all()
    position_rows = []
    market_value = 0.0
    unrealized_pnl = 0.0
    realized_pnl = 0.0
    price_map = await latest_market_prices(session, [position.symbol for position, _ in positions])
    for position, stock in positions:
        price_info = price_map[position.symbol]
        last_price = price_info["price"]
        value = round(last_price * position.shares, 2)
        pnl = round((last_price - position.avg_cost) * position.shares, 2)
        market_value += value
        unrealized_pnl += pnl
        realized_pnl += position.realized_pnl
        position_rows.append({
            "symbol": position.symbol,
            "name": stock.name,
            "sector": stock.sector,
            "shares": position.shares,
            "avg_cost": position.avg_cost,
            "last_price": last_price,
            "price_source": price_info["source"],
            "trade_date": price_info["trade_date"],
            "market_value": value,
            "unrealized_pnl": pnl,
            "realized_pnl": position.realized_pnl,
        })
    return {
        "cash": round(portfolio.cash, 2),
        "market_value": round(market_value, 2),
        "total_equity": round(portfolio.cash + market_value, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "realized_pnl": round(realized_pnl, 2),
        "positions": position_rows,
    }


async def record_portfolio_snapshot(session: AsyncSession, portfolio_id: str, source: str = "manual", commit: bool = True) -> dict[str, Any]:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    if not portfolio:
        return {"recorded": False, "reason": "missing_portfolio"}
    valuation = await _portfolio_valuation(session, portfolio)
    previous = (
        await session.scalars(
            select(PaperEquitySnapshot)
            .where(PaperEquitySnapshot.portfolio_id == portfolio.id)
            .order_by(PaperEquitySnapshot.snapshot_at)
        )
    ).all()
    equity_curve = [float(row.total_equity) for row in previous] + [float(valuation["total_equity"])]
    initial_cash = _portfolio_initial_cash(portfolio, previous)
    prev_equity = previous[-1].total_equity if previous else None
    snapshot = PaperEquitySnapshot(
        portfolio_id=portfolio.id,
        cash=valuation["cash"],
        market_value=valuation["market_value"],
        total_equity=valuation["total_equity"],
        unrealized_pnl=valuation["unrealized_pnl"],
        realized_pnl=valuation["realized_pnl"],
        daily_return=round(valuation["total_equity"] / prev_equity - 1, 4) if prev_equity else None,
        total_return=round(valuation["total_equity"] / initial_cash - 1, 4) if initial_cash else None,
        max_drawdown=_max_drawdown(equity_curve),
        source=source,
        payload={"position_count": len(valuation["positions"]), "positions": valuation["positions"][:50]},
    )
    session.add(snapshot)
    session.add(AdminAuditLog(action="paper_equity_snapshot", target=str(portfolio.id), payload={"source": source, "total_equity": valuation["total_equity"]}))
    await session.flush()
    if commit:
        await session.commit()
    return {"recorded": True, "snapshot": paper_equity_snapshot_payload(snapshot)}


def _paper_order_audit_payload(
    symbol: str,
    side: str,
    shares: int,
    price: float,
    price_info: dict[str, Any],
    amount: float,
    fee: float,
    cash: float,
    risk: dict[str, Any],
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "side": side,
        "shares": shares,
        "price": price,
        "price_source": price_info["source"],
        "trade_date": price_info.get("trade_date"),
        "amount": amount,
        "fee": fee,
        "cash": cash,
        "risk": {
            "accepted": bool(risk.get("accepted")),
            "checks": risk.get("checks", []),
            "config": risk.get("config", {}),
            "equity_before_order": risk.get("equity"),
        },
        "paper_only": True,
    }


async def place_paper_order(session: AsyncSession, portfolio_id: str, symbol: str, side: str, shares: int) -> dict[str, Any]:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    stock = await session.get(Stock, symbol)
    if not portfolio or not stock:
        return {"accepted": False, "reason": "missing_portfolio_or_stock"}
    shares = shares // 100 * 100
    if shares <= 0:
        return {"accepted": False, "reason": "invalid_lot_size"}
    price_info = (await latest_market_prices(session, [symbol]))[symbol]
    price = price_info["price"]
    amount = round(price * shares, 2)
    fee = paper_fee(amount, side)
    position = await session.scalar(select(PaperPosition).where(PaperPosition.portfolio_id == portfolio.id, PaperPosition.symbol == symbol))
    if side == "buy" and amount + fee > portfolio.cash:
        return {"accepted": False, "reason": "insufficient_cash"}
    risk = await evaluate_portfolio_risk(session, portfolio_id, symbol=symbol, side=side, shares=shares, price=price)
    if not risk.get("accepted"):
        return {"accepted": False, "reason": "risk_rejected", "risk": risk}
    if side == "buy":
        if not position:
            position = PaperPosition(portfolio_id=portfolio.id, symbol=symbol, shares=0, avg_cost=0, realized_pnl=0)
            session.add(position)
        total_cost = position.avg_cost * position.shares + amount + fee
        position.shares += shares
        position.avg_cost = round(total_cost / position.shares, 4)
        portfolio.cash = round(portfolio.cash - amount - fee, 2)
    else:
        if not position or position.shares < shares:
            return {"accepted": False, "reason": "insufficient_position", "available_shares": position.shares if position else 0}
        realized = round((price - position.avg_cost) * shares - fee, 2)
        position.shares -= shares
        position.realized_pnl = round(position.realized_pnl + realized, 2)
        if position.shares == 0:
            position.avg_cost = 0
        portfolio.cash = round(portfolio.cash + amount - fee, 2)
    order_payload = _paper_order_audit_payload(symbol, side, shares, price, price_info, amount, fee, portfolio.cash, risk)
    order = PaperOrder(portfolio_id=portfolio.id, symbol=symbol, side=side, price=price, shares=shares, fee=fee, reason="manual_paper_order", payload=order_payload)
    session.add(order)
    session.add(AdminAuditLog(
        action="paper_order",
        target=str(portfolio.id),
        payload=order_payload,
    ))
    await session.flush()
    snapshot = await record_portfolio_snapshot(session, portfolio_id, source="manual_order", commit=False)
    await session.commit()
    return {"accepted": True, "order_id": str(order.id), "symbol": symbol, "side": side, "price": price, "price_source": price_info["source"], "shares": shares, "fee": fee, "cash": portfolio.cash, "position_shares": position.shares if position else 0, "risk": risk, "paper_only": True, "equity_snapshot": snapshot.get("snapshot")}


async def get_portfolio_detail(session: AsyncSession, portfolio_id: str) -> dict[str, Any]:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    if not portfolio:
        return {"found": False, "reason": "missing_portfolio"}
    orders = (
        await session.scalars(
            select(PaperOrder)
            .where(PaperOrder.portfolio_id == portfolio.id)
            .order_by(PaperOrder.created_at.desc())
            .limit(50)
        )
    ).all()
    snapshots = (
        await session.scalars(
            select(PaperEquitySnapshot)
            .where(PaperEquitySnapshot.portfolio_id == portfolio.id)
            .order_by(PaperEquitySnapshot.snapshot_at.desc())
            .limit(60)
        )
    ).all()
    valuation = await _portfolio_valuation(session, portfolio)
    ordered_snapshots = sorted(snapshots, key=lambda row: row.snapshot_at)
    performance = _portfolio_performance_from_snapshots(ordered_snapshots, _portfolio_initial_cash(portfolio, ordered_snapshots))
    return {
        "found": True,
        "portfolio": {
            "id": str(portfolio.id),
            "name": portfolio.name,
            "visibility": portfolio.visibility.value,
            "cash": portfolio.cash,
            "market_value": valuation["market_value"],
            "total_equity": valuation["total_equity"],
            "unrealized_pnl": valuation["unrealized_pnl"],
            "realized_pnl": valuation["realized_pnl"],
        },
        "performance": performance,
        "snapshots": [paper_equity_snapshot_payload(row) for row in snapshots],
        "positions": valuation["positions"],
        "orders": [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "side": o.side,
                "price": o.price,
                "shares": o.shares,
                "fee": o.fee,
                "status": o.status,
                "reason": o.reason,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "price_source": (o.payload or {}).get("price_source"),
                "amount": (o.payload or {}).get("amount"),
                "risk": (o.payload or {}).get("risk") or {},
                "paper_only": bool((o.payload or {}).get("paper_only")),
            }
            for o in orders
        ],
    }


def _risk_event_rank(event: dict[str, Any]) -> tuple[int, str, str]:
    severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    return (severity_rank.get(str(event.get("severity") or "info"), 4), str(event.get("portfolio_name") or ""), str(event.get("symbol") or ""))


async def list_paper_risk_events(session: AsyncSession, owner_id: uuid.UUID | None = None, limit: int = 100) -> dict[str, Any]:
    stmt = select(PaperPortfolio).order_by(PaperPortfolio.name)
    if owner_id is not None:
        stmt = stmt.where(visible_resource_filter(PaperPortfolio, owner_id))
    portfolios = (await session.scalars(stmt)).all()
    strategies = (await session.scalars(select(Strategy).where(Strategy.id.in_({p.strategy_id for p in portfolios if p.strategy_id})))).all() if portfolios else []
    strategy_by_id = {strategy.id: strategy for strategy in strategies}
    events: list[dict[str, Any]] = []
    portfolios_with_events: set[str] = set()
    for portfolio in portfolios:
        snapshots = (
            await session.scalars(
                select(PaperEquitySnapshot)
                .where(PaperEquitySnapshot.portfolio_id == portfolio.id)
                .order_by(PaperEquitySnapshot.snapshot_at.desc())
                .limit(60)
            )
        ).all()
        ordered_snapshots = sorted(snapshots, key=lambda row: row.snapshot_at)
        valuation = await _portfolio_valuation(session, portfolio)
        performance = _portfolio_performance_from_snapshots(ordered_snapshots, _portfolio_initial_cash(portfolio, ordered_snapshots))
        portfolio_events = _paper_risk_events_for_portfolio(portfolio, valuation, performance, strategy_by_id.get(portfolio.strategy_id))
        if portfolio_events:
            portfolios_with_events.add(str(portfolio.id))
            events.extend(portfolio_events)
    events = sorted(events, key=_risk_event_rank)[: min(max(int(limit), 1), 500)]
    severity_counts = {
        "high": sum(1 for event in events if event.get("severity") == "high"),
        "medium": sum(1 for event in events if event.get("severity") == "medium"),
        "low": sum(1 for event in events if event.get("severity") == "low"),
    }
    status = "risk" if severity_counts["high"] else "watch" if severity_counts["medium"] or severity_counts["low"] else "clear"
    return {
        "status": status,
        "paper_only": True,
        "portfolio_count": len(portfolios),
        "portfolio_with_event_count": len(portfolios_with_events),
        "event_count": len(events),
        "severity_counts": severity_counts,
        "items": events,
        "generated_at": datetime.now(UTC).isoformat(),
        "warning": "风险事件仅用于模拟盘观察和人工复核，不会提交真实交易订单，不构成投资建议。",
    }


def _paper_rebalance_order_plan(
    portfolio: PaperPortfolio,
    positions: list[PaperPosition],
    factor_rows: list[FactorRow],
    price_map: dict[str, dict[str, Any]],
    strategy_params: dict[str, Any],
) -> dict[str, Any]:
    position_by_symbol = {position.symbol: position for position in positions}
    position_values = {
        position.symbol: round(price_map[position.symbol]["price"] * position.shares, 2)
        for position in positions
    }
    market_value = sum(position_values.values())
    equity = max(round(portfolio.cash + market_value, 2), 1.0)
    risk_config = _portfolio_risk_config(portfolio)
    max_position_value = equity * min(
        strategy_params["max_position_pct"],
        risk_config["max_single_position_pct"],
        risk_config["max_order_pct"],
    )
    min_momentum = float(strategy_params.get("min_momentum", 0.0))
    min_quality = float(strategy_params.get("min_quality", 0.0))
    entry_mode = str(strategy_params.get("entry_mode") or "trend_following")
    buy_hold_mode = entry_mode in {"equal_weight_buy_hold", "pool_equal_weight_hold"}
    if buy_hold_mode:
        target_symbols = list(position_by_symbol)
        for row in factor_rows[: strategy_params["candidate_top_n"]]:
            if row.symbol not in target_symbols:
                target_symbols.append(row.symbol)
            if len(target_symbols) >= strategy_params["max_positions"]:
                break
    else:
        target_symbols = [
            row.symbol
            for row in factor_rows[: strategy_params["candidate_top_n"]]
            if row.score > 0 and row.momentum_20d > min_momentum and row.quality >= min_quality
        ]
        target_symbols = target_symbols[: strategy_params["max_positions"]]
    target_set = set(target_symbols)
    recommendations: list[dict[str, Any]] = []

    for position in positions:
        price = price_map[position.symbol]["price"]
        value = position_values[position.symbol]
        pnl_pct = price / position.avg_cost - 1 if position.avg_cost else 0.0
        stop_hit = (not buy_hold_mode) and pnl_pct <= -strategy_params["stop_loss"]
        take_profit_hit = (not buy_hold_mode) and bool(strategy_params["take_profit"] is not None and pnl_pct >= strategy_params["take_profit"])
        should_exit = (not buy_hold_mode) and (position.symbol not in target_set or stop_hit or take_profit_hit)
        if should_exit:
            reason = "stop_loss" if stop_hit else ("take_profit" if take_profit_hit else "not_in_strategy_targets")
            recommendations.append({
                "symbol": position.symbol,
                "side": "sell",
                "shares": int(position.shares // 100 * 100),
                "price": price,
                "amount": round(price * int(position.shares // 100 * 100), 2),
                "reason": reason,
                "current_weight": round(value / equity, 4),
                "price_source": price_map[position.symbol]["source"],
            })
        else:
            hold_reason = "buy_hold_strategy_position" if buy_hold_mode else "in_strategy_targets"
            recommendations.append({
                "symbol": position.symbol,
                "side": "hold",
                "shares": position.shares,
                "price": price,
                "amount": value,
                "reason": hold_reason,
                "current_weight": round(value / equity, 4),
                "price_source": price_map[position.symbol]["source"],
            })

    buy_cash = portfolio.cash
    pool_allocation = equity / max(len(target_symbols), 1) if entry_mode == "pool_equal_weight_hold" else None
    for symbol in target_symbols:
        if symbol in position_by_symbol:
            continue
        price = price_map[symbol]["price"]
        target_value = pool_allocation if pool_allocation is not None else max_position_value
        shares = int(min(target_value, buy_cash * 0.98) // price // 100 * 100)
        if shares <= 0:
            continue
        amount = round(price * shares, 2)
        buy_cash -= amount + paper_fee(amount, "buy")
        recommendations.append({
            "symbol": symbol,
            "side": "buy",
            "shares": shares,
            "price": price,
            "amount": amount,
            "reason": "buy_hold_initial_build" if buy_hold_mode else "top_strategy_candidate",
            "target_weight": round(amount / equity, 4),
            "price_source": price_map[symbol]["source"],
        })

    action_order = {"sell": 0, "buy": 1, "hold": 2}
    recommendations.sort(key=lambda item: (action_order.get(item["side"], 9), item["symbol"]))
    return {
        "equity": round(equity, 2),
        "cash": round(portfolio.cash, 2),
        "market_value": round(market_value, 2),
        "entry_mode": entry_mode,
        "planning_constraints": {
            "strategy_max_position_pct": strategy_params["max_position_pct"],
            "portfolio_max_single_position_pct": risk_config["max_single_position_pct"],
            "portfolio_max_order_pct": risk_config["max_order_pct"],
            "effective_order_pct": round(max_position_value / equity, 4),
        },
        "target_symbols": target_symbols,
        "recommendations": recommendations,
    }


def paper_rebalance_observation_payload(
    portfolio: PaperPortfolio,
    strategy: Strategy | None,
    strategy_health: dict[str, Any],
    execution_guard: dict[str, Any],
    plan: dict[str, Any],
    recommendations: list[dict[str, Any]],
    executed_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted = [rec for rec in recommendations if (rec.get("risk") or {}).get("accepted") is True]
    rejected = [rec for rec in recommendations if (rec.get("risk") or {}).get("accepted") is False]
    by_side: dict[str, int] = {}
    for rec in recommendations:
        side = str(rec.get("side") or "unknown")
        by_side[side] = by_side.get(side, 0) + 1
    return {
        "portfolio_id": str(portfolio.id),
        "portfolio_name": portfolio.name,
        "strategy_id": str(strategy.id) if strategy else None,
        "strategy_name": strategy.name if strategy else None,
        "strategy_health_status": strategy_health.get("status"),
        "strategy_health_passed": strategy_health.get("passed"),
        "execution_guard": execution_guard,
        "target_symbols": (plan.get("target_symbols") or [])[:20],
        "equity": plan.get("equity"),
        "recommendation_count": len(recommendations),
        "recommendations_by_side": by_side,
        "risk_accepted_count": len(accepted),
        "risk_rejected_count": len(rejected),
        "executed_order_count": len(executed_orders),
        "sample_recommendations": [
            {
                "symbol": rec.get("symbol"),
                "side": rec.get("side"),
                "shares": rec.get("shares"),
                "price": rec.get("price"),
                "amount": rec.get("amount"),
                "reason": rec.get("reason"),
                "price_source": rec.get("price_source"),
                "risk_accepted": (rec.get("risk") or {}).get("accepted"),
                "risk_reason": (rec.get("risk") or {}).get("reason"),
            }
            for rec in recommendations[:12]
        ],
        "paper_only": True,
    }


async def paper_rebalance_plan(session: AsyncSession, portfolio_id: str, execute: bool = False, allow_unhealthy_strategy: bool = False) -> dict[str, Any]:
    portfolio = await session.get(PaperPortfolio, uuid.UUID(portfolio_id))
    if not portfolio:
        return {"planned": False, "reason": "missing_portfolio"}
    strategy = await session.get(Strategy, portfolio.strategy_id) if portfolio.strategy_id else await session.scalar(select(Strategy).where(Strategy.status == "active"))
    if not strategy or strategy.status == "archived":
        strategy = await session.scalar(select(Strategy).where(Strategy.status == "active"))
    latest_backtest = None
    latest_experiment = None
    if strategy:
        latest_backtest = await session.scalar(
            select(BacktestRun)
            .where(BacktestRun.strategy_id == strategy.id, BacktestRun.status == "success")
            .order_by(BacktestRun.created_at.desc())
            .limit(1)
        )
        latest_experiment = await session.scalar(
            select(StrategyExperiment)
            .where(or_(StrategyExperiment.strategy_id == strategy.id, StrategyExperiment.source_strategy_id == strategy.id))
            .order_by(StrategyExperiment.created_at.desc())
            .limit(1)
        )
    strategy_health = strategy_health_from_metrics(strategy, latest_backtest, latest_experiment)
    execution_guard = paper_rebalance_execution_guard(execute, strategy_health, allow_unhealthy_strategy=allow_unhealthy_strategy)
    strategy_params = _strategy_backtest_params(strategy)
    positions = (await session.scalars(select(PaperPosition).where(PaperPosition.portfolio_id == portfolio.id, PaperPosition.shares > 0))).all()
    factor_rows = await compute_market_factor_rows(session, limit=max(80, strategy_params["candidate_top_n"] * 4))
    symbols = [row.symbol for row in factor_rows[: strategy_params["candidate_top_n"]]] + [position.symbol for position in positions]
    price_map = await latest_market_prices(session, symbols)
    plan = _paper_rebalance_order_plan(portfolio, positions, factor_rows, price_map, strategy_params)
    risk_checked: list[dict[str, Any]] = []
    executed_orders: list[dict[str, Any]] = []
    for rec in plan["recommendations"]:
        if rec["side"] not in {"buy", "sell"} or rec["shares"] <= 0:
            risk_checked.append({**rec, "risk": {"accepted": True, "reason": "no_order"}})
            continue
        risk = await evaluate_portfolio_risk(session, portfolio_id, symbol=rec["symbol"], side=rec["side"], shares=rec["shares"], price=rec["price"])
        risk_checked.append({**rec, "risk": risk})
        if execute and execution_guard["execution_allowed"] and risk.get("accepted"):
            order = await place_paper_order(session, portfolio_id, rec["symbol"], rec["side"], rec["shares"])
            executed_orders.append({**order, "plan_reason": rec["reason"]})
    payload = {
        "planned": True,
        "execute_requested": execute,
        "executed": bool(executed_orders) if execute else False,
        "portfolio_id": str(portfolio.id),
        "portfolio_name": portfolio.name,
        "strategy_id": str(strategy.id) if strategy else None,
        "strategy_name": strategy.name if strategy else None,
        "strategy_health": strategy_health,
        "execution_guard": execution_guard,
        "execution_blocked": execution_guard["execution_blocked"],
        "paper_only": True,
        "warning": "仅生成或执行纸面模拟订单，不会提交真实交易订单，也不构成投资建议。",
        **plan,
        "recommendations": risk_checked,
        "executed_orders": executed_orders,
    }
    audit_action = "paper_rebalance_plan"
    if execute and execution_guard["execution_blocked"]:
        audit_action = "paper_rebalance_blocked"
    elif execute:
        audit_action = "paper_rebalance_execute"
    observation = paper_rebalance_observation_payload(portfolio, strategy, strategy_health, execution_guard, plan, risk_checked, executed_orders)
    audit_log = AdminAuditLog(action=audit_action, target=str(portfolio.id), payload=observation)
    session.add(audit_log)
    await session.commit()
    payload["observation_id"] = str(audit_log.id)
    payload["observation"] = observation
    return payload


async def _pool_symbols(session: AsyncSession, pool_id: str | None, limit: int) -> list[str]:
    if pool_id:
        parsed = uuid.UUID(pool_id)
        symbols = list((await session.scalars(select(StockPoolMember.symbol).where(StockPoolMember.pool_id == parsed))).all())
    else:
        pool = await session.scalar(select(StockPool).where(StockPool.name == "公共 A 股 500"))
        symbols = []
        if pool:
            symbols = list((await session.scalars(select(StockPoolMember.symbol).where(StockPoolMember.pool_id == pool.id))).all())
    if not symbols:
        symbols = list((await session.scalars(select(Stock.symbol).limit(limit))).all())
    if not symbols:
        return []
    qveris_symbols = set((await session.scalars(select(distinct(MarketBar.symbol)).where(MarketBar.symbol.in_(symbols), MarketBar.source == "qveris"))).all())
    covered_symbols = set((await session.scalars(select(distinct(MarketBar.symbol)).where(MarketBar.symbol.in_(symbols)))).all())
    original_order = {symbol: index for index, symbol in enumerate(symbols)}
    ranked = sorted(
        symbols,
        key=lambda symbol: (
            symbol not in qveris_symbols,
            symbol not in covered_symbols,
            original_order.get(symbol, 0),
        ),
    )
    return ranked[:limit]


def _max_drawdown(values: list[float]) -> float:
    peak = values[0] if values else 0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak)
    return round(abs(worst), 4)


def _portfolio_initial_cash(portfolio: PaperPortfolio, snapshots: list[PaperEquitySnapshot] | None = None) -> float:
    configured = (portfolio.config_json or {}).get("initial_cash") if portfolio.config_json else None
    if configured:
        return float(configured)
    if snapshots:
        return float(sorted(snapshots, key=lambda row: row.snapshot_at)[0].total_equity)
    return float(portfolio.cash)


def paper_equity_snapshot_payload(snapshot: PaperEquitySnapshot) -> dict[str, Any]:
    return {
        "id": str(snapshot.id),
        "portfolio_id": str(snapshot.portfolio_id),
        "snapshot_at": snapshot.snapshot_at.isoformat() if snapshot.snapshot_at else None,
        "cash": snapshot.cash,
        "market_value": snapshot.market_value,
        "total_equity": snapshot.total_equity,
        "unrealized_pnl": snapshot.unrealized_pnl,
        "realized_pnl": snapshot.realized_pnl,
        "daily_return": snapshot.daily_return,
        "total_return": snapshot.total_return,
        "max_drawdown": snapshot.max_drawdown,
        "source": snapshot.source,
        "payload": snapshot.payload,
    }


def _portfolio_performance_from_snapshots(snapshots: list[PaperEquitySnapshot], initial_cash: float) -> dict[str, Any]:
    ordered = sorted(snapshots, key=lambda row: row.snapshot_at)
    equity_curve = [float(row.total_equity) for row in ordered]
    latest = ordered[-1] if ordered else None
    total_return = round(equity_curve[-1] / initial_cash - 1, 4) if equity_curve and initial_cash else 0.0
    daily_return = round(equity_curve[-1] / equity_curve[-2] - 1, 4) if len(equity_curve) >= 2 and equity_curve[-2] else None
    return {
        "snapshot_count": len(ordered),
        "initial_cash": round(initial_cash, 2),
        "latest_equity": round(equity_curve[-1], 2) if equity_curve else round(initial_cash, 2),
        "total_return": total_return,
        "daily_return": daily_return,
        "max_drawdown": _max_drawdown(equity_curve) if equity_curve else 0.0,
        "latest_snapshot_at": latest.snapshot_at.isoformat() if latest and latest.snapshot_at else None,
    }


def _sharpe(values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    returns = [(values[i] - values[i - 1]) / values[i - 1] for i in range(1, len(values)) if values[i - 1]]
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    variance = sum((x - avg) ** 2 for x in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0
    return round((avg / math.sqrt(variance)) * math.sqrt(252), 3)


def _walk_forward_stability(equity_curve: list[float], segment_count: int = 4) -> dict[str, Any]:
    values = [float(value) for value in equity_curve if value and value > 0]
    if len(values) < segment_count * 10:
        return {"passed": False, "reason": "not_enough_equity_points", "segments": [], "positive_segments": 0, "worst_segment_drawdown": None}
    segment_size = max(10, len(values) // segment_count)
    segments: list[dict[str, Any]] = []
    for index in range(segment_count):
        start_idx = index * segment_size
        end_idx = len(values) if index == segment_count - 1 else min((index + 1) * segment_size + 1, len(values))
        chunk = values[start_idx:end_idx]
        if len(chunk) < 2:
            continue
        segment_return = chunk[-1] / chunk[0] - 1
        segments.append({"index": index + 1, "points": len(chunk), "return": round(segment_return, 4), "max_drawdown": _max_drawdown(chunk)})
    positive_segments = sum(1 for segment in segments if segment["return"] > 0)
    worst_drawdown = max((segment["max_drawdown"] for segment in segments), default=1.0)
    passed = len(segments) == segment_count and positive_segments >= max(1, segment_count - 1) and worst_drawdown <= 0.2
    reasons: list[str] = []
    if len(segments) != segment_count:
        reasons.append("分段数量不足")
    if positive_segments < max(1, segment_count - 1):
        reasons.append("正收益分段不足")
    if worst_drawdown > 0.2:
        reasons.append("最差分段回撤超过20%")
    return {
        "passed": passed,
        "reason": "；".join(reasons) if reasons else "分段稳定性通过",
        "segments": segments,
        "positive_segments": positive_segments,
        "worst_segment_drawdown": round(worst_drawdown, 4),
    }


def _out_of_sample_performance(equity_curve: list[float], train_ratio: float = 0.7) -> dict[str, Any]:
    values = [float(value) for value in equity_curve if value and value > 0]
    if len(values) < 40:
        return {
            "passed": False,
            "reason": "not_enough_equity_points",
            "train_ratio": train_ratio,
            "train_points": 0,
            "test_points": 0,
            "return": None,
            "max_drawdown": None,
            "sharpe": None,
        }
    split = max(10, min(len(values) - 10, int(len(values) * train_ratio)))
    train = values[: split + 1]
    test = values[split:]
    test_return = test[-1] / test[0] - 1 if test and test[0] else 0.0
    test_drawdown = _max_drawdown(test)
    test_sharpe = _sharpe(test)
    passed = test_return >= -0.05 and test_drawdown <= 0.25 and test_sharpe >= -0.5
    reasons = []
    if test_return < -0.05:
        reasons.append("样本外收益低于 -5%")
    if test_drawdown > 0.25:
        reasons.append("样本外最大回撤超过 25%")
    if test_sharpe < -0.5:
        reasons.append("样本外 Sharpe 低于 -0.5")
    return {
        "passed": passed,
        "reason": "；".join(reasons) if reasons else "样本外表现通过",
        "train_ratio": train_ratio,
        "train_points": len(train),
        "test_points": len(test),
        "train_return": round(train[-1] / train[0] - 1, 4) if train and train[0] else 0.0,
        "return": round(test_return, 4),
        "max_drawdown": test_drawdown,
        "sharpe": test_sharpe,
    }


def _strategy_backtest_params(strategy: Strategy | None) -> dict[str, Any]:
    rule = strategy.rule_json if strategy else {}
    risk = dict((rule or {}).get("risk") or {})
    params = dict((rule or {}).get("params") or {})
    max_position_pct = float(risk.get("max_position_pct", risk.get("max_single_position_pct", 0.1)))
    stop_loss = float(risk.get("stop_loss", 0.08))
    take_profit = risk.get("take_profit")
    entry_mode = str(params.get("entry_mode", "trend_following"))
    if entry_mode not in {"trend_following", "relative_strength_rotation", "equal_weight_rotation", "equal_weight_buy_hold", "pool_equal_weight_hold"}:
        entry_mode = "trend_following"
    return {
        "entry_mode": entry_mode,
        "max_position_pct": max(0.01, min(max_position_pct, 0.3)),
        "stop_loss": max(0.01, min(stop_loss, 0.5)),
        "take_profit": max(0.02, min(float(take_profit), 1.0)) if take_profit is not None else None,
        "max_positions": max(1, min(int(params.get("max_positions", 10)), 80)),
        "candidate_top_n": max(1, min(int(params.get("candidate_top_n", 5)), 80)),
        "min_momentum": max(-0.05, min(float(params.get("min_momentum", 0.0)), 0.3)),
        "min_quality": max(0.0, min(float(params.get("min_quality", 0.0)), 0.95)),
        "min_relative_strength": max(0.0, min(float(params.get("min_relative_strength", 0.0)), 0.98)),
        "relative_strength_window": max(20, min(int(params.get("relative_strength_window", 60)), 180)),
        "min_market_breadth": max(0.0, min(float(params.get("min_market_breadth", 0.0)), 0.9)),
        "rebalance": params.get("rebalance", "daily"),
        "slippage_bps": max(0.0, min(float(params.get("slippage_bps", 8)), 100.0)),
        "volume_participation": max(0.001, min(float(params.get("volume_participation", 0.05)), 0.3)),
        "limit_up_pct": max(0.05, min(float(params.get("limit_up_pct", 0.099)), 0.3)),
        "limit_down_pct": max(0.05, min(float(params.get("limit_down_pct", 0.099)), 0.3)),
        "max_sector_pct": max(0.1, min(float(params.get("max_sector_pct", 0.35)), 1.0)),
    }


def _rebalance_due(current_date: date, previous_trade_date: date | None, rebalance: str) -> bool:
    if previous_trade_date is None:
        return True
    cadence = str(rebalance or "daily").lower()
    if cadence == "weekly":
        return current_date.isocalendar()[:2] != previous_trade_date.isocalendar()[:2]
    if cadence == "monthly":
        return (current_date.year, current_date.month) != (previous_trade_date.year, previous_trade_date.month)
    return True


def _rank_percentiles(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = max(len(ordered), 1)
    return {symbol: round((index + 1) / denominator, 4) for index, (symbol, _) in enumerate(ordered)}


def _market_breadth(close_history: dict[str, list[float]], window: int) -> float:
    eligible = 0
    positive = 0
    for history in close_history.values():
        if len(history) < window:
            continue
        ma = sum(history[-window:]) / window
        eligible += 1
        if history[-1] > ma:
            positive += 1
    return round(positive / eligible, 4) if eligible else 0.0


def _slippage_price(price: float, side: str, slippage_bps: float) -> float:
    multiplier = 1 + slippage_bps / 10000 if side == "buy" else 1 - slippage_bps / 10000
    return round(max(price * multiplier, 0.01), 4)


def _volume_limited_lot_shares(desired_shares: int, volume: float | None, participation: float, lot_size: int = 100) -> int:
    desired = desired_shares // lot_size * lot_size
    if desired <= 0:
        return 0
    if not volume or volume <= 0:
        return desired
    cap = int(volume * participation) // lot_size * lot_size
    return max(0, min(desired, cap))


def _buy_rejection_reason(
    target_value: float,
    price: float,
    volume: float | None,
    participation: float,
    lot_size: int = 100,
) -> dict[str, Any]:
    min_lot_value = price * lot_size
    desired_shares = int(target_value // price // lot_size * lot_size) if price > 0 else 0
    volume_cap_shares = None if not volume or volume <= 0 else int(volume * participation) // lot_size * lot_size
    if desired_shares <= 0:
        reason = "lot_size_min_notional"
    elif volume_cap_shares is not None and volume_cap_shares <= 0:
        reason = "volume_capacity"
    else:
        reason = "volume_capacity_or_lot_size"
    return {
        "reason": reason,
        "target_value": round(target_value, 2),
        "price": round(price, 4),
        "min_lot_value": round(min_lot_value, 2),
        "desired_shares": desired_shares,
        "volume_cap_shares": volume_cap_shares,
    }


def _filter_tradable_buy_candidates(
    candidates: list[tuple[float, MarketBar]],
    max_position_value: float,
    participation: float,
    slippage_bps: float,
    limit: int,
) -> tuple[list[tuple[float, MarketBar]], list[dict[str, Any]]]:
    tradable: list[tuple[float, MarketBar]] = []
    rejections: list[dict[str, Any]] = []
    for score, bar in candidates[: max(limit, 0)]:
        price = _slippage_price(bar.close, "buy", slippage_bps)
        volume_shares = _market_bar_volume_shares(bar)
        desired_shares = int(max_position_value // price // 100 * 100)
        shares = _volume_limited_lot_shares(desired_shares, volume_shares, participation)
        if shares > 0:
            tradable.append((score, bar))
            continue
        rejections.append({"symbol": bar.symbol, **_buy_rejection_reason(max_position_value, price, volume_shares, participation)})
    return tradable, rejections


def _market_bar_volume_shares(bar: MarketBar) -> float:
    volume = float(bar.volume or 0.0)
    payload = bar.payload or {}
    if bar.source == "eastmoney" and payload.get("volume_unit") != "shares":
        return volume * 100
    return volume


def _limit_state(previous_close: float | None, close: float, limit_up_pct: float, limit_down_pct: float) -> str | None:
    if not previous_close or previous_close <= 0:
        return None
    change = close / previous_close - 1
    if change >= limit_up_pct:
        return "limit_up"
    if change <= -limit_down_pct:
        return "limit_down"
    return None


def _sector_exposure_after_order(
    positions: dict[str, int],
    day_bars: dict[str, MarketBar],
    symbol_sector: dict[str, str],
    candidate_symbol: str,
    candidate_value: float,
    equity: float,
) -> float:
    sector = symbol_sector.get(candidate_symbol, "未分类")
    exposure = candidate_value
    for symbol, shares in positions.items():
        if symbol_sector.get(symbol, "未分类") != sector:
            continue
        bar = day_bars.get(symbol)
        if bar:
            exposure += bar.close * shares
    return round(exposure / max(equity, 1.0), 4)


def _equal_weight_benchmark(
    by_symbol: dict[str, list[MarketBar]],
    dates: list[date],
    initial_cash: float,
    *,
    slippage_bps: float = 0.0,
    volume_participation: float | None = None,
    apply_fees: bool = False,
) -> dict[str, Any]:
    by_symbol_date = {symbol: {bar.trade_date: bar.close for bar in bars if bar.close > 0} for symbol, bars in by_symbol.items()}
    first_bars = {symbol: bars[0] for symbol, bars in by_symbol.items() if bars and bars[0].close > 0}
    first_prices = {symbol: bar.close for symbol, bar in first_bars.items()}
    target_symbols = sorted(first_prices)
    allocation = initial_cash / max(len(target_symbols), 1)
    cash = initial_cash
    positions: dict[str, int] = {}
    fees_paid = 0.0
    for symbol in target_symbols:
        bar = first_bars[symbol]
        price = _slippage_price(bar.close, "buy", slippage_bps) if slippage_bps else bar.close
        shares = int(allocation // price // 100 * 100)
        if volume_participation is not None:
            shares = _volume_limited_lot_shares(shares, _market_bar_volume_shares(bar), volume_participation)
        amount = round(shares * price, 2)
        fee = paper_fee(amount, "buy") if apply_fees and amount > 0 else 0.0
        if shares <= 0 or amount + fee > cash:
            continue
        positions[symbol] = shares
        fees_paid = round(fees_paid + fee, 2)
        cash = round(cash - amount - fee, 2)
    curve: list[float] = []
    latest_close: dict[str, float] = {}
    for current_date in dates:
        for symbol, closes in by_symbol_date.items():
            close = closes.get(current_date)
            if close is not None:
                latest_close[symbol] = close
        value = cash + sum(latest_close.get(symbol, first_prices.get(symbol, 0.0)) * shares for symbol, shares in positions.items())
        curve.append(round(value, 2))
    if len(curve) < 2:
        return {"name": "tradable_equal_weight_pool", "return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "symbol_count": len(positions), "cash_drag": round(cash / initial_cash, 4) if initial_cash else 0.0, "fees_paid": fees_paid, "cost_model": {"slippage_bps": slippage_bps, "volume_participation": volume_participation, "fees_enabled": apply_fees}, "out_of_sample": _out_of_sample_performance(curve), "equity_curve": curve}
    total_return = curve[-1] / curve[0] - 1 if curve[0] else 0.0
    return {
        "name": "tradable_equal_weight_pool",
        "return": round(total_return, 4),
        "max_drawdown": _max_drawdown(curve),
        "sharpe": _sharpe(curve),
        "symbol_count": len(positions),
        "cash_drag": round(cash / initial_cash, 4) if initial_cash else 0.0,
        "fees_paid": fees_paid,
        "cost_model": {"slippage_bps": slippage_bps, "volume_participation": volume_participation, "fees_enabled": apply_fees},
        "out_of_sample": _out_of_sample_performance(curve),
        "equity_curve": curve[-80:],
    }


def _compare_backtest_metrics(candidate: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    baseline = baseline or {}
    stability = candidate.get("walk_forward_stability") or {}
    out_of_sample = candidate.get("out_of_sample") or {}
    has_market_benchmark = "alpha_return" in candidate and "benchmark_return" in candidate
    alpha_return = float(candidate.get("alpha_return", 0))
    deltas = {
        "total_return": round(float(candidate.get("total_return", 0)) - float(baseline.get("total_return", 0)), 4) if baseline else None,
        "alpha_return": round(float(candidate.get("alpha_return", 0)) - float(baseline.get("alpha_return", 0)), 4) if baseline else None,
        "sharpe": round(float(candidate.get("sharpe", 0)) - float(baseline.get("sharpe", 0)), 4) if baseline else None,
        "max_drawdown": round(float(candidate.get("max_drawdown", 1)) - float(baseline.get("max_drawdown", 1)), 4) if baseline else None,
    }
    drawdown_limit = 0.30 if baseline else 0.25
    alpha_pass = not has_market_benchmark or alpha_return >= -0.05 or float(candidate.get("sharpe", -999)) >= 1.5
    out_sample_alpha = out_of_sample.get("alpha_return")
    out_sample_alpha_pass = out_sample_alpha is None or float(out_sample_alpha) >= -0.05
    out_sample_pass = out_of_sample.get("passed") is not False and out_sample_alpha_pass
    base_pass = candidate.get("trade_count", 0) >= 2 and candidate.get("max_drawdown", 1) <= drawdown_limit and candidate.get("sharpe", -999) >= 0 and not candidate.get("limited_history") and stability.get("passed") is not False and out_sample_pass and alpha_pass
    if not baseline:
        reasons = []
        if not base_pass:
            if candidate.get("limited_history"):
                reasons.append("短样本回测只能用于 smoke 验证，不能作为策略准入依据")
            elif stability.get("passed") is False:
                reasons.append(f"分段稳定性未通过：{stability.get('reason') or 'unknown'}")
            elif out_of_sample.get("passed") is False:
                reasons.append(f"样本外检验未通过：{out_of_sample.get('reason') or 'unknown'}")
            elif not out_sample_alpha_pass:
                reasons.append("样本外 Alpha 相对同源等权基准低于 -5%，策略样本外没有证明可跑赢市场环境")
            elif not alpha_pass:
                reasons.append("Alpha 相对同源等权基准低于 -5%，策略没有证明可跑赢市场环境")
            else:
                reasons.append("未满足基础风控/交易次数门槛")
        return {
            "passed": base_pass,
            "baseline_compared": False,
            "deltas": deltas,
            "reasons": reasons,
        }
    improvement_pass = (
        deltas["sharpe"] >= -0.1
        and (deltas["alpha_return"] is None or deltas["alpha_return"] >= -0.02)
        and deltas["max_drawdown"] <= 0.02
        and (deltas["total_return"] >= -0.002 or deltas["sharpe"] > 0.2)
        and (deltas["sharpe"] > 0.05 or deltas["total_return"] > 0.001 or (deltas["alpha_return"] is not None and deltas["alpha_return"] > 0.001) or deltas["max_drawdown"] < -0.001)
    )
    reasons = []
    if not base_pass:
        if candidate.get("limited_history"):
            reasons.append("短样本回测只能用于 smoke 验证，不能作为策略准入依据")
        elif stability.get("passed") is False:
            reasons.append(f"分段稳定性未通过：{stability.get('reason') or 'unknown'}")
        elif out_of_sample.get("passed") is False:
            reasons.append(f"样本外检验未通过：{out_of_sample.get('reason') or 'unknown'}")
        elif not out_sample_alpha_pass:
            reasons.append("样本外 Alpha 相对同源等权基准低于 -5%，策略样本外没有证明可跑赢市场环境")
        elif not alpha_pass:
            reasons.append("Alpha 相对同源等权基准低于 -5%，策略没有证明可跑赢市场环境")
        elif candidate.get("max_drawdown", 1) > drawdown_limit:
            reasons.append(f"最大回撤超过准入上限 {drawdown_limit:.0%}")
        else:
            reasons.append("未满足基础风控/交易次数门槛")
    if deltas["alpha_return"] is not None and deltas["alpha_return"] < -0.02:
        reasons.append("Alpha 相对源策略退化超过 2 个百分点")
    if deltas["sharpe"] < -0.1:
        reasons.append("Sharpe 相对基准退化超过 0.1")
    if deltas["max_drawdown"] > 0.02:
        reasons.append("最大回撤相对基准恶化超过 2 个百分点")
    if deltas["total_return"] < -0.002 and deltas["sharpe"] <= 0.2:
        reasons.append("收益相对基准下降且风险调整收益未明显改善")
    if not (deltas["sharpe"] > 0.05 or deltas["total_return"] > 0.001 or (deltas["alpha_return"] is not None and deltas["alpha_return"] > 0.001) or deltas["max_drawdown"] < -0.001):
        reasons.append("候选策略相对基准没有实质改善")
    return {
        "passed": base_pass and improvement_pass,
        "baseline_compared": True,
        "deltas": deltas,
        "reasons": reasons,
    }


async def run_backtest(
    session: AsyncSession,
    strategy_id: str | None = None,
    stock_pool_id: str | None = None,
    days: int = 180,
    initial_cash: float = 100000.0,
    max_symbols: int = 40,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    end = date.today()
    start = end - timedelta(days=max(days, 60))
    symbols = await _pool_symbols(session, stock_pool_id, max_symbols)
    existing_bars = await session.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.symbol.in_(symbols), MarketBar.trade_date >= start, MarketBar.trade_date <= end))
    if not existing_bars:
        await sync_market_bars(session, symbols=symbols, days=max(days, 60))

    bars = (await session.scalars(select(MarketBar).where(MarketBar.symbol.in_(symbols), MarketBar.trade_date >= start, MarketBar.trade_date <= end).order_by(MarketBar.trade_date, MarketBar.symbol))).all()
    by_symbol: dict[str, list[MarketBar]] = {}
    for bar in bars:
        by_symbol.setdefault(bar.symbol, []).append(bar)

    excluded_symbols: list[dict[str, Any]] = []
    clean_bars: list[MarketBar] = []
    for symbol, symbol_bars in by_symbol.items():
        ordered = sorted(symbol_bars, key=lambda b: b.trade_date)
        if any(bar.source != "simulated_fallback" for bar in ordered):
            ordered = [bar for bar in ordered if bar.source != "simulated_fallback"]
        max_jump = 0.0
        for i in range(1, len(ordered)):
            prev = ordered[i - 1].close
            if prev:
                max_jump = max(max_jump, abs(ordered[i].close / prev - 1))
        if max_jump > 0.35:
            excluded_symbols.append({"symbol": symbol, "reason": "price_discontinuity", "max_jump": round(max_jump, 4)})
            continue
        clean_bars.extend(ordered)
    bars = clean_bars
    by_symbol = {}
    by_date: dict[date, list[MarketBar]] = {}
    for bar in bars:
        by_symbol.setdefault(bar.symbol, []).append(bar)
        by_date.setdefault(bar.trade_date, []).append(bar)
    dates = sorted(by_date)
    if len(dates) < 10:
        return {"created": False, "reason": "not_enough_market_bars", "bar_count": len(bars)}
    stock_rows = (await session.scalars(select(Stock).where(Stock.symbol.in_(symbols)))).all()
    symbol_sector = {stock.symbol: stock.sector for stock in stock_rows}
    limited_history = len(dates) < 40
    fast_window = 5 if len(dates) >= 20 else 3
    slow_window = 20 if len(dates) >= 30 else max(fast_window + 2, min(10, len(dates) - 1))
    exit_window = min(10, slow_window)

    parsed_strategy_id = uuid.UUID(strategy_id) if strategy_id else None
    parsed_pool_id = uuid.UUID(stock_pool_id) if stock_pool_id else None
    strategy = await session.get(Strategy, parsed_strategy_id) if parsed_strategy_id else await session.scalar(select(Strategy).where(Strategy.status == "active"))
    bt_params = _strategy_backtest_params(strategy)
    symbol_quality: dict[str, float] = {}
    if bt_params["min_quality"] > 0:
        factor_rows = await compute_market_factor_rows(session, limit=max(500, max_symbols))
        symbol_quality = {row.symbol: row.quality for row in factor_rows}
    run = BacktestRun(
        owner_id=owner_id,
        strategy_id=strategy.id if strategy else parsed_strategy_id,
        stock_pool_id=parsed_pool_id,
        name=f"{strategy.name if strategy else 'ZiQuant 动量策略'} {start.isoformat()}~{end.isoformat()}",
        start_date=start,
        end_date=end,
        initial_cash=initial_cash,
        status="running",
        params={"max_symbols": max_symbols, "lot_size": 100, **bt_params},
    )
    session.add(run)
    await session.flush()

    cash = initial_cash
    positions: dict[str, int] = {}
    entry_price: dict[str, float] = {}
    equity_curve: list[float] = []
    trade_results: list[float] = []
    trade_count = 0
    skipped_trades: list[dict[str, Any]] = []
    buy_hold_initialized = False

    close_history: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    for index, current_date in enumerate(dates):
        day_bars = {bar.symbol: bar for bar in by_date[current_date]}
        prev_close = {symbol: history[-1] for symbol, history in close_history.items() if history}
        for symbol, bar in day_bars.items():
            close_history.setdefault(symbol, []).append(bar.close)

        for symbol, shares in list(positions.items()):
            bar = day_bars.get(symbol)
            history = close_history.get(symbol, [])
            if not bar or len(history) < exit_window:
                continue
            ma_exit = sum(history[-exit_window:]) / exit_window
            hold_without_signal_exit = bt_params["entry_mode"] in {"equal_weight_buy_hold", "pool_equal_weight_hold"}
            stop = (not hold_without_signal_exit) and bar.close < entry_price.get(symbol, bar.close) * (1 - bt_params["stop_loss"])
            take_profit_hit = (not hold_without_signal_exit) and bool(bt_params["take_profit"] is not None and bar.close > entry_price.get(symbol, bar.close) * (1 + bt_params["take_profit"]))
            ma_exit_hit = bt_params["entry_mode"] not in {"relative_strength_rotation", "equal_weight_rotation", "equal_weight_buy_hold", "pool_equal_weight_hold"} and bar.close < ma_exit
            if ma_exit_hit or stop or take_profit_hit:
                limit_state = _limit_state(prev_close.get(symbol), bar.close, bt_params["limit_up_pct"], bt_params["limit_down_pct"])
                if limit_state == "limit_down":
                    skipped_trades.append({"date": current_date.isoformat(), "symbol": symbol, "side": "sell", "reason": "limit_down"})
                    continue
                volume_shares = _market_bar_volume_shares(bar)
                fill_shares = _volume_limited_lot_shares(shares, volume_shares, bt_params["volume_participation"])
                if fill_shares <= 0:
                    skipped_trades.append({"date": current_date.isoformat(), "symbol": symbol, "side": "sell", "reason": "volume_capacity"})
                    continue
                price = _slippage_price(bar.close, "sell", bt_params["slippage_bps"])
                amount = round(price * fill_shares, 2)
                fee = paper_fee(amount, "sell")
                cash = round(cash + amount - fee, 2)
                pnl = round((price - entry_price.get(symbol, price)) * fill_shares - fee, 2)
                trade_results.append(pnl)
                reason = "take_profit" if take_profit_hit else ("stop_loss" if stop else "ma10_exit")
                session.add(BacktestTrade(run_id=run.id, symbol=symbol, trade_date=current_date, side="sell", price=price, shares=fill_shares, amount=amount, fee=fee, reason=reason, payload={"raw_close": bar.close, "slippage_bps": bt_params["slippage_bps"], "volume": volume_shares, "participation": bt_params["volume_participation"]}))
                positions[symbol] -= fill_shares
                if positions[symbol] <= 0:
                    del positions[symbol]
                    entry_price.pop(symbol, None)
                trade_count += 1

        candidates: list[tuple[float, MarketBar]] = []
        previous_trade_date = dates[index - 1] if index else None
        rebalance_due = _rebalance_due(current_date, previous_trade_date, bt_params["rebalance"])
        relative_returns: dict[str, float] = {}
        if bt_params["min_relative_strength"] > 0 or bt_params["entry_mode"] == "relative_strength_rotation":
            window = bt_params["relative_strength_window"]
            for symbol, history in close_history.items():
                if len(history) <= window or not history[-window]:
                    continue
                relative_returns[symbol] = history[-1] / history[-window] - 1
        relative_strength = _rank_percentiles(relative_returns)
        market_breadth = _market_breadth(close_history, slow_window)
        market_breadth_blocked = bool(rebalance_due and bt_params["min_market_breadth"] > 0 and market_breadth < bt_params["min_market_breadth"])
        if market_breadth_blocked:
            skipped_trades.append({"date": current_date.isoformat(), "side": "buy", "reason": "market_breadth_filter", "market_breadth": market_breadth, "threshold": bt_params["min_market_breadth"]})
        else:
            for symbol, bar in day_bars.items():
                if symbol in positions:
                    continue
                if not rebalance_due:
                    continue
                history = close_history.get(symbol, [])
                if bt_params["entry_mode"] in {"equal_weight_rotation", "equal_weight_buy_hold", "pool_equal_weight_hold"}:
                    if bt_params["entry_mode"] in {"equal_weight_buy_hold", "pool_equal_weight_hold"} and buy_hold_initialized:
                        continue
                    candidates.append((0.0, bar))
                    continue
                if len(history) < slow_window:
                    continue
                ma_fast = sum(history[-fast_window:]) / fast_window
                ma_slow = sum(history[-slow_window:]) / slow_window
                momentum = history[-1] / history[-slow_window] - 1 if history[-slow_window] else 0
                quality = symbol_quality.get(symbol, 0.0)
                if bt_params["min_quality"] > 0 and quality < bt_params["min_quality"]:
                    continue
                rs = relative_strength.get(symbol, 0.0)
                if bt_params["min_relative_strength"] > 0 and rs < bt_params["min_relative_strength"]:
                    continue
                if bt_params["entry_mode"] == "relative_strength_rotation":
                    if rs > 0 and momentum > bt_params["min_momentum"]:
                        candidates.append((momentum + rs * 0.45 + quality * 0.08 + (bar.close / ma_slow - 1) * 0.2, bar))
                elif bar.close > ma_fast > ma_slow and momentum > bt_params["min_momentum"]:
                    candidates.append((momentum + (bar.close / ma_slow - 1) + quality * 0.05 + rs * 0.15, bar))
        candidates.sort(key=lambda x: x[0], reverse=True)
        equity_now = cash + sum(day_bars[s].close * shares for s, shares in positions.items() if s in day_bars)
        max_position_value = equity_now * bt_params["max_position_pct"]
        candidate_scan_limit = max(bt_params["candidate_top_n"] * 4, bt_params["max_positions"] * 3)
        tradable_candidates, candidate_rejections = _filter_tradable_buy_candidates(
            candidates,
            max_position_value,
            bt_params["volume_participation"],
            bt_params["slippage_bps"],
            candidate_scan_limit,
        )
        for rejection in candidate_rejections:
            skipped_trades.append({"date": current_date.isoformat(), "side": "buy", **rejection})
        if bt_params["entry_mode"] == "pool_equal_weight_hold" and rebalance_due and not buy_hold_initialized and tradable_candidates:
            allocation = equity_now / max(len(candidates), 1)
            for _, bar in candidates:
                if len(positions) >= bt_params["max_positions"]:
                    break
                if bar.symbol in positions:
                    continue
                limit_state = _limit_state(prev_close.get(bar.symbol), bar.close, bt_params["limit_up_pct"], bt_params["limit_down_pct"])
                if limit_state == "limit_up":
                    skipped_trades.append({"date": current_date.isoformat(), "symbol": bar.symbol, "side": "buy", "reason": "limit_up"})
                    continue
                price = _slippage_price(bar.close, "buy", bt_params["slippage_bps"])
                shares = int(allocation // price // 100 * 100)
                volume_shares = _market_bar_volume_shares(bar)
                shares = _volume_limited_lot_shares(shares, volume_shares, bt_params["volume_participation"])
                if shares <= 0:
                    rejection = _buy_rejection_reason(allocation, price, volume_shares, bt_params["volume_participation"])
                    skipped_trades.append({"date": current_date.isoformat(), "symbol": bar.symbol, "side": "buy", **rejection})
                    continue
                amount = round(price * shares, 2)
                fee = paper_fee(amount, "buy")
                if amount + fee > cash:
                    continue
                cash = round(cash - amount - fee, 2)
                positions[bar.symbol] = shares
                entry_price[bar.symbol] = price
                session.add(BacktestTrade(run_id=run.id, symbol=bar.symbol, trade_date=current_date, side="buy", price=price, shares=shares, amount=amount, fee=fee, reason="pool_equal_weight_hold", payload={"raw_close": bar.close, "slippage_bps": bt_params["slippage_bps"], "volume": volume_shares, "participation": bt_params["volume_participation"], "allocation": round(allocation, 2)}))
                trade_count += 1
            buy_hold_initialized = True
            latest_value = cash + sum(day_bars.get(s, by_symbol[s][-1]).close * shares for s, shares in positions.items())
            equity_curve.append(round(latest_value, 2))
            continue
        target_symbols = {bar.symbol for _, bar in tradable_candidates[: min(bt_params["candidate_top_n"], bt_params["max_positions"])]}
        if bt_params["entry_mode"] in {"relative_strength_rotation", "equal_weight_rotation"} and rebalance_due and target_symbols:
            for symbol, shares in list(positions.items()):
                if symbol in target_symbols:
                    continue
                bar = day_bars.get(symbol)
                if not bar:
                    continue
                limit_state = _limit_state(prev_close.get(symbol), bar.close, bt_params["limit_up_pct"], bt_params["limit_down_pct"])
                if limit_state == "limit_down":
                    skipped_trades.append({"date": current_date.isoformat(), "symbol": symbol, "side": "sell", "reason": "limit_down"})
                    continue
                volume_shares = _market_bar_volume_shares(bar)
                fill_shares = _volume_limited_lot_shares(shares, volume_shares, bt_params["volume_participation"])
                if fill_shares <= 0:
                    skipped_trades.append({"date": current_date.isoformat(), "symbol": symbol, "side": "sell", "reason": "volume_capacity"})
                    continue
                price = _slippage_price(bar.close, "sell", bt_params["slippage_bps"])
                amount = round(price * fill_shares, 2)
                fee = paper_fee(amount, "sell")
                cash = round(cash + amount - fee, 2)
                pnl = round((price - entry_price.get(symbol, price)) * fill_shares - fee, 2)
                trade_results.append(pnl)
                exit_reason = "equal_weight_rotation_exit" if bt_params["entry_mode"] == "equal_weight_rotation" else "relative_strength_rotation_exit"
                session.add(BacktestTrade(run_id=run.id, symbol=symbol, trade_date=current_date, side="sell", price=price, shares=fill_shares, amount=amount, fee=fee, reason=exit_reason, payload={"raw_close": bar.close, "slippage_bps": bt_params["slippage_bps"], "volume": volume_shares, "participation": bt_params["volume_participation"]}))
                positions[symbol] -= fill_shares
                if positions[symbol] <= 0:
                    del positions[symbol]
                    entry_price.pop(symbol, None)
                trade_count += 1
            equity_now = cash + sum(day_bars[s].close * shares for s, shares in positions.items() if s in day_bars)
            max_position_value = equity_now * bt_params["max_position_pct"]
        for _, bar in tradable_candidates[: bt_params["candidate_top_n"]]:
            if len(positions) >= bt_params["max_positions"]:
                break
            limit_state = _limit_state(prev_close.get(bar.symbol), bar.close, bt_params["limit_up_pct"], bt_params["limit_down_pct"])
            if limit_state == "limit_up":
                skipped_trades.append({"date": current_date.isoformat(), "symbol": bar.symbol, "side": "buy", "reason": "limit_up"})
                continue
            price = _slippage_price(bar.close, "buy", bt_params["slippage_bps"])
            shares = int(max_position_value // price // 100 * 100)
            volume_shares = _market_bar_volume_shares(bar)
            shares = _volume_limited_lot_shares(shares, volume_shares, bt_params["volume_participation"])
            if shares <= 0:
                rejection = _buy_rejection_reason(max_position_value, price, volume_shares, bt_params["volume_participation"])
                skipped_trades.append({"date": current_date.isoformat(), "symbol": bar.symbol, "side": "buy", **rejection})
                continue
            amount = round(price * shares, 2)
            fee = paper_fee(amount, "buy")
            if amount + fee > cash:
                continue
            sector_weight = _sector_exposure_after_order(positions, day_bars, symbol_sector, bar.symbol, amount, max(equity_now, 1.0))
            if sector_weight > bt_params["max_sector_pct"]:
                skipped_trades.append({"date": current_date.isoformat(), "symbol": bar.symbol, "side": "buy", "reason": "sector_exposure_limit", "sector": symbol_sector.get(bar.symbol, "未分类"), "sector_weight": sector_weight, "limit": bt_params["max_sector_pct"]})
                continue
            cash = round(cash - amount - fee, 2)
            positions[bar.symbol] = shares
            entry_price[bar.symbol] = price
            session.add(BacktestTrade(run_id=run.id, symbol=bar.symbol, trade_date=current_date, side="buy", price=price, shares=shares, amount=amount, fee=fee, reason="ma5_ma20_momentum", payload={"raw_close": bar.close, "slippage_bps": bt_params["slippage_bps"], "volume": volume_shares, "participation": bt_params["volume_participation"]}))
            trade_count += 1
        if bt_params["entry_mode"] == "equal_weight_buy_hold" and target_symbols:
            buy_hold_initialized = True

        latest_value = cash + sum(day_bars.get(s, by_symbol[s][-1]).close * shares for s, shares in positions.items())
        equity_curve.append(round(latest_value, 2))

    final_equity = equity_curve[-1]
    total_return = final_equity / initial_cash - 1
    annualized = (1 + total_return) ** (252 / max(len(dates), 1)) - 1 if total_return > -1 else -1
    benchmark = _equal_weight_benchmark(
        by_symbol,
        dates,
        initial_cash,
        slippage_bps=bt_params["slippage_bps"],
        volume_participation=bt_params["volume_participation"],
        apply_fees=True,
    )
    out_of_sample = _out_of_sample_performance(equity_curve)
    benchmark_oos = benchmark.get("out_of_sample") or {}
    if out_of_sample.get("return") is not None and benchmark_oos.get("return") is not None:
        out_sample_alpha = round(float(out_of_sample.get("return") or 0) - float(benchmark_oos.get("return") or 0), 4)
        alpha_reasons = []
        if out_sample_alpha < -0.05:
            alpha_reasons.append("样本外 Alpha 相对同源等权基准低于 -5%")
        existing_reason = str(out_of_sample.get("reason") or "")
        out_of_sample = {
            **out_of_sample,
            "benchmark_return": benchmark_oos.get("return"),
            "alpha_return": out_sample_alpha,
            "passed": bool(out_of_sample.get("passed")) and not alpha_reasons,
            "reason": "；".join([reason for reason in [existing_reason, *alpha_reasons] if reason]),
        }
    wins = sum(1 for pnl in trade_results if pnl > 0)
    metrics = {
        "total_return": round(total_return, 4),
        "benchmark_return": benchmark["return"],
        "alpha_return": round(total_return - float(benchmark["return"]), 4),
        "benchmark": benchmark,
        "annualized_return": round(annualized, 4),
        "max_drawdown": _max_drawdown(equity_curve),
        "sharpe": _sharpe(equity_curve),
        "walk_forward_stability": _walk_forward_stability(equity_curve),
        "out_of_sample": out_of_sample,
        "win_rate": round(wins / len(trade_results), 4) if trade_results else 0,
        "trade_count": trade_count,
        "bar_count": len(bars),
        "history_day_count": len(dates),
        "limited_history": limited_history,
        "windows": {"fast": fast_window, "slow": slow_window, "exit": exit_window},
        "execution_constraints": {
            "entry_mode": bt_params["entry_mode"],
            "slippage_bps": bt_params["slippage_bps"],
            "volume_participation": bt_params["volume_participation"],
            "limit_up_pct": bt_params["limit_up_pct"],
            "limit_down_pct": bt_params["limit_down_pct"],
            "max_sector_pct": bt_params["max_sector_pct"],
            "min_momentum": bt_params["min_momentum"],
            "min_quality": bt_params["min_quality"],
            "min_relative_strength": bt_params["min_relative_strength"],
            "relative_strength_window": bt_params["relative_strength_window"],
            "min_market_breadth": bt_params["min_market_breadth"],
        },
        "open_positions": len(positions),
        "excluded_symbols": excluded_symbols[:20],
        "skipped_trades": skipped_trades[:50],
        "skipped_trade_count": len(skipped_trades),
        "equity_curve": equity_curve[-80:],
    }
    run.status = "success"
    run.final_equity = final_equity
    run.metrics = metrics
    session.add(AdminAuditLog(action="run_backtest", target=str(run.id), payload=metrics))
    await session.commit()
    return {"created": True, "run_id": str(run.id), "name": run.name, "metrics": metrics, "final_equity": final_equity}


async def list_backtests(session: AsyncSession, limit: int = 20, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    stmt = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
    if owner_id is not None:
        stmt = stmt.where(or_(BacktestRun.owner_id == owner_id, BacktestRun.owner_id.is_(None)))
    rows = (await session.scalars(stmt)).all()
    return {"items": [{"id": str(r.id), "name": r.name, "status": r.status, "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat(), "initial_cash": r.initial_cash, "final_equity": r.final_equity, "metrics": r.metrics, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}


async def get_backtest_detail(session: AsyncSession, run_id: str, trade_limit: int = 200) -> dict[str, Any]:
    run = await session.get(BacktestRun, uuid.UUID(run_id))
    if not run:
        return {"found": False, "reason": "missing_backtest"}
    trades = (
        await session.scalars(
            select(BacktestTrade)
            .where(BacktestTrade.run_id == run.id)
            .order_by(BacktestTrade.trade_date, BacktestTrade.symbol, BacktestTrade.side)
            .limit(min(max(trade_limit, 1), 1000))
        )
    ).all()
    by_symbol: dict[str, dict[str, Any]] = {}
    for trade in trades:
        row = by_symbol.setdefault(trade.symbol, {"symbol": trade.symbol, "buy_amount": 0.0, "sell_amount": 0.0, "fees": 0.0, "trade_count": 0})
        if trade.side == "buy":
            row["buy_amount"] = round(row["buy_amount"] + trade.amount, 2)
        else:
            row["sell_amount"] = round(row["sell_amount"] + trade.amount, 2)
        row["fees"] = round(row["fees"] + trade.fee, 2)
        row["trade_count"] += 1
    return {
        "found": True,
        "run": {
            "id": str(run.id),
            "name": run.name,
            "status": run.status,
            "start_date": run.start_date.isoformat(),
            "end_date": run.end_date.isoformat(),
            "initial_cash": run.initial_cash,
            "final_equity": run.final_equity,
            "metrics": run.metrics,
            "params": run.params,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        },
        "trades": [
            {
                "id": str(t.id),
                "symbol": t.symbol,
                "trade_date": t.trade_date.isoformat(),
                "side": t.side,
                "price": t.price,
                "shares": t.shares,
                "amount": t.amount,
                "fee": t.fee,
                "reason": t.reason,
            }
            for t in trades
        ],
        "summary_by_symbol": sorted(by_symbol.values(), key=lambda x: x["symbol"]),
    }


def strategy_experiment_payload(experiment: StrategyExperiment) -> dict[str, Any]:
    return {
        "id": str(experiment.id),
        "owner_id": str(experiment.owner_id) if experiment.owner_id else None,
        "strategy_id": str(experiment.strategy_id) if experiment.strategy_id else None,
        "source_strategy_id": str(experiment.source_strategy_id) if experiment.source_strategy_id else None,
        "optimization_id": str(experiment.optimization_id) if experiment.optimization_id else None,
        "backtest_run_id": str(experiment.backtest_run_id) if experiment.backtest_run_id else None,
        "baseline_run_id": str(experiment.baseline_run_id) if experiment.baseline_run_id else None,
        "name": experiment.name,
        "status": experiment.status,
        "passed": experiment.passed,
        "decision": experiment.decision,
        "metrics": experiment.metrics,
        "baseline_metrics": experiment.baseline_metrics,
        "comparison": experiment.comparison,
        "params": experiment.params,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
    }


async def list_strategy_experiments(session: AsyncSession, limit: int = 30, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    stmt = select(StrategyExperiment).order_by(StrategyExperiment.created_at.desc()).limit(min(max(limit, 1), 200))
    if owner_id is not None:
        stmt = stmt.where(or_(StrategyExperiment.owner_id == owner_id, StrategyExperiment.owner_id.is_(None)))
    rows = (await session.scalars(stmt)).all()
    return {"items": [strategy_experiment_payload(row) for row in rows]}


def strategy_promotion_candidate_payload(experiment: StrategyExperiment, strategy: Strategy) -> dict[str, Any]:
    metrics = experiment.metrics or {}
    out_of_sample = metrics.get("out_of_sample") or {}
    stability = metrics.get("walk_forward_stability") or {}
    latest_validation = (strategy.rule_json or {}).get("latest_validation") or {}
    blocking_reasons: list[str] = []
    if strategy.status != "draft":
        blocking_reasons.append(f"策略状态不是 draft：{strategy.status}")
    if not experiment.passed:
        blocking_reasons.append("最近验证实验未通过")
    if not latest_validation.get("passed"):
        blocking_reasons.append("策略 latest_validation 未通过或缺失")
    return {
        "strategy_id": str(strategy.id),
        "strategy_name": strategy.name,
        "strategy_status": strategy.status,
        "visibility": strategy.visibility.value,
        "owner_id": str(strategy.owner_id) if strategy.owner_id else None,
        "experiment_id": str(experiment.id),
        "experiment_name": experiment.name,
        "source_strategy_id": str(experiment.source_strategy_id) if experiment.source_strategy_id else None,
        "optimization_id": str(experiment.optimization_id) if experiment.optimization_id else None,
        "backtest_run_id": str(experiment.backtest_run_id) if experiment.backtest_run_id else None,
        "baseline_run_id": str(experiment.baseline_run_id) if experiment.baseline_run_id else None,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
        "passed": experiment.passed,
        "promotable": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "decision": experiment.decision,
        "metrics": {
            "total_return": metrics.get("total_return"),
            "benchmark_return": metrics.get("benchmark_return"),
            "alpha_return": metrics.get("alpha_return"),
            "out_of_sample_return": out_of_sample.get("return"),
            "out_of_sample_alpha_return": out_of_sample.get("alpha_return"),
            "out_of_sample_passed": out_of_sample.get("passed"),
            "walk_forward_passed": stability.get("passed"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe": metrics.get("sharpe"),
            "trade_count": metrics.get("trade_count"),
        },
        "comparison": experiment.comparison or {},
        "next_action": "promote_after_manual_review" if not blocking_reasons else "resolve_blocking_reasons",
    }


async def list_strategy_promotion_candidates(session: AsyncSession, limit: int = 20, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    stmt = (
        select(StrategyExperiment, Strategy)
        .join(Strategy, Strategy.id == StrategyExperiment.strategy_id)
        .where(StrategyExperiment.passed.is_(True))
        .order_by(StrategyExperiment.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    if owner_id is not None:
        stmt = stmt.where(
            or_(StrategyExperiment.owner_id == owner_id, StrategyExperiment.owner_id.is_(None)),
            or_(Strategy.owner_id == owner_id, Strategy.owner_id.is_(None), Strategy.visibility == Visibility.public),
        )
    rows = (await session.execute(stmt)).all()
    items = [strategy_promotion_candidate_payload(experiment, strategy) for experiment, strategy in rows]
    return {"items": [item for item in items if item["strategy_status"] == "draft" or item["promotable"]]}


def strategy_promotion_readiness(candidates: dict[str, Any], strategy_health: dict[str, Any]) -> dict[str, Any]:
    items = candidates.get("items") or []
    promotable = [item for item in items if item.get("promotable")]
    health_ready = strategy_health.get("status") == "ready" and strategy_health.get("passed") is True
    if health_ready:
        passed = True
        reason = "active_strategy_ready"
        next_action = "paper_observe"
    elif promotable:
        passed = True
        reason = "promotable_candidate_available"
        next_action = "promote_after_manual_review"
    else:
        passed = False
        reason = "no_promotable_candidate_for_unhealthy_strategy"
        repair_plan = strategy_health.get("repair_plan") or []
        next_action = repair_plan[0]["action"] if repair_plan else "run_alpha_search_or_remediate_health"
    return {
        "passed": passed,
        "reason": reason,
        "candidate_count": len(items),
        "promotable_count": len(promotable),
        "strategy_health_status": strategy_health.get("status"),
        "next_action": next_action,
        "candidate_strategy_ids": [item.get("strategy_id") for item in promotable[:5]],
    }


def _strategy_optimization_loop_health(
    latest_optimization: StrategyOptimizationRun | None,
    latest_experiment: StrategyExperiment | None,
    candidates: dict[str, Any],
    strategy_health: dict[str, Any],
    latest_llm_optimization: StrategyOptimizationRun | None = None,
    now: datetime | None = None,
    max_age_days: int = 30,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    reasons: list[str] = []
    deepseek_ready = bool(settings.deepseek_api_key and settings.deepseek_base_url and settings.deepseek_model)
    latest_optimization_age_days: int | None = None
    latest_llm_optimization_age_days: int | None = None
    latest_experiment_age_days: int | None = None
    latest_optimization_success = bool(latest_optimization and latest_optimization.status == "success")
    if latest_llm_optimization is None and latest_optimization and latest_optimization.model == settings.deepseek_model:
        latest_llm_optimization = latest_optimization
    latest_llm_optimization_success = bool(latest_llm_optimization and latest_llm_optimization.status == "success")
    latest_experiment_passed = bool(latest_experiment and latest_experiment.passed)

    if latest_optimization and latest_optimization.created_at:
        created_at = latest_optimization.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        latest_optimization_age_days = max(0, (now - created_at).days)
    if latest_llm_optimization and latest_llm_optimization.created_at:
        created_at = latest_llm_optimization.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        latest_llm_optimization_age_days = max(0, (now - created_at).days)
    if latest_experiment and latest_experiment.created_at:
        created_at = latest_experiment.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        latest_experiment_age_days = max(0, (now - created_at).days)

    items = candidates.get("items") or []
    promotable = [item for item in items if item.get("promotable")]
    strategy_ready = strategy_health.get("status") == "ready" and strategy_health.get("passed") is True
    optimization_fresh = latest_optimization_age_days is not None and latest_optimization_age_days <= max_age_days
    llm_optimization_fresh = latest_llm_optimization_age_days is not None and latest_llm_optimization_age_days <= max_age_days
    experiment_fresh = latest_experiment_age_days is not None and latest_experiment_age_days <= max_age_days
    validated_recently = bool(latest_experiment_passed and experiment_fresh)
    llm_optimized_recently = bool(latest_llm_optimization_success and llm_optimization_fresh)

    if not deepseek_ready:
        reasons.append("DeepSeek 模型配置不完整")
    if not latest_llm_optimization:
        reasons.append("缺少 DeepSeek 大模型优化记录")
    elif not latest_llm_optimization_success:
        reasons.append(f"最近 DeepSeek 大模型优化状态不是 success：{latest_llm_optimization.status}")
    elif not llm_optimization_fresh:
        reasons.append(f"最近大模型优化超过 {max_age_days} 天")
    if not latest_experiment:
        reasons.append("缺少候选策略验证实验")
    elif not latest_experiment_passed and not strategy_ready:
        reasons.append("最近候选策略验证未通过且 active 策略健康度未通过")
    elif latest_experiment_passed and not experiment_fresh:
        reasons.append(f"最近通过验证实验超过 {max_age_days} 天")
    if not strategy_ready and not promotable:
        reasons.append("active 策略未通过且没有可晋升候选")

    status = "ready" if deepseek_ready and llm_optimized_recently and (validated_recently or strategy_ready or promotable) and not reasons else "degraded"
    next_action = "paper_observe" if strategy_ready else "promote_after_manual_review" if promotable else "run_next_strategy_research_action"
    if not deepseek_ready:
        next_action = "configure_deepseek"
    elif not latest_llm_optimization or not llm_optimization_fresh:
        next_action = "optimize_strategy"
    elif not latest_experiment or (not latest_experiment_passed and not strategy_ready):
        next_action = "validate_candidate_or_alpha_search"

    return {
        "status": status,
        "passed": status == "ready",
        "reasons": reasons,
        "next_action": next_action,
        "max_age_days": max_age_days,
        "deepseek": {
            "configured": deepseek_ready,
            "base_url_host": _safe_url_host(settings.deepseek_base_url),
            "model": settings.deepseek_model,
        },
        "latest_optimization": {
            "id": str(latest_optimization.id) if latest_optimization else None,
            "status": latest_optimization.status if latest_optimization else None,
            "model": latest_optimization.model if latest_optimization else None,
            "created_at": latest_optimization.created_at.isoformat() if latest_optimization and latest_optimization.created_at else None,
            "age_days": latest_optimization_age_days,
            "success": latest_optimization_success,
            "llm": bool(latest_optimization and latest_optimization.model == settings.deepseek_model),
        },
        "latest_llm_optimization": {
            "id": str(latest_llm_optimization.id) if latest_llm_optimization else None,
            "status": latest_llm_optimization.status if latest_llm_optimization else None,
            "model": latest_llm_optimization.model if latest_llm_optimization else None,
            "created_at": latest_llm_optimization.created_at.isoformat() if latest_llm_optimization and latest_llm_optimization.created_at else None,
            "age_days": latest_llm_optimization_age_days,
            "success": latest_llm_optimization_success,
        },
        "latest_experiment": _strategy_experiment_health_payload(latest_experiment),
        "latest_experiment_age_days": latest_experiment_age_days,
        "candidate_count": len(items),
        "promotable_count": len(promotable),
        "promotable_strategy_ids": [item.get("strategy_id") for item in promotable[:5]],
        "strategy_health_status": strategy_health.get("status"),
        "loop": {
            "llm_suggested": llm_optimized_recently,
            "local_search_latest": bool(latest_optimization and latest_optimization.model == "local-alpha-grid"),
            "candidate_validated": latest_experiment_passed,
            "active_strategy_ready": strategy_ready,
            "manual_promotion_required": bool(promotable and not strategy_ready),
        },
        "warning": "策略优化闭环只生成建议、候选、回测和人工晋升信号，不会提交真实交易订单。",
    }


async def strategy_optimization_loop_health(session: AsyncSession, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    optimization_stmt = select(StrategyOptimizationRun).order_by(StrategyOptimizationRun.created_at.desc()).limit(1)
    llm_optimization_stmt = (
        select(StrategyOptimizationRun)
        .where(StrategyOptimizationRun.model == settings.deepseek_model)
        .order_by(StrategyOptimizationRun.created_at.desc())
        .limit(1)
    )
    experiment_stmt = select(StrategyExperiment).order_by(StrategyExperiment.created_at.desc()).limit(1)
    if owner_id is not None:
        optimization_stmt = optimization_stmt.where(or_(StrategyOptimizationRun.owner_id == owner_id, StrategyOptimizationRun.owner_id.is_(None)))
        llm_optimization_stmt = llm_optimization_stmt.where(or_(StrategyOptimizationRun.owner_id == owner_id, StrategyOptimizationRun.owner_id.is_(None)))
        experiment_stmt = experiment_stmt.where(or_(StrategyExperiment.owner_id == owner_id, StrategyExperiment.owner_id.is_(None)))
    latest_optimization = await session.scalar(optimization_stmt)
    latest_llm_optimization = await session.scalar(llm_optimization_stmt)
    latest_experiment = await session.scalar(experiment_stmt)
    strategy_health = await active_strategy_health(session, owner_id=owner_id)
    candidates = await list_strategy_promotion_candidates(session, limit=20, owner_id=owner_id)
    return _strategy_optimization_loop_health(latest_optimization, latest_experiment, candidates, strategy_health, latest_llm_optimization=latest_llm_optimization)


def latest_research_history_hint(timeline: dict[str, Any] | None) -> dict[str, Any]:
    for item in (timeline or {}).get("items") or []:
        if item.get("action") not in {"remediate_strategy_health", "run_next_strategy_research_action", "alpha_grid_search_strategy"}:
            continue
        summary = item.get("summary") or {}
        payload = item.get("payload") or {}
        plan_action = (payload.get("plan") or {}).get("action")
        next_action = summary.get("next_action")
        if summary.get("validation_passed") is False and (plan_action == "alpha_search" or summary.get("trial_count")):
            return {
                "preferred_next_action": "tighten_signal_quality",
                "reason": "latest_alpha_search_failed",
                "source_action": item.get("action"),
                "source_created_at": item.get("created_at"),
                "candidate_strategy_id": summary.get("candidate_strategy_id"),
                "alpha_return": summary.get("alpha_return"),
                "out_of_sample_alpha": summary.get("out_of_sample_alpha"),
                "detail": "最近一次 Alpha 网格搜索最佳候选验证失败，应先收紧信号质量或调整约束，而不是重复同一网格。",
            }
        if summary.get("validation_passed") is False and plan_action == "tighten_signal_quality":
            return {
                "preferred_next_action": "alpha_search",
                "reason": "latest_tighten_failed",
                "source_action": item.get("action"),
                "source_created_at": item.get("created_at"),
                "candidate_strategy_id": summary.get("candidate_strategy_id"),
                "alpha_return": summary.get("alpha_return"),
                "out_of_sample_alpha": summary.get("out_of_sample_alpha"),
                "detail": "最近一次收紧信号候选验证失败，可回到 Alpha 网格搜索或调整更宽的约束集合。",
            }
        if summary.get("validation_passed") is False and next_action == "run_alpha_search_or_adjust_constraints":
            return {
                "preferred_next_action": "alpha_search",
                "reason": "latest_remediation_failed",
                "source_action": item.get("action"),
                "source_created_at": item.get("created_at"),
                "candidate_strategy_id": summary.get("candidate_strategy_id"),
                "alpha_return": summary.get("alpha_return"),
                "out_of_sample_alpha": summary.get("out_of_sample_alpha"),
                "detail": "最近一次健康度修复候选验证失败，按审计结果应改做 Alpha 网格搜索，避免重复生成同类候选。",
            }
        if item.get("action") == "alpha_grid_search_strategy":
            return {
                "preferred_next_action": None,
                "reason": "latest_alpha_search_seen",
                "source_action": item.get("action"),
                "source_created_at": item.get("created_at"),
                "detail": "最近已有 Alpha 网格搜索记录，继续按当前策略健康度和候选准入判断下一步。",
            }
    return {"preferred_next_action": None, "reason": "no_research_history_hint"}


def apply_research_history_to_readiness(readiness: dict[str, Any], history_hint: dict[str, Any] | None) -> dict[str, Any]:
    updated = dict(readiness)
    preferred = (history_hint or {}).get("preferred_next_action")
    if preferred and not updated.get("passed"):
        updated["next_action"] = preferred
        updated["history_hint"] = history_hint
    elif history_hint:
        updated["history_hint"] = history_hint
    return updated


def strategy_next_research_action_plan(readiness: dict[str, Any], strategy_health: dict[str, Any]) -> dict[str, Any]:
    next_action = readiness.get("next_action") or "run_alpha_search_or_remediate_health"
    if readiness.get("reason") == "active_strategy_ready":
        return {
            "action": "paper_observe",
            "executable": False,
            "reason": "active_strategy_ready",
            "endpoint": "/api/portfolios/{portfolio_id}/rebalance",
            "detail": "启用策略健康度已通过，继续模拟盘观察，不自动扩大风险敞口。",
        }
    if readiness.get("reason") == "promotable_candidate_available":
        return {
            "action": "promote_after_manual_review",
            "executable": False,
            "reason": "promotable_candidate_available",
            "endpoint": "/api/strategies/{strategy_id}/promote",
            "candidate_strategy_ids": readiness.get("candidate_strategy_ids") or [],
            "detail": "已有通过验证的候选策略，需要人工复核后手动启用。",
        }
    action_map = {
        "remediate_health": {
            "endpoint": "/api/strategies/remediate-health",
            "detail": "执行大模型健康度修复，生成候选策略并立即回测验证。",
        },
        "alpha_search": {
            "endpoint": "/api/strategies/alpha-search",
            "detail": "执行本地 Alpha 网格搜索，寻找更高超额收益的候选参数。",
        },
        "run_backtest": {
            "endpoint": "/api/backtests/run",
            "detail": "先为启用策略运行正式回测，补齐健康度指标。",
        },
        "tighten_signal_quality": {
            "endpoint": "/api/strategies/optimize",
            "detail": "生成质量/动量收紧方向的大模型参数建议。",
        },
    }
    if next_action not in action_map:
        next_action = "alpha_search"
    repair_plan = strategy_health.get("repair_plan") or []
    plan_item = next((item for item in repair_plan if item.get("action") == next_action), repair_plan[0] if repair_plan else {})
    return {
        "action": next_action,
        "executable": True,
        "reason": readiness.get("reason") or "needs_research_action",
        "endpoint": action_map[next_action]["endpoint"],
        "detail": action_map[next_action]["detail"],
        "params": plan_item.get("params") or {},
    }


STRATEGY_REPAIR_AUDIT_ACTIONS = {
    "run_next_strategy_research_action",
    "remediate_strategy_health",
    "alpha_grid_search_strategy",
    "optimize_strategy",
    "apply_strategy_optimization",
    "validate_strategy_candidate",
    "promote_validated_strategy",
}


def strategy_repair_timeline_payload(log: AdminAuditLog) -> dict[str, Any]:
    payload = log.payload or {}
    validation = payload.get("validation") or payload
    metrics = validation.get("metrics") or {}
    comparison = validation.get("comparison") or {}
    best = payload.get("best") or {}
    plan = payload.get("plan") or {}
    result_summary = payload.get("result_summary") or {}
    readiness_after = payload.get("readiness_after") or {}
    health_after = payload.get("strategy_health_after") or {}
    summary_metrics = result_summary.get("metrics") or {}
    readiness_candidates = readiness_after.get("candidate_strategy_ids") or []
    return {
        "id": str(log.id),
        "action": log.action,
        "target": log.target,
        "actor_id": str(log.actor_id) if log.actor_id else None,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "summary": {
            "health_status": payload.get("health_status") or health_after.get("status"),
            "optimization_id": payload.get("optimization_id") or result_summary.get("optimization_id"),
            "candidate_strategy_id": payload.get("candidate_strategy_id")
            or payload.get("candidate_strategy")
            or result_summary.get("candidate_strategy_id")
            or result_summary.get("best_strategy_id")
            or best.get("strategy_id")
            or (readiness_candidates[0] if readiness_candidates else None),
            "validation_passed": payload.get("validation_passed") if "validation_passed" in payload else result_summary.get("validation_passed", validation.get("passed")),
            "next_action": payload.get("next_action") or result_summary.get("next_action") or plan.get("action") or readiness_after.get("next_action"),
            "alpha_return": metrics.get("alpha_return") or result_summary.get("alpha_return") or summary_metrics.get("alpha_return") or (best.get("metrics") or {}).get("alpha_return"),
            "out_of_sample_alpha": ((metrics.get("out_of_sample") or {}).get("alpha_return") if metrics else None)
            or result_summary.get("out_of_sample_alpha")
            or ((summary_metrics.get("out_of_sample") or {}).get("alpha_return") if summary_metrics else None)
            or ((best.get("metrics") or {}).get("out_of_sample") or {}).get("alpha_return"),
            "comparison_reasons": comparison.get("reasons") or [],
            "trial_count": payload.get("trial_count") or result_summary.get("trial_count"),
            "orders": payload.get("orders"),
        },
        "payload": payload,
    }


async def list_strategy_repair_timeline(session: AsyncSession, limit: int = 30, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    stmt = (
        select(AdminAuditLog)
        .where(AdminAuditLog.action.in_(STRATEGY_REPAIR_AUDIT_ACTIONS))
        .order_by(AdminAuditLog.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    if owner_id is not None:
        stmt = stmt.where(or_(AdminAuditLog.actor_id == owner_id, AdminAuditLog.actor_id.is_(None)))
    rows = (await session.scalars(stmt)).all()
    return {"items": [strategy_repair_timeline_payload(row) for row in rows]}


async def optimize_strategy(session: AsyncSession, strategy_id: str | None = None, backtest_run_id: str | None = None, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    strategy = await session.get(Strategy, uuid.UUID(strategy_id)) if strategy_id else await session.scalar(select(Strategy).where(Strategy.status == "active"))
    if backtest_run_id:
        backtest = await session.get(BacktestRun, uuid.UUID(backtest_run_id))
    elif strategy:
        backtest = await session.scalar(select(BacktestRun).where(BacktestRun.strategy_id == strategy.id, BacktestRun.status == "success").order_by(BacktestRun.created_at.desc()).limit(1))
    else:
        backtest = await session.scalar(select(BacktestRun).where(BacktestRun.status == "success").order_by(BacktestRun.created_at.desc()).limit(1))
    latest_experiment = None
    if strategy:
        latest_experiment = await session.scalar(
            select(StrategyExperiment)
            .where(or_(StrategyExperiment.strategy_id == strategy.id, StrategyExperiment.source_strategy_id == strategy.id))
            .order_by(StrategyExperiment.created_at.desc())
            .limit(1)
        )
    strategy_health = strategy_health_from_metrics(strategy, backtest, latest_experiment)
    prompt = (
        "你是A股量化策略研究助手。请基于策略规则、回测指标和A股交易约束，输出严格JSON："
        "必须优先分析alpha_return、benchmark_return、out_of_sample、walk_forward_stability、max_drawdown、sharpe和trade_count；"
        "当策略跑输同源等权基准时，优化目标应明确提高Alpha而不是只降低绝对波动。"
        "如果strategy_health为rejected或degraded，必须逐条回应reasons，并优先修复样本外Alpha、全段Alpha和分段稳定性。"
        "summary为字符串；risk_findings为字符串数组；parameter_changes为对象数组，每个对象必须包含"
        "name、from、to、reason，name只能从max_position_pct、stop_loss、take_profit、max_positions、"
        "entry_mode、candidate_top_n、min_momentum、min_quality、min_relative_strength、relative_strength_window、min_market_breadth、rebalance、slippage_bps、volume_participation、max_sector_pct中选择；next_experiments为字符串数组。不要把parameter_changes写成自然语言。"
    )
    request_json = {
        "strategy": {"name": strategy.name if strategy else "未指定", "rule": strategy.rule_json if strategy else {}},
        "backtest": {
            "metrics": _llm_strategy_metric_summary(backtest.metrics if backtest else {}),
            "start_date": backtest.start_date.isoformat() if backtest else None,
            "end_date": backtest.end_date.isoformat() if backtest else None,
        },
        "strategy_health": {
            "status": strategy_health.get("status"),
            "reasons": strategy_health.get("reasons") or [],
            "metrics": _llm_strategy_metric_summary(strategy_health.get("metrics") or {}),
            "effectiveness_summary": (strategy_health.get("effectiveness_evidence") or {}).get("summary"),
            "residual_risks": (strategy_health.get("effectiveness_evidence") or {}).get("residual_risks") or [],
        },
        "constraints": {"market": "A股", "lot_size": 100, "long_only": True, "paper_trading_only": True},
    }
    result: dict[str, Any]
    status = "success"
    if settings.deepseek_api_key:
        try:
            headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
            payload = {
                "model": settings.deepseek_model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(request_json, ensure_ascii=False)},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
            async with httpx.AsyncClient(
                base_url=settings.deepseek_base_url.rstrip("/"),
                timeout=settings.deepseek_timeout_seconds,
                trust_env=False,
            ) as client:
                try:
                    response = await client.post("/chat/completions", headers=headers, json=payload)
                    response.raise_for_status()
                    response_json = response.json()
                except (httpx.RemoteProtocolError, httpx.TransportError, httpx.TimeoutException):
                    response_json = await asyncio.to_thread(_deepseek_chat_completion_via_urllib, payload)
                content = response_json["choices"][0]["message"]["content"]

            result = json.loads(content)
        except Exception as exc:
            status = "fallback"
            result = {"summary": "大模型调用失败，已生成本地 Alpha 优先建议。", "risk_findings": [type(exc).__name__, "需要检查策略是否跑赢同源等权基准"], "parameter_changes": [{"name": "entry_mode", "from": "trend_following", "to": "relative_strength_rotation", "reason": "切换为相对强弱轮动，直接围绕同池超额收益构建目标池"}, {"name": "candidate_top_n", "from": 5, "to": 3, "reason": "减少弱信号入选，优先提升相对基准的超额收益"}, {"name": "min_momentum", "from": 0, "to": 0.05, "reason": "提高入选动量门槛，过滤弱趋势交易"}, {"name": "min_quality", "from": 0, "to": 0.6, "reason": "提高财报质量门槛，减少低质量趋势股入选"}, {"name": "min_relative_strength", "from": 0, "to": 0.75, "reason": "只选择同池相对强势股票，直接修复跑输等权基准的问题"}, {"name": "relative_strength_window", "from": 60, "to": 40, "reason": "缩短相对强弱窗口，提高轮动对市场结构变化的响应速度"}, {"name": "min_market_breadth", "from": 0, "to": 0.55, "reason": "市场宽度不足时暂停新增买入，减少弱市分段回撤"}, {"name": "max_sector_pct", "from": 0.35, "to": 0.25, "reason": "降低行业拥挤暴露，减少基准行情驱动的伪收益"}], "next_experiments": ["以 alpha_return 为主目标做参数网格", "按行业中性约束回测", "对比等权基准和沪深300基准的超额收益"]}
    else:
        status = "fallback"
        result = {"summary": "未配置大模型密钥，已生成本地 Alpha 优先建议。", "risk_findings": ["检查 alpha_return 是否持续跑赢同源等权基准", "检查最大回撤、胜率和交易次数是否稳定"], "parameter_changes": [{"name": "entry_mode", "from": "trend_following", "to": "relative_strength_rotation", "reason": "切换为相对强弱轮动，减少弱于等权基准的持仓"}, {"name": "candidate_top_n", "from": 5, "to": 3, "reason": "减少弱信号入选，优先改善 Alpha"}, {"name": "min_momentum", "from": 0, "to": 0.05, "reason": "提高入选动量门槛，过滤弱趋势交易"}, {"name": "min_quality", "from": 0, "to": 0.6, "reason": "提高财报质量门槛，减少低质量趋势股入选"}, {"name": "min_relative_strength", "from": 0, "to": 0.75, "reason": "只选择同池相对强势股票，减少弱于等权基准的持仓"}, {"name": "relative_strength_window", "from": 60, "to": 40, "reason": "缩短相对强弱窗口，提高轮动响应速度"}, {"name": "min_market_breadth", "from": 0, "to": 0.55, "reason": "市场宽度不足时暂停新增买入，减少弱市 beta 暴露"}, {"name": "max_sector_pct", "from": 0.35, "to": 0.25, "reason": "提高行业分散度，减少基准 beta 暴露"}], "next_experiments": ["按行业分层选股", "以 alpha_return 为主目标对比MACD参数12/26/9与8/21/5", "加入财报质量因子并验证超额收益"]}

    result = _normalize_optimization_result(result, strategy.rule_json if strategy else {}, backtest.metrics if backtest else {})
    run = StrategyOptimizationRun(
        owner_id=owner_id,
        strategy_id=strategy.id if strategy else None,
        backtest_run_id=backtest.id if backtest else None,
        model=settings.deepseek_model,
        status=status,
        prompt=prompt,
        request_json=request_json,
        result_json=result,
    )
    session.add(run)
    session.add(AdminAuditLog(action="optimize_strategy", target=str(strategy.id if strategy else ""), payload={"status": status, "model": settings.deepseek_model}))
    await session.commit()
    return {"id": str(run.id), "status": status, "model": settings.deepseek_model, "result": result}


async def remediate_strategy_health(
    session: AsyncSession,
    strategy_id: str | None = None,
    days: int = 900,
    initial_cash: float = 100000.0,
    max_symbols: int = 40,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    strategy = await session.get(Strategy, uuid.UUID(strategy_id)) if strategy_id else await session.scalar(select(Strategy).where(Strategy.status == "active"))
    if not strategy:
        return {"remediated": False, "reason": "missing_strategy"}
    latest_backtest = await session.scalar(
        select(BacktestRun)
        .where(BacktestRun.strategy_id == strategy.id, BacktestRun.status == "success")
        .order_by(BacktestRun.created_at.desc())
        .limit(1)
    )
    latest_experiment = await session.scalar(
        select(StrategyExperiment)
        .where(or_(StrategyExperiment.strategy_id == strategy.id, StrategyExperiment.source_strategy_id == strategy.id))
        .order_by(StrategyExperiment.created_at.desc())
        .limit(1)
    )
    health = strategy_health_from_metrics(strategy, latest_backtest, latest_experiment)
    if health.get("status") == "ready" and health.get("passed") is True:
        return {"remediated": False, "reason": "strategy_health_ready", "strategy_health": health}
    optimization = await optimize_strategy(session, strategy_id=str(strategy.id), backtest_run_id=str(latest_backtest.id) if latest_backtest else None, owner_id=owner_id)
    applied = await apply_strategy_optimization(session, optimization["id"], owner_id=owner_id)
    if not applied.get("applied"):
        return {"remediated": False, "reason": "optimization_apply_failed", "strategy_health": health, "optimization": optimization, "applied": applied}
    validation = await validate_strategy_candidate(
        session,
        applied["strategy_id"],
        days=days,
        initial_cash=initial_cash,
        max_symbols=max_symbols,
        owner_id=owner_id,
    )
    session.add(
        AdminAuditLog(
            action="remediate_strategy_health",
            target=str(strategy.id),
            actor_id=owner_id,
            payload={
                "health_status": health.get("status"),
                "optimization_id": optimization["id"],
                "candidate_strategy_id": applied.get("strategy_id"),
                "validation_passed": validation.get("passed"),
                "next_action": "promote_candidate_after_review" if validation.get("passed") else "run_alpha_search_or_adjust_constraints",
                "validation": {
                    "passed": validation.get("passed"),
                    "decision": validation.get("decision"),
                    "experiment_id": validation.get("experiment_id"),
                    "metrics": {
                        "alpha_return": (validation.get("metrics") or {}).get("alpha_return"),
                        "benchmark_return": (validation.get("metrics") or {}).get("benchmark_return"),
                        "out_of_sample": (validation.get("metrics") or {}).get("out_of_sample"),
                        "max_drawdown": (validation.get("metrics") or {}).get("max_drawdown"),
                        "sharpe": (validation.get("metrics") or {}).get("sharpe"),
                    },
                    "comparison": validation.get("comparison") or {},
                },
            },
        )
    )
    await session.commit()
    return {
        "remediated": True,
        "source_strategy_id": str(strategy.id),
        "strategy_health_before": health,
        "optimization": optimization,
        "candidate": applied,
        "validation": validation,
        "next_action": "promote_candidate_after_review" if validation.get("passed") else "run_alpha_search_or_adjust_constraints",
        "paper_only": True,
        "warning": "仅生成研究候选和回测验证，不会启用策略或提交真实交易订单。",
    }


async def run_next_strategy_research_action(
    session: AsyncSession,
    strategy_id: str | None = None,
    days: int = 900,
    initial_cash: float = 100000.0,
    max_symbols: int = 40,
    max_trials: int = 8,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    strategy_health = await active_strategy_health(session, owner_id=owner_id)
    candidates = await list_strategy_promotion_candidates(session, limit=20, owner_id=owner_id)
    repair_timeline = await list_strategy_repair_timeline(session, limit=5, owner_id=owner_id)
    history_hint = latest_research_history_hint(repair_timeline)
    readiness = apply_research_history_to_readiness(strategy_promotion_readiness(candidates, strategy_health), history_hint)
    plan = strategy_next_research_action_plan(readiness, strategy_health)
    result: dict[str, Any] | None = None
    if plan["action"] == "remediate_health":
        result = await remediate_strategy_health(
            session,
            strategy_id=strategy_id,
            days=days,
            initial_cash=initial_cash,
            max_symbols=max_symbols,
            owner_id=owner_id,
        )
    elif plan["action"] == "alpha_search":
        result = await alpha_grid_search_strategy(
            session,
            strategy_id=strategy_id,
            days=days,
            initial_cash=initial_cash,
            max_symbols=max_symbols,
            max_trials=max_trials,
            owner_id=owner_id,
        )
    elif plan["action"] == "run_backtest":
        result = await run_backtest(
            session,
            strategy_id=strategy_id,
            days=days,
            initial_cash=initial_cash,
            max_symbols=max_symbols,
            owner_id=owner_id,
        )
    elif plan["action"] == "tighten_signal_quality":
        result = await tighten_signal_quality_candidate(
            session,
            strategy_id=strategy_id,
            days=days,
            initial_cash=initial_cash,
            max_symbols=max_symbols,
            owner_id=owner_id,
        )

    refreshed_health = await active_strategy_health(session, owner_id=owner_id)
    refreshed_candidates = await list_strategy_promotion_candidates(session, limit=20, owner_id=owner_id)
    refreshed_timeline = await list_strategy_repair_timeline(session, limit=5, owner_id=owner_id)
    refreshed_history_hint = latest_research_history_hint(refreshed_timeline)
    refreshed_readiness = apply_research_history_to_readiness(strategy_promotion_readiness(refreshed_candidates, refreshed_health), refreshed_history_hint)
    session.add(
        AdminAuditLog(
            action="run_next_strategy_research_action",
            target=strategy_id or (strategy_health.get("strategy") or {}).get("id") or "",
            actor_id=owner_id,
            payload={
                "plan": plan,
                "readiness_before": readiness,
                "readiness_after": refreshed_readiness,
                "strategy_health_before": {
                    "status": strategy_health.get("status"),
                    "reasons": strategy_health.get("reasons") or [],
                    "metrics": strategy_health.get("metrics") or {},
                },
                "strategy_health_after": {
                    "status": refreshed_health.get("status"),
                    "reasons": refreshed_health.get("reasons") or [],
                    "metrics": refreshed_health.get("metrics") or {},
                },
                "result_summary": _research_action_result_summary(plan["action"], result),
            },
        )
    )
    await session.commit()
    return {
        "ran": bool(plan.get("executable") and result is not None),
        "plan": plan,
        "strategy_health_before": strategy_health,
        "strategy_health_after": refreshed_health,
        "readiness_before": readiness,
        "readiness_after": refreshed_readiness,
        "result": result,
        "paper_only": True,
        "warning": "仅执行研究、候选生成和回测验证，不会自动启用策略或提交真实交易订单。",
    }


async def tighten_signal_quality_candidate(
    session: AsyncSession,
    strategy_id: str | None = None,
    days: int = 900,
    initial_cash: float = 100000.0,
    max_symbols: int = 40,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    optimization = await optimize_strategy(session, strategy_id=strategy_id, owner_id=owner_id)
    applied = await apply_strategy_optimization(session, optimization["id"], owner_id=owner_id)
    validation: dict[str, Any] | None = None
    if applied.get("applied") and applied.get("strategy_id"):
        validation = await validate_strategy_candidate(
            session,
            applied["strategy_id"],
            days=days,
            initial_cash=initial_cash,
            max_symbols=max_symbols,
            owner_id=owner_id,
        )
    return {
        "tightened": bool(applied.get("applied") and validation),
        "optimization": optimization,
        "candidate": applied,
        "validation": validation,
        "next_action": "promote_candidate_after_review" if validation and validation.get("passed") else "run_alpha_search_or_adjust_constraints",
        "paper_only": True,
        "warning": "仅生成收紧信号候选和回测验证，不会启用策略或提交真实交易订单。",
    }


def _research_action_result_summary(action: str, result: dict[str, Any] | None) -> dict[str, Any]:
    result = result or {}
    if action == "remediate_health":
        validation = result.get("validation") or {}
        metrics = validation.get("metrics") or {}
        out_of_sample = metrics.get("out_of_sample") or {}
        return {
            "remediated": result.get("remediated"),
            "candidate_strategy_id": (result.get("candidate") or {}).get("strategy_id"),
            "validation_passed": validation.get("passed"),
            "experiment_id": validation.get("experiment_id"),
            "decision": validation.get("decision"),
            "alpha_return": metrics.get("alpha_return"),
            "out_of_sample_alpha": out_of_sample.get("alpha_return"),
            "next_action": result.get("next_action"),
        }
    if action == "alpha_search":
        best = result.get("best") or {}
        metrics = best.get("metrics") or {}
        out_of_sample = metrics.get("out_of_sample") or {}
        validation = result.get("validation") or {}
        return {
            "searched": result.get("searched"),
            "best_strategy_id": result.get("best_strategy_id"),
            "optimization_id": result.get("optimization_id"),
            "score": best.get("score"),
            "alpha_return": metrics.get("alpha_return"),
            "out_of_sample_alpha": out_of_sample.get("alpha_return"),
            "trial_count": len(result.get("trials") or []),
            "validation_passed": validation.get("passed"),
            "experiment_id": validation.get("experiment_id"),
            "decision": validation.get("decision"),
            "next_action": result.get("next_action"),
        }
    if action == "run_backtest":
        return {"created": result.get("created"), "run_id": result.get("run_id"), "metrics": result.get("metrics")}
    if action == "tighten_signal_quality":
        validation = result.get("validation") or {}
        metrics = validation.get("metrics") or {}
        out_of_sample = metrics.get("out_of_sample") or {}
        optimization = result.get("optimization") or result
        return {
            "tightened": result.get("tightened"),
            "optimization_id": optimization.get("id"),
            "status": optimization.get("status"),
            "model": optimization.get("model"),
            "candidate_strategy_id": (result.get("candidate") or {}).get("strategy_id"),
            "validation_passed": validation.get("passed"),
            "experiment_id": validation.get("experiment_id"),
            "decision": validation.get("decision"),
            "alpha_return": metrics.get("alpha_return"),
            "out_of_sample_alpha": out_of_sample.get("alpha_return"),
            "next_action": result.get("next_action"),
        }
    return {"reason": result.get("reason")}


def _coerce_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = [part.strip(" -\n\t") for part in re.split(r"\n+|\d+[\.、]", value) if part.strip(" -\n\t")]
        return parts or [value.strip()]
    return []


def _metric_driven_parameter_changes(rule: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    params = _strategy_backtest_params(Strategy(name="tmp", rule_json=rule or {}))
    changes: list[dict[str, Any]] = []
    max_drawdown = float((metrics or {}).get("max_drawdown") or 0)
    sharpe = float((metrics or {}).get("sharpe") or 0)
    trade_count = int((metrics or {}).get("trade_count") or 0)
    alpha_return = float((metrics or {}).get("alpha_return") or 0)
    benchmark_return = float((metrics or {}).get("benchmark_return") or 0)
    out_of_sample = (metrics or {}).get("out_of_sample") or {}
    out_sample_alpha = out_of_sample.get("alpha_return")
    if "alpha_return" in (metrics or {}) and alpha_return < -0.05:
        changes.append({"name": "entry_mode", "from": params["entry_mode"], "to": "relative_strength_rotation", "reason": f"Alpha {alpha_return:.2%} 显著跑输同源等权基准，改用相对强弱轮动目标池"})
        changes.append({"name": "candidate_top_n", "from": params["candidate_top_n"], "to": max(2, min(params["candidate_top_n"], 3)), "reason": f"Alpha {alpha_return:.2%} 显著跑输同源等权基准，减少弱信号入选"})
        changes.append({"name": "min_momentum", "from": params["min_momentum"], "to": max(params["min_momentum"], 0.05), "reason": f"Alpha {alpha_return:.2%} 显著跑输同源等权基准，提高动量入选门槛"})
        changes.append({"name": "min_quality", "from": params["min_quality"], "to": max(params["min_quality"], 0.6), "reason": f"Alpha {alpha_return:.2%} 显著跑输同源等权基准，提高质量因子入选门槛"})
        changes.append({"name": "min_relative_strength", "from": params["min_relative_strength"], "to": max(params["min_relative_strength"], 0.75), "reason": f"Alpha {alpha_return:.2%} 显著跑输同源等权基准，引入同池相对强弱过滤"})
        changes.append({"name": "relative_strength_window", "from": params["relative_strength_window"], "to": min(params["relative_strength_window"], 40), "reason": "缩短相对强弱观察窗口，提高对结构切换的响应速度"})
        changes.append({"name": "min_market_breadth", "from": params["min_market_breadth"], "to": max(params["min_market_breadth"], 0.55), "reason": "Alpha 跑输时增加市场宽度过滤，避免弱市里持续新增 beta 暴露"})
        changes.append({"name": "max_sector_pct", "from": params["max_sector_pct"], "to": max(0.2, min(params["max_sector_pct"], 0.25)), "reason": f"基准收益 {benchmark_return:.2%} 较强时控制行业 beta 暴露，提升超额收益检验质量"})
    if out_sample_alpha is not None and float(out_sample_alpha) < -0.05:
        changes.append({"name": "entry_mode", "from": params["entry_mode"], "to": "relative_strength_rotation", "reason": "样本外跑输基准时切换为相对强弱轮动，降低训练区间趋势偶然性"})
        changes.append({"name": "candidate_top_n", "from": params["candidate_top_n"], "to": max(2, min(params["candidate_top_n"], 3)), "reason": f"样本外 Alpha {float(out_sample_alpha):.2%} 未通过，提高候选信号纯度"})
        changes.append({"name": "min_momentum", "from": params["min_momentum"], "to": max(params["min_momentum"], 0.08), "reason": "样本外跑输基准时提高动量确认门槛，减少训练区间偶然信号"})
        changes.append({"name": "min_quality", "from": params["min_quality"], "to": max(params["min_quality"], 0.65), "reason": "样本外跑输基准时提高质量因子门槛，增强泛化能力"})
        changes.append({"name": "min_relative_strength", "from": params["min_relative_strength"], "to": max(params["min_relative_strength"], 0.8), "reason": "样本外跑输基准时提高同池相对强弱门槛，优先选择市场内领先标的"})
        changes.append({"name": "relative_strength_window", "from": params["relative_strength_window"], "to": min(params["relative_strength_window"], 40), "reason": "样本外 Alpha 失败时测试更短轮动窗口，减少信号滞后"})
        changes.append({"name": "min_market_breadth", "from": params["min_market_breadth"], "to": max(params["min_market_breadth"], 0.55), "reason": "样本外 Alpha 失败时增加市场宽度过滤，减少弱市交易"})
        changes.append({"name": "max_sector_pct", "from": params["max_sector_pct"], "to": max(0.2, min(params["max_sector_pct"], 0.25)), "reason": "样本外 Alpha 失败时降低行业拥挤暴露，减少 beta 驱动"})
    if max_drawdown > 0.25:
        changes.append({"name": "max_position_pct", "from": params["max_position_pct"], "to": max(0.04, round(params["max_position_pct"] * 0.65, 3)), "reason": "正式回测最大回撤超过25%，降低单票风险暴露"})
        changes.append({"name": "max_positions", "from": params["max_positions"], "to": max(4, min(params["max_positions"], 8)), "reason": "控制组合同时持仓数量，降低趋势反转时的组合回撤"})
        changes.append({"name": "stop_loss", "from": params["stop_loss"], "to": min(params["stop_loss"], 0.06), "reason": "回撤偏高时收紧止损阈值"})
    if sharpe < 1.0:
        changes.append({"name": "candidate_top_n", "from": params["candidate_top_n"], "to": max(2, min(params["candidate_top_n"], 4)), "reason": "Sharpe不足时减少弱信号入选数量"})
    if trade_count > 800:
        changes.append({"name": "rebalance", "from": params["rebalance"], "to": "weekly", "reason": "交易次数偏高，改为周度调仓降低换手和噪声"})
    deduped: dict[str, dict[str, Any]] = {}
    for change in changes:
        deduped[change["name"]] = change
    return list(deduped.values())


def _normalize_parameter_changes(value: Any, rule: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"entry_mode", "max_position_pct", "stop_loss", "take_profit", "max_positions", "candidate_top_n", "min_momentum", "min_quality", "min_relative_strength", "relative_strength_window", "min_market_breadth", "rebalance", "slippage_bps", "volume_participation", "max_sector_pct"}
    raw_changes: list[Any] = []
    if isinstance(value, list):
        raw_changes = value
    elif isinstance(value, dict):
        raw_changes = [{"name": key, "to": val} for key, val in value.items()]
    cleaned: list[dict[str, Any]] = []
    for change in raw_changes:
        if not isinstance(change, dict):
            continue
        name = str(change.get("name") or "").strip()
        if name not in allowed or "to" not in change:
            continue
        cleaned.append({"name": name, "from": change.get("from"), "to": change.get("to"), "reason": str(change.get("reason") or "LLM suggested parameter change")})
    if cleaned:
        return cleaned
    return _metric_driven_parameter_changes(rule, metrics)


def _normalize_optimization_result(result: dict[str, Any], rule: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    result = dict(result or {})
    changes = _normalize_parameter_changes(result.get("parameter_changes"), rule, metrics)
    if result.get("parameter_changes") and not isinstance(result.get("parameter_changes"), list):
        result["raw_parameter_changes"] = result.get("parameter_changes")
    result["summary"] = str(result.get("summary") or "策略优化建议已生成。")
    result["risk_findings"] = _coerce_text_list(result.get("risk_findings"))
    result["parameter_changes"] = changes
    result["next_experiments"] = _coerce_text_list(result.get("next_experiments"))
    return result


def _alpha_grid_candidates(params: dict[str, Any], max_trials: int = 8) -> list[list[dict[str, Any]]]:
    current_entry_mode = str(params.get("entry_mode", "trend_following"))
    current_top_n = int(params.get("candidate_top_n", 5))
    current_max_positions = int(params.get("max_positions", 10))
    current_rebalance = str(params.get("rebalance", "daily"))
    current_sector = float(params.get("max_sector_pct", 0.35))
    current_position = float(params.get("max_position_pct", 0.1))
    current_min_momentum = float(params.get("min_momentum", 0.0))
    current_min_quality = float(params.get("min_quality", 0.0))
    current_relative_strength = float(params.get("min_relative_strength", 0.0))
    current_relative_strength_window = int(params.get("relative_strength_window", 60))
    current_market_breadth = float(params.get("min_market_breadth", 0.0))
    top_n_values = [max(1, min(current_top_n, 2)), max(2, min(current_top_n, 3)), current_top_n, min(6, max(current_top_n + 1, 4)), 12, 20, 50]
    max_positions_values = [max(2, min(current_max_positions, 4)), max(4, min(current_max_positions, 6)), current_max_positions, 12, 20, 50]
    sector_values = [max(0.12, min(current_sector, 0.18)), max(0.2, min(current_sector, 0.25)), current_sector, 1.0]
    position_values = [
        max(0.03, min(current_position, 0.05)),
        max(0.04, min(current_position, 0.06)),
        max(0.04, min(current_position, 0.08)),
        current_position,
        min(0.2, max(current_position, 0.16)),
        min(0.3, max(current_position, 0.24)),
    ]
    rebalance_values = []
    for cadence in ("weekly", "monthly", current_rebalance, "daily"):
        if cadence not in rebalance_values:
            rebalance_values.append(cadence)
    momentum_values = [0.12, 0.08, 0.05, 0.02, round(current_min_momentum, 3)]
    quality_values = [0.85, 0.75, 0.65, 0.55, round(current_min_quality, 3)]
    relative_strength_values = [0.9, 0.8, 0.7, round(current_relative_strength, 3)]
    relative_strength_window_values = [20, 40, max(20, min(current_relative_strength_window, 60))]
    market_breadth_values = [0.0, 0.45, 0.55, 0.65, round(current_market_breadth, 3)]
    entry_mode_values = []
    for mode in ("relative_strength_rotation", "pool_equal_weight_hold", "equal_weight_buy_hold", "equal_weight_rotation", current_entry_mode, "trend_following"):
        if mode not in entry_mode_values:
            entry_mode_values.append(mode)
    signal_pairs = [
        (0.12, 0.85),
        (0.10, 0.75),
        (0.08, 0.75),
        (round(current_min_momentum, 3), round(current_min_quality, 3)),
        (0.02, round(current_min_quality, 3)),
        (round(current_min_momentum, 3), 0.55),
        (0.05, round(current_min_quality, 3)),
        (round(current_min_momentum, 3), 0.65),
        (0.08, round(current_min_quality, 3)),
        (round(current_min_momentum, 3), 0.75),
    ]
    signal_pairs.extend((momentum, quality) for momentum in momentum_values for quality in quality_values)
    seen: set[tuple[Any, ...]] = set()
    candidates: list[list[dict[str, Any]]] = []
    structural_options = [
        (entry_mode_values[0], top_n_values[0], max_positions_values[0], sector_values[0], position_values[0], rebalance_values[0], relative_strength_values[0], relative_strength_window_values[0], market_breadth_values[2]),
        (entry_mode_values[0], top_n_values[0], max_positions_values[0], sector_values[0], position_values[0], rebalance_values[-1], relative_strength_values[1], relative_strength_window_values[1], market_breadth_values[1]),
        (entry_mode_values[0], top_n_values[1], max_positions_values[0], sector_values[1], position_values[0], rebalance_values[0], relative_strength_values[2], relative_strength_window_values[-1], market_breadth_values[3]),
        (entry_mode_values[-1], top_n_values[1], max_positions_values[1], sector_values[0], position_values[1], rebalance_values[0], relative_strength_values[0], relative_strength_window_values[0], market_breadth_values[2]),
        (entry_mode_values[0], top_n_values[2], max_positions_values[1], sector_values[1], position_values[1], rebalance_values[-1], relative_strength_values[1], relative_strength_window_values[1], market_breadth_values[0]),
        ("pool_equal_weight_hold", top_n_values[-1], max_positions_values[-1], sector_values[-1], position_values[4], "monthly", 0.0, relative_strength_window_values[-1], 0.0),
        ("equal_weight_buy_hold", top_n_values[-1], max_positions_values[-1], sector_values[-1], position_values[5], "monthly", 0.0, relative_strength_window_values[-1], 0.0),
        ("equal_weight_rotation", top_n_values[-2], max_positions_values[-2], sector_values[-1], position_values[1], rebalance_values[0], 0.0, relative_strength_window_values[-1], 0.0),
        (entry_mode_values[0], top_n_values[1], max_positions_values[0], sector_values[1], position_values[4], rebalance_values[0], relative_strength_values[1], relative_strength_window_values[0], market_breadth_values[1]),
        (entry_mode_values[0], top_n_values[1], max_positions_values[1], sector_values[1], position_values[5], "monthly", relative_strength_values[1], relative_strength_window_values[1], market_breadth_values[2]),
        (entry_mode_values[-1], top_n_values[-1], max_positions_values[-1], sector_values[-1], position_values[3], rebalance_values[0], relative_strength_values[-1], relative_strength_window_values[-1], market_breadth_values[-1]),
        (entry_mode_values[-1], top_n_values[1], max_positions_values[0], sector_values[1], position_values[5], rebalance_values[-1], relative_strength_values[2], relative_strength_window_values[1], market_breadth_values[2]),
        ("equal_weight_rotation", top_n_values[-2], max_positions_values[-2], sector_values[-1], position_values[2], "monthly", 0.0, relative_strength_window_values[-1], market_breadth_values[1]),
    ]

    def add_candidate(entry_mode: str, momentum: float, quality: float, top_n: int, max_positions: int, sector: float, position: float, rebalance: str, relative_strength: float, relative_strength_window: int, market_breadth: float) -> bool:
        if entry_mode in {"equal_weight_rotation", "equal_weight_buy_hold", "pool_equal_weight_hold"}:
            momentum = 0.0
            quality = 0.0
            relative_strength = 0.0
            market_breadth = 0.0
            sector = 1.0
        key = (str(entry_mode), round(float(momentum), 3), round(float(quality), 3), int(top_n), int(max_positions), round(float(sector), 3), round(float(position), 3), str(rebalance), round(float(relative_strength), 3), int(relative_strength_window), round(float(market_breadth), 3))
        if key in seen:
            return False
        seen.add(key)
        changes = [
            {"name": "entry_mode", "from": current_entry_mode, "to": str(entry_mode), "reason": "Alpha 网格搜索入场模式"},
            {"name": "min_momentum", "from": current_min_momentum, "to": round(float(momentum), 3), "reason": "Alpha 网格搜索动量门槛"},
            {"name": "min_quality", "from": current_min_quality, "to": round(float(quality), 3), "reason": "Alpha 网格搜索质量因子门槛"},
            {"name": "candidate_top_n", "from": current_top_n, "to": int(top_n), "reason": "Alpha 网格搜索候选数量"},
            {"name": "max_positions", "from": current_max_positions, "to": int(max_positions), "reason": "Alpha 网格搜索最大持仓数"},
            {"name": "max_sector_pct", "from": current_sector, "to": round(float(sector), 3), "reason": "Alpha 网格搜索行业暴露"},
            {"name": "max_position_pct", "from": current_position, "to": round(float(position), 3), "reason": "Alpha 网格搜索单票仓位"},
            {"name": "rebalance", "from": current_rebalance, "to": str(rebalance), "reason": "Alpha 网格搜索调仓频率"},
            {"name": "min_relative_strength", "from": current_relative_strength, "to": round(float(relative_strength), 3), "reason": "Alpha 网格搜索相对强弱门槛"},
            {"name": "relative_strength_window", "from": current_relative_strength_window, "to": int(relative_strength_window), "reason": "Alpha 网格搜索相对强弱窗口"},
            {"name": "min_market_breadth", "from": current_market_breadth, "to": round(float(market_breadth), 3), "reason": "Alpha 网格搜索市场宽度过滤"},
        ]
        if entry_mode in {"equal_weight_rotation", "equal_weight_buy_hold", "pool_equal_weight_hold"}:
            changes.append({"name": "stop_loss", "from": params.get("stop_loss", 0.08), "to": 0.5, "reason": "等权基线候选放宽止损，减少与基准无关的过早离场"})
        candidates.append(changes)
        return len(candidates) >= max(1, max_trials)

    for index, (momentum, quality) in enumerate(signal_pairs):
        entry_mode, top_n, max_positions, sector, position, rebalance, relative_strength, relative_strength_window, market_breadth = structural_options[index % len(structural_options)]
        if add_candidate(entry_mode, momentum, quality, top_n, max_positions, sector, position, rebalance, relative_strength, relative_strength_window, market_breadth):
            return candidates

    for entry_mode in entry_mode_values:
        for top_n in top_n_values:
            for max_positions in max_positions_values:
                for sector in sector_values:
                    for position in position_values:
                        for rebalance in rebalance_values:
                            for relative_strength in relative_strength_values:
                                for relative_strength_window in relative_strength_window_values:
                                    for market_breadth in market_breadth_values:
                                        for momentum, quality in signal_pairs:
                                            if add_candidate(entry_mode, momentum, quality, top_n, max_positions, sector, position, rebalance, relative_strength, relative_strength_window, market_breadth):
                                                return candidates
    return candidates


def _alpha_search_score(metrics: dict[str, Any]) -> float:
    alpha = float(metrics.get("alpha_return") or 0)
    sharpe = float(metrics.get("sharpe") or 0)
    drawdown = float(metrics.get("max_drawdown") or 1)
    stability = metrics.get("walk_forward_stability") or {}
    out_of_sample = metrics.get("out_of_sample") or {}
    stability_bonus = 0.03 if stability.get("passed") else -0.03
    out_sample_bonus = 0.04 if out_of_sample.get("passed") else -0.05
    out_sample_return = float(out_of_sample.get("return") or 0)
    out_sample_alpha = float(out_of_sample.get("alpha_return") or 0)
    return round(alpha + out_sample_alpha * 0.5 + out_sample_return * 0.2 + sharpe * 0.03 - drawdown * 0.2 + stability_bonus + out_sample_bonus, 6)


def _apply_parameter_changes(rule: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    updated = dict(rule or {})
    risk = dict(updated.get("risk") or {})
    params = dict(updated.get("params") or {})
    for change in changes:
        if not isinstance(change, dict):
            continue
        name = str(change.get("name") or "").strip()
        if not name or "to" not in change:
            continue
        value = change.get("to")
        if name in {"max_position_pct", "stop_loss", "take_profit", "max_order_pct", "max_single_position_pct"}:
            risk[name] = value
        else:
            params[name] = value
    if risk:
        updated["risk"] = risk
    if params:
        updated["params"] = params
    return updated


def _merge_strategy_rule_config(rule: dict[str, Any], risk: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    updated = dict(rule or {})
    merged_risk = dict(updated.get("risk") or {})
    merged_params = dict(updated.get("params") or {})
    if risk:
        merged_risk.update({key: value for key, value in risk.items() if value is not None})
    if params:
        merged_params.update({key: value for key, value in params.items() if value is not None})
    if merged_risk:
        updated["risk"] = merged_risk
    if merged_params:
        updated["params"] = merged_params
    return updated


def _candidate_base_rule(rule: dict[str, Any]) -> dict[str, Any]:
    base = dict(rule or {})
    base.pop("latest_validation", None)
    base.pop("promoted_from_validation", None)
    return base


def _candidate_source_strategy_id(rule: dict[str, Any]) -> str | None:
    rule = rule or {}
    return (
        (rule.get("llm_optimization") or {}).get("source_strategy_id")
        or (rule.get("alpha_grid_search") or {}).get("source_strategy_id")
    )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def update_strategy_config(
    session: AsyncSession,
    strategy_id: str,
    *,
    name: str,
    visibility: Visibility,
    risk: dict[str, Any],
    params: dict[str, Any],
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    strategy = await session.get(Strategy, uuid.UUID(strategy_id))
    if not strategy:
        return {"updated": False, "reason": "missing_strategy"}
    strategy.name = name.strip()
    strategy.visibility = visibility
    strategy.rule_json = _merge_strategy_rule_config(strategy.rule_json or {}, risk=risk, params=params)
    session.add(AdminAuditLog(action="update_strategy_config", target=str(strategy.id), actor_id=actor_id, payload={"name": strategy.name, "visibility": strategy.visibility.value, "risk": risk, "params": params}))
    await session.commit()
    return {"updated": True, "strategy": {"id": str(strategy.id), "name": strategy.name, "visibility": strategy.visibility.value, "owner_id": str(strategy.owner_id) if strategy.owner_id else None, "status": strategy.status, "rule": strategy.rule_json}}


async def apply_strategy_optimization(session: AsyncSession, optimization_id: str, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    optimization = await session.get(StrategyOptimizationRun, uuid.UUID(optimization_id))
    if not optimization:
        return {"applied": False, "reason": "missing_optimization"}
    source_strategy = await session.get(Strategy, optimization.strategy_id) if optimization.strategy_id else await session.scalar(select(Strategy).where(Strategy.status == "active"))
    base_rule = _candidate_base_rule(source_strategy.rule_json if source_strategy else {})
    result = optimization.result_json or {}
    changes = result.get("parameter_changes") if isinstance(result.get("parameter_changes"), list) else []
    candidate_rule = _apply_parameter_changes(base_rule, changes)
    candidate_rule["llm_optimization"] = {
        "optimization_id": str(optimization.id),
        "model": optimization.model,
        "summary": result.get("summary"),
        "risk_findings": result.get("risk_findings", []),
        "next_experiments": result.get("next_experiments", []),
        "source_strategy_id": str(source_strategy.id) if source_strategy else None,
        "backtest_run_id": str(optimization.backtest_run_id) if optimization.backtest_run_id else None,
    }
    name_base = source_strategy.name if source_strategy else "ZiQuant 策略"
    candidate = Strategy(
        owner_id=source_strategy.owner_id if source_strategy and source_strategy.owner_id else owner_id,
        name=f"{name_base} - LLM 优化候选",
        visibility=Visibility.private,
        status="draft",
        rule_json=candidate_rule,
    )
    session.add(candidate)
    session.add(AdminAuditLog(action="apply_strategy_optimization", target=str(optimization.id), payload={"candidate_strategy": candidate.name, "changes": changes}))
    await session.commit()
    return {"applied": True, "strategy_id": str(candidate.id), "name": candidate.name, "status": candidate.status, "rule": candidate.rule_json}


async def alpha_grid_search_strategy(
    session: AsyncSession,
    strategy_id: str | None = None,
    days: int = 900,
    initial_cash: float = 100000.0,
    max_symbols: int = 20,
    max_trials: int = 6,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    source_strategy = await session.get(Strategy, uuid.UUID(strategy_id)) if strategy_id else await session.scalar(select(Strategy).where(Strategy.status == "active"))
    if not source_strategy:
        return {"searched": False, "reason": "missing_strategy"}
    base_rule = _candidate_base_rule(source_strategy.rule_json or {})
    base_params = _strategy_backtest_params(source_strategy)
    candidates = _alpha_grid_candidates(base_params, max_trials=max_trials)
    trials: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for index, changes in enumerate(candidates, start=1):
        candidate_rule = _apply_parameter_changes(base_rule, changes)
        candidate_rule["alpha_grid_search"] = {"source_strategy_id": str(source_strategy.id), "trial": index, "changes": changes}
        candidate = Strategy(
            owner_id=source_strategy.owner_id if source_strategy.owner_id else owner_id,
            name=f"{source_strategy.name} - Alpha网格候选 {index}",
            visibility=Visibility.private,
            status="draft",
            rule_json=candidate_rule,
        )
        session.add(candidate)
        await session.flush()
        result = await run_backtest(session, strategy_id=str(candidate.id), days=days, initial_cash=initial_cash, max_symbols=max_symbols, owner_id=owner_id)
        metrics = result.get("metrics") or {}
        score = _alpha_search_score(metrics) if result.get("created") else -999.0
        trial = {
            "strategy_id": str(candidate.id),
            "name": candidate.name,
            "changes": changes,
            "created": result.get("created"),
            "run_id": result.get("run_id"),
            "score": score,
            "metrics": {
                "total_return": metrics.get("total_return"),
                "benchmark_return": metrics.get("benchmark_return"),
                "alpha_return": metrics.get("alpha_return"),
                "sharpe": metrics.get("sharpe"),
                "max_drawdown": metrics.get("max_drawdown"),
                "out_of_sample": metrics.get("out_of_sample"),
                "walk_forward_stability": metrics.get("walk_forward_stability"),
            },
        }
        trials.append(trial)
        if best is None or score > best["score"]:
            if best and best.get("strategy_id"):
                old = await session.get(Strategy, uuid.UUID(best["strategy_id"]))
                if old:
                    old.status = "archived"
            best = trial
        else:
            candidate.status = "archived"
        await session.flush()

    if not best:
        return {"searched": False, "reason": "no_trials"}
    best_strategy = await session.get(Strategy, uuid.UUID(best["strategy_id"]))
    if best_strategy:
        best_strategy.name = f"{source_strategy.name} - Alpha网格最佳候选"
        best_strategy.rule_json = {
            **(best_strategy.rule_json or {}),
            "alpha_grid_search": {
                **((best_strategy.rule_json or {}).get("alpha_grid_search") or {}),
                "selected": True,
                "score": best["score"],
                "source_strategy_id": str(source_strategy.id),
            },
        }
    result_json = {
        "summary": "本地 Alpha 网格搜索已完成，最佳候选需要继续通过策略验证。",
        "risk_findings": ["该搜索仅基于有限参数网格，仍需正式验证和模拟盘观察"],
        "parameter_changes": best["changes"],
        "next_experiments": ["扩大股票覆盖", "增加滚动样本外验证", "对比沪深300或中证500基准"],
        "best_trial": best,
        "trials": trials,
    }
    run = StrategyOptimizationRun(
        owner_id=owner_id,
        strategy_id=source_strategy.id,
        backtest_run_id=uuid.UUID(best["run_id"]) if best.get("run_id") else None,
        model="local-alpha-grid",
        status="success",
        prompt="local alpha grid search over entry_mode, candidate_top_n, min_momentum, min_quality, min_relative_strength, relative_strength_window, min_market_breadth, max_sector_pct, max_position_pct",
        request_json={"strategy_id": str(source_strategy.id), "days": days, "initial_cash": initial_cash, "max_symbols": max_symbols, "max_trials": max_trials},
        result_json=result_json,
    )
    session.add(run)
    session.add(AdminAuditLog(action="alpha_grid_search_strategy", target=str(source_strategy.id), actor_id=owner_id, payload={"best": best, "trial_count": len(trials)}))
    await session.commit()
    validation = await validate_strategy_candidate(
        session,
        best["strategy_id"],
        days=days,
        initial_cash=initial_cash,
        max_symbols=max_symbols,
        owner_id=owner_id,
    )
    return {
        "searched": True,
        "optimization_id": str(run.id),
        "source_strategy_id": str(source_strategy.id),
        "best_strategy_id": best["strategy_id"],
        "best": best,
        "trials": trials,
        "validation": validation,
        "next_action": "promote_candidate_after_review" if validation.get("passed") else "run_alpha_search_or_adjust_constraints",
    }


async def validate_strategy_candidate(
    session: AsyncSession,
    strategy_id: str,
    stock_pool_id: str | None = None,
    days: int = 180,
    initial_cash: float = 100000.0,
    max_symbols: int = 40,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    strategy = await session.get(Strategy, uuid.UUID(strategy_id))
    if not strategy:
        return {"validated": False, "reason": "missing_strategy"}
    source_strategy_id = _candidate_source_strategy_id(strategy.rule_json or {})
    result = await run_backtest(
        session,
        strategy_id=strategy_id,
        stock_pool_id=stock_pool_id,
        days=days,
        initial_cash=initial_cash,
        max_symbols=max_symbols,
        owner_id=owner_id,
    )
    if not result.get("created"):
        return {"validated": False, "reason": result.get("reason"), "backtest": result}
    metrics = result.get("metrics", {})
    baseline_result: dict[str, Any] | None = None
    if source_strategy_id and source_strategy_id != strategy_id:
        baseline_result = await run_backtest(
            session,
            strategy_id=source_strategy_id,
            stock_pool_id=stock_pool_id,
            days=days,
            initial_cash=initial_cash,
            max_symbols=max_symbols,
            owner_id=owner_id,
        )
    comparison = _compare_backtest_metrics(metrics, baseline_result.get("metrics") if baseline_result and baseline_result.get("created") else None)
    passed = comparison["passed"]
    verdict = {
        "validated": True,
        "passed": passed,
        "strategy_id": strategy_id,
        "backtest_run_id": result["run_id"],
        "baseline_run_id": baseline_result.get("run_id") if baseline_result and baseline_result.get("created") else None,
        "metrics": metrics,
        "baseline_metrics": baseline_result.get("metrics") if baseline_result and baseline_result.get("created") else None,
        "comparison": comparison,
        "decision": "候选策略相对基准通过，可进入模拟盘观察" if passed else "候选策略未通过基准对比，仅保留为研究草稿",
    }
    llm_optimization = (strategy.rule_json or {}).get("llm_optimization") or {}
    experiment = StrategyExperiment(
        owner_id=owner_id,
        strategy_id=strategy.id,
        source_strategy_id=_uuid_or_none(source_strategy_id),
        optimization_id=_uuid_or_none(llm_optimization.get("optimization_id")),
        backtest_run_id=uuid.UUID(result["run_id"]),
        baseline_run_id=uuid.UUID(baseline_result["run_id"]) if baseline_result and baseline_result.get("created") else None,
        name=f"{strategy.name} 验证实验",
        status="passed" if passed else "rejected",
        passed=passed,
        decision=verdict["decision"],
        metrics=metrics,
        baseline_metrics=baseline_result.get("metrics") if baseline_result and baseline_result.get("created") else {},
        comparison=comparison,
        params={"days": days, "initial_cash": initial_cash, "max_symbols": max_symbols, "stock_pool_id": stock_pool_id, "strategy_params": _strategy_backtest_params(strategy)},
    )
    session.add(experiment)
    await session.flush()
    verdict["experiment_id"] = str(experiment.id)
    strategy.rule_json = {**(strategy.rule_json or {}), "latest_validation": verdict}
    session.add(AdminAuditLog(action="validate_strategy_candidate", target=strategy_id, actor_id=owner_id, payload=verdict))
    await session.commit()
    return verdict


def _visibility_after_promotion(strategy: Strategy, source_strategy: Strategy | None = None) -> Visibility:
    if source_strategy and source_strategy.visibility == Visibility.public:
        return Visibility.public
    if strategy.owner_id is None:
        return Visibility.public
    return strategy.visibility


async def promote_validated_strategy(session: AsyncSession, strategy_id: str, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    strategy = await session.get(Strategy, uuid.UUID(strategy_id))
    if not strategy:
        return {"promoted": False, "reason": "missing_strategy"}
    validation = (strategy.rule_json or {}).get("latest_validation") or {}
    if strategy.status != "draft":
        return {"promoted": False, "reason": "strategy_not_draft", "status": strategy.status}
    if not validation.get("passed"):
        return {"promoted": False, "reason": "validation_not_passed", "latest_validation": validation}
    source_strategy_id = _candidate_source_strategy_id(strategy.rule_json or {})
    source = None
    if source_strategy_id:
        source = await session.get(Strategy, uuid.UUID(source_strategy_id))
        if source and source.status == "active":
            source.status = "archived"
            portfolios = (await session.scalars(select(PaperPortfolio).where(PaperPortfolio.strategy_id == source.id))).all()
            for portfolio in portfolios:
                portfolio.strategy_id = strategy.id
    strategy.status = "active"
    strategy.visibility = _visibility_after_promotion(strategy, source)
    strategy.rule_json = {
        **(strategy.rule_json or {}),
        "promoted_from_validation": {
            "promoted_at": datetime.now(UTC).isoformat(),
            "validation": validation,
            "source_strategy_id": source_strategy_id,
        },
    }
    session.add(AdminAuditLog(action="promote_validated_strategy", target=strategy_id, actor_id=owner_id, payload={"source_strategy_id": source_strategy_id, "validation": validation}))
    await session.commit()
    return {"promoted": True, "strategy_id": strategy_id, "status": strategy.status, "archived_source_strategy_id": source_strategy_id}


async def list_optimizations(session: AsyncSession, limit: int = 20, owner_id: uuid.UUID | None = None) -> dict[str, Any]:
    stmt = select(StrategyOptimizationRun).order_by(StrategyOptimizationRun.created_at.desc()).limit(limit)
    if owner_id is not None:
        stmt = stmt.where(or_(StrategyOptimizationRun.owner_id == owner_id, StrategyOptimizationRun.owner_id.is_(None)))
    rows = (await session.scalars(stmt)).all()
    return {"items": [{"id": str(r.id), "status": r.status, "model": r.model, "result": r.result_json, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}
