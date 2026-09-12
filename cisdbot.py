"""
CISD BOT v6.0-bybit — Bybit USDT linear, 10 пар × tf7+tf8, SHADOW/LIVE
====================================================================
Стратегия ТЗ v6: LIMIT-only на cisd_level, TP=1R, vwap-фильтр, 1 поз/пара, max 7.
По умолчанию SHADOW (dry_run): реальные котировки, виртуальные сделки, ордеров нет.
Не запускать вместе с MEXC-cisdbot: один TELEGRAM_TOKEN.
Деплой: /opt/cisdbotbybit, systemd cisdbotbybit.service, SSH-хост cisdbotbybit.
  /resume /start — запустить сканер
  /stop   — пауза или полная остановка
  /mode   — SHADOW ↔ LIVE (с подтверждением); /paper — алиас
  /status /stats /pairs
"""

import asyncio
import ccxt
import gzip
import hashlib
import json
import logging
import math
import logging.handlers
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

import ctl_server


def _load_env_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ============================================================
# РЕЖИМ БОТА  ← начальные значения, меняются командами /resume /paper
# ============================================================
PAPER_TRADING = True   # True = SHADOW (dry_run). False = LIVE, только с ключами Bybit

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
BYBIT_API_KEY    = os.environ.get("BYBIT_API_KEY", "").strip()
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "").strip()

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0") or "0")

SYMBOL = "BTC/USDT:USDT"  # legacy; для скриптов — см. active_symbol()

# qtyStep / tickSize сверены с Bybit GET /v5/market/instruments-info (linear) 08.09.2026
_BYBIT_FEES = {"maker_fee": 0.00036, "taker_fee": 0.001}

SYMBOL_PROFILES: dict[str, dict] = {
    "SOL": {
        "symbol": "SOL/USDT:USDT",
        "label": "SOL/USDT",
        "contract_value": 0.1,
        "price_tick": 0.01,
        "sweep_bucket": 1.0,
        **_BYBIT_FEES,
    },
    "BTC": {
        "symbol": "BTC/USDT:USDT",
        "label": "BTC/USDT",
        "contract_value": 0.001,
        "price_tick": 0.1,
        "sweep_bucket": 10.0,
        **_BYBIT_FEES,
    },
    "ETH": {
        "symbol": "ETH/USDT:USDT",
        "label": "ETH/USDT",
        "contract_value": 0.01,
        "price_tick": 0.01,
        "sweep_bucket": 1.0,
        **_BYBIT_FEES,
    },
    "DOGE": {
        "symbol": "DOGE/USDT:USDT",
        "label": "DOGE/USDT",
        "contract_value": 1.0,
        "price_tick": 0.00001,
        "sweep_bucket": 0.001,
        **_BYBIT_FEES,
    },
    "KAS": {
        "symbol": "KAS/USDT:USDT",
        "label": "KAS/USDT",
        "contract_value": 10.0,
        "price_tick": 0.00001,
        "sweep_bucket": 0.001,
        **_BYBIT_FEES,
    },
    "ADA": {
        "symbol": "ADA/USDT:USDT",
        "label": "ADA/USDT",
        "contract_value": 1.0,
        "price_tick": 0.0001,
        "sweep_bucket": 0.001,
        **_BYBIT_FEES,
    },
    "BNB": {
        "symbol": "BNB/USDT:USDT",
        "label": "BNB/USDT",
        "contract_value": 0.01,
        "price_tick": 0.1,
        "sweep_bucket": 0.1,
        **_BYBIT_FEES,
    },
    "LINK": {
        "symbol": "LINK/USDT:USDT",
        "label": "LINK/USDT",
        "contract_value": 0.1,
        "price_tick": 0.001,
        "sweep_bucket": 0.01,
        **_BYBIT_FEES,
    },
    "LTC": {
        "symbol": "LTC/USDT:USDT",
        "label": "LTC/USDT",
        "contract_value": 0.1,
        "price_tick": 0.01,
        "sweep_bucket": 0.1,
        **_BYBIT_FEES,
    },
    "XRP": {
        "symbol": "XRP/USDT:USDT",
        "label": "XRP/USDT",
        "contract_value": 0.1,
        "price_tick": 0.0001,
        "sweep_bucket": 0.001,
        **_BYBIT_FEES,
    },
}
DEFAULT_SYMBOL_KEY = "SOL"
ACTIVE_SYMBOL_KEYS = (
    "SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP",
)
_CCXT_TO_SYMBOL_KEY = {p["symbol"]: k for k, p in SYMBOL_PROFILES.items()}

CONFIG = {
    # ── Риск-менеджмент ──────────────────────────────────────────
    # Настройки для депо $100. Шпаргалка:
    #   $100  → max_positions 2, min_balance 50
    #   $300  → max_positions 3, min_balance 80
    #   $500  → max_positions 4, min_balance 100
    #   $1000 → max_positions 6, min_balance 150
    "risk_per_trade_pct":  1.0,   # % текущего баланса на сделку
    "leverage":            20,    # изолированная маржа 20x
    "max_positions":       7,     # суммарно по всем парам и ТФ
    "margin_reserve_pct":  5.0,   # небольшой запас свободной маржи
    "min_balance_usdt":    20.0,
    "min_contracts":       1,
    "min_notional_usdt":   5.0,   # Bybit minNotional linear
    "min_stop_pct":        0.25,  # сигналы со стопом < 0.25% не торгуем
    "hedge_mode":          False, # one-way: 1 позиция на пару
    "emergency_stop_pct":  0.3,    # % за стоп-ценой → принудительное закрытие маркетом
    "min_rr":              0.2,    # min R:R (reward/risk); MARKET retest — от текущей цены
    "slope_ema_threshold_pct": 0.0,  # мёртвая зона slope EMA (%); 0 = выкл; /prog_ema
    "slope_ema_spans": {},           # override span по htf_ratio ("60","120"); /prog_ema ema
    "slope_timing_mode": "hermes",   # hermes = htf_floor+offsets (как бэктест); trigger = @триггер
    "slope_cisd_arm_block_htf_windows": 2,  # cisd_cross arm ban после slope skip (HTF окон)
    "sl_tp_restore_alert_cooldown_s": 300,  # debounce TG «SL/TP переставлены»
    "sl_tp_manual_alert_cooldown_s": 60,  # debounce TG «SL/TP сдвинуты вручную»
    "sl_tp_restore_grace_s": 25,  # не restore сразу: UI MEXC при сдвиге кратко снимает stoporder
    "size_mult":           1.0,    # размер = риск$ / стоп%; без урезания
    "quality_size_enabled": False,
    # Mild P(SL) quartile overlay поверх QSZ; frozen model, итоговый cap 0.60…1.35
    "psl_size_enabled": False,
    # Frozen continuous quality-stop: SOL tf7 score q60→q90, SL distance 1.00→0.85
    "quality_stop_enabled": False,  # стоп фиксирован за экстремумом свипа
    "quality_stop_q60": 5.209029019106522,
    "quality_stop_q90": 7.535410159157014,
    "quality_stop_min_mult": 0.85,
    # ── Комиссии ────────────────────────────────────────────────
    "maker_fee":           0.00036,  # 0.036% Bybit account (fallback; /fee)
    "taker_fee":           0.001,    # 0.100%
    "contract_value":      0.001,    # BTC на лот бота (Bybit linear qty в монете)

    # ── Тайминги ────────────────────────────────────────────────
    "limit_check_s":       5,
    "position_check_s":    10,
    "position_exchange_grace_s": 120,  # не считать «нет на бирже» сразу после входа (после exchange_seen)
    "position_exchange_grace_multi_s": 90,  # доп. grace если несколько open в одном direction
    "position_unconfirmed_max_s":  600,  # ждём появления на fetch_positions перед absent/closed_sync
    "position_confirm_poll_s":     5.0,  # опрос при ожидании позиции после fill
    "position_confirm_after_fill_s": 120,  # макс ожидание перед SL/TP в _finalize_limit_fill
    "position_unconfirmed_alert_s": 300,  # TG если позиция так и не видна на бирже
    "position_absent_retries":   8,    # опросов перед «нет на бирже»
    "position_absent_retry_s":   3.0,
    "position_absent_retries_multi_extra": 4,  # +к retries при 2+ open в одном direction
    "closed_sync_confirm_polls": 4,    # подтверждение closed_sync перед снятием SL/TP
    "closed_sync_confirm_poll_s": 4.0,
    "close_deal_lookback_min":   360,  # история close-fill для manual/closed_sync (MEXC hedge side=3)
    "filled_pending_stale_s":  600,   # filled pending без Position → не блокировать orphan
    "orphan_after_close_grace_s": 180,  # не создавать orphan после нашего TP/SL (лаг fetch_positions)
    "ghost_cleanup_enabled":     True,  # закрывать хвост на бирже после TP/SL (ex_ctr > bot_ctr)
    "ghost_cleanup_grace_s":     25,    # пауза после TP/SL перед проверкой (лаг MEXC)
    "ghost_cleanup_polls":       3,
    "ghost_cleanup_poll_s":      8,
    "ghost_cleanup_max_ctr":     15,    # больше — только TG, без авто-close
    "ghost_cleanup_sync_min_s":  90,    # throttle фоновой проверки в sync_exchange
    "exchange_fill_entry_tol_pct": 0.0008,  # матч pending↔биржа по entry (0.08%)
    "close_verify_delay_s":    0.6,   # пауза после MEXC close перед проверкой
    "price_stale_s":       10,
    "paper_balance":       100.0,

    # ── Таймфреймы ───────────────────────────────────────────────
    # Активный ТФ выбирается командой /tf; остальные не сканируются,
    # но уже открытые позиции/лимитки с других ТФ живут до закрытия.
    "tf0": {
        "timeframe":  "5m",
        "htf_ratio":  60,
        "limit_h":    1,     # 1H ожидание входа
        "position_h": 6,     # 6H ожидание выхода
        "ohlcv":      500,
        "scan_s":     15,    # поллинг OHLCV (сек); scan_m — legacy fallback
        "scan_m":     5,
        "label":      "5m → 1H",
    },
    "tf1": {
        "timeframe":  "15m",
        "htf_ratio":  240,
        "limit_h":    5,     # 5H ожидание входа
        "position_h": 16,    # 16H ожидание выхода
        "ohlcv":      500,
        "scan_s":     20,
        "scan_m":     15,
        "label":      "15m → 4H",
    },
    "tf2": {
        "timeframe":  "1h",
        "htf_ratio":  1440,
        "limit_h":    24,    # 24H ожидание входа
        "position_h": 24,    # 24H ожидание выхода
        "ohlcv":      200,
        "scan_s":     60,
        "scan_m":     60,
        "label":      "1H → Daily",
    },
    "tf3": {
        "timeframe":  "1m",
        "htf_ratio":  60,
        "limit_h":    1,     # 1H ожидание входа
        "position_h": 4,     # 4H ожидание выхода
        "ohlcv":      200,
        "scan_s":     10,
        "scan_m":     1,
        "label":      "1m → 1H",
    },
    "tf4": {
        "timeframe":  "10m",
        "htf_ratio":  60,
        "htf_confirm_windows": 3,  # окно MSS/close-arm: 3 HTF-диапазона от anchor
        "limit_h":    1,     # 1H ожидание лимитки
        "position_h": 6,     # 6H ожидание TP/позиции
        "ohlcv":      500,
        "scan_s":     20,
        "scan_m":     10,
        "label":      "10m → 1H",
    },
    "tf5": {
        "timeframe":  "10m",
        "confirm_timeframe": "5m",  # MSS confirm по close 5m; серия/триггер — 10m
        "htf_ratio":  120,   # 2H HTF (10m×12 баров)
        "limit_h":    2,     # 2H ожидание лимитки
        "position_h": 12,    # 12H ожидание TP/позиции
        "ohlcv":      500,
        "scan_s":     20,
        "scan_m":     10,
        "label":      "10m → 2H",
    },
    "tf6": {
        "timeframe":  "10m",
        "htf_ratio":  240,   # 4H HTF (10m×24 бара)
        "limit_h":    5,     # 5H ожидание входа
        "position_h": 16,    # 16H ожидание выхода
        "ohlcv":      500,
        "scan_s":     20,
        "scan_m":     10,
        "label":      "10m → 4H",
    },
    "tf7": {
        "timeframe":  "5m",
        "htf_ratio":  240,   # 4H HTF (5m×48 баров)
        "limit_h":    20 / 60,  # 20 мин = 4 бара 5m
        "position_h": 16,       # 16 ч = 192 бара 5m
        "ohlcv":      1000,
        "scan_s":     15,
        "scan_m":     5,
        "label":      "5m → 4H",
        "economic_gate_mode": "off",
        "max_fee_r": 0.25,
        "market_min_net_rr": 0.80,
    },
    "tf8": {
        "timeframe":  "30m",
        "confirm_timeframe": "5m",  # MSS по 5m из того же буфера
        "htf_ratio":  480,   # 8H HTF (30m×16 баров)
        "limit_h":    0.5,   # 30 мин = 1 бар 30m
        "position_h": 6,     # 6 ч = 12 баров 30m
        "ohlcv":      200,
        "scan_s":     15,
        "scan_m":     30,
        "label":      "30m → 8H",
        "economic_gate_mode": "off",
    },
}

TF_KEYS = ("tf0", "tf1", "tf2", "tf3", "tf4", "tf5", "tf6", "tf7", "tf8")
ACTIVE_TF_KEYS = ("tf7", "tf8")
OHLCV_5M_BARS = 1000  # один запрос 5m на пару за цикл
# tf4 (10m→1H): особый паттерн «2 бара HTF + подтверждение баром 3»
TF4_BAR3_PATTERN_TF = "tf4"

# Sweep size / ATR(14) на баре trigger — отсекает мелкие свипы
SWEEP_ATR_FILTER = {
    "min_atr": 0.40,
}

# Trigger volume / SMA — KEEP LOW (отсекает кульминацию на свипе)
TRIGGER_VOL_FILTER = {
    "ma": 20,
    "max_ratio": 2.5,
}

# Detect-фильтры v6: только vwap. ATR / VOL(SMA) / D / QSZ / PSL / QSTOP вырезаны.
DETECT_FILTERS_DEFAULT = {
    "atr_enabled": False,
    "vol_enabled": False,
    "d_enabled": False,
}

# Slope EMA: профиль по HTF активного ТФ (None — фильтр не применяется)
SLOPE_EMA_PROFILES: dict[int, dict] = {
    60:  {"span": 2, "ohlcv_tf": "1h", "label": "1H"},   # 1m/5m/10m → 1H
    120: {"span": 3, "ohlcv_tf": "2h", "label": "2H"},   # 10m → 2H
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(BASE_DIR, exist_ok=True)

POSITIONS_FILE = os.path.join(BASE_DIR, "positions.json")
TRADES_FILE    = os.path.join(BASE_DIR, "trades.json")
TRADES_ARCHIVE_DIR = os.path.join(BASE_DIR, "archives")
TRADES_STATS_EPOCH_FILE = os.path.join(BASE_DIR, "trades_stats_epoch.txt")
TRADE_LOG_DIR  = os.path.join(BASE_DIR, "trade_logs")
TRADE_LOG_ARCHIVE_DIR = os.path.join(TRADE_LOG_DIR, "archive")
_trade_log_month: str = ""
SIGNALS_CACHE  = os.path.join(BASE_DIR, "signals_cache.json")
PENDING_FILE   = os.path.join(BASE_DIR, "pending_limits.json")
BOT_STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")
LOG_FILE       = os.path.join(BASE_DIR, "bot.log")


def _positions_file() -> str:
    name = "shadow_positions.json" if state.paper else "positions.json"
    return os.path.join(BASE_DIR, name)


def _pending_file() -> str:
    name = "shadow_pending.json" if state.paper else "pending_limits.json"
    return os.path.join(BASE_DIR, name)


def _trades_file() -> str:
    name = "shadow_trades.json" if state.paper else "trades.json"
    return os.path.join(BASE_DIR, name)


def _mode_prefix() -> str:
    return "🧪 SHADOW" if state.paper else "🔴 LIVE"


def _mode_tag() -> str:
    return "shadow" if state.paper else "live"

# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================
# Ротация: 10 МБ на файл, хранить 7 файлов (~70 МБ макс)
_file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _console_handler])

# Убираем мусор от httpx/telegram (getUpdates каждые 10с = 8640 строк/день)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
# Сетевые ретраи внутри библиотеки — не наша ошибка, либа сама обрабатывает
logging.getLogger("telegram.ext._utils.networkloop").setLevel(logging.CRITICAL)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("cisd_bot")

# /start: временное хранилище сигналов для inline-кнопок yes/no
_pending_start_signals: dict[str, dict] = {}
_start_confirm_tasks: dict[str, asyncio.Task] = {}


def _cancel_start_confirm_timer(sig_hash: str):
    t = _start_confirm_tasks.pop(sig_hash, None)
    if t and not t.done():
        t.cancel()


# ============================================================
# ДЕТЕКТОР
# ============================================================
from detectors.cisd_htf import CISDDetector

# ============================================================
# BYBIT USDT LINEAR (REST, unified v5)
# ============================================================
exchange = ccxt.bybit({
    "apiKey":          BYBIT_API_KEY,
    "secret":          BYBIT_API_SECRET,
    "timeout":         30000,
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
        "defaultSubType": "linear",
        "recvWindow": 10000,
        "adjustForTimeDifference": True,
    },
})


def _position_idx(direction: str) -> int:
    """Bybit: 0 one-way, 1 hedge long, 2 hedge short."""
    if not _hedge_mode_config():
        return 0
    return 1 if str(direction).upper() == "LONG" else 2


def _to_ex_qty(contracts, symbol_key: Optional[str] = None) -> float:
    cv = float(symbol_profile(symbol_key)["contract_value"])
    return float(contracts) * cv


def _from_ex_qty(qty, symbol_key: Optional[str] = None) -> float:
    cv = float(symbol_profile(symbol_key)["contract_value"])
    if cv <= 0:
        return float(qty or 0)
    return float(qty or 0) / cv


def _qty_ex(contracts, symbol_key: Optional[str] = None) -> float:
    """Лоты бота → qty Bybit linear (base coin), с precision рынка."""
    qty = _to_ex_qty(contracts, symbol_key)
    sym = symbol_profile(symbol_key)["symbol"]
    try:
        return float(exchange.amount_to_precision(sym, qty))
    except Exception:
        return qty


def _trade_vol_contracts(trade: dict, symbol_key: Optional[str] = None) -> float:
    """Объём fill в лотах бота. ccxt amount на Bybit linear = база (SOL/BTC)."""
    info = trade.get("info") or {}
    raw = trade.get("amount")
    if raw in (None, "", 0, "0"):
        raw = info.get("execQty") or info.get("closedSize") or info.get("qty") or 0
    try:
        return _from_ex_qty(float(raw or 0), symbol_key)
    except (TypeError, ValueError):
        return 0.0


def _trade_side_str(trade: dict) -> str:
    info = trade.get("info") or {}
    return str(trade.get("side") or info.get("side") or "").lower()


def _synthetic_position_id(symbol_key: str, direction: str) -> str:
    return f"{symbol_key}:{_position_idx(direction)}"


def _tpsl_synthetic_id(symbol_key: str, direction: str) -> str:
    return f"tpsl:{symbol_key}:{_position_idx(direction)}"


def _fetch_positions_linear(symbols=None):
    params = {"category": "linear"}
    if symbols:
        return exchange.fetch_positions(list(symbols), params)
    return exchange.fetch_positions(None, params)

# ============================================================
# МУТАБЕЛЬНЫЙ СТЕЙТ БОТА
# ============================================================
class BotState:
    """Общее состояние между asyncio-задачами и Telegram-хендлерами."""

    def __init__(self):
        self.paper: bool            = PAPER_TRADING
        self.running: asyncio.Event = asyncio.Event()
        self.tasks_live: asyncio.Event = asyncio.Event()  # False = все торговые задачи в idle
        self.tasks_live.set()
        self.pending_limits: list   = []
        self.positions: list        = []
        self.paper_balance: float   = CONFIG["paper_balance"]
        self.active_tf: str         = "tf7"
        self.active_symbol_key: str  = DEFAULT_SYMBOL_KEY  # для fetch/detect текущего цикла
        self.fees_by_symbol: dict[str, dict] = {}
        self._trade_counter: int    = 0
        self._counter_date: str     = ""
        self.processed: set         = set()   # хэши обработанных сигналов
        # Ручной бан сетапов после /close лимитки: key -> expire_ts
        # Key НЕ содержит trigger_idx (чтобы не пересоздавалось на соседнем триггер-баре),
        # но содержит SL/TP и HTF окно.
        self.manual_setup_bans: dict[str, float] = {}
        self.last_ohlcv_low: Optional[float] = None
        self.last_ohlcv_high: Optional[float] = None
        self.ohlcv_closed: dict[str, dict] = {}  # f"{symbol}|{tf}" → {low, high, close}
        self.df_cache: dict = {}  # f"{symbol}|{tf}" → DataFrame рабочего ТФ
        self.start_confirm_until_ts: float = 0.0
        self._fill_in_progress: set[str] = set()  # pending.id во время _finalize_limit_fill
        self._close_in_progress: set[str] = set()  # pos.id во время _finalize_position_close
        self._force_close_in_progress: set[str] = set()  # pos.id: cancel SL/TP → market close
        self._recent_closes: list[tuple[float, str, float, int]] = []  # ts, dir, entry, ctr
        self._unconfirmed_alerted: set[str] = set()  # pos.id — одно TG «не видна на бирже»
        self._sl_tp_restore_locks: dict[str, asyncio.Lock] = {}
        self._sl_tp_restore_alert_ts: dict[str, float] = {}  # pos.id → last restore TG
        self._sl_tp_manual_alert_ts: dict[str, float] = {}  # pos.id → last manual-move TG
        self._sl_tp_incomplete_since: dict[str, float] = {}  # pos.id → когда впервые увидели дыру
        self._ghost_cleanup_locks: dict[str, asyncio.Lock] = {}
        self._ghost_cleanup_last: dict[str, float] = {}  # direction → ts последней попытки
        # Кандидаты свипов для режима "2 HTF окна": храним только живые сетапы из текущего/предыдущего HTF-окна.
        # Не переживает рестарт (осознанно), чтобы не поднимать backlog.
        self.sweep_candidates: dict[str, dict] = {}
        # После первого сетапа в HTF-окне — ждём пересвип (глубже trigger), иначе detect молчит.
        self.htf_sweep_lock: dict[str, dict] = {}
        # Один принятый триггер на HTF-окно (tf|htf_time) — opposite/2nd CISD не берём.
        self.htf_taken: dict[str, dict] = {}
        # Pine bear/bull_sweep_check: уже проверенные закрытые HTF-окна (tf|htf_time).
        self.htf_sweep_validated: dict[str, bool] = {}
        # Одно TG-уведомление на постоянный пропуск сигнала (category:hash).
        self.skip_tg_keys: set[str] = set()
        self.slope_filter_enabled: bool = False  # /slope — EMA slope 2H
        # Detect-фильтры ATR/VOL — persist в bot_state.json
        self.detect_filters: dict = dict(DETECT_FILTERS_DEFAULT)
        self.quality_size_enabled: bool = False
        # P(SL) overlay поверх Lever-1 — отдельный persist toggle
        self.psl_size_enabled: bool = bool(CONFIG.get("psl_size_enabled", False))
        # Continuous quality-score tightening initial SL — отдельный persist toggle
        self.quality_stop_enabled: bool = bool(CONFIG.get("quality_stop_enabled", False))
        # slope отклонил HTF+sweep → cisd_cross arm запрещён (2 HTF окна)
        self.slope_cisd_arm_blocked: list[dict] = []
        self.exchange_hedge_mode: bool = False  # подтверждённый режим MEXC (fetch после set)
        # Пока окно подтверждения /start активно — в LIVE не автопоставляем лимитки
        if PAPER_TRADING:
            self.running.set()

    def next_trade_num(self) -> int:
        """Дневной счётчик сделок — сбрасывается в 0 каждый день."""
        today = utcnow().strftime("%Y-%m-%d")
        if today != self._counter_date:
            self._trade_counter = 0
            self._counter_date  = today
        self._trade_counter += 1
        return self._trade_counter

    def mode_str(self) -> str:
        mode     = _mode_prefix()
        if not self.tasks_live.is_set():
            run = "🛑 HALTED"
        elif self.running.is_set():
            run = "▶ RUNNING"
        else:
            run = "⏸ PAUSED"
        tf_label = " + ".join(CONFIG[k]["label"] for k in ACTIVE_TF_KEYS)
        n_pairs = len(ACTIVE_SYMBOL_KEYS)
        pos_mode = "hedge" if _allow_both_directions() else "one-way"
        return f"{mode} | {run} | {n_pairs} пар | {tf_label} | {pos_mode}"


state = BotState()


def _hedge_mode_config() -> bool:
    return bool(CONFIG.get("hedge_mode", False))


def _allow_both_directions() -> bool:
    """Long+short одновременно: CONFIG hedge_mode и биржа реально в hedge."""
    if not _hedge_mode_config():
        return False
    if state.paper:
        return True
    return bool(getattr(state, "exchange_hedge_mode", False))


def active_symbol_key() -> str:
    k = getattr(state, "active_symbol_key", None) or DEFAULT_SYMBOL_KEY
    return k if k in SYMBOL_PROFILES else DEFAULT_SYMBOL_KEY


def symbol_profile(key: Optional[str] = None) -> dict:
    sk = active_symbol_key() if key is None else key
    if sk not in SYMBOL_PROFILES:
        sk = DEFAULT_SYMBOL_KEY
    return SYMBOL_PROFILES[sk]


def active_symbol() -> str:
    return symbol_profile()["symbol"]


def _symbol_key_from_ccxt(sym: str) -> str:
    return _CCXT_TO_SYMBOL_KEY.get(sym, DEFAULT_SYMBOL_KEY)


def _pos_symbol_key(obj) -> str:
    k = getattr(obj, "symbol_key", None) or DEFAULT_SYMBOL_KEY
    return k if k in SYMBOL_PROFILES else DEFAULT_SYMBOL_KEY


def _price_decimals(tick: float) -> int:
    s = f"{tick:.10f}".rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def _round_to_tick(px: float, tick: float) -> float:
    if tick <= 0:
        return float(px)
    return round(round(float(px) / tick) * tick, _price_decimals(tick))


def _round_price(px: float, symbol_key: Optional[str] = None) -> float:
    return _round_to_tick(px, symbol_profile(symbol_key)["price_tick"])


def _round_sweep_level(sweep: float, symbol_key: Optional[str] = None) -> float:
    bucket = symbol_profile(symbol_key)["sweep_bucket"]
    return round(float(sweep or 0) / bucket) * bucket


def _contract_value(symbol_key: Optional[str] = None) -> float:
    return symbol_profile(symbol_key)["contract_value"]


def _tracked_symbol_keys() -> set[str]:
    keys = set(ACTIVE_SYMBOL_KEYS)
    for p in state.positions:
        if p.status == "open":
            keys.add(_pos_symbol_key(p))
    for pl in state.pending_limits:
        if pl.status == "pending":
            keys.add(_pos_symbol_key(pl))
    return keys


def _persist_active_symbol_fees() -> None:
    key = active_symbol_key()
    state.fees_by_symbol[key] = {
        "maker": float(CONFIG["maker_fee"]),
        "taker": float(CONFIG["taker_fee"]),
    }


_STALE_VIP0_FEES = {"maker": 0.0002, "taker": 0.00055}


def _migrate_stale_account_fee(kind: str, value: float, fallback: float) -> float:
    """VIP0-фолбэк в bot_state → реальные ставки аккаунта. Кастом /fee не трогаем."""
    stale = _STALE_VIP0_FEES.get(kind)
    if stale is not None and abs(float(value) - stale) < 1e-12:
        return float(fallback)
    return float(value)


def _apply_symbol_key(key: str) -> None:
    if key not in SYMBOL_PROFILES:
        key = DEFAULT_SYMBOL_KEY
    state.active_symbol_key = key
    p = SYMBOL_PROFILES[key]
    CONFIG["contract_value"] = p["contract_value"]
    fees = state.fees_by_symbol.get(key)
    if fees:
        CONFIG["maker_fee"] = float(fees.get("maker", p["maker_fee"]))
        CONFIG["taker_fee"] = float(fees.get("taker", p["taker_fee"]))
    else:
        CONFIG["maker_fee"] = p["maker_fee"]
        CONFIG["taker_fee"] = p["taker_fee"]


@contextmanager
def _use_symbol(symbol_key: Optional[str]):
    """Временно переключить active_symbol_key (сканер / ордера пары)."""
    prev = active_symbol_key()
    if symbol_key and symbol_key in SYMBOL_PROFILES and symbol_key != prev:
        _apply_symbol_key(symbol_key)
        try:
            yield
        finally:
            _apply_symbol_key(prev)
    else:
        yield
_create_pending_lock = asyncio.Lock()
_slope_ohlcv_cache: dict[str, dict] = {}

# ============================================================
# КЭШ ЦЕНЫ (по символу)
# ============================================================
price_cache: dict[str, dict] = {}


def _price_slot(symbol_key: Optional[str] = None) -> dict:
    sk = symbol_key or active_symbol_key()
    slot = price_cache.get(sk)
    if slot is None:
        slot = {"last": None, "bid": None, "ask": None, "ts": 0.0}
        price_cache[sk] = slot
    return slot


# ============================================================
# МОДЕЛИ
# ============================================================
class PendingLimit:
    def __init__(self, lid, direction, entry_price, stop_price, tp_price,
                 contracts, created_at, timeout_at, exit_h, tf="tf1", trade_num=0):
        self.id          = lid
        self.direction   = direction
        self.entry_price = entry_price
        self.stop_price  = stop_price   # экстремум тригер-бара = экстремум цисда
        self.tp_price    = tp_price
        self.contracts   = contracts
        self.created_at  = created_at
        self.timeout_at  = timeout_at
        self.exit_h      = exit_h
        self.tf          = tf
        self.trade_num   = trade_num    # дневной порядковый номер
        self.status      = "pending"
        self.order_id    = None
        self.order_placed_at: Optional[datetime] = None
        self.sig_hash    = ""   # хэш сигнала для удаления из processed при инвалидации
        self.price_at_creation: float = 0.0  # цена при создании (для детекта ретестовых входов)
        self.cancel_fail_alerted: bool = False  # не спамить TG при повторных неудачах cancel
        self.entry_is_plan: bool = False  # STOP-LIMIT/LIMIT plan вход → planorder cancel
        self.htf_time: str = ""  # ISO timestamp начала HTF-окна, к которому относится сигнал
        self.fib_1x: Optional[float] = None  # уровень 1.0x (для защиты "пропущено по фибо")
        self.confirm_on_sweep: bool = False  # confirm на баре свипа (метка сетапа)
        self.confirm_close: float = 0.0      # close CISD confirm-бара (журнал)
        self.confirm_bar_time: str = ""      # ISO open-time конфирм-бара
        self.sweep_close_close: float = 0.0  # close бара close-свипа → тип входа STOP-LIMIT/MARKET
        self.cisd_level: float = 0.0       # уровень CISD (для цены лимитки без taker-fill)
        self.defer_entry: bool = False     # ждём ретест, пока лимитка не «в рынке»
        self.entry_kind: str = ""          # STOP-LIMIT | MARKET | LIMIT
        self.sweep_level: Optional[float] = None  # HTF sweep для журнала / бэктеста
        # legacy; вход на CISD — STOP-LIMIT, не MARKET (one-bar тоже ждёт ретест).
        self.force_market: bool = False
        # tf4: бар 3 подтвердил импульс → LIMIT на CISD, не STOP-LIMIT.
        self.force_limit_retest: bool = False
        # legacy: live cisd_cross arm → STOP-LIMIT @ CISD (не MARKET).
        self.cisd_cross_market: bool = False
        # Исходный sweep-trigger (до перелоя на confirm-баре) — для пересчёта SL/TP.
        self.cand_trigger_time: str = ""
        self.trigger_bar_at: Optional[datetime] = None  # open trigger-бара (журнал)
        self.pyramid_parent_id: str = ""  # доливка в open-ногу (SL/TP родителя)
        self.symbol_key: str = DEFAULT_SYMBOL_KEY
        self.quality_score: float = 0.0
        self.quality_stop_original: Optional[float] = None
        self.quality_stop_mult: float = 1.0
        self.quality_stop_model: str = ""
        self.vwap_dev: float = 0.0

    def to_dict(self):
        d = {
            "id": self.id, "direction": self.direction,
            "entry_price": self.entry_price, "stop_price": self.stop_price,
            "tp_price": self.tp_price, "contracts": self.contracts,
            "created_at": self.created_at.isoformat(),
            "timeout_at": self.timeout_at.isoformat(),
            "exit_h": self.exit_h, "tf": self.tf,
            "trade_num": self.trade_num,
            "status": self.status, "order_id": self.order_id,
            "order_placed_at": self.order_placed_at.isoformat() if self.order_placed_at else None,
            "sig_hash": self.sig_hash,
            "price_at_creation": self.price_at_creation,
            "entry_is_plan": self.entry_is_plan,
            "htf_time": self.htf_time,
            "fib_1x": self.fib_1x,
            "confirm_on_sweep": self.confirm_on_sweep,
            "confirm_close": self.confirm_close or None,
            "confirm_bar_time": self.confirm_bar_time or None,
            "sweep_close_close": self.sweep_close_close or None,
            "cisd_level": self.cisd_level,
            "defer_entry": self.defer_entry,
            "entry_kind": self.entry_kind,
            "sweep_level": self.sweep_level,
            "force_market": self.force_market,
            "force_limit_retest": self.force_limit_retest,
            "cisd_cross_market": self.cisd_cross_market,
            "cand_trigger_time": self.cand_trigger_time or None,
            "pyramid_parent_id": self.pyramid_parent_id or None,
            "quality_score": self.quality_score,
            "quality_stop_original": self.quality_stop_original,
            "quality_stop_mult": self.quality_stop_mult,
            "quality_stop_model": self.quality_stop_model or None,
        }
        if self.trigger_bar_at:
            d["trigger_bar_at"] = self.trigger_bar_at.isoformat()
        if self.symbol_key and self.symbol_key != DEFAULT_SYMBOL_KEY:
            d["symbol_key"] = self.symbol_key
        return d

    @classmethod
    def from_dict(cls, d):
        p = cls(
            d["id"], d["direction"],
            d["entry_price"], d["stop_price"], d["tp_price"], d["contracts"],
            datetime.fromisoformat(d["created_at"]),
            datetime.fromisoformat(d["timeout_at"]),
            d.get("exit_h", 16), d.get("tf", "tf1"),
            d.get("trade_num", 0),
        )
        p.status           = d.get("status", "pending")
        p.order_id         = d.get("order_id")
        opa = d.get("order_placed_at")
        p.order_placed_at  = datetime.fromisoformat(opa) if opa else None
        p.sig_hash         = d.get("sig_hash", "")
        p.price_at_creation = float(d.get("price_at_creation", 0.0))
        p.entry_is_plan    = bool(d.get("entry_is_plan", False))
        p.htf_time         = d.get("htf_time", "") or ""
        p.fib_1x           = _safe_float(d.get("fib_1x"))
        p.confirm_on_sweep = bool(d.get("confirm_on_sweep", False))
        p.confirm_close    = float(d.get("confirm_close") or 0)
        p.confirm_bar_time = str(d.get("confirm_bar_time") or "")
        p.sweep_close_close = float(d.get("sweep_close_close") or 0)
        p.cisd_level       = float(d.get("cisd_level") or 0)
        p.defer_entry      = bool(d.get("defer_entry", False))
        p.entry_kind       = d.get("entry_kind", "") or ""
        p.sweep_level      = _safe_float(d.get("sweep_level"))
        p.force_market     = bool(d.get("force_market", False))
        p.force_limit_retest = bool(d.get("force_limit_retest", False))
        p.cisd_cross_market = bool(d.get("cisd_cross_market", False))
        p.cand_trigger_time = str(d.get("cand_trigger_time") or "")
        tba = d.get("trigger_bar_at") or d.get("series_start_at")
        p.trigger_bar_at = datetime.fromisoformat(tba) if tba else None
        p.pyramid_parent_id = str(d.get("pyramid_parent_id") or "")
        p.symbol_key = str(d.get("symbol_key") or DEFAULT_SYMBOL_KEY)
        p.quality_score = float(d.get("quality_score") or 0)
        p.quality_stop_original = _safe_float(d.get("quality_stop_original"))
        p.quality_stop_mult = float(d.get("quality_stop_mult") or 1)
        p.quality_stop_model = str(d.get("quality_stop_model") or "")
        p.vwap_dev = float(d.get("vwap_dev") or 0)
        if p.status == "pending":
            p.force_market = False
            p.cisd_cross_market = False
            if not p.force_limit_retest and p.entry_kind == "MARKET":
                p.entry_kind = "STOP-LIMIT"
        return p


class Position:
    def __init__(self, pos_id, direction, entry_price, stop_price, tp_price,
                 contracts, entry_time, exit_time, tf="tf1", trade_num=0):
        self.id             = pos_id
        self.direction      = direction
        self.entry_price    = entry_price
        self.stop_price     = stop_price
        self.tp_price       = tp_price
        self.contracts      = contracts
        self.entry_time     = entry_time
        self.exit_time      = exit_time
        self.tf             = tf
        self.trade_num      = trade_num
        self.status         = "open"
        self.close_price    = None
        self.pnl            = None
        self.fees           = None
        self.pnl_net        = None
        self.stop_order_id  = None
        self.tp_order_id    = None
        self.tpsl_order_id: Optional[str] = None  # stoporder/place — SL+TP одной записью
        self.exchange_position_id: Optional[str] = None  # MEXC positionId ноги при входе
        self.exchange_seen: bool = False  # хотя бы раз подтверждена в fetch_positions
        self.protection_alert_sent: bool = False  # уже предупредили, что SL/TP не подтверждены
        self.protection_ok_alert_sent: bool = False  # уже сообщили, что позиция защищена
        # метаданные сигнала (для журнала и сравнения с бэктестом)
        self.entry_kind: str = ""
        self.signal_category: str = ""
        self.signal_entry: Optional[float] = None
        self.price_at_creation: float = 0.0
        self.cisd_level: float = 0.0
        self.sweep_level: Optional[float] = None
        self.fib_1x: Optional[float] = None
        self.confirm_on_sweep: bool = False
        self.htf_time: str = ""
        self.sig_hash: str = ""
        self.pending_created_at: Optional[datetime] = None
        self.symbol_key: str = DEFAULT_SYMBOL_KEY
        self.quality_score: float = 0.0
        self.quality_stop_original: Optional[float] = None
        self.quality_stop_mult: float = 1.0
        self.quality_stop_model: str = ""
        self.vwap_dev: float = 0.0
        self.confirm_bar_time: str = ""

    def to_dict(self):
        d = {
            "id": self.id, "direction": self.direction,
            "entry_price": self.entry_price, "stop_price": self.stop_price,
            "tp_price": self.tp_price, "contracts": self.contracts,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "tf": self.tf, "trade_num": self.trade_num,
            "status": self.status,
            "close_price": self.close_price, "pnl": self.pnl,
            "fees": self.fees, "pnl_net": self.pnl_net,
            "stop_order_id": self.stop_order_id,
            "tp_order_id":   self.tp_order_id,
        }
        if self.tpsl_order_id:
            d["tpsl_order_id"] = self.tpsl_order_id
        if self.exchange_position_id:
            d["exchange_position_id"] = self.exchange_position_id
        if self.exchange_seen:
            d["exchange_seen"] = True
        if self.protection_alert_sent:
            d["protection_alert_sent"] = True
        if self.protection_ok_alert_sent:
            d["protection_ok_alert_sent"] = True
        if self.entry_kind:
            d["entry_kind"] = self.entry_kind
        if self.signal_category:
            d["signal_category"] = self.signal_category
        if self.signal_entry is not None:
            d["signal_entry"] = self.signal_entry
        if self.price_at_creation:
            d["price_at_creation"] = self.price_at_creation
        if self.cisd_level:
            d["cisd_level"] = self.cisd_level
        if self.sweep_level is not None:
            d["sweep_level"] = self.sweep_level
        if self.fib_1x is not None:
            d["fib_1x"] = self.fib_1x
        if self.confirm_on_sweep:
            d["confirm_on_sweep"] = self.confirm_on_sweep
        if self.htf_time:
            d["htf_time"] = self.htf_time
        if self.sig_hash:
            d["sig_hash"] = self.sig_hash
        if self.pending_created_at:
            d["pending_created_at"] = self.pending_created_at.isoformat()
        if self.symbol_key and self.symbol_key != DEFAULT_SYMBOL_KEY:
            d["symbol_key"] = self.symbol_key
        d["quality_score"] = self.quality_score
        d["quality_stop_original"] = self.quality_stop_original
        d["quality_stop_mult"] = self.quality_stop_mult
        if self.quality_stop_model:
            d["quality_stop_model"] = self.quality_stop_model
        return d

    @classmethod
    def from_dict(cls, d):
        p = cls(
            d["id"], d["direction"],
            d["entry_price"], d["stop_price"], d["tp_price"], d["contracts"],
            datetime.fromisoformat(d["entry_time"]),
            datetime.fromisoformat(d["exit_time"]),
            d.get("tf", "tf1"), d.get("trade_num", 0),
        )
        p.status        = d.get("status", "open")
        p.close_price   = d.get("close_price")
        p.pnl           = d.get("pnl")
        p.fees          = d.get("fees")
        p.pnl_net       = d.get("pnl_net")
        p.stop_order_id = d.get("stop_order_id")
        p.tp_order_id   = d.get("tp_order_id")
        tpsl = d.get("tpsl_order_id")
        p.tpsl_order_id = str(tpsl) if tpsl else None
        ep = d.get("exchange_position_id")
        p.exchange_position_id = str(ep) if ep else None
        p.exchange_seen = bool(d.get("exchange_seen", False) or ep)
        p.protection_alert_sent = bool(d.get("protection_alert_sent", False))
        p.protection_ok_alert_sent = bool(d.get("protection_ok_alert_sent", False))
        p.entry_kind    = d.get("entry_kind", "") or ""
        p.signal_category = d.get("signal_category", "") or ""
        p.signal_entry  = _safe_float(d.get("signal_entry"))
        p.price_at_creation = float(d.get("price_at_creation") or 0)
        p.cisd_level    = float(d.get("cisd_level") or 0)
        p.sweep_level   = _safe_float(d.get("sweep_level"))
        p.fib_1x        = _safe_float(d.get("fib_1x"))
        p.confirm_on_sweep = bool(d.get("confirm_on_sweep", False))
        p.htf_time      = d.get("htf_time", "") or ""
        p.sig_hash      = d.get("sig_hash", "") or ""
        pca = d.get("pending_created_at")
        p.pending_created_at = datetime.fromisoformat(pca) if pca else None
        p.symbol_key = str(d.get("symbol_key") or DEFAULT_SYMBOL_KEY)
        p.quality_score = float(d.get("quality_score") or 0)
        p.quality_stop_original = _safe_float(d.get("quality_stop_original"))
        p.quality_stop_mult = float(d.get("quality_stop_mult") or 1)
        p.quality_stop_model = str(d.get("quality_stop_model") or "")
        return p


# ============================================================
# УТИЛИТЫ: JSON
# ============================================================
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # Windows иногда блокирует файл (антивирус и т.п.) — retry
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.15)
                else:
                    raise
    except Exception:
        # Убираем .tmp чтобы не засорять папку
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def load_positions():
    return [Position.from_dict(d) for d in load_json(_positions_file(), [])]


def save_positions(positions):
    save_json(_positions_file(), [p.to_dict() for p in positions])


def save_bot_state():
    """Сохраняет активный ТФ, режим и таймауты на диск."""
    save_json(BOT_STATE_FILE, {
        "active_tf": state.active_tf,
        "active_symbol": active_symbol_key(),
        "paper":     state.paper,
        "timeouts": {
            tf: {
                "limit_h":    CONFIG[tf]["limit_h"],
                "position_h": CONFIG[tf]["position_h"],
            }
            for tf in TF_KEYS
        },
        "maker_fee": CONFIG["maker_fee"],
        "taker_fee": CONFIG["taker_fee"],
        "fees_by_symbol": state.fees_by_symbol,
        "slope_filter_enabled": state.slope_filter_enabled,
        "slope_ema_threshold_pct": CONFIG.get("slope_ema_threshold_pct", 0.0),
        "slope_ema_spans": CONFIG.get("slope_ema_spans") or {},
        "slope_timing_mode": CONFIG.get("slope_timing_mode", "hermes"),
        "detect_filters": {
            "atr_enabled": False,
            "vol_enabled": False,
            "d_enabled": False,
        },
        "quality_size_enabled": False,
        "psl_size_enabled": False,
        "quality_stop_enabled": False,
        "htf_taken": {
            str(k): dict(v) if isinstance(v, dict) else {"direction": str(v)}
            for k, v in (state.htf_taken or {}).items()
        },
        "tasks_halted": not state.tasks_live.is_set(),
    })


def load_bot_state():
    """Загружает активный ТФ, режим и таймауты с диска."""
    d = load_json(BOT_STATE_FILE, {})
    if "active_tf" in d and d["active_tf"] in TF_KEYS:
        state.active_tf = d["active_tf"] if d["active_tf"] in ACTIVE_TF_KEYS else "tf7"
    if "fees_by_symbol" in d and isinstance(d["fees_by_symbol"], dict):
        cleaned_fees: dict[str, dict] = {}
        for k, v in d["fees_by_symbol"].items():
            if k not in SYMBOL_PROFILES or not isinstance(v, dict):
                continue
            try:
                cleaned_fees[k] = {
                    "maker": _migrate_stale_account_fee(
                        "maker",
                        float(v.get("maker", SYMBOL_PROFILES[k]["maker_fee"])),
                        SYMBOL_PROFILES[k]["maker_fee"],
                    ),
                    "taker": _migrate_stale_account_fee(
                        "taker",
                        float(v.get("taker", SYMBOL_PROFILES[k]["taker_fee"])),
                        SYMBOL_PROFILES[k]["taker_fee"],
                    ),
                }
            except (TypeError, ValueError):
                continue
        state.fees_by_symbol = cleaned_fees
    if "maker_fee" in d:
        state.fees_by_symbol.setdefault(DEFAULT_SYMBOL_KEY, {})["maker"] = (
            _migrate_stale_account_fee(
                "maker",
                float(d["maker_fee"]),
                SYMBOL_PROFILES[DEFAULT_SYMBOL_KEY]["maker_fee"],
            )
        )
    if "taker_fee" in d:
        state.fees_by_symbol.setdefault(DEFAULT_SYMBOL_KEY, {})["taker"] = (
            _migrate_stale_account_fee(
                "taker",
                float(d["taker_fee"]),
                SYMBOL_PROFILES[DEFAULT_SYMBOL_KEY]["taker_fee"],
            )
        )
    sym_key = d.get("active_symbol", DEFAULT_SYMBOL_KEY)
    if sym_key not in SYMBOL_PROFILES:
        sym_key = DEFAULT_SYMBOL_KEY
    _apply_symbol_key(sym_key)
    if "paper" in d:
        state.paper = bool(d["paper"])
        if state.paper and not state.running.is_set():
            state.running.set()
    for tf, vals in d.get("timeouts", {}).items():
        if tf in ACTIVE_TF_KEYS:
            continue  # tf7/tf8 таймауты фиксированы ТЗ
        if tf in CONFIG:
            if "limit_h"    in vals: CONFIG[tf]["limit_h"]    = float(vals["limit_h"])
            if "position_h" in vals: CONFIG[tf]["position_h"] = float(vals["position_h"])
    state.slope_filter_enabled = False  # v5.2: slope-фильтр снят
    if "slope_ema_threshold_pct" in d:
        try:
            CONFIG["slope_ema_threshold_pct"] = float(d["slope_ema_threshold_pct"])
        except (TypeError, ValueError):
            pass
    if "slope_ema_spans" in d and isinstance(d["slope_ema_spans"], dict):
        cleaned: dict[str, int] = {}
        for k, v in d["slope_ema_spans"].items():
            try:
                ratio = int(k)
                if ratio in SLOPE_EMA_PROFILES:
                    cleaned[str(ratio)] = max(1, int(v))
            except (TypeError, ValueError):
                pass
        CONFIG["slope_ema_spans"] = cleaned
    if "slope_timing_mode" in d:
        mode = str(d["slope_timing_mode"]).strip().lower()
        if mode in ("hermes", "trigger"):
            CONFIG["slope_timing_mode"] = mode
    state.detect_filters = {
        "atr_enabled": False,
        "vol_enabled": False,
        "d_enabled": False,
    }
    state.quality_size_enabled = False
    state.psl_size_enabled = False
    state.quality_stop_enabled = False
    ht_raw = d.get("htf_taken") if isinstance(d.get("htf_taken"), dict) else {}
    cleaned_ht: dict[str, dict] = {}
    for k, v in ht_raw.items():
        if not k or not isinstance(k, str):
            continue
        if isinstance(v, dict):
            cleaned_ht[k] = {
                "direction": str(v.get("direction") or ""),
                "trade_num": v.get("trade_num"),
                "at": str(v.get("at") or ""),
            }
        else:
            cleaned_ht[k] = {"direction": str(v), "trade_num": None, "at": ""}
    state.htf_taken = cleaned_ht
    if d.get("tasks_halted"):
        state.tasks_live.clear()
        state.running.clear()
        logger.info("Загружено: tasks_halted=True — торговые задачи выключены до /start")
    if state.paper:
        try:
            trades = load_json(_trades_file(), [])
            if isinstance(trades, list):
                pnl = sum(float(t.get("pnl_net") or 0.0) for t in trades)
                state.paper_balance = float(CONFIG["paper_balance"]) + pnl
                logger.info(
                    f"paper_balance restore: {len(trades)} trades, "
                    f"pnl={pnl:+.4f} → {state.paper_balance:.4f}"
                )
        except Exception as e:
            logger.warning(f"paper_balance restore: {e}")
    logger.info(
        f"Загружено состояние: пара={symbol_profile()['label']}, ТФ={state.active_tf}, "
        f"paper={state.paper}, slope_filter={state.slope_filter_enabled}, "
        f"detect_filters=vwap, "
        + " | ".join(
            f"{tf}: вход={_fmt_h(CONFIG[tf]['limit_h'])} выход={_fmt_h(CONFIG[tf]['position_h'])}"
            for tf in TF_KEYS
        )
    )


def load_pending():
    return [PendingLimit.from_dict(d) for d in load_json(_pending_file(), [])]


def save_pending(pending):
    save_json(_pending_file(), [p.to_dict() for p in pending])


def _reload_pending_merged():
    """Диск + память: не затираем order_id / order_placed_at свежей постановки."""
    fresh = load_pending()
    mem_by_id = {p.id: p for p in state.pending_limits}
    merged: list[PendingLimit] = []
    fresh_ids: set[str] = set()
    for p in fresh:
        fresh_ids.add(p.id)
        mem = mem_by_id.get(p.id)
        if mem:
            if mem.order_id:
                p.order_id = mem.order_id
            if mem.order_placed_at:
                p.order_placed_at = mem.order_placed_at
            # Не откатывать cancelled/filled из RAM в pending с диска
            if mem.status != "pending":
                p.status = mem.status
        merged.append(p)
    for p in state.pending_limits:
        if p.id not in fresh_ids and p.status == "pending":
            merged.append(p)
    state.pending_limits = merged


def _pending_exchange_grace_s(pl: PendingLimit, now: Optional[datetime] = None) -> float:
    """Секунды с постановки ордера (order_placed_at или created_at)."""
    now = now or utcnow()
    anchor = pl.order_placed_at or pl.created_at
    return (now - anchor).total_seconds()


def _pending_in_exchange_grace(pl: PendingLimit, seconds: float = 90.0) -> bool:
    if not pl.order_id:
        return False
    grace = 180.0 if getattr(pl, "entry_is_plan", False) else seconds
    return _pending_exchange_grace_s(pl) < grace


def _position_in_exchange_grace(pos: "Position", now: Optional[datetime] = None) -> bool:
    """После fill MEXC часто отдаёт пустой fetch_positions 10–60 с."""
    now = now or utcnow()
    grace = float(CONFIG.get("position_exchange_grace_s", 120))
    if len(_bot_open_in_direction(pos.direction)) > 1:
        grace += float(CONFIG.get("position_exchange_grace_multi_s", 90))
    return (now - pos.entry_time).total_seconds() < grace


def _position_exchange_confirmed(pos: "Position") -> bool:
    """Позиция хотя бы раз видна в fetch_positions (или legacy positionId)."""
    return bool(getattr(pos, "exchange_seen", False) or pos.exchange_position_id)


def _maybe_mark_exchange_seen(pos: "Position", real_open: list[dict]) -> bool:
    """Отметить exchange_seen и подтянуть positionId при матче с биржей."""
    if not _position_matches_exchange(pos, real_open):
        return False
    if not pos.exchange_seen:
        pos.exchange_seen = True
        logger.info(
            f"exchange_seen #{pos.trade_num} {pos.direction} "
            f"@ {pos.entry_price:.1f}"
        )
    if not pos.exchange_position_id:
        for r in real_open:
            if r.get("direction") != pos.direction:
                continue
            if not _entry_near(r["entry"], pos.entry_price):
                continue
            if not _contracts_near(r["contracts"], pos.contracts):
                continue
            rpid = r.get("position_id")
            if rpid:
                pos.exchange_position_id = str(rpid)
                logger.info(
                    f"positionId backfill #{pos.trade_num} {pos.direction}: {rpid}"
                )
                break
    return True


async def _has_recent_open_deal_for_leg(
    direction: str,
    contracts: int,
    *,
    entry_near: Optional[float] = None,
    lookback_min: int = 15,
    trade_num: int = 0,
    symbol_key: Optional[str] = None,
) -> bool:
    """Недавний open-fill (Bybit buy/sell; MEXC side 1/3)."""
    if state.paper:
        return False
    label = f"#{trade_num}" if trade_num else direction
    since_ms = int((utcnow() - timedelta(minutes=lookback_min)).timestamp() * 1000)
    sym_ccxt = symbol_profile(symbol_key)["symbol"]
    loop = asyncio.get_event_loop()
    try:
        trades = await loop.run_in_executor(
            None,
            lambda: exchange.fetch_my_trades(sym_ccxt, since=since_ms, limit=80),
        )
    except Exception as e:
        logger.warning(f"open_deal_check {label}: {e}")
        return False
    need_vol = max(1.0, contracts * 0.45)
    for t in trades or []:
        info = t.get("info") or {}
        if not _mexc_trade_is_open_fill(info, direction, t):
            continue
        vol = _trade_vol_contracts(t, symbol_key)
        if vol < need_vol:
            continue
        if entry_near is not None:
            try:
                px = float(
                    info.get("dealAvgPrice")
                    or info.get("price")
                    or t.get("average")
                    or t.get("price")
                    or 0
                )
            except (TypeError, ValueError):
                px = 0.0
            if px > 0 and not _entry_near(px, entry_near):
                continue
        logger.info(f"open_deal {label} {direction}: side={side} vol={vol}")
        return True
    return False


async def _try_confirm_position_on_exchange(
    pos: "Position",
    real_open: Optional[list[dict]] = None,
) -> bool:
    """Подтвердить позицию на бирже (fetch_positions или open-deal)."""
    if _position_exchange_confirmed(pos):
        return True
    ro = real_open if real_open is not None else await _fetch_real_open_positions()
    if _maybe_mark_exchange_seen(pos, ro):
        return True
    if await _has_recent_open_deal_for_leg(
        pos.direction,
        pos.contracts,
        entry_near=pos.entry_price,
        trade_num=pos.trade_num,
    ):
        pos.exchange_seen = True
        logger.info(
            f"exchange_seen #{pos.trade_num} {pos.direction}: open-deal"
        )
        return True
    return False


async def _await_position_on_exchange(
    pos: "Position",
    *,
    timeout_s: Optional[float] = None,
) -> bool:
    """Ждать появления позиции на бирже после fill (до timeout_s)."""
    if await _try_confirm_position_on_exchange(pos):
        return True
    deadline = time.time() + float(
        timeout_s if timeout_s is not None
        else CONFIG.get("position_confirm_after_fill_s", 120)
    )
    poll = float(CONFIG.get("position_confirm_poll_s", 5.0))
    while time.time() < deadline:
        await asyncio.sleep(poll)
        if await _try_confirm_position_on_exchange(pos):
            return True
    return False


async def _maybe_alert_unconfirmed_position(pos: "Position") -> None:
    """TG если позиция долго не видна на бирже (ложный fill у MEXC)."""
    if pos.id in state._unconfirmed_alerted:
        return
    alert_s = float(CONFIG.get("position_unconfirmed_alert_s", 300))
    age = (utcnow() - pos.entry_time).total_seconds()
    if age < alert_s:
        return
    state._unconfirmed_alerted.add(pos.id)
    await send_telegram(
        f"⚠️ #{pos.trade_num} {pos.direction}: позиция не видна на бирже "
        f"{int(age)}с после fill @ {pos.entry_price:.1f}\n"
        f"Проверь Bybit вручную. closed_sync заблокирован до подтверждения."
    )


def _position_absent_retry_count(pos: "Position") -> int:
    n = int(CONFIG.get("position_absent_retries", 8))
    if len(_bot_open_in_direction(pos.direction)) > 1:
        n += int(CONFIG.get("position_absent_retries_multi_extra", 4))
    return max(3, n)


async def _position_absent_on_exchange(
    pos: "Position",
    real_open: Optional[list[dict]] = None,
) -> bool:
    """True только если позиция реально исчезла с биржи (не лаг API)."""
    if not _position_exchange_confirmed(pos):
        await _maybe_alert_unconfirmed_position(pos)
        return False
    if _position_in_exchange_grace(pos):
        return False
    if real_open is not None and _position_matches_exchange(pos, real_open):
        _maybe_mark_exchange_seen(pos, real_open)
        return False
    retries = _position_absent_retry_count(pos)
    delay = float(CONFIG.get("position_absent_retry_s", 3.0))
    for attempt in range(max(1, retries)):
        ro = await _fetch_real_open_positions()
        if _position_matches_exchange(pos, ro):
            _maybe_mark_exchange_seen(pos, ro)
            return False
        if attempt < retries - 1:
            await asyncio.sleep(delay)
    logger.warning(
        f"Позиция #{pos.trade_num} {pos.direction}: нет на бирже после "
        f"{retries} опросов (бот entry={pos.entry_price:.1f} {pos.contracts}ctr)"
    )
    return True


def _bot_open_in_direction(
    direction: str, symbol_key: Optional[str] = None,
) -> list["Position"]:
    out = [p for p in state.positions if p.status == "open" and p.direction == direction]
    if symbol_key is not None:
        out = [p for p in out if _pos_symbol_key(p) == symbol_key]
    return out


def _find_open_position_for_pyramid(direction: str, tf_name: str) -> Optional["Position"]:
    """Первая open-нога для доливки. v6: доливки нет (1 позиция на пару)."""
    return None
    cands = [
        p for p in state.positions
        if (
            p.status == "open"
            and p.direction == direction
            and p.tf == tf_name
            and _pos_symbol_key(p) == active_symbol_key()
        )
    ]
    if not cands:
        return None
    return min(cands, key=lambda p: p.entry_time or utcnow())


def _has_pyramid_pending(direction: str, tf_name: str) -> bool:
    for pl in state.pending_limits:
        if pl.status != "pending" or pl.direction != direction or pl.tf != tf_name:
            continue
        if getattr(pl, "pyramid_parent_id", ""):
            return True
    return False


def _position_by_id(pos_id: str) -> Optional["Position"]:
    for p in state.positions:
        if p.id == pos_id:
            return p
    return None


def _weighted_entry_price(
    old_entry: float, old_ctr: int, add_price: float, add_ctr: int,
) -> float:
    total = int(old_ctr) + int(add_ctr)
    if total <= 0:
        return float(add_price)
    return (float(old_entry) * int(old_ctr) + float(add_price) * int(add_ctr)) / total


def _exchange_position_id_from_order(order_info: Optional[dict]) -> Optional[str]:
    if not order_info:
        return None
    raw_info = order_info.get("info") or {}
    pid = (
        raw_info.get("positionId") or raw_info.get("position_id")
        or order_info.get("positionId")
    )
    return str(pid) if pid not in (None, "") else None


def _exchange_position_id_from_raw(rp: dict) -> Optional[str]:
    info = rp.get("info") or {}
    idx = info.get("positionIdx")
    if idx not in (None, ""):
        sk = _symbol_key_from_ccxt(str(rp.get("symbol") or info.get("symbol") or ""))
        return f"{sk}:{idx}"
    pid = info.get("positionId") or info.get("position_id") or rp.get("positionId")
    return str(pid) if pid not in (None, "") else None


def _other_open_on_same_exchange_pid(pos: "Position") -> list["Position"]:
    pid = pos.exchange_position_id
    if not pid:
        return []
    return [
        p for p in state.positions
        if p.status == "open" and p.id != pos.id
        and str(p.exchange_position_id or "") == str(pid)
    ]


def _bot_open_on_same_exchange_pid(pos: "Position") -> list["Position"]:
    """Open-ноги бота на том же positionId (MEXC агрегирует в одну биржевую ногу)."""
    pid = pos.exchange_position_id
    if not pid:
        return [p for p in _bot_open_in_direction(pos.direction) if p.id == pos.id]
    return [
        p for p in state.positions
        if p.status == "open"
        and p.direction == pos.direction
        and str(p.exchange_position_id or "") == str(pid)
    ]


def _exchange_row_for_pid(
    real_open: list[dict], position_id: str, direction: str,
) -> Optional[dict]:
    for r in real_open:
        if str(r.get("position_id") or "") != str(position_id):
            continue
        if r.get("direction") != direction:
            continue
        if float(r.get("contracts") or 0) < 0.5:
            return None
        return r
    return None


async def _resolve_exchange_position_id_for_fill(
    pl: "PendingLimit",
    avg_price: float,
    actual_ctr: int,
) -> Optional[str]:
    if state.paper:
        return None
    if pl.order_id:
        order_info = await get_order_status(pl.order_id, _pos_symbol_key(pl))
        pid = _exchange_position_id_from_order(order_info)
        if pid:
            return pid
    real_open = await _fetch_real_open_positions()
    for p in _bot_open_in_direction(pl.direction):
        spid = p.exchange_position_id
        if not spid:
            continue
        row = _exchange_row_for_pid(real_open, spid, pl.direction)
        if row is not None:
            return str(spid)
    for r in real_open:
        if r.get("direction") != pl.direction:
            continue
        if not _entry_near(r["entry"], avg_price):
            continue
        if not _contracts_near(r["contracts"], actual_ctr):
            continue
        rpid = r.get("position_id")
        if rpid:
            return str(rpid)
    return None


async def _backfill_exchange_position_id(pos: "Position") -> bool:
    """Для старых open без positionId — подтянуть с биржи по entry/объёму."""
    if state.paper or pos.exchange_position_id:
        return False
    real_open = await _fetch_real_open_positions()
    for p in _bot_open_in_direction(pos.direction):
        if p.id == pos.id or not p.exchange_position_id:
            continue
        row = _exchange_row_for_pid(real_open, p.exchange_position_id, pos.direction)
        if row is not None:
            pos.exchange_position_id = str(p.exchange_position_id)
            logger.info(
                f"positionId backfill #{pos.trade_num} {pos.direction}: "
                f"{pos.exchange_position_id} (from #{p.trade_num})"
            )
            return True
    for r in real_open:
        if r.get("direction") != pos.direction:
            continue
        if not _entry_near(r["entry"], pos.entry_price):
            continue
        if not _contracts_near(r["contracts"], pos.contracts):
            continue
        rpid = r.get("position_id")
        if not rpid:
            continue
        pos.exchange_position_id = str(rpid)
        logger.info(
            f"positionId backfill #{pos.trade_num} {pos.direction}: {rpid}"
        )
        return True
    return False


def _has_opposite_open_position(
    direction: str, symbol_key: Optional[str] = None,
) -> bool:
    """Есть ли open/pending в противоположном направлении (one-way: блокирует вход)."""
    opp = "SHORT" if direction == "LONG" else "LONG"
    sk = symbol_key if symbol_key is not None else active_symbol_key()
    if _bot_open_in_direction(opp, symbol_key=sk):
        return True
    return any(
        p.status == "pending" and p.direction == opp and _pos_symbol_key(p) == sk
        for p in state.pending_limits
    )


def _slope_cisd_arm_block_htf_windows() -> int:
    try:
        return max(1, int(CONFIG.get("slope_cisd_arm_block_htf_windows", 2)))
    except (TypeError, ValueError):
        return 2


def _slope_cisd_arm_ban_key(
    tf_name: str, direction: str, htf_time: str, sweep_level: float,
) -> str:
    sk = active_symbol_key()
    sweep_r = _round_sweep_level(sweep_level, sk)
    try:
        tf_cfg = CONFIG.get(tf_name) or {}
        htf_ratio = int(tf_cfg.get("htf_ratio") or 60)
        anchor = str(pd.Timestamp(htf_time).floor(f"{htf_ratio}min"))
    except Exception:
        anchor = str(htf_time)
    return f"{tf_name}|{direction}|htf={anchor}|sweep={sweep_r:.0f}"


def _prune_slope_cisd_arm_blocked(now: Optional[pd.Timestamp] = None) -> None:
    now = now or pd.Timestamp.utcnow()
    kept: list[dict] = []
    for rec in state.slope_cisd_arm_blocked:
        try:
            if pd.Timestamp(rec["expires_at"]) > now:
                kept.append(rec)
        except Exception:
            continue
    state.slope_cisd_arm_blocked = kept


def _record_slope_cisd_arm_block(sig: dict, tf_name: str) -> None:
    """Slope отклонил сетап — cisd_cross не arm'ить с тем же HTF-окном и sweep."""
    direction = str(sig.get("direction") or "")
    htf_s = str(sig.get("htf_time") or "")
    sweep_lvl = float(sig.get("htf_sweep_level") or 0)
    if direction not in ("LONG", "SHORT") or not htf_s or sweep_lvl <= 0:
        return
    tf_cfg = CONFIG.get(tf_name) or {}
    htf_ratio = int(tf_cfg.get("htf_ratio") or 60)
    try:
        anchor = pd.Timestamp(htf_s).floor(f"{htf_ratio}min")
    except Exception:
        return
    n_win = _slope_cisd_arm_block_htf_windows()
    expires = anchor + pd.Timedelta(minutes=htf_ratio * n_win)
    ban_key = _slope_cisd_arm_ban_key(tf_name, direction, htf_s, sweep_lvl)
    _prune_slope_cisd_arm_blocked()
    state.slope_cisd_arm_blocked = [
        r for r in state.slope_cisd_arm_blocked if r.get("ban_key") != ban_key
    ]
    state.slope_cisd_arm_blocked.append({
        "ban_key": ban_key,
        "tf": tf_name,
        "direction": direction,
        "htf_anchor": str(anchor),
        "sweep_level": sweep_lvl,
        "expires_at": expires.isoformat(),
    })
    logger.info(
        f"slope cisd_cross ban: {direction} [{tf_name}] "
        f"htf={anchor} sweep={sweep_lvl:.1f} до {expires}"
    )


def _is_slope_cisd_arm_blocked(
    tf_name: str, direction: str, htf_time: str, sweep_level: float,
) -> bool:
    ban_key = _slope_cisd_arm_ban_key(tf_name, direction, htf_time, sweep_level)
    _prune_slope_cisd_arm_blocked()
    return any(r.get("ban_key") == ban_key for r in state.slope_cisd_arm_blocked)


def _sig_has_mss_confirm(sig: dict) -> bool:
    cc = _safe_float(sig.get("confirm_close")) or 0.0
    cbt = str(sig.get("confirm_bar_time") or "")
    return cc > 0 and bool(cbt)


def _confirm_extreme_touched_fib1(
    direction: str, bar_high: float, bar_low: float, fib1: float,
) -> bool:
    """Экстремум конфирм-бара в сторону импульса достал до fib 1.0x."""
    if not fib1 or fib1 <= 0:
        return False
    if direction == "LONG":
        return float(bar_high) >= float(fib1)
    return float(bar_low) <= float(fib1)


def _exchange_contracts_sum(real_open: list[dict], direction: str) -> float:
    return sum(float(r["contracts"]) for r in real_open if r["direction"] == direction)


def _exchange_leg_covers_bot_open(direction: str, real_open: list[dict]) -> bool:
    """На бирже одна агрегированная нога ≥ суммы open бота — не orphan."""
    bot_same = _bot_open_in_direction(direction)
    if not bot_same:
        return False
    ex_ctr = _exchange_contracts_sum(real_open, direction)
    bot_total = sum(p.contracts for p in bot_same)
    if ex_ctr < max(1, bot_total - 2):
        return False
    same_dir = [r for r in real_open if r["direction"] == direction]
    if not same_dir:
        return False
    for p in bot_same:
        for r in same_dir:
            ep_ok = abs(r["entry"] - p.entry_price) / max(p.entry_price, 1.0) < 0.025
            if ep_ok:
                return True
    return len(bot_same) >= 1 and ex_ctr >= bot_total - 2


def _position_matches_exchange(pos: Position, real_open: list[dict]) -> bool:
    """Есть ли эта запись бота среди реальных позиций на бирже (one-way: несколько бот-записей → одна нога)."""
    sk = _pos_symbol_key(pos)
    real_open = [r for r in real_open if r.get("symbol_key", DEFAULT_SYMBOL_KEY) == sk]
    if pos.exchange_position_id:
        row = _exchange_row_for_pid(
            real_open, pos.exchange_position_id, pos.direction,
        )
        if row is None:
            return False
        siblings = _bot_open_on_same_exchange_pid(pos)
        ex_ctr = float(row["contracts"])
        if len(siblings) <= 1:
            return _contracts_near(ex_ctr, pos.contracts)
        bot_total = sum(p.contracts for p in siblings)
        if ex_ctr >= max(1, bot_total - 2):
            return True
        return ex_ctr >= max(1, pos.contracts - 1)

    same_dir = [r for r in real_open if r["direction"] == pos.direction]
    if not same_dir:
        return False

    ex_ctr = _exchange_contracts_sum(real_open, pos.direction)
    bot_same = _bot_open_in_direction(pos.direction)
    bot_total = sum(p.contracts for p in bot_same)

    for r in same_dir:
        ct_ok = abs(r["contracts"] - pos.contracts) <= max(1, pos.contracts * 0.25)
        ep_ok = abs(r["entry"] - pos.entry_price) / max(pos.entry_price, 1) < 0.015
        if ct_ok and ep_ok:
            return True

    for r in same_dir:
        if abs(r["contracts"] - pos.contracts) <= max(1, pos.contracts * 0.25):
            return True

    # one-way: на бирже одна нога, в боте несколько open — объём ноги ≥ нашей доли
    if ex_ctr >= max(1, pos.contracts - 1):
        ep_ok = any(
            abs(r["entry"] - pos.entry_price) / max(pos.entry_price, 1) < 0.02
            for r in same_dir
        )
        if ep_ok:
            return True
        if len(bot_same) > 1 and ex_ctr >= bot_total - 2:
            return True

    if len(same_dir) == 1 and ex_ctr >= max(1, pos.contracts - 2):
        if len(bot_same) <= 1:
            return abs(same_dir[0]["contracts"] - pos.contracts) <= max(2, pos.contracts * 0.5)
        return ex_ctr >= pos.contracts - 1

    return False


async def _has_recent_close_deal_for_leg(
    direction: str,
    contracts: int,
    *,
    lookback_min: Optional[int] = None,
    trade_num: int = 0,
    symbol_key: Optional[str] = None,
) -> bool:
    """Недавний close-fill на бирже для направления/объёма."""
    if state.paper:
        return False
    if lookback_min is None:
        lookback_min = int(CONFIG.get("close_deal_lookback_min", 360))
    label = f"#{trade_num}" if trade_num else direction
    since_ms = int((utcnow() - timedelta(minutes=lookback_min)).timestamp() * 1000)
    sym_ccxt = symbol_profile(symbol_key)["symbol"]
    loop = asyncio.get_event_loop()
    try:
        trades = await loop.run_in_executor(
            None,
            lambda: exchange.fetch_my_trades(sym_ccxt, since=since_ms, limit=80),
        )
    except Exception as e:
        logger.warning(f"close_deal_check {label}: {e}")
        return False
    need_vol = max(1.0, contracts * 0.45)
    for t in trades or []:
        info = t.get("info") or {}
        if not _mexc_trade_is_close_fill(info, direction, t):
            continue
        vol = _trade_vol_contracts(t, symbol_key)
        if vol >= need_vol:
            logger.info(
                f"close_deal {label} {direction}: side={_trade_side_str(t)} vol={vol} "
                f"reduceOnly={info.get('reduceOnly')}"
            )
            return True
    return False


def _mexc_trade_reduce_only(info: dict, trade: Optional[dict] = None) -> bool:
    vals = [info.get("reduceOnly"), info.get("isReduceOnly")]
    if trade:
        vals.append(trade.get("reduceOnly"))
    return any(v in (True, "true", "True", 1, "1") for v in vals)


def _closed_size(info: dict) -> float:
    try:
        return float(info.get("closedSize") or 0)
    except (TypeError, ValueError):
        return 0.0


def _mexc_trade_is_close_fill(
    info: dict, direction: str, trade: Optional[dict] = None,
) -> bool:
    """Close-fill: Bybit closedSize/reduceOnly + buy/sell; MEXC side 2/4."""
    side = _trade_side_str(trade or {"info": info})
    closed = _closed_size(info) > 0
    reduce = _mexc_trade_reduce_only(info, trade)
    if closed or reduce:
        if direction == "LONG" and side in ("sell", "4", "3"):
            return True
        if direction == "SHORT" and side in ("buy", "1", "2"):
            return True
        if closed and side in ("buy", "sell"):
            return (direction == "LONG" and side == "sell") or (
                direction == "SHORT" and side == "buy"
            )
    try:
        si = int(info.get("side") or 0)
    except (TypeError, ValueError):
        si = 0
    close_side = 4 if direction == "LONG" else 2
    if si == close_side:
        return True
    if reduce:
        if direction == "LONG" and si in (3, 4):
            return True
        if direction == "SHORT" and si in (1, 2):
            return True
    return False


def _mexc_trade_is_open_fill(
    info: dict, direction: str, trade: Optional[dict] = None,
) -> bool:
    if _mexc_trade_is_close_fill(info, direction, trade):
        return False
    side = _trade_side_str(trade or {"info": info})
    if direction == "LONG" and side in ("buy", "1"):
        return True
    if direction == "SHORT" and side in ("sell", "3"):
        return True
    try:
        si = int(info.get("side") or 0)
    except (TypeError, ValueError):
        return False
    return (direction == "LONG" and si == 1) or (direction == "SHORT" and si == 3)


async def _has_recent_close_deal(pos: "Position", *, lookback_min: Optional[int] = None) -> bool:
    if lookback_min is None:
        lookback_min = int(CONFIG.get("close_deal_lookback_min", 360))
    return await _has_recent_close_deal_for_leg(
        pos.direction, pos.contracts, lookback_min=lookback_min,
        trade_num=pos.trade_num, symbol_key=_pos_symbol_key(pos),
    )


def _record_recent_close(pos: "Position") -> None:
    """Память о недавнем закрытии — sync_exchange не создаёт orphan на лаге MEXC."""
    state._recent_closes.append(
        (time.time(), pos.direction, float(pos.entry_price), int(pos.contracts))
    )
    grace = float(CONFIG.get("orphan_after_close_grace_s", 180)) + 60
    cutoff = time.time() - grace
    state._recent_closes = [r for r in state._recent_closes if r[0] >= cutoff]


def _exchange_leg_matches_recent_close(
    direction: str, entry_price: float, contracts: int,
) -> bool:
    """Та же нога, что мы только что закрыли (TP/SL) — ghost в fetch_positions."""
    grace = float(CONFIG.get("orphan_after_close_grace_s", 180))
    cutoff = time.time() - grace
    for ts, d, ep, ctr in state._recent_closes:
        if ts < cutoff or d != direction:
            continue
        ep_ok = abs(ep - entry_price) / max(entry_price, 1.0) < 0.015
        ct_ok = abs(ctr - contracts) <= max(1, contracts * 0.25)
        if ep_ok and ct_ok:
            return True
    for p in state.positions:
        if p.direction != direction or p.status not in (
            "closed_tp", "closed_sl", "closed_time", "closed_manual",
        ):
            continue
        ep_ok = abs(p.entry_price - entry_price) / max(entry_price, 1.0) < 0.015
        ct_ok = abs(p.contracts - contracts) <= max(1, contracts * 0.25)
        if ep_ok and ct_ok:
            return True
    return False


def _ghost_cleanup_lock(direction: str) -> asyncio.Lock:
    lock = state._ghost_cleanup_locks.get(direction)
    if lock is None:
        lock = asyncio.Lock()
        state._ghost_cleanup_locks[direction] = lock
    return lock


def _exchange_ghost_remainder(
    direction: str,
    real_open: list[dict],
    symbol_key: Optional[str] = None,
) -> tuple[int, Optional[str], float, str]:
    """Избыточные ctr на бирже относительно суммы open бота в этом direction."""
    sk = symbol_key or active_symbol_key()
    bot_total = sum(
        p.contracts for p in _bot_open_in_direction(direction, symbol_key=sk)
    )
    same_dir = [
        r for r in real_open
        if r.get("direction") == direction and r.get("symbol_key", DEFAULT_SYMBOL_KEY) == sk
    ]
    if not same_dir:
        return 0, None, 0.0, sk
    ex_ctr = sum(float(r.get("contracts") or 0) for r in same_dir)
    remainder = int(round(ex_ctr - bot_total))
    if remainder <= 0:
        return 0, None, 0.0, sk
    leg = max(same_dir, key=lambda r: float(r.get("contracts") or 0))
    pid = leg.get("position_id")
    entry = float(leg.get("entry") or 0)
    return remainder, str(pid) if pid else None, entry, sk


async def _try_cleanup_exchange_ghost(
    direction: str,
    *,
    source_trade_num: int = 0,
    grace_s: Optional[float] = None,
    polls: Optional[int] = None,
    symbol_key: Optional[str] = None,
) -> bool:
    """Market-close хвоста на агрегированной ноге MEXC (ex_ctr > bot_ctr)."""
    if state.paper or not CONFIG.get("ghost_cleanup_enabled", True):
        return False

    max_ctr = int(CONFIG.get("ghost_cleanup_max_ctr", 15))
    n_polls = max(1, int(polls if polls is not None else CONFIG.get("ghost_cleanup_polls", 3)))
    poll_s = float(CONFIG.get("ghost_cleanup_poll_s", 8))
    initial_grace = float(
        grace_s if grace_s is not None else CONFIG.get("ghost_cleanup_grace_s", 25)
    )

    async with _ghost_cleanup_lock(direction):
        if initial_grace > 0:
            await asyncio.sleep(initial_grace)

        remainder = 0
        pid: Optional[str] = None
        entry = 0.0
        sk = symbol_key or active_symbol_key()
        for i in range(n_polls):
            ro = await _fetch_real_open_positions()
            remainder, pid, entry, sk = _exchange_ghost_remainder(direction, ro, sk)
            if remainder <= 0:
                return False
            if i + 1 < n_polls:
                await asyncio.sleep(poll_s)

        if remainder > max_ctr:
            tag = f"#{source_trade_num}" if source_trade_num else direction
            logger.warning(
                f"ghost_cleanup {tag}: {remainder}ctr {direction} @ {entry:.1f} "
                f"> max {max_ctr} — только TG"
            )
            await send_telegram(
                f"⚠️ Ghost {remainder} ctr {direction} @ {entry:.1f}\n"
                f"Слишком много для авто-закрытия (max {max_ctr}). "
                f"Проверь Bybit вручную."
            )
            return False

        px = get_price() or entry or 0.0
        tag = f"#{source_trade_num}" if source_trade_num else direction
        logger.info(
            f"ghost_cleanup {tag}: close {remainder}ctr {direction} "
            f"pid={pid} @~{entry:.1f}"
        )
        resp = await mexc_close_position_market(
            direction, remainder, price_hint=px, position_id=pid,
            symbol_key=sk,
        )
        if not resp:
            await send_telegram(
                f"⚠️ Ghost {remainder} ctr {direction}: не удалось закрыть на бирже"
            )
            return False

        await asyncio.sleep(float(CONFIG.get("close_verify_delay_s", 0.6)))
        ro_after = await _fetch_real_open_positions()
        rem_after, _, _, _ = _exchange_ghost_remainder(direction, ro_after, sk)
        if rem_after >= remainder:
            logger.error(
                f"ghost_cleanup verify fail {tag}: осталось {rem_after}ctr"
            )
            await send_telegram(
                f"⚠️ Ghost {remainder} ctr {direction}: close отправлен, "
                f"но на бирже ещё {rem_after} ctr"
            )
            return False

        await send_telegram(
            f"🧹 Ghost: закрыто {remainder} ctr {direction} @ market\n"
            f"Хвост после {tag} TP/SL (entry биржи ~{entry:.1f})"
        )
        logger.info(f"ghost_cleanup ok {tag}: closed {remainder}ctr {direction}")
        return True


async def _cleanup_ghost_after_protection_close(pos: "Position") -> None:
    try:
        await _try_cleanup_exchange_ghost(
            pos.direction, source_trade_num=pos.trade_num,
        )
    except Exception as e:
        logger.error(f"ghost_cleanup #{pos.trade_num}: {e}")


def _maybe_schedule_ghost_cleanup_sync(direction: str, real_open: list[dict]) -> None:
    """Фоновая проверка хвоста при sync (не только сразу после TP/SL)."""
    if state.paper or not CONFIG.get("ghost_cleanup_enabled", True):
        return
    for sk in _tracked_symbol_keys():
        remainder, _, _, _ = _exchange_ghost_remainder(direction, real_open, sk)
        if remainder <= 0:
            continue
        max_ctr = int(CONFIG.get("ghost_cleanup_max_ctr", 15))
        if remainder > max_ctr:
            continue
        min_s = float(CONFIG.get("ghost_cleanup_sync_min_s", 90))
        now = time.time()
        gkey = f"{sk}|{direction}"
        if now - state._ghost_cleanup_last.get(gkey, 0) < min_s:
            continue
        state._ghost_cleanup_last[gkey] = now
        asyncio.create_task(
            _try_cleanup_exchange_ghost(
                direction, symbol_key=sk, grace_s=min_s * 0.5,
            )
        )
        return


async def _confirm_closed_sync(pos: "Position") -> bool:
    """Доп. проверка перед closed_sync: не снимать SL/TP на лаге fetch_positions."""
    polls = int(CONFIG.get("closed_sync_confirm_polls", 4))
    delay = float(CONFIG.get("closed_sync_confirm_poll_s", 4.0))
    bot_same = _bot_open_in_direction(pos.direction)
    bot_total = sum(p.contracts for p in bot_same)
    multi = len(bot_same) > 1

    baseline_ctr: Optional[float] = None
    consecutive_zero = 0
    last_ctr = 0.0

    for i in range(max(2, polls)):
        ro = await _fetch_real_open_positions()
        if _position_matches_exchange(pos, ro):
            _maybe_mark_exchange_seen(pos, ro)
            logger.warning(
                f"closed_sync confirm fail #{pos.trade_num}: снова видна на бирже (poll {i+1})"
            )
            return False
        last_ctr = _exchange_contracts_sum(ro, pos.direction)
        if baseline_ctr is None:
            baseline_ctr = last_ctr
        if last_ctr < 1:
            consecutive_zero += 1
        else:
            consecutive_zero = 0
        if i < polls - 1:
            await asyncio.sleep(delay)

    if multi:
        if baseline_ctr is not None and baseline_ctr < 1 and consecutive_zero >= polls:
            if await _has_recent_close_deal(pos):
                return True
            logger.warning(
                f"closed_sync confirm fail #{pos.trade_num}: multi {pos.direction}, "
                f"fetch пустой без close-deal (bot_total={bot_total})"
            )
            return False
        dropped = (baseline_ctr or 0) - last_ctr
        if last_ctr > bot_total - pos.contracts + 1:
            logger.warning(
                f"closed_sync confirm fail #{pos.trade_num}: на бирже {last_ctr:.0f}ctr, "
                f"ожидали ≤{bot_total - pos.contracts + 1}"
            )
            return False
        if dropped >= max(1, pos.contracts - 1):
            return True
        if await _has_recent_close_deal(pos):
            return True
        logger.warning(
            f"closed_sync confirm fail #{pos.trade_num}: объём не упал "
            f"({baseline_ctr:.0f}→{last_ctr:.0f}, need -{pos.contracts})"
        )
        return False

    if last_ctr >= max(1, pos.contracts - 1):
        logger.warning(
            f"closed_sync confirm fail #{pos.trade_num}: на бирже ещё {last_ctr:.0f}ctr"
        )
        return False
    if consecutive_zero >= polls:
        lookback = int(CONFIG.get("close_deal_lookback_min", 360))
        if await _has_recent_close_deal(pos, lookback_min=lookback):
            return True
        scanned = await _scan_filled_protection_orders(pos)
        if scanned:
            logger.info(
                f"closed_sync confirm #{pos.trade_num}: {scanned[0]} "
                f"from plan @ {scanned[1]:.1f}"
            )
            return True
        if pos.exchange_seen and not multi:
            logger.info(
                f"closed_sync confirm #{pos.trade_num}: empty fetch x{consecutive_zero}, "
                f"exchange_seen — accept external/manual close"
            )
            return True
        logger.warning(
            f"closed_sync confirm fail #{pos.trade_num}: пустой fetch "
            f"без close-deal и без исполненного SL/TP"
        )
        return False
    if await _has_recent_close_deal(pos, lookback_min=int(CONFIG.get("close_deal_lookback_min", 360))):
        return True
    logger.warning(
        f"closed_sync confirm fail #{pos.trade_num}: нет нулевого подтверждения и нет close-deal"
    )
    return False


async def _close_position_on_exchange(
    pos: "Position",
    *,
    price_hint: Optional[float] = None,
    notify_blocked: bool = True,
) -> bool:
    """Закрыть ногу через MEXC side=2/4 и убедиться, что запись бота больше не на бирже."""
    if state.paper:
        return True
    others = _other_open_on_same_exchange_pid(pos)
    if others:
        nums = ", ".join(f"#{p.trade_num}" for p in others)
        logger.info(
            f"CLOSE blocked #{pos.trade_num} {pos.direction}: "
            f"общий positionId {pos.exchange_position_id} с {nums}"
        )
        if notify_blocked:
            await send_telegram(
                f"🚨 #{pos.trade_num} {pos.direction}: не закрываю на бирже\n"
                f"Общий positionId {pos.exchange_position_id} с {nums}.\n"
                f"Закрой вручную или дождись закрытия соседней ноги."
            )
        return False
    resp = await mexc_close_position_market(
        pos.direction, pos.contracts, price_hint=price_hint,
        position_id=pos.exchange_position_id,
        symbol_key=_pos_symbol_key(pos),
    )
    if not resp:
        return False
    await asyncio.sleep(float(CONFIG.get("close_verify_delay_s", 0.6)))
    ro = await _fetch_real_open_positions()
    if _position_matches_exchange(pos, ro):
        logger.error(
            f"CLOSE verify fail #{pos.trade_num} {pos.direction}: "
            f"биржа всё ещё {pos.contracts}ctr @~{pos.entry_price:.1f}"
        )
        return False
    logger.info(f"CLOSE verify ok #{pos.trade_num} {pos.direction}")
    return True


async def _live_force_close_position(
    pos: "Position",
    reason: str,
    close_price: float,
    *,
    notify: bool = True,
    fail_msg: str = "",
) -> bool:
    """Отмена plan SL/TP → MEXC close → finalize. При ошибке close позиция остаётся open."""
    if state.paper:
        await _finalize_position_close(pos, reason, close_price, notify=notify)
        return True

    others = _other_open_on_same_exchange_pid(pos)
    if others:
        nums = ", ".join(f"#{p.trade_num}" for p in others)
        logger.info(
            f"force close deferred #{pos.trade_num} {pos.direction}: "
            f"shared positionId {pos.exchange_position_id} with {nums}"
        )
        return False

    state._force_close_in_progress.add(pos.id)
    try:
        await _cancel_position_sl_tp_plans(pos)
        pos.stop_order_id = None
        pos.tp_order_id = None
        if not await _close_position_on_exchange(
            pos, price_hint=close_price, notify_blocked=False,
        ):
            state._force_close_in_progress.discard(pos.id)
            tfl = tf_label(pos.tf)
            msg = fail_msg or (
                f"🚨 #{pos.trade_num} {pos.direction} [{tfl}]: не удалось закрыть на бирже!\n"
                f"Проверь Bybit — позиция может остаться открытой."
            )
            await _restore_position_sl_tp(pos, alert=True)
            await send_telegram(msg)
            return False

        await _finalize_position_close(pos, reason, close_price, notify=notify)
        return True
    finally:
        state._force_close_in_progress.discard(pos.id)


def _active_same_setup_conflict(sig: dict, tf_name: str) -> Optional[str]:
    """Уже есть нога с тем же SL/TP (любой HTF) — не дублировать MARKET/лимитку."""
    sp = _sig_setup_params(sig, tf_name)
    sl, tp = float(sp["sl"]), float(sp["tp"])
    if sl <= 0 or tp <= 0:
        return None
    direction = str(sp["direction"])

    for p in state.positions:
        if p.status != "open" or p.tf != sp["tf"] or p.direction != direction:
            continue
        if _setup_sl_tp_match(p.stop_price, p.tp_price, sl, tp):
            return f"OPEN #{p.trade_num} @ {p.entry_price:.1f}"

    for pl in state.pending_limits:
        if pl.tf != sp["tf"] or pl.direction != direction:
            continue
        if not _setup_sl_tp_match(pl.stop_price, pl.tp_price, sl, tp):
            continue
        if pl.status == "pending":
            return f"PENDING #{pl.trade_num} {pl.id[:8]}"
        if pl.id in state._fill_in_progress:
            return f"FILL in progress #{pl.trade_num}"
        if pl.status == "filled" and not _filled_pending_stale(pl):
            return f"FILLED pending #{pl.trade_num}"
    leg_k = _setup_leg_lock_key(sp["tf"], direction, sl, tp)
    if leg_k in state.htf_sweep_lock:
        return f"setup lock {leg_k}"
    return None


def _duplicate_active_setup(sig: dict, tf_name: str) -> bool:
    """True если тот же сетап уже в fill/OPEN (защита от второго MARKET после STOP fill)."""
    direction = str(sig.get("direction") or "")
    sig_hash = str(sig.get("hash") or "")
    entry = float(sig.get("entry") or 0)
    sig_htf = _htf_time_for_sig(sig, tf_name)

    for p in state.positions:
        if p.status != "open" or p.direction != direction:
            continue
        if not _htf_times_match(sig_htf, _htf_time_for_position(p)):
            continue
        if sig_hash and getattr(p, "sig_hash", None) == sig_hash:
            return True
        if entry > 0 and _entry_near(p.entry_price, entry, pct=0.003):
            return True

    for pl in state.pending_limits:
        if pl.direction != direction or pl.tf != tf_name:
            continue
        if not _htf_times_match(sig_htf, _htf_time_for_pending(pl, tf_name)):
            continue
        if pl.id in state._fill_in_progress:
            return True
        if pl.status != "filled":
            continue
        if sig_hash and pl.sig_hash == sig_hash:
            return True
        if entry > 0 and _entry_near(pl.entry_price, entry, pct=0.003):
            age = (utcnow() - pl.created_at).total_seconds() if pl.created_at else 0
            if age < float(CONFIG.get("position_exchange_grace_s", 120)) + 60:
                return True
    return False


def _filled_pending_stale(pl: "PendingLimit") -> bool:
    """filled pending без open Position дольше filled_pending_stale_s — не ждём finalize."""
    if pl.status != "filled":
        return False
    if any(p.status == "open" and p.id == pl.id for p in state.positions):
        return False
    if pl.id in state._fill_in_progress:
        return False
    if not pl.created_at:
        return True
    age = (utcnow() - pl.created_at).total_seconds()
    return age >= float(CONFIG.get("filled_pending_stale_s", 600))


def _cleanup_stale_filled_pendings() -> int:
    """Снимает зависшие filled pending (нет open Position, давно)."""
    n = 0
    for pl in list(state.pending_limits):
        if not _filled_pending_stale(pl):
            continue
        pl.status = "cancelled_stale"
        _journal_log_pending_cancelled(pl)
        n += 1
        logger.info(
            f"STALE pending {pl.id[:8]} #{pl.trade_num} {pl.direction} "
            f"— снят с учёта (filled без Position)"
        )
    if n:
        save_pending(state.pending_limits)
    return n


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return None if (v != v) else v
    except Exception:
        return None


def _archive_trade(pos: Position):
    trades = load_json(_trades_file(), [])
    trades.append(pos.to_dict())
    save_json(_trades_file(), trades)
    _journal_on_trade_closed(pos)


def tf_label(tf_name: str) -> str:
    """Читаемый лейбл таймфрейма из конфига."""
    return CONFIG.get(tf_name, {}).get("label", tf_name)


def _fee_rate_to_pct_str(rate: float) -> str:
    """Внутренний rate → строка как на бирже: 0.0001 → '0.01'."""
    pct = float(rate) * 100.0
    return f"{pct:.4f}".rstrip("0").rstrip(".")


def _parse_fee_percent_input(text: str) -> Optional[float]:
    """Процент с биржи (0.02) → rate (0.0002). None если невалидно."""
    raw = (text or "").strip().replace(",", ".").replace("%", "")
    if not raw:
        return None
    try:
        pct = float(raw)
    except ValueError:
        return None
    if pct < 0 or pct > 5:
        return None
    return pct / 100.0


def _trade_levels_valid(direction: str, entry: float, stop: float, tp: float) -> bool:
    if direction == "LONG":
        return float(entry) > float(stop) and float(tp) > float(entry)
    return float(stop) > float(entry) and float(entry) > float(tp)


def _calc_rr(direction: str, entry: float, stop: float, tp: float) -> Optional[float]:
    if not _trade_levels_valid(direction, entry, stop, tp):
        return None
    risk = abs(float(entry) - float(stop))
    if risk <= 0:
        return None
    return abs(float(tp) - float(entry)) / risk


def _cisd_limit_price(entry_price: float, cisd_level: float) -> float:
    return float(cisd_level) if cisd_level and cisd_level > 0 else float(entry_price)


def _is_retrace_at_creation(direction: str, cisd: float, price_ref: float) -> bool:
    """Цена при создании уже за CISD — ждём откат лимиткой, не market."""
    if price_ref <= 0 or cisd <= 0:
        return False
    if direction == "LONG":
        return price_ref > cisd
    return price_ref < cisd


def _late_retest_entry(direction: str, cisd: float, price_ref: float) -> bool:
    """Close конфирма уже за CISD — LIMIT @ CISD, ждём ретест к уровню (не STOP-LIMIT)."""
    return _is_retrace_at_creation(direction, cisd, price_ref)


def _entry_kind_for_signal(sig: dict) -> str:
    """v6: только LIMIT на cisd_level."""
    return "LIMIT"


def _entry_price_for_rr(
    entry_kind: str,
    cisd: float,
    price_ref: float,
) -> float:
    """R:R от фактического планового входа: MARKET — ref/fill, LIMIT/STOP — CISD."""
    if (entry_kind or "").upper() == "MARKET" and price_ref > 0:
        return float(price_ref)
    return float(cisd)


def _is_tf4_early_two_bar_pattern(
    tf_name: str,
    recent_from: int,
    trigger_idx: int,
    confirm_idx: int,
    sweep_close_idx: int,
) -> bool:
    """tf4: бар 1 HTF — свип, бар 2 — close-свип + CISD на одном баре."""
    if tf_name != TF4_BAR3_PATTERN_TF:
        return False
    bar2_idx = recent_from + 1
    if trigger_idx != recent_from:
        return False
    if confirm_idx != bar2_idx:
        return False
    return sweep_close_idx == confirm_idx


def _tf4_bar3_confirms_direction(
    df: pd.DataFrame,
    direction: str,
    recent_from: int,
) -> tuple[bool, str]:
    """Бар 3 HTF закрылся в сторону импульса за экстремум бара 2."""
    bar2_idx = recent_from + 1
    bar3_idx = recent_from + 2
    if bar3_idx >= len(df):
        return False, "нет бара 3 в df"
    bar2 = df.iloc[bar2_idx]
    bar3_close = float(df.iloc[bar3_idx]["close"])
    if direction == "SHORT":
        ext = float(bar2["low"])
        ok = bar3_close < ext
        return ok, f"bar3 close={bar3_close:.1f} {'<' if ok else '≥'} bar2 low={ext:.1f}"
    ext = float(bar2["high"])
    ok = bar3_close > ext
    return ok, f"bar3 close={bar3_close:.1f} {'>' if ok else '≤'} bar2 high={ext:.1f}"


def _price_ref_for_entry_kind(
    *,
    confirm_close: float = 0.0,
    price_at_creation: float = 0.0,
    fallback: float = 0.0,
) -> float:
    """Ref для типа входа: close конфирм-бара приоритетнее live-цены."""
    if confirm_close and confirm_close > 0:
        return float(confirm_close)
    if price_at_creation and price_at_creation > 0:
        return float(price_at_creation)
    return float(fallback or 0.0)


def _pending_entry_price_ref(pl: "PendingLimit") -> float:
    cisd = pl.cisd_level or pl.entry_price
    cc = float(getattr(pl, "confirm_close", 0) or 0)
    sc = float(getattr(pl, "sweep_close_close", 0) or 0)
    return _price_ref_for_entry_kind(
        confirm_close=cc if cc > 0 else sc,
        price_at_creation=pl.price_at_creation,
        fallback=cisd,
    )


def _signal_entry_price_ref(sig: dict) -> float:
    """MSS confirm_close приоритетнее; иначе close бара close-свипа (STOP-LIMIT)."""
    cc = _safe_float(sig.get("confirm_close")) or 0.0
    sc = _safe_float(sig.get("sweep_close_close")) or 0.0
    live = get_price() or 0.0
    return _price_ref_for_entry_kind(
        confirm_close=cc if cc > 0 else sc,
        price_at_creation=live,
        fallback=float(sig.get("cisd_level") or sig.get("entry") or 0),
    )


def _cisd_price_crossed(direction: str, cisd: float, price: float) -> bool:
    """Live-цена пересекла уровень CISD (LONG: >=, SHORT: <=)."""
    if not cisd or not price:
        return False
    if direction == "LONG":
        return float(price) >= float(cisd)
    return float(price) <= float(cisd)


def _has_cisd_cross_pending(tf_name: str, direction: str, htf_time: str) -> bool:
    return _has_pending_for_htf(tf_name, direction, htf_time)


def _has_pending_for_htf(tf_name: str, direction: str, htf_time: str) -> bool:
    for pl in state.pending_limits:
        if pl.status != "pending":
            continue
        if pl.tf != tf_name or pl.direction != direction:
            continue
        if _htf_times_match(htf_time, _htf_time_for_pending(pl, tf_name)):
            return True
    return False


def _find_near_pending_duplicate(
    tf_name: str,
    direction: str,
    entry: float,
    stop: float,
) -> Optional["PendingLimit"]:
    """Pending с тем же направлением/ТФ и близким entry (любой HTF)."""
    stop_dist = abs(float(entry) - float(stop)) if entry and stop else 0.0
    if stop_dist <= 0 and entry > 0:
        stop_dist = float(entry) * 0.005
    for pl in state.pending_limits:
        if pl.status != "pending":
            continue
        if pl.tf != tf_name or pl.direction != direction:
            continue
        if abs(pl.entry_price - float(entry)) < stop_dist:
            return pl
    return None


def _confirm_close_past_sweep(direction: str, close: float, sweep_level: float) -> bool:
    """Конфирм-бар закрылся телом за уровнем свипа (не только фитиль)."""
    if sweep_level <= 0:
        return True
    if direction == "LONG":
        return float(close) > float(sweep_level)
    return float(close) < float(sweep_level)


def _confirm_wick_past_sweep(
    direction: str,
    bar_high: float,
    bar_low: float,
    sweep_level: float,
) -> bool:
    """Фитиль конфирм-бара достал до уровня свипа."""
    if sweep_level <= 0:
        return False
    if direction == "LONG":
        return float(bar_high) >= float(sweep_level)
    return float(bar_low) <= float(sweep_level)


def _sweep_cisd_retest_limit(
    direction: str, sweep_level: float, cisd_level: float,
) -> bool:
    """SHORT: свип ниже CISD; LONG: свип выше CISD → LIMIT на ретест CISD."""
    if sweep_level <= 0 or cisd_level <= 0:
        return False
    if direction == "LONG":
        return sweep_level > cisd_level
    return sweep_level < cisd_level


def _pending_is_limit_retest(pl: "PendingLimit") -> bool:
    """Pending с LIMIT на CISD и ожиданием отката (не STOP-LIMIT пробой)."""
    if getattr(pl, "force_limit_retest", False):
        return True
    cisd = pl.cisd_level or pl.entry_price
    pac = _pending_entry_price_ref(pl)
    kind = pl.entry_kind or _pending_entry_kind(pl)
    if kind != "LIMIT":
        return False
    sweep = float(pl.sweep_level or 0)
    return (
        _is_retrace_at_creation(pl.direction, cisd, pac)
        or _sweep_cisd_retest_limit(pl.direction, sweep, cisd)
    )


def _pending_fib2_touched_without_fill(
    pl: "PendingLimit",
    price: Optional[float],
    ohlc_low: Optional[float],
    ohlc_high: Optional[float],
) -> bool:
    """Цена/экстремум дошли до TP (fib 2.0x), а вход ещё не случился."""
    tp_lvl = float(pl.tp_price)
    if pl.direction == "LONG":
        return bool(
            (price is not None and price >= tp_lvl and price > pl.entry_price)
            or (
                ohlc_high is not None
                and ohlc_high >= tp_lvl
                and (price is None or price > pl.entry_price)
            )
        )
    return bool(
        (price is not None and price <= tp_lvl and price < pl.entry_price)
        or (
            ohlc_low is not None
            and ohlc_low <= tp_lvl
            and (price is None or price < pl.entry_price)
        )
    )


def _df_touched_tp_since(
    df: pd.DataFrame,
    direction: str,
    tp: float,
    since_ts,
) -> bool:
    """Есть ли бар с since (включительно), где high/low уже касался TP."""
    if df is None or len(df) == 0 or tp <= 0:
        return False
    try:
        since = pd.Timestamp(since_ts)
    except Exception:
        return False
    idx = df.index
    try:
        if getattr(idx, "tz", None) is not None:
            since = since.tz_localize(idx.tz) if since.tzinfo is None else since.tz_convert(idx.tz)
        else:
            since = since.tz_localize(None) if since.tzinfo is not None else since
    except Exception:
        try:
            since = pd.Timestamp(since_ts).tz_localize(None)
        except Exception:
            return False
    sub = df[idx >= since]
    if sub.empty:
        return False
    if direction == "LONG":
        return float(sub["high"].max()) >= float(tp) - 1e-12
    if direction == "SHORT":
        return float(sub["low"].min()) <= float(tp) + 1e-12
    return False


async def _hist_tp_already_touched(
    *,
    direction: str,
    tp: float,
    tf_name: str,
    confirm_bar_time: str = "",
    trigger_bar_time: str = "",
) -> tuple[bool, str]:
    """
    True если после MSS confirm (fallback: trigger) цена уже касалась TP.
    Возвращает (hit, since_label).
    """
    if direction not in ("LONG", "SHORT") or float(tp or 0) <= 0:
        return False, ""
    since = str(confirm_bar_time or trigger_bar_time or "").strip()
    if not since:
        return False, ""
    # Сейчас цена уже за TP — тоже hit (без OHLC).
    px = get_price()
    if px:
        if direction == "LONG" and float(px) >= float(tp):
            return True, f"price_now={_fmt_px(px)} ≥ TP={_fmt_px(tp)}"
        if direction == "SHORT" and float(px) <= float(tp):
            return True, f"price_now={_fmt_px(px)} ≤ TP={_fmt_px(tp)}"

    confirm_tf = _confirm_timeframe_for(tf_name) or "1m"
    df = await fetch_ohlcv(confirm_tf, limit=1500)
    if df is None or len(df) < 2:
        tf_cfg = CONFIG.get(tf_name, {})
        df = await fetch_ohlcv(
            str(tf_cfg.get("timeframe") or "5m"),
            int(tf_cfg.get("ohlcv") or 500),
        )
    if df is None or len(df) < 2:
        return False, ""
    if _df_touched_tp_since(df, direction, float(tp), since):
        return True, f"since={since} TP={_fmt_px(tp)}"
    return False, ""


def _ban_setup_after_tp_miss(pl_or_sig_htf: str, *, tf: str, direction: str,
                             sl: float, tp: float, sig_hash: str = "") -> None:
    """Как cancelled_tp_hit /close: не перевыставлять тот же SL/TP в этом HTF."""
    if sig_hash:
        _mark_signal_skipped(sig_hash)
    if pl_or_sig_htf:
        ban_h = _manual_setup_ban_hash(
            tf=tf, direction=direction, htf_time=str(pl_or_sig_htf),
            sl=float(sl), tp=float(tp),
        )
        state.processed.add(ban_h)
        save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])


async def _cancel_pending_tp_already_hit(pl: "PendingLimit", detail: str) -> None:
    """Pending ещё без fill, но TP уже был — снимаем и баним сетап."""
    if pl.order_id and not await _cancel_pending_entry(pl):
        await _alert_cancel_fail(
            pl,
            f"🚨 ЛИМИТКА #{pl.trade_num} — TP уже был, но ордер НЕ снят!\n"
            f"ID: {pl.id}  |  order: {pl.order_id}\n"
            f"TP: {_fmt_px(pl.tp_price)}  Entry: {_fmt_px(pl.entry_price)}\n"
            f"Отмени вручную на Bybit",
        )
        return
    pl.status = "cancelled_tp_hit"
    _journal_log_pending_cancelled(pl)
    _ban_setup_after_tp_miss(
        pl.htf_time or _htf_time_for_pending(pl, pl.tf),
        tf=pl.tf, direction=pl.direction,
        sl=float(pl.stop_price), tp=float(pl.tp_price),
        sig_hash=pl.sig_hash or "",
    )
    # После cancel orphan-clear снимает taken — вернём one-shot, окно не переоткрываем.
    ht = pl.htf_time or _htf_time_for_pending(pl, pl.tf)
    if ht:
        _mark_htf_taken(pl.tf, ht, direction=pl.direction, trade_num=pl.trade_num)
    tfl = tf_label(pl.tf)
    await send_telegram(
        f"🗑 ЛИМИТКА #{pl.trade_num} отменена — TP уже был до входа [{tfl}]\n"
        f"ID: {pl.id}  |  {pl.direction}\n"
        f"Entry: {_fmt_px(pl.entry_price)}  |  TP: {_fmt_px(pl.tp_price)}\n"
        f"{detail}"
    )


def _min_rr_threshold() -> float:
    try:
        return max(0.0, float(CONFIG.get("min_rr", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _passes_min_rr(
    direction: str, entry: float, stop: float, tp: float,
) -> tuple[bool, Optional[float], str]:
    min_rr = _min_rr_threshold()
    rr = _calc_rr(direction, entry, stop, tp)
    if min_rr <= 0:
        return True, rr, ""
    if rr is None:
        return False, None, "невалидная геометрия TP/entry/stop"
    if rr < min_rr:
        return False, rr, f"R:R {rr:.2f} < min {min_rr:.2f}"
    return True, rr, ""


def _planned_economic_metrics(
    direction: str,
    entry: float,
    stop: float,
    tp: float,
    entry_kind: str,
    symbol_key: Optional[str] = None,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Gross RR, ожидаемый fee drag в R и net RR по live MEXC rates."""
    gross_rr = _calc_rr(direction, entry, stop, tp)
    risk = abs(float(entry) - float(stop))
    if gross_rr is None or risk <= 0 or entry <= 0 or tp <= 0:
        return gross_rr, None, None
    entry_fee = float(entry) * _entry_fee_rate(entry_kind, symbol_key)
    exit_fee = float(tp) * _exit_fee_rate("tp", symbol_key)
    fee_r = (entry_fee + exit_fee) / risk
    return gross_rr, fee_r, gross_rr - fee_r


def _economic_gate_decision(
    tf_name: str,
    direction: str,
    entry: float,
    stop: float,
    tp: float,
    entry_kind: str,
    symbol_key: Optional[str] = None,
) -> tuple[bool, str, dict]:
    """Решение live economic gate; shadow никогда не блокирует."""
    cfg = CONFIG.get(tf_name, {})
    mode = str(cfg.get("economic_gate_mode") or "off").lower()
    if mode not in ("off", "shadow", "enforce"):
        mode = "off"
    gross_rr, fee_r, net_rr = _planned_economic_metrics(
        direction, entry, stop, tp, entry_kind, symbol_key,
    )
    details = {
        "mode": mode,
        "gross_rr": gross_rr,
        "fee_r": fee_r,
        "net_rr": net_rr,
    }
    if mode == "off":
        return True, "", details

    reasons = []
    max_fee_r = _safe_float(cfg.get("max_fee_r"))
    if max_fee_r is not None and max_fee_r > 0 and (
        fee_r is None or fee_r > max_fee_r
    ):
        reasons.append(
            f"fee {fee_r:.3f}R > {max_fee_r:.3f}R"
            if fee_r is not None else "fee R не рассчитан"
        )
    market_min_net_rr = _safe_float(cfg.get("market_min_net_rr"))
    if (
        str(entry_kind or "").upper() == "MARKET"
        and market_min_net_rr is not None
        and market_min_net_rr > 0
        and (net_rr is None or net_rr < market_min_net_rr)
    ):
        reasons.append(
            f"MARKET net RR {net_rr:.3f} < {market_min_net_rr:.3f}"
            if net_rr is not None else "MARKET net RR не рассчитан"
        )
    reason = "; ".join(reasons)
    return mode != "enforce" or not reasons, reason, details


async def _cancel_pending_for_min_rr(
    pl: "PendingLimit", px: float, rr_reason: str,
) -> None:
    pl.status = "cancelled_min_rr"
    _journal_log_pending_cancelled(pl)
    tfl = tf_label(pl.tf)
    await send_telegram(
        f"⛔ ЛИМИТКА #{pl.trade_num} ОТМЕНЕНА — R:R ниже мин. [{tfl}]\n"
        f"{rr_reason}\n"
        f"Entry ref: {_fmt_px(px)}  Stop: {_fmt_px(pl.stop_price)}  TP: {_fmt_px(pl.tp_price)}"
    )
    save_pending(state.pending_limits)


def _trade_notional_usdt(
    price: float, contracts: int, symbol_key: Optional[str] = None,
) -> float:
    return float(price) * int(contracts) * _contract_value(symbol_key)


def _fee_rates_for(symbol_key: Optional[str] = None) -> tuple[float, float]:
    sk = symbol_key or active_symbol_key()
    fees = state.fees_by_symbol.get(sk)
    if fees:
        return float(fees.get("maker", 0)), float(fees.get("taker", 0))
    p = symbol_profile(sk)
    return float(p["maker_fee"]), float(p["taker_fee"])


def _entry_fee_rate(entry_kind: str, symbol_key: Optional[str] = None) -> float:
    maker, taker = _fee_rates_for(symbol_key)
    kind = (entry_kind or "").upper()
    if kind == "LIMIT":
        return maker
    return taker  # MARKET / STOP-LIMIT / sync — на MEXC taker


def _exit_fee_rate(exit_reason: str, symbol_key: Optional[str] = None) -> float:
    del exit_reason
    return _fee_rates_for(symbol_key)[1]  # TP/SL stoporder, timeout, manual — market close


def _calc_gross_pnl(
    entry_price: float, close_price: float, contracts: int, direction: str,
    symbol_key: Optional[str] = None,
) -> float:
    cv = int(contracts) * _contract_value(symbol_key)
    sign = 1 if direction == "LONG" else -1
    return (float(close_price) - float(entry_price)) * cv * sign


def _calc_trade_fees(
    entry_price: float,
    close_price: float,
    contracts: int,
    entry_kind: str,
    exit_reason: str,
    symbol_key: Optional[str] = None,
) -> float:
    entry_fee = _trade_notional_usdt(entry_price, contracts, symbol_key) * _entry_fee_rate(entry_kind, symbol_key)
    exit_fee  = _trade_notional_usdt(close_price, contracts, symbol_key) * _exit_fee_rate(exit_reason, symbol_key)
    return entry_fee + exit_fee


def _apply_close_pnl(pos: Position, close_price: float, exit_reason: str) -> tuple[float, float, float]:
    """Записывает gross/fees/net в pos. Returns (gross, fees, net)."""
    sk = _pos_symbol_key(pos)
    gross = _calc_gross_pnl(pos.entry_price, close_price, pos.contracts, pos.direction, sk)
    fees  = _calc_trade_fees(
        pos.entry_price, close_price, pos.contracts,
        pos.entry_kind, exit_reason, sk,
    )
    net = gross - fees
    pos.pnl = gross
    pos.fees = fees
    pos.pnl_net = net
    return gross, fees, net


async def _fetch_history_position_row(
    position_id: str,
    *,
    symbol_key: Optional[str] = None,
    retries: int = 4,
    delay_s: float = 2.0,
) -> Optional[dict]:
    """Закрытая нога: Bybit closed PnL (нет MEXC positionId)."""
    if state.paper or not position_id:
        return None
    sk = symbol_key or active_symbol_key()
    sym = symbol_profile(sk)["symbol"]
    loop = asyncio.get_event_loop()
    pid = str(position_id)
    fn = getattr(exchange, "fetch_positions_history", None)
    for attempt in range(max(1, retries)):
        if attempt > 0:
            await asyncio.sleep(delay_s)
        rows = None
        try:
            if fn:
                rows = await loop.run_in_executor(
                    None,
                    lambda: fn(sym, None, 50, {"category": "linear"}),
                )
            else:
                raw = await loop.run_in_executor(
                    None,
                    lambda: exchange.privateGetV5PositionClosedPnl({
                        "category": "linear",
                        "symbol": _mexc_market_id(sk),
                        "limit": "50",
                    }),
                )
                lst = ((raw or {}).get("result") or {}).get("list") or []
                rows = [{"info": r, **r} for r in lst]
        except Exception as e:
            logger.warning(f"history_positions {pid}: {e}")
            continue
        for row in rows or []:
            info = row.get("info") or row
            rid = str(
                info.get("orderId")
                or row.get("id")
                or info.get("execId")
                or ""
            )
            if rid and rid == pid:
                return _normalize_closed_pnl_row(row)
        if rows:
            return _normalize_closed_pnl_row(rows[0])
    return None


def _normalize_closed_pnl_row(row: dict) -> dict:
    info = row.get("info") or row
    net = info.get("closedPnl") or row.get("realizedPnl") or row.get("realised") or 0
    close_px = (
        info.get("avgExitPrice")
        or row.get("exitPrice")
        or info.get("closeAvgPrice")
        or row.get("closeAvgPrice")
        or 0
    )
    fees = info.get("execFee") or info.get("totalFee") or row.get("fee") or 0
    return {
        "state": "3",
        "_src": "bybit",
        "closeProfitLoss": net,
        "realised": net,
        "totalFee": fees,
        "closeAvgPrice": close_px,
        "info": info,
    }


def _pnl_from_history_row(
    pos: Position,
    row: dict,
    close_price: float,
    exit_reason: str,
) -> tuple[float, float, float]:
    """Bybit closedPnl ≈ net; MEXC: realised = closeProfitLoss − totalFee + holdFee."""
    calc_gross = _calc_gross_pnl(
        pos.entry_price, close_price, pos.contracts, pos.direction, _pos_symbol_key(pos),
    )
    try:
        ex_net = float(
            row.get("realised") or row.get("closedPnl") or row.get("closeProfitLoss") or 0
        )
    except (TypeError, ValueError):
        ex_net = 0.0
    try:
        gross = float(row.get("closeProfitLoss") or 0)
    except (TypeError, ValueError):
        gross = calc_gross
    if abs(gross) < 1e-12:
        gross = calc_gross
    try:
        fees = abs(float(row.get("totalFee") or row.get("fee") or 0))
    except (TypeError, ValueError):
        fees = 0.0
    try:
        net = float(row.get("realised") or 0)
    except (TypeError, ValueError):
        try:
            hold = float(row.get("holdFee") or 0)
        except (TypeError, ValueError):
            hold = 0.0
        net = gross - fees + hold
    if row.get("_src") == "bybit" and abs(ex_net) > 1e-12:
        net = ex_net
        if fees <= 0:
            fees = abs(calc_gross - net)
        gross = calc_gross
        try:
            ex_close = float(row.get("closeAvgPrice") or 0)
            if ex_close > 0:
                pos.close_price = ex_close
        except (TypeError, ValueError):
            pass
        pos.pnl = gross
        pos.fees = fees
        pos.pnl_net = net
        return gross, fees, net
    try:
        ex_close = float(row.get("closeAvgPrice") or 0)
        if ex_close > 0:
            pos.close_price = ex_close
    except (TypeError, ValueError):
        pass
    pos.pnl = gross
    pos.fees = fees
    pos.pnl_net = net
    if fees <= 0 and not state.paper:
        return _apply_close_pnl(pos, pos.close_price or close_price, exit_reason)
    return gross, fees, net


async def _resolve_close_pnl(
    pos: Position, close_price: float, exit_reason: str,
) -> tuple[float, float, float]:
    """Live: realised с биржи; paper / нет history — расчёт по ставкам."""
    if state.paper:
        return _apply_close_pnl(pos, close_price, exit_reason)
    if pos.exchange_position_id:
        row = await _fetch_history_position_row(
            pos.exchange_position_id, symbol_key=_pos_symbol_key(pos),
        )
        if row and str(row.get("state") or "") == "3":
            gross, fees, net = _pnl_from_history_row(pos, row, close_price, exit_reason)
            logger.info(
                f"close_pnl #{pos.trade_num} ex realised={net:.4f} "
                f"gross={gross:.4f} fees={fees:.4f} pid={pos.exchange_position_id}"
            )
            return gross, fees, net
    return _apply_close_pnl(pos, close_price, exit_reason)


def _format_close_pnl_lines(gross: float, fees: float, net: float, margin: float) -> str:
    g_pct = gross / margin * 100 if margin > 0 else 0.0
    n_pct = net / margin * 100 if margin > 0 else 0.0
    return (
        f"PnL:   {gross:+.2f} USDT  ({g_pct:+.1f}%)\n"
        f"Fees:  −{fees:.2f} USDT\n"
        f"Net:   {net:+.2f} USDT  ({n_pct:+.1f}%)"
    )


def _trade_pnl_value(trade: dict) -> float:
    """Net PnL для статистики, если есть; иначе gross."""
    if trade.get("pnl_net") is not None:
        return float(trade["pnl_net"])
    return float(trade.get("pnl") or 0.0)


def _fmt_h(h: float) -> str:
    """Форматирует часы в читаемый вид: 0.5 → '30м', 1 → '1ч', 1.5 → '1ч 30м'."""
    total_min = int(round(h * 60))
    hrs, mins = divmod(total_min, 60)
    if hrs and mins:
        return f"{hrs}ч {mins}м"
    if hrs:
        return f"{hrs}ч"
    return f"{mins}м"


def _fmt_px(px: float, symbol_key: Optional[str] = None) -> str:
    """Цена для TG/логов по tick символа (SOL 74.95, не 75.0)."""
    try:
        v = float(px)
    except (TypeError, ValueError):
        return "—"
    if v != v:  # NaN
        return "—"
    sk = symbol_key
    if sk is None and hasattr(state, "active_symbol_key"):
        sk = state.active_symbol_key
    dec = _price_decimals(symbol_profile(sk)["price_tick"])
    return f"{v:.{dec}f}"


def tf_htf_name(tf_name: str) -> str:
    """Название HTF (старший ТФ) для отображения в сообщениях."""
    ratio = CONFIG.get(tf_name, {}).get("htf_ratio", 0)
    if ratio >= 1440:  return "Daily"
    if ratio >= 240:   return "4H"
    if ratio >= 120:   return "2H"
    if ratio >= 60:    return "1H"
    return CONFIG.get(tf_name, {}).get("label", tf_name).split("→")[-1].strip()


def utcnow() -> datetime:
    """Timezone-naive UTC datetime (замена устаревшему datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def msk(dt: Optional[datetime]) -> Optional[datetime]:
    """Перевод naive-UTC datetime в московское время (UTC+3), без tzinfo."""
    if dt is None:
        return None
    return dt + timedelta(hours=3)


def _bar_time_to_utc(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return pd.Timestamp(ts).to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None


# ============================================================
# TELEGRAM — отправка уведомлений
# ============================================================
_tg_app: Optional[Application] = None
_tg_online: bool = False
_task_alert_ts: dict[str, float] = {}

BOT_COMMANDS = [
    BotCommand("resume", "▶ Запустить / возобновить торговлю"),
    BotCommand("start",  "▶ Запустить сканер"),
    BotCommand("stop",   "⏸ Пауза или полная остановка"),
    BotCommand("mode",   "🔄 SHADOW ↔ LIVE"),
    BotCommand("status", "📊 Статус: позиции, баланс"),
    BotCommand("stats",  "📈 Статистика по парам и ТФ"),
    BotCommand("pairs",  "🪙 Активные пары"),
    BotCommand("close",  "🔒 Закрыть позицию / отменить лимитку"),
    BotCommand("fee",    "💰 Maker / taker fee %"),
]


def _tg_owner(update: Update) -> bool:
    chat_id = update.effective_chat.id if update.effective_chat else None
    user_id = update.effective_user.id if update.effective_user else None
    return chat_id == TELEGRAM_CHAT_ID or user_id == TELEGRAM_CHAT_ID


async def _tg_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Чужие чаты/юзеры не доходят до команд — иначе /start включает LIVE."""
    if _tg_owner(update):
        return
    uid = update.effective_user.id if update.effective_user else None
    cid = update.effective_chat.id if update.effective_chat else None
    text = ""
    msg = update.effective_message
    if msg is not None and msg.text:
        text = msg.text[:40]
    logger.warning(f"TG ignore user={uid} chat={cid} {text!r}")
    raise ApplicationHandlerStop


async def cmd_start_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Системный /start Telegram не включает торговлю."""
    if update.message:
        await update.message.reply_text(
            "Системный /start торговлю не включает.\n"
            "Возобновление: /resume\n"
            "Стоп: /stop"
        )


def _build_tg_application() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(TypeHandler(Update, _tg_gate), group=-1)
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("resume", cmd_start))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CallbackQueryHandler(callback_stop, pattern=r"^stop:"))
    app.add_handler(CommandHandler("mode",   cmd_mode))
    app.add_handler(CommandHandler("paper",  cmd_mode))
    app.add_handler(CallbackQueryHandler(callback_mode, pattern=r"^mode:"))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("price",  cmd_price))
    app.add_handler(CommandHandler("pairs",  cmd_pairs))
    app.add_handler(CommandHandler("pair",   cmd_pairs))
    app.add_handler(CommandHandler("close",  cmd_close))
    app.add_handler(CommandHandler("tf",     cmd_tf))
    app.add_handler(CommandHandler("timeout", cmd_timeout))
    app.add_handler(CommandHandler("filters", cmd_filters))
    app.add_handler(CommandHandler("filter", cmd_filter))
    app.add_handler(CommandHandler("filter_atr", cmd_filter_cut))
    app.add_handler(CommandHandler("filter_vol", cmd_filter_cut))
    app.add_handler(CommandHandler("filter_d", cmd_filter_cut))
    app.add_handler(CommandHandler("filter_qsz", cmd_filter_cut))
    app.add_handler(CommandHandler("filter_psl", cmd_filter_cut))
    app.add_handler(CommandHandler("filter_qstop", cmd_filter_cut))
    app.add_handler(CommandHandler("filters_atr", cmd_filter_cut))
    app.add_handler(CommandHandler("filters_vol", cmd_filter_cut))
    app.add_handler(CommandHandler("filters_d", cmd_filter_cut))
    app.add_handler(CommandHandler("filters_qsz", cmd_filter_cut))
    app.add_handler(CommandHandler("quality_size", cmd_filter_cut))
    app.add_handler(CommandHandler("filters_psl", cmd_filter_cut))
    app.add_handler(CommandHandler("psl_size", cmd_filter_cut))
    app.add_handler(CommandHandler("filters_qstop", cmd_filter_cut))
    app.add_handler(CommandHandler("quality_stop", cmd_filter_cut))
    app.add_handler(CommandHandler("fee",     cmd_fee))
    app.add_handler(CommandHandler("slope",      cmd_slope))
    app.add_handler(CommandHandler("slop_trend", cmd_slop_trend))
    app.add_handler(CommandHandler("prog_ema",   cmd_prog_ema))
    app.add_handler(CallbackQueryHandler(callback_prog_ema, pattern=r"^prog_ema:"))
    app.add_handler(CallbackQueryHandler(callback_stats,   pattern=r"^stats:"))
    app.add_handler(CallbackQueryHandler(callback_fee,     pattern=r"^fee:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_fee_text_input))
    app.add_handler(CallbackQueryHandler(callback_tf,      pattern=r"^tf:"))
    app.add_handler(CallbackQueryHandler(callback_pair,    pattern=r"^pair:"))
    app.add_handler(CallbackQueryHandler(callback_timeout, pattern=r"^timeout:"))
    app.add_handler(CallbackQueryHandler(callback_close,   pattern=r"^close:"))
    app.add_handler(CallbackQueryHandler(callback_start_signal, pattern=r"^start_sig:"))
    return app


async def _tg_shutdown_safe():
    """Корректно останавливает PTB; ошибки глотаются."""
    global _tg_online
    _tg_online = False
    if _tg_app is None:
        return
    updater = getattr(_tg_app, "updater", None)
    if updater and getattr(updater, "running", False):
        try:
            await _tg_app.updater.stop()
        except Exception as e:
            logger.debug(f"updater.stop: {e}")
    if getattr(_tg_app, "running", False):
        try:
            await _tg_app.stop()
        except Exception as e:
            logger.debug(f"app.stop: {e}")
    try:
        await _tg_app.shutdown()
    except Exception as e:
        logger.debug(f"app.shutdown: {e}")


async def telegram_connect_loop():
    """Подключается к Telegram API с retry; торговля не ждёт."""
    global _tg_online
    delay = 10
    while True:
        try:
            await _tg_shutdown_safe()
            await _tg_app.initialize()
            await _tg_app.start()
            try:
                await _tg_app.bot.set_my_commands(BOT_COMMANDS)
            except Exception as e:
                logger.warning(f"set_my_commands пропущен: {e}")
            await _tg_app.updater.start_polling(drop_pending_updates=True)
            _tg_online = True
            logger.info("Telegram подключён, polling запущен")
            await send_telegram(
                f"🤖 CISD BOT v6 запущен\n"
                f"Режим: {_mode_prefix()} | "
                f"{'▶ RUNNING' if state.running.is_set() else '⏸ PAUSED'}\n"
                f"{'─' * 28}\n"
                f"10 пар × 5m→4H + 30m→8H | LIMIT TP=1R vwap\n"
                f"Команды: /start  /stop  /mode  /status  /stats  /pairs"
            )
            # Держим задачу живой, пока polling работает
            while getattr(_tg_app.updater, "running", False):
                await asyncio.sleep(30)
            _tg_online = False
            logger.warning("Telegram polling остановился — переподключение...")
        except asyncio.CancelledError:
            await _tg_shutdown_safe()
            raise
        except (TimedOut, NetworkError) as e:
            _tg_online = False
            logger.warning(f"Telegram недоступен, retry через {delay}с: {e}")
            await _tg_shutdown_safe()
            await asyncio.sleep(delay)
        except Exception as e:
            _tg_online = False
            logger.warning(f"Telegram ошибка, retry через {delay}с: {e}")
            await _tg_shutdown_safe()
            await asyncio.sleep(delay)


def _tg_send_transient(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return any(
        s in name or s in msg
        for s in ("timeout", "timed out", "network", "temporarily", "retryafter", "429")
    )


async def send_telegram(text: str, reply_markup=None):
    """Отправка в TG + зеркало в CTL event feed. None = в TG не доставлено."""
    try:
        await ctl_server.emit_event("telegram", text or "")
    except Exception:
        pass
    if not _tg_online or _tg_app is None:
        preview = text.replace("\n", " ")[:120]
        logger.info(f"[TG offline] {preview}")
        return None
    delays = (0.0, 1.5, 3.0)
    last_err: BaseException | None = None
    for i, delay in enumerate(delays):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await _tg_app.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text[:4096],
                reply_markup=reply_markup,
            )
        except Exception as e:
            last_err = e
            if _tg_send_transient(e) and i < len(delays) - 1:
                logger.warning(
                    f"Telegram send retry {i + 1}/{len(delays) - 1}: {e}"
                )
                continue
            logger.error(f"Telegram send: {e}")
            return None
    if last_err is not None:
        logger.error(f"Telegram send: {last_err}")
    return None


# ============================================================
# OHLCV
# ============================================================
# MEXC futures не отдаёт 10m — собираем из младшего ТФ (как на TV).
_SYNTHETIC_OHLCV: dict[str, tuple[str, int]] = {
    "10m": ("5m", 2),
    "30m": ("5m", 6),  # tf8: 30m только локальный ресемпл из 5m
    "2h":  ("1h", 2),
}


def _tf_to_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("m"):
        return int(tf[:-1])
    raise ValueError(f"unknown timeframe: {tf}")


def _resample_ohlcv(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    mins = _tf_to_minutes(target_tf)
    rule = f"{mins}min"
    out = pd.DataFrame({
        "open":   df["open"].resample(rule, label="left", closed="left").first(),
        "high":   df["high"].resample(rule, label="left", closed="left").max(),
        "low":    df["low"].resample(rule, label="left", closed="left").min(),
        "close":  df["close"].resample(rule, label="left", closed="left").last(),
        "volume": df["volume"].resample(rule, label="left", closed="left").sum(),
    })
    return out.dropna(subset=["open"])


def _confirm_timeframe_for(tf_name: str) -> Optional[str]:
    return CONFIG.get(tf_name, {}).get("confirm_timeframe")


def _mss_max_range(
    htf_ratio: int,
    htf_confirm_windows: int,
    main_tf: str,
    confirm_tf: Optional[str],
) -> int:
    """max_range для find_confirmation: на LTF — всё HTF-окно, не 50 LTF-баров."""
    base = 50
    if not confirm_tf:
        return base
    main_m = _tf_to_minutes(main_tf)
    ltf_m = _tf_to_minutes(confirm_tf)
    if ltf_m <= 0 or ltf_m >= main_m:
        return base
    return max(base, htf_confirm_windows * int(htf_ratio) // ltf_m + 20)


def _map_htf_ts_to_ltf_iloc(df_ltf: pd.DataFrame, htf_ts: pd.Timestamp) -> int:
    """iloc первого LTF-бара в HTF-бакете (или на той же метке времени)."""
    pos = int(df_ltf.index.searchsorted(pd.Timestamp(htf_ts), side="left"))
    return max(0, min(pos, len(df_ltf) - 1))


def _map_ltf_ts_to_series_iloc(df_series: pd.DataFrame, ltf_ts: pd.Timestamp) -> int:
    """iloc бара series-TF (5m), в чьём бакете находится LTF-метка confirm."""
    pos = int(df_series.index.searchsorted(pd.Timestamp(ltf_ts), side="right")) - 1
    return max(0, min(pos, len(df_series) - 1))


def _ltf_bar_in_htf_bucket(
    ltf_ts: pd.Timestamp, htf_ts: pd.Timestamp, htf_minutes: int,
) -> bool:
    rule = f"{int(htf_minutes)}min"
    return pd.Timestamp(ltf_ts).floor(rule) == pd.Timestamp(htf_ts).floor(rule)


def _slice_confirm_df(
    df_confirm: pd.DataFrame, df_htf: pd.DataFrame, htf_minutes: int,
) -> pd.DataFrame:
    """Окно LTF-баров, покрывающее тот же период, что и df_htf."""
    if df_confirm is None or len(df_confirm) == 0 or len(df_htf) == 0:
        return df_confirm
    t0 = pd.Timestamp(df_htf.index[0])
    t1 = pd.Timestamp(df_htf.index[-1]) + pd.Timedelta(minutes=int(htf_minutes))
    return df_confirm.loc[(df_confirm.index >= t0) & (df_confirm.index < t1)]


async def _fetch_confirm_ohlcv(tf_name: str, tf_cfg: dict) -> Optional[pd.DataFrame]:
    confirm_tf = _confirm_timeframe_for(tf_name)
    if not confirm_tf:
        return None
    base = int(tf_cfg.get("ohlcv", 500))
    htf_m = _tf_to_minutes(str(tf_cfg.get("timeframe") or "10m"))
    ltf_m = _tf_to_minutes(confirm_tf)
    limit = min(2000, max(base * 3, base * htf_m // max(ltf_m, 1) + 50))
    return await _fetch_ohlcv_exchange(confirm_tf, limit=limit)


def _closed_ltf_in_synthetic_bucket(
    bucket_start: pd.Timestamp,
    df_ltf: pd.DataFrame,
    now: datetime,
    *,
    ltf_minutes: int,
    bucket_minutes: int,
) -> int:
    """Закрытые LTF-свечи внутри одного синтетического HTF-бакета."""
    bucket_start = pd.Timestamp(bucket_start)
    bucket_end = bucket_start + pd.Timedelta(minutes=bucket_minutes)
    n = 0
    now_ts = pd.Timestamp(now)
    for ts in df_ltf.index:
        if ts < bucket_start or ts >= bucket_end:
            continue
        if ts + pd.Timedelta(minutes=ltf_minutes) <= now_ts:
            n += 1
    return n


async def _cisd_cross_eval_iloc(
    df_htf: pd.DataFrame,
    timeframe: str,
    now: datetime,
) -> Optional[int]:
    """iloc 10m для cisd_cross arm; None — в бакете ещё не 2 закр. 5m."""
    forming_iloc = len(df_htf) - 1
    synth = _SYNTHETIC_OHLCV.get(timeframe)
    if synth is None:
        return forming_iloc

    src_tf, need = synth
    ltf_min = int(src_tf.rstrip("m"))
    htf_min = int(timeframe.rstrip("m"))
    df_ltf = await _fetch_ohlcv_exchange(src_tf, limit=max(need + 6, 14))
    if df_ltf is None:
        return None

    for iloc in (forming_iloc, forming_iloc - 1):
        if iloc < 0:
            continue
        bucket_ts = df_htf.index[iloc]
        n = _closed_ltf_in_synthetic_bucket(
            bucket_ts, df_ltf, now,
            ltf_minutes=ltf_min, bucket_minutes=htf_min,
        )
        if n >= need:
            return iloc
    return None


async def _fetch_ohlcv_exchange(timeframe: str, limit: int, symbol: Optional[str] = None) -> Optional[pd.DataFrame]:
    loop = asyncio.get_event_loop()
    sym = symbol or active_symbol()
    for retry in range(3):
        try:
            ohlcv = await loop.run_in_executor(
                None, lambda s=sym, tf=timeframe, n=limit: exchange.fetch_ohlcv(s, tf, limit=n)
            )
            df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            df.set_index("ts", inplace=True)
            df.index = df.index.tz_localize(None)
            return df
        except Exception as e:
            logger.warning(f"OHLCV {sym} {timeframe} retry {retry + 1}: {e}")
            await asyncio.sleep(5)
    return None


async def fetch_ohlcv(timeframe="15m", limit=500, symbol: Optional[str] = None) -> Optional[pd.DataFrame]:
    synth = _SYNTHETIC_OHLCV.get(timeframe)
    if synth is not None:
        src_tf, mult = synth
        raw_limit = min(max(limit * mult + mult, 50), 1500)
        df = await _fetch_ohlcv_exchange(src_tf, raw_limit, symbol=symbol)
        if df is None or len(df) < mult:
            return None
        df = _resample_ohlcv(df, timeframe)
        if len(df) > limit:
            df = df.iloc[-limit:]
        return df if len(df) >= 1 else None
    return await _fetch_ohlcv_exchange(timeframe, limit, symbol=symbol)


async def _ltf_bar_closed(
    tf_name: str, timeframe: str, last_bar_ts: dict,
) -> bool:
    """True если с прошлого peek начался новый LTF-бар (закрылся предыдущий)."""
    df = await fetch_ohlcv(timeframe, limit=3)
    if df is None or len(df) < 1:
        return False
    cur = df.index[-1]
    prev = last_bar_ts.get(tf_name)
    if prev is not None and cur != prev:
        last_bar_ts[tf_name] = cur
        return True
    if prev is None:
        last_bar_ts[tf_name] = cur
    return False


def _scan_interval_s(tf_cfg: dict) -> int:
    if "scan_s" in tf_cfg:
        return max(5, int(tf_cfg["scan_s"]))
    return max(5, int(tf_cfg.get("scan_m", 1)) * 60)


# ============================================================
# ДЕТЕКЦИЯ СИГНАЛОВ (сразу после HTF-свипа)
# ============================================================
def _cand_key(tf_name: str, direction: str, htf_time: str, symbol_key: Optional[str] = None) -> str:
    sk = symbol_key or active_symbol_key()
    return f"{sk}|{tf_name}|{direction}|{htf_time}"


def _tf_has_sweep_candidates(tf_name: str) -> bool:
    sk = active_symbol_key()
    return any(
        v.get("tf") == tf_name
        and v.get("direction") in ("LONG", "SHORT")
        and str(v.get("symbol_key") or sk) == sk
        for v in state.sweep_candidates.values()
    )


def _cand_symbol_key(cand: dict, store_key: str = "") -> str:
    sk = str(cand.get("symbol_key") or "")
    if sk in SYMBOL_PROFILES:
        return sk
    head = str(store_key).split("|", 1)[0]
    return head if head in SYMBOL_PROFILES else active_symbol_key()


def _cands_for_symbol(tf_name: str, symbol_key: Optional[str] = None) -> list:
    """Кандидаты только этой пары. Иначе LTC видит Sweep/Ext от LINK/SOL."""
    sk = symbol_key or active_symbol_key()
    out = []
    for k, v in state.sweep_candidates.items():
        if v.get("tf") != tf_name:
            continue
        if str(v.get("direction") or "") not in ("LONG", "SHORT"):
            continue
        if _cand_symbol_key(v, k) != sk:
            continue
        out.append(v)
    return out


def _cand_matches_sweep(sweep: dict, cand: dict) -> bool:
    """Свип из detect_htf_sweeps соответствует кандидату (тот же HTF-сетап)."""
    want = "bearish" if str(cand.get("direction")) == "SHORT" else "bullish"
    if str(sweep.get("type") or "") != want:
        return False
    try:
        if pd.Timestamp(sweep.get("htf_time")) != pd.Timestamp(cand.get("htf_time")):
            return False
    except Exception:
        return False
    if abs(float(sweep.get("sweep_level") or 0) - float(cand.get("sweep_level") or 0)) > 1e-6:
        return False
    return True


def _find_sweep_for_cand(sweeps: list, cand: dict) -> dict | None:
    for s in sweeps:
        if _cand_matches_sweep(s, cand):
            return s
    return None


def _find_sweep_for_cand_by_htf(sweeps: list, cand: dict) -> dict | None:
    """Свип того же HTF-окна и направления (уровень может смениться при пересвипе)."""
    want = "bearish" if str(cand.get("direction")) == "SHORT" else "bullish"
    try:
        cand_htf = pd.Timestamp(cand.get("htf_time"))
    except Exception:
        return None
    for s in sweeps:
        if str(s.get("type") or "") != want:
            continue
        try:
            if pd.Timestamp(s.get("htf_time")) != cand_htf:
                continue
        except Exception:
            continue
        return s
    return None


def _sync_cand_from_sweep(cand: dict, sweep: dict, df: pd.DataFrame) -> None:
    direction = str(cand.get("direction") or "")
    is_bearish = direction == "SHORT"
    trigger_idx = int(sweep["trigger_idx"])
    cand["sweep_level"] = float(sweep.get("sweep_level") or 0)
    cand["type"] = str(sweep.get("type") or "")
    cand["trigger_idx"] = trigger_idx
    cand["trigger_time"] = str(pd.Timestamp(df.index[trigger_idx]))
    cand["trigger_extreme"] = _trigger_extreme_at(df, trigger_idx, is_bearish)


def _drop_sweep_candidate(
    tf_name: str, direction: str, htf_s: str, reason: str,
    symbol_key: Optional[str] = None,
) -> None:
    state.sweep_candidates.pop(_cand_key(tf_name, direction, htf_s, symbol_key), None)
    logger.info(f"detect:   -> кандидат снят [{htf_s}] {direction}: {reason}")


def _htf_sweep_validate_key(tf_name: str, htf_time: str, symbol_key: Optional[str] = None) -> str:
    sk = symbol_key or active_symbol_key()
    return f"{sk}|{tf_name}|{htf_time}"


def _htf_window_ltf_bars(
    df: pd.DataFrame, htf_ts: pd.Timestamp, htf_ratio: int,
) -> int:
    """Сколько LTF-баров попало в HTF-окно [htf_ts, htf_ts + ratio)."""
    start = pd.Timestamp(htf_ts)
    end = start + pd.Timedelta(minutes=int(htf_ratio))
    return int(((df.index >= start) & (df.index < end)).sum())


def _htf_closed_sweep_flags(
    df_htf: pd.DataFrame,
    closed_idx: int,
    df: pd.DataFrame | None = None,
    htf_ratio: int | None = None,
    tf_minutes: int | None = None,
) -> tuple[bool, bool] | None:
    """Pine f_is_sweep между закрытым HTF-баром и предыдущим: (high_sweep, low_sweep).

    None — в закрытой свече не все LTF-бары (рестарт/дыра в df), валидацию пропускаем.
    """
    if closed_idx < 1 or closed_idx >= len(df_htf):
        return True, True
    if df is not None and htf_ratio and tf_minutes:
        expected = max(1, int(htf_ratio) // int(tf_minutes))
        n = _htf_window_ltf_bars(df, df_htf.index[closed_idx], int(htf_ratio))
        if n < expected:
            return None
    c2 = df_htf.iloc[closed_idx]
    c3 = df_htf.iloc[closed_idx - 1]
    return (
        CISDDetector.htf_candles_sweep(c2, c3, True),
        CISDDetector.htf_candles_sweep(c2, c3, False),
    )


def _htf_loc_for_time(df_htf: pd.DataFrame, htf_time: str) -> int | None:
    try:
        loc = df_htf.index.get_loc(pd.Timestamp(htf_time))
    except (KeyError, TypeError, ValueError):
        return None
    if isinstance(loc, slice):
        return int(loc.start) if loc.start is not None else None
    if isinstance(loc, np.ndarray):
        return int(loc[0]) if len(loc) else None
    return int(loc)


async def _invalidate_pending_no_htf_inter_sweep(
    tf_name: str,
    df: pd.DataFrame | None = None,
) -> int:
    """
    Pine bear/bull_sweep_check: HTF-окно закрылось без свипа между диапазонами →
    снять pending (позиции не трогаем).
    """
    tf_cfg = CONFIG.get(tf_name, {})
    htf_ratio = int(tf_cfg.get("htf_ratio") or 60)
    tf_minutes = _tf_to_minutes(str(tf_cfg.get("timeframe") or "5m"))
    if df is None:
        df = await fetch_ohlcv(tf_cfg["timeframe"], tf_cfg.get("ohlcv", 500))
    if df is None or len(df) < 50:
        return 0

    det = CISDDetector(htf_ratio=htf_ratio)
    df_htf = det.resample_to_htf(df)
    if len(df_htf) < 3:
        return 0

    forming_htf = pd.Timestamp(df_htf.index[-1])
    checks: dict[str, tuple[bool, bool]] = {}

    for pl in state.pending_limits:
        if pl.status != "pending" or pl.tf != tf_name:
            continue
        pl_htf = _htf_time_for_pending(pl, tf_name)
        if not pl_htf:
            continue
        try:
            pl_ts = pd.Timestamp(pl_htf)
        except Exception:
            continue
        if pl_ts >= forming_htf:
            continue
        checks.setdefault(pl_htf, (True, True))

    closed_htf = str(pd.Timestamp(df_htf.index[-2]))
    checks.setdefault(closed_htf, (True, True))

    cancelled = 0
    prefix = _mode_prefix() + " "
    tfl = tf_label(tf_name)
    htf_name = tf_htf_name(tf_name)

    for htf_s, _ in list(checks.items()):
        vk = _htf_sweep_validate_key(tf_name, htf_s)
        if state.htf_sweep_validated.get(vk):
            continue
        idx = _htf_loc_for_time(df_htf, htf_s)
        if idx is None or idx >= len(df_htf) - 1:
            continue

        flags = _htf_closed_sweep_flags(
            df_htf, idx, df=df, htf_ratio=htf_ratio, tf_minutes=tf_minutes,
        )
        if flags is None:
            expected = max(1, htf_ratio // tf_minutes)
            n = _htf_window_ltf_bars(df, df_htf.index[idx], htf_ratio)
            logger.info(
                f"detect:   -> HTF {htf_s} неполное окно "
                f"({n}/{expected} баров) — валидацию пропускаем"
            )
            continue
        has_high, has_low = flags
        state.htf_sweep_validated[vk] = True
        if len(state.htf_sweep_validated) > 300:
            for old_k in list(state.htf_sweep_validated.keys())[:100]:
                state.htf_sweep_validated.pop(old_k, None)

        if not has_high:
            _drop_sweep_candidate(
                tf_name, "SHORT", htf_s,
                "HTF закрыто без high-свипа между диапазонами",
            )
        if not has_low:
            _drop_sweep_candidate(
                tf_name, "LONG", htf_s,
                "HTF закрыто без low-свипа между диапазонами",
            )

        for pl in list(state.pending_limits):
            if pl.status != "pending" or pl.tf != tf_name:
                continue
            pl_htf = _htf_time_for_pending(pl, tf_name)
            if not _htf_times_match(pl_htf, htf_s):
                continue
            if pl.direction == "SHORT" and has_high:
                continue
            if pl.direction == "LONG" and has_low:
                continue

            logger.info(
                f"HTF NO SWEEP [{tfl}] {pl.direction} #{pl.trade_num}: "
                f"htf={htf_s} high={has_high} low={has_low}"
            )
            if pl.order_id and not state.paper and not await _cancel_pending_entry(pl):
                await _alert_cancel_fail(
                    pl,
                    f"🚨 ЛИМИТКА #{pl.trade_num} — HTF без свипа, ордер НЕ снят!\n"
                    f"ID: {pl.id}  |  order: {pl.order_id}\n"
                    f"Отмени вручную на Bybit",
                )
                continue

            pl.status = "cancelled_htf_no_sweep"
            _journal_log_pending_cancelled(pl)
            if float(pl.sweep_level or 0) > 0:
                state.htf_sweep_lock.pop(
                    _htf_sweep_lock_key(pl.tf, pl.direction, float(pl.sweep_level)),
                    None,
                )
            state.htf_sweep_lock.pop(
                _setup_leg_lock_key(pl.tf, pl.direction, pl.stop_price, pl.tp_price),
                None,
            )
            await send_telegram(
                f"{prefix}❌ ЛИМИТКА #{pl.trade_num} ОТМЕНЕНА — HTF без свипа [{tfl}]\n"
                f"ID: {pl.id}  |  {pl.direction}\n"
                f"HTF-окно {htf_s} закрылось без свипа между {htf_name}-диапазонами\n"
                f"Паттерн CISD отменён (как в Pine sweep_check)"
            )
            cancelled += 1

    if cancelled:
        save_pending(state.pending_limits)
    return cancelled


def _last_closed_bar_iloc(df: pd.DataFrame) -> int:
    """iloc последнего закрытого LTF-бара (без формирующейся свечи)."""
    if len(df) == 0:
        return -1
    return len(df) - 2 if len(df) >= 2 else len(df) - 1


BT_DETECT_WARMUP = 100  # bot_aligned warmup — фаза detect_step


def _detect_step_bars(tf_cfg: dict) -> int:
    """Частота detect_signals в bot_aligned: 60m / main TF."""
    bar_min = _tf_to_minutes(str(tf_cfg.get("timeframe") or "5m"))
    return max(1, 60 // bar_min)


def _is_detect_step_ts(ts: pd.Timestamp, bar_min: int, d_step: int) -> bool:
    """Как bot_aligned: (bar_num - warmup) % detect_step == 0."""
    ts = pd.Timestamp(ts)
    if ts.tz is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    bar_num = int(ts.timestamp() // (bar_min * 60))
    return ((bar_num - BT_DETECT_WARMUP) % d_step) == 0


def _is_detect_step_bar(df: pd.DataFrame, tf_cfg: dict) -> bool:
    lc = _last_closed_bar_iloc(df)
    if lc < 0:
        return False
    bar_min = _tf_to_minutes(str(tf_cfg.get("timeframe") or "5m"))
    return _is_detect_step_ts(pd.Timestamp(df.index[lc]), bar_min, _detect_step_bars(tf_cfg))


def _htf_detect_context(
    df: pd.DataFrame, df_htf: pd.DataFrame, htf_ratio: int,
) -> tuple[Optional[pd.Timestamp], int, Optional[pd.Timestamp]]:
    """
    HTF-контекст для detect: active_htf/recent_from и forming_htf (последний resample-bucket).

  На закрытии последнего LTF-бара HTF-окна ccxt уже отдаёт forming-бар следующего окна;
  resample сдвигает current_htf вперёд — свип предыдущего окна теряется. В этом случае
    active_htf = предпоследний закрытый HTF-bucket.
    """
    if len(df_htf) == 0:
        bar_min = int((df.index[1] - df.index[0]).total_seconds() / 60) if len(df) >= 2 else 15
        htf_bars = max(1, htf_ratio // bar_min)
        return None, max(0, len(df) - htf_bars), None

    forming_htf_time = pd.Timestamp(df_htf.index[-1])
    rule = f"{int(htf_ratio)}min"

    if len(df) >= 2 and len(df_htf) >= 2:
        forming_ltf = pd.Timestamp(df.index[-1])
        closed_ltf = pd.Timestamp(df.index[-2])
        if (
            forming_ltf.floor(rule) == forming_htf_time
            and closed_ltf.floor(rule) < forming_htf_time
        ):
            active_htf_time = pd.Timestamp(df_htf.index[-2])
            try:
                recent_from = int(df.index.get_loc(active_htf_time))
            except Exception:
                bar_min = int((df.index[1] - df.index[0]).total_seconds() / 60)
                recent_from = max(0, len(df) - max(1, htf_ratio // bar_min))
            return active_htf_time, recent_from, forming_htf_time

    try:
        recent_from = int(df.index.get_loc(forming_htf_time))
    except Exception:
        bar_min = int((df.index[1] - df.index[0]).total_seconds() / 60) if len(df) >= 2 else 15
        recent_from = max(0, len(df) - max(1, htf_ratio // bar_min))
    return forming_htf_time, recent_from, forming_htf_time


def _resolve_cand_trigger_idx(df: pd.DataFrame, cand: dict) -> int | None:
    """iloc триггера по фиксированному времени (не плавающий idx в rolling df)."""
    ts = cand.get("trigger_time")
    if ts:
        try:
            t = pd.Timestamp(ts)
        except Exception:
            return None
        if t not in df.index:
            return None
        loc = df.index.get_loc(t)
        if isinstance(loc, slice):
            return int(loc.start) if loc.start is not None else None
        return int(loc)
    try:
        idx = int(cand["trigger_idx"])
        if 0 <= idx < len(df):
            return idx
    except (TypeError, ValueError, KeyError):
        pass
    return None


def _htf_sweep_lock_key(
    tf_name: str, direction: str, sweep_level: float,
    symbol_key: Optional[str] = None,
) -> str:
    """Ключ lock по symbol+tf+direction+sweep."""
    sk = symbol_key or active_symbol_key()
    sweep_r = _round_sweep_level(sweep_level, sk)
    return f"{sk}|{tf_name}|{direction}|sweep={sweep_r:.0f}"


def _setup_leg_lock_key(tf_name: str, direction: str, stop: float, tp: float) -> str:
    sk = active_symbol_key()
    sl_r = _round_price(stop, sk)
    tp_r = _round_price(tp, sk)
    dec = _price_decimals(symbol_profile(sk)["price_tick"])
    return f"{sk}|{tf_name}|{direction}|sl={sl_r:.{dec}f}|tp={tp_r:.{dec}f}"


def _trigger_extreme_at(df: pd.DataFrame, trigger_idx: int, is_bearish: bool) -> float:
    row = df.iloc[int(trigger_idx)]
    return float(row["high"] if is_bearish else row["low"])


def _deepest_bar_iloc(
    df: pd.DataFrame, from_iloc: int, to_iloc: int, is_bearish: bool,
) -> int:
    """Бар с самым глубоким экстремумом в [from_iloc, to_iloc] включительно."""
    lo, hi = int(from_iloc), int(to_iloc)
    if lo > hi:
        lo, hi = hi, lo
    best = lo
    for i in range(lo, hi + 1):
        if is_bearish:
            if float(df.iloc[i]["high"]) > float(df.iloc[best]["high"]):
                best = i
        else:
            if float(df.iloc[i]["low"]) < float(df.iloc[best]["low"]):
                best = i
    return best


def _sync_cand_trigger(
    cand: dict, df: pd.DataFrame, trigger_idx: int, is_bearish: bool,
) -> None:
    cand["trigger_idx"] = int(trigger_idx)
    cand["trigger_time"] = str(pd.Timestamp(df.index[int(trigger_idx)]))
    cand["trigger_extreme"] = _trigger_extreme_at(df, int(trigger_idx), is_bearish)


def _upsert_sweep_candidate(k: str, incoming: dict) -> None:
    """Создать или обновить кандидата, если появился более глубокий trigger."""
    existing = state.sweep_candidates.get(k)
    if existing is None:
        state.sweep_candidates[k] = incoming
        logger.info(
            f"detect:   -> кандидат {incoming.get('direction')} "
            f"[{incoming.get('htf_time')}] "
            f"sweep={float(incoming.get('sweep_level') or 0):.1f} "
            f"tr={incoming.get('trigger_time')} "
            f"ext={float(incoming.get('trigger_extreme') or 0):.1f}"
        )
        return
    direction = str(incoming.get("direction") or "")
    new_ext = float(incoming.get("trigger_extreme") or 0)
    old_ext = float(existing.get("trigger_extreme") or 0)
    new_sweep = float(incoming.get("sweep_level") or 0)
    old_sweep = float(existing.get("sweep_level") or 0)
    if _is_resweep_extreme(direction, new_ext, old_ext) or _is_resweep_level(
        direction, new_sweep, old_sweep,
    ):
        state.sweep_candidates[k] = incoming
        logger.info(
            f"detect:   -> кандидат обновлён {direction} [{incoming.get('htf_time')}] "
            f"sweep={new_sweep:.1f} tr={incoming.get('trigger_time')} "
            f"ext={new_ext:.1f} (было sweep={old_sweep:.1f} ext={old_ext:.1f})"
        )


def _tp_1r(direction: str, entry: float, stop: float) -> Optional[float]:
    """Тейк 1R: вход ± |вход − стоп|. ТЗ v6, не fib."""
    entry_px = float(entry)
    stop_px = float(stop)
    risk = abs(entry_px - stop_px)
    if risk <= 0:
        return None
    if direction == "LONG":
        return entry_px + risk
    return entry_px - risk


def _levels_from_trigger(
    det: "CISDDetector",
    df: pd.DataFrame,
    trigger_idx: int,
    direction: str,
    is_bearish: bool,
) -> Optional[dict]:
    """CISD / stop / tp / fib от trigger-бара (wick-проекция)."""
    if is_bearish:
        series = det.find_bullish_series(df, trigger_idx)
        cisd_level = series.get("min_open")
    else:
        series = det.find_bearish_series(df, trigger_idx)
        cisd_level = series.get("max_open")
    if not series.get("found") or cisd_level is None:
        return None
    start_idx = series.get("start_index")
    if start_idx is None:
        return None
    base_high, base_low = det.compute_projection_base(
        df, int(start_idx), trigger_idx, is_bearish, "wick",
    )
    if base_high <= base_low:
        return None
    fib_prices = det._fib_prices(base_high, base_low, is_bearish)
    entry = float(cisd_level)
    stop = float(base_low if direction == "LONG" else base_high)
    tp = _tp_1r(direction, entry, stop)
    if tp is None:
        return None
    if any(v is None or (v != v) for v in [entry, stop, tp]) or stop == 0:
        return None
    if direction == "LONG" and (entry <= stop or tp <= entry):
        return None
    if direction == "SHORT" and (stop <= entry or entry <= tp):
        return None
    return {
        "entry": entry,
        "stop": stop,
        "tp": tp,
        "start_idx": int(start_idx),
        "fib_prices": fib_prices,
        "cisd_level": entry,
    }


def _recalc_cisd_cross_pending_levels(
    pl: "PendingLimit",
    df: pd.DataFrame,
    det: "CISDDetector",
) -> bool:
    """Пересчёт stop/tp перед MARKET; False — сетап инвалидирован (low confirm < stop)."""
    cand_ts = str(getattr(pl, "cand_trigger_time", "") or "")
    if not cand_ts:
        return True
    try:
        cand_trigger_idx = int(df.index.get_loc(pd.Timestamp(cand_ts)))
        if isinstance(cand_trigger_idx, slice):
            cand_trigger_idx = int(cand_trigger_idx.start or 0)
    except Exception:
        return True
    is_bearish = pl.direction == "SHORT"
    last_closed = _last_closed_bar_iloc(df)
    if last_closed < 0 or last_closed < cand_trigger_idx:
        return True
    try:
        htf_anchor = pd.Timestamp(pl.htf_time) if pl.htf_time else None
    except Exception:
        htf_anchor = None
    pre = _levels_from_trigger(det, df, cand_trigger_idx, pl.direction, is_bearish)
    if pre is None:
        return False
    confirm_idx = det.find_confirmation(
        df, cand_trigger_idx, pre["cisd_level"], is_bearish, pre["start_idx"],
        htf_anchor=htf_anchor,
    )
    if confirm_idx is None or last_closed < int(confirm_idx):
        return True
    eff_trigger = _deepest_bar_iloc(df, cand_trigger_idx, last_closed, is_bearish)
    lv = _levels_from_trigger(det, df, eff_trigger, pl.direction, is_bearish)
    if lv is None:
        return False
    closed_low = float(df.iloc[last_closed]["low"])
    closed_high = float(df.iloc[last_closed]["high"])
    if pl.direction == "LONG" and closed_low < lv["stop"]:
        return False
    if pl.direction == "SHORT" and closed_high > lv["stop"]:
        return False
    pl.stop_price = lv["stop"]
    pl.tp_price = lv["tp"]
    pl.fib_1x = _safe_float(lv["fib_prices"][0])
    pl.cisd_level = lv["entry"]
    pl.entry_price = lv["entry"]
    save_pending(state.pending_limits)
    return True


def _is_resweep_extreme(direction: str, fresh_extreme: float, locked_extreme: float) -> bool:
    """True если wick-trigger глубже экстремума уже отработанного сетапа (пересвип)."""
    eps = 1e-8
    if direction == "LONG":
        return float(fresh_extreme) < float(locked_extreme) - eps
    return float(fresh_extreme) > float(locked_extreme) + eps


def _is_resweep_level(direction: str, fresh_level: float, locked_level: float) -> bool:
    """True если HTF sweep-level ушёл глубже (пересвип диапазона)."""
    eps = 1e-8
    if direction == "LONG":
        return float(fresh_level) < float(locked_level) - eps
    return float(fresh_level) > float(locked_level) + eps


def _mark_htf_sweep_consumed(
    tf_name: str,
    direction: str,
    htf_time: str,
    *,
    trigger_extreme: float,
    sweep_level: float,
    stop: float = 0.0,
    tp: float = 0.0,
    trigger_idx: int = -1,
) -> None:
    if float(sweep_level or 0) <= 0:
        return
    k = _htf_sweep_lock_key(tf_name, direction, sweep_level)
    state.htf_sweep_lock[k] = {
        "trigger_extreme": float(trigger_extreme),
        "sweep_level": float(sweep_level),
        "trigger_idx": int(trigger_idx),
        "htf_time": str(htf_time or ""),
        "stop": float(stop),
        "tp": float(tp),
    }
    if stop > 0 and tp > 0:
        state.htf_sweep_lock[_setup_leg_lock_key(tf_name, direction, stop, tp)] = {
            "trigger_extreme": float(trigger_extreme),
            "sweep_level": float(sweep_level),
            "htf_time": str(htf_time or ""),
        }
    logger.info(
        f"HTF sweep lock: {direction} [{htf_time}] "
        f"ext={trigger_extreme:.1f} sweep={sweep_level:.1f}"
    )


def _lock_has_active_work(tf_name: str, direction: str, lock: dict) -> bool:
    """Open/pending/fill на той же ноге, что и HTF sweep lock."""
    lock_htf = str(lock.get("htf_time") or "")
    lock_sweep = float(lock.get("sweep_level") or 0)
    lock_sl = float(lock.get("stop") or 0)
    lock_tp = float(lock.get("tp") or 0)

    def _leg_match(
        pl_htf: str, pl_sweep: float, pl_sl: float, pl_tp: float,
    ) -> bool:
        if lock_sl > 0 and lock_tp > 0 and _setup_sl_tp_match(pl_sl, pl_tp, lock_sl, lock_tp):
            return True
        if lock_htf and lock_sweep > 0 and _htf_times_match(pl_htf, lock_htf):
            if lock_sweep <= 0 or abs(pl_sweep - lock_sweep) < 0.05:
                return True
        return False

    for pl in state.pending_limits:
        if pl.tf != tf_name or pl.direction != direction:
            continue
        active = (
            pl.status == "pending"
            or pl.id in state._fill_in_progress
            or (pl.status == "filled" and not _filled_pending_stale(pl))
        )
        if not active:
            continue
        if _leg_match(
            _htf_time_for_pending(pl, tf_name),
            float(pl.sweep_level or 0),
            float(pl.stop_price),
            float(pl.tp_price),
        ):
            return True

    for pos in state.positions:
        if pos.status != "open" or pos.tf != tf_name or pos.direction != direction:
            continue
        if _leg_match(
            _htf_time_for_position(pos),
            float(pos.sweep_level or 0),
            float(pos.stop_price),
            float(pos.tp_price),
        ):
            return True
    return False


def _htf_time_in_keep_set(htf_time: str, keep_htf_times: set) -> bool:
    if not htf_time:
        return False
    for t in keep_htf_times:
        if _htf_times_match(htf_time, str(t)):
            return True
    return False


def _prune_htf_sweep_locks(tf_name: str, keep_htf_times: set) -> None:
    """Снять sweep lock, если его HTF-окно ушло из keep и нет open/pending на ноге."""
    if not keep_htf_times:
        return
    prefix = f"{tf_name}|"
    for k, lock in list(state.htf_sweep_lock.items()):
        if not k.startswith(prefix) or "|sweep=" not in k:
            continue
        parts = k.split("|", 2)
        if len(parts) < 2:
            continue
        direction = parts[1]
        if direction not in ("LONG", "SHORT"):
            continue
        lock_htf = str(lock.get("htf_time") or "")
        if _htf_time_in_keep_set(lock_htf, keep_htf_times):
            continue
        if _lock_has_active_work(tf_name, direction, lock):
            continue
        logger.info(
            f"HTF sweep lock prune: {direction} [{lock_htf}] "
            f"sweep={float(lock.get('sweep_level') or 0):.1f} — окно закрыто, нет open/pending"
        )
        _clear_htf_sweep_lock_entry(tf_name, direction, lock)


def _clear_htf_sweep_lock_entry(tf_name: str, direction: str, lock: dict) -> None:
    sweep_lvl = float(lock.get("sweep_level") or 0)
    if sweep_lvl > 0:
        state.htf_sweep_lock.pop(
            _htf_sweep_lock_key(tf_name, direction, sweep_lvl), None,
        )
    sl, tp = float(lock.get("stop") or 0), float(lock.get("tp") or 0)
    if sl > 0 and tp > 0:
        state.htf_sweep_lock.pop(
            _setup_leg_lock_key(tf_name, direction, sl, tp), None,
        )


def _sig_hash_stable(
    direction: str,
    htf_time: str,
    sweep_level: float,
    cisd_level: float,
    stop: float,
    tp: float,
) -> str:
    """Стабильный hash сетапа (без trigger/confirm idx) — не плодит «новые» сигналы каждый бар."""
    sk = active_symbol_key()
    sweep_r = _round_sweep_level(sweep_level, sk)
    dec = _price_decimals(symbol_profile(sk)["price_tick"])
    return hashlib.md5(
        f"{direction}_{htf_time}_{sweep_r}_"
        f"cisd={_round_price(cisd_level, sk):.{dec}f}_"
        f"sl={_round_price(stop, sk):.{dec}f}_tp={_round_price(tp, sk):.{dec}f}".encode()
    ).hexdigest()[:16]


def _detect_filter_flags() -> dict:
    return {
        "atr_enabled": False,
        "vol_enabled": False,
        "d_enabled": False,
    }


def _min_sweep_atr() -> float:
    return 0.0


def _trigger_vol_ma() -> int:
    return max(1, int(TRIGGER_VOL_FILTER.get("ma") or 20))


def _trigger_vol_max_ratio() -> float:
    return 0.0


def _trigger_vol_max_ratio_cfg() -> float:
    return 0.0


def _on_off(v: bool) -> str:
    return "ON" if v else "OFF"


def _quality_size_enabled() -> bool:
    return False


def _psl_size_enabled() -> bool:
    return False


def _psl_overlay_enabled() -> bool:
    return False


def _quality_stop_enabled() -> bool:
    return False


def _quality_stop_mult(score: float) -> float:
    """score q60→q90 linearly maps initial stop distance 1.00→0.85."""
    try:
        q60 = float(CONFIG["quality_stop_q60"])
        q90 = float(CONFIG["quality_stop_q90"])
        min_mult = float(CONFIG["quality_stop_min_mult"])
        value = float(score)
    except (KeyError, TypeError, ValueError):
        return 1.0
    if not all(math.isfinite(x) for x in (q60, q90, min_mult, value)):
        return 1.0
    if q90 <= q60 or not 0 < min_mult <= 1:
        return 1.0
    strength = min(1.0, max(0.0, (value - q60) / (q90 - q60)))
    return 1.0 - (1.0 - min_mult) * strength


def _apply_quality_stop_to_signal(sig: dict, tf_name: str) -> bool:
    """QSTOP вырезан: стоп остаётся за экстремумом свипа."""
    sig["quality_stop_applied"] = True
    sig["quality_stop_mult"] = 1.0
    return False


def _detect_filters_profile_name(flags: Optional[dict] = None) -> str:
    return "только vwap"


def _filters_status_text() -> str:
    return "\n".join([
        "Фильтры:",
        "  vwap  ON  (SHORT vd≤0, LONG vd≤−3)",
        "",
        "ATR / VOL(SMA) / D / QSZ / PSL / QSTOP вырезаны.",
    ])


def _trigger_filters_desc() -> str:
    return "vwap=ON"


def _apply_vol_or_touches_gate(
    *,
    df: pd.DataFrame,
    trigger_idx: int,
    direction: str,
    sweep_level: float,
    htf_time: str,
    htf_ratio: int,
    trigger_extreme: float,
    tf_name: str,
    d_enabled: bool,
    vol_enabled: bool,
    vol_max: float,
    vol_ratios,
    vol_ma: int,
    touch_atr14,
    trigger_vol_max_ok,
) -> tuple[Optional[str], Optional[int], bool]:
    """ATR/VOL вырезаны: только vwap дальше по пайплайну."""
    _ = (df, trigger_idx, direction, sweep_level, htf_time, htf_ratio,
         trigger_extreme, tf_name, d_enabled, vol_enabled, vol_max,
         vol_ratios, vol_ma, touch_atr14, trigger_vol_max_ok)
    return None, None, False


def _fmt_bar_msk(ts) -> str:
    try:
        dt = pd.Timestamp(ts).to_pydatetime().replace(tzinfo=None)
        m = msk(dt)
        return m.strftime("%d.%m %H:%M") if m else str(ts)[:16]
    except Exception:
        return str(ts)[:16] if ts is not None else "?"


def _fmt_when_utc_msk(ts) -> str:
    """UTC + МСК в одной строке — для отсевов в Telegram."""
    utc = "—"
    try:
        t = pd.Timestamp(ts)
        if getattr(t, "tzinfo", None) is not None:
            t = t.tz_convert("UTC").tz_localize(None)
        utc = t.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        utc = str(ts)[:16] if ts is not None else "—"
    msk_s = _fmt_bar_msk(ts)
    return f"{utc}  ({msk_s} МСК)"


def _remember_skip_tg_key(key: str) -> bool:
    """Резерв ключа перед send. True = шлём; при фейле — _release_skip_tg_key."""
    if key in state.skip_tg_keys:
        return False
    state.skip_tg_keys.add(key)
    if len(state.skip_tg_keys) > 400:
        state.skip_tg_keys = set(list(state.skip_tg_keys)[-200:])
    return True


def _release_skip_tg_key(key: str) -> None:
    """Снять резерв после неуспешной доставки — следующий скан сможет дослать."""
    state.skip_tg_keys.discard(key)


def _schedule_coro(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            coro.close()
        except Exception:
            pass
        return
    loop.create_task(coro)


async def _send_skip_tg_or_release(dedup: str, msg: str) -> None:
    """Доставить skip-TG; при сетевом фейле снять ключ (дошлёт следующий скан)."""
    if not _tg_online or _tg_app is None:
        await send_telegram(msg)  # лог [TG offline]; ключ оставляем
        return
    ok = await send_telegram(msg)
    if ok is None:
        _release_skip_tg_key(dedup)


def _queue_pre_signal_filter_skip(
    *,
    tf_name: str,
    direction: str,
    category: str,
    filter_title: str,
    trigger_time: str,
    htf_time: str,
    sweep_level: float,
    trigger_extreme: float,
    detail: str,
    symbol_key: Optional[str] = None,
) -> None:
    """TG + лог для pre-signal отсева. Цифры замораживаются здесь, не при send."""
    sk = str(symbol_key or active_symbol_key())
    if sk not in SYMBOL_PROFILES:
        sk = active_symbol_key()
    lbl = str(symbol_profile(sk)["label"])
    sweep_v = float(sweep_level)
    ext_v = float(trigger_extreme)
    trig_s = str(trigger_time)
    htf_s = str(htf_time)
    title = str(filter_title)
    detail_s = str(detail or "").strip()
    dir_s = str(direction)
    dedup = (
        f"{category}:{sk}:{tf_name}:{dir_s}:"
        f"{htf_s}:{trig_s}:{sweep_v:.6g}"
    )
    if not _remember_skip_tg_key(dedup):
        return
    tfl = tf_label(tf_name)
    arrow = "📈" if dir_s == "LONG" else "📉"
    sep = "─" * 34
    msg = "\n".join([
        f"{_mode_prefix()} ⛔ Отсев {arrow} {dir_s} {lbl} [{tfl}] — {title}",
        sep,
        f"Сигнал: {_fmt_when_utc_msk(trig_s)}",
        f"HTF-окно: {_fmt_when_utc_msk(htf_s)}",
        f"Sweep: {_fmt_px(sweep_v, sk)}  Ext: {_fmt_px(ext_v, sk)}",
        sep,
        detail_s,
    ])
    logger.info(
        f"prefilter skip: {sk} {dir_s} [{tf_name}] {title} | "
        f"sweep={sweep_v} ext={ext_v} | {detail_s.replace(chr(10), ' | ')}"
    )
    _schedule_coro(_send_skip_tg_or_release(str(dedup), str(msg)))


def detect_signals(
    df: pd.DataFrame,
    processed: set,
    *,
    htf_ratio: int = 240,
    tf_name: str = "tf1",
    df_confirm: Optional[pd.DataFrame] = None,
    min_sweep_atr: float = 0.0,
) -> list:
    """
    Сигнал после HTF-свипа + MSS confirm. Вход: LIMIT/STOP-LIMIT на cisd_level.
    confirm_timeframe (если задан): MSS на LTF; серия/триггер — на timeframe (tf5: 5m, tf7: 1m).
    Закрытый MSS на LTF → лимитка без ожидания close-свипа на main TF.
    Без MSS — сигнал не создаём.
    """
    tf_cfg = CONFIG.get(tf_name, {})
    htf_bar_m = _tf_to_minutes(str(tf_cfg.get("timeframe") or "15m"))
    confirm_tf = _confirm_timeframe_for(tf_name)
    df_mss = df
    if confirm_tf and df_confirm is not None and len(df_confirm) >= 2:
        sliced = _slice_confirm_df(df_confirm, df, htf_bar_m)
        if sliced is not None and len(sliced) >= 2:
            df_mss = sliced
    htf_confirm_windows = int(tf_cfg.get("htf_confirm_windows", 2))
    n_htf_keep = max(2, htf_confirm_windows)
    det = CISDDetector(
        htf_ratio=htf_ratio,
        htf_confirm_windows=htf_confirm_windows,
        max_range=_mss_max_range(
            htf_ratio,
            htf_confirm_windows,
            str(tf_cfg.get("timeframe") or "15m"),
            confirm_tf,
        ),
    )
    df_htf = det.resample_to_htf(df)
    sweeps = det.detect_htf_sweeps(df_htf, df)

    active_htf_time, recent_from, forming_htf_time = _htf_detect_context(
        df, df_htf, htf_ratio,
    )
    current_htf_time = active_htf_time
    if (
        active_htf_time is not None
        and forming_htf_time is not None
        and active_htf_time != forming_htf_time
    ):
        logger.info(
            f"detect: HTF boundary — active={active_htf_time} "
            f"forming_bucket={forming_htf_time}"
        )

    # DEBUG: сводка
    n_total = len(sweeps)
    n_recent = sum(1 for s in sweeps if s["trigger_idx"] >= recent_from)
    logger.info(f"detect: всего свипов={n_total}, свежих={n_recent}, df_len={len(df)}, recent_from={recent_from}")

    signals = []
    skipped_old = 0
    skipped_no_sweep_close = 0
    skipped_no_series = 0
    skipped_no_confirm = 0
    skipped_extremum = 0
    skipped_resweep_wait = 0
    skipped_bad = 0
    skipped_dup = 0
    skipped_cand_drop = 0
    skipped_tf4_bar3 = 0
    skipped_no_mss_entry = 0
    skipped_physical_dup = 0
    skipped_small_sweep = 0
    skipped_high_vol = 0
    skipped_soft_touches = 0
    seen_physical: set[str] = set()
    min_sweep_atr = 0.0
    vol_enabled = False
    vol_max = 0.0
    sweep_atr14 = None
    vol_ratios = None
    touch_atr14 = None
    sweep_atr_ratio_fn = None
    trigger_vol_max_ok = None
    vol_ma = 20
    d_enabled = False

    # 1) upsert кандидаты из текущего HTF-окна
    for sweep in sweeps:
        try:
            sweep_htf = pd.Timestamp(sweep.get("htf_time"))
        except Exception:
            continue
        if current_htf_time is None or sweep_htf != pd.Timestamp(current_htf_time):
            continue
        is_bearish = sweep["type"] == "bearish"
        direction = "SHORT" if is_bearish else "LONG"
        trigger_idx = int(sweep["trigger_idx"])
        if trigger_idx < recent_from:
            continue
        sweep_lvl_i = float(sweep.get("sweep_level") or 0)
        htf_s = str(sweep.get("htf_time") or "")
        trigger_time = str(pd.Timestamp(df.index[trigger_idx]))
        tr_row = df.iloc[trigger_idx]
        trigger_extreme = float(tr_row["high"] if is_bearish else tr_row["low"])
        if min_sweep_atr > 0 and not sweep_min_atr_ok(
            df,
            trigger_idx,
            sweep_lvl_i,
            is_bearish,
            min_ratio=min_sweep_atr,
            atr14=sweep_atr14,
        ):
            skipped_small_sweep += 1
            atr_r = (
                sweep_atr_ratio_fn(
                    df, trigger_idx, sweep_lvl_i, is_bearish, atr14=sweep_atr14,
                )
                if sweep_atr_ratio_fn is not None else None
            )
            atr_txt = f"{atr_r:.2f}" if atr_r is not None else "n/a"
            _queue_pre_signal_filter_skip(
                tf_name=tf_name,
                direction=direction,
                category="skipped_sweep_atr",
                filter_title="sweep/ATR",
                trigger_time=trigger_time,
                htf_time=htf_s,
                sweep_level=sweep_lvl_i,
                trigger_extreme=trigger_extreme,
                detail=f"sweep/ATR = {atr_txt} < min {min_sweep_atr:.2f}",
                symbol_key=active_symbol_key(),
            )
            continue
        skip_cat, _, _ = _apply_vol_or_touches_gate(
            df=df,
            trigger_idx=trigger_idx,
            direction=direction,
            sweep_level=sweep_lvl_i,
            htf_time=htf_s,
            htf_ratio=htf_ratio,
            trigger_extreme=trigger_extreme,
            tf_name=tf_name,
            d_enabled=d_enabled,
            vol_enabled=vol_enabled,
            vol_max=vol_max,
            vol_ratios=vol_ratios,
            vol_ma=vol_ma,
            touch_atr14=touch_atr14,
            trigger_vol_max_ok=trigger_vol_max_ok,
        )
        if skip_cat == "skipped_soft_dow_touches":
            skipped_soft_touches += 1
            continue
        if skip_cat == "skipped_trigger_vol":
            skipped_high_vol += 1
            continue
        incoming = {
            "tf": tf_name,
            "symbol_key": active_symbol_key(),
            "direction": direction,
            "htf_time": htf_s,
            "type": str(sweep.get("type") or ""),
            "sweep_level": sweep_lvl_i,
            "trigger_idx": trigger_idx,
            "trigger_time": trigger_time,
            "trigger_extreme": trigger_extreme,
        }
        k = _cand_key(tf_name, direction, htf_s)
        _upsert_sweep_candidate(k, incoming)

    # 2) prune кандидатов: последние n_htf_keep HTF-окон (tf4: 3, остальные: 2)
    if current_htf_time is not None:
        keep = set()
        tail_n = min(n_htf_keep, len(df_htf.index))
        for t in df_htf.index[-tail_n:]:
            keep.add(str(pd.Timestamp(t)))
        drop = []
        sk_now = active_symbol_key()
        for k, v in state.sweep_candidates.items():
            if v.get("tf") != tf_name:
                continue
            if _cand_symbol_key(v, k) != sk_now:
                continue
            if str(pd.Timestamp(v.get("htf_time"))) not in keep:
                drop.append(k)
        for k in drop:
            state.sweep_candidates.pop(k, None)
        _prune_htf_sweep_locks(tf_name, keep)
        _prune_htf_taken(tf_name, keep)

    # 3) Обрабатываем кандидатов (текущий + предыдущий), но сигнал разрешаем только если confirm в текущем окне.
    cands = _cands_for_symbol(tf_name)
    for cand in cands:
        direction = str(cand["direction"])
        is_bearish = direction == "SHORT"
        sweep_lvl = float(cand.get("sweep_level") or 0)
        htf_s = str(cand.get("htf_time") or "")
        try:
            htf_anchor = pd.Timestamp(cand["htf_time"])
        except Exception:
            continue

        matched = _find_sweep_for_cand(sweeps, cand)
        if matched is None:
            relaxed = _find_sweep_for_cand_by_htf(sweeps, cand)
            if relaxed is not None:
                new_ext = _trigger_extreme_at(
                    df, int(relaxed["trigger_idx"]), is_bearish,
                )
                old_ext = float(cand.get("trigger_extreme") or 0)
                new_lvl = float(relaxed.get("sweep_level") or 0)
                old_lvl = float(cand.get("sweep_level") or 0)
                if _is_resweep_extreme(direction, new_ext, old_ext) or _is_resweep_level(
                    direction, new_lvl, old_lvl,
                ):
                    _sync_cand_from_sweep(cand, relaxed, df)
                    state.sweep_candidates[_cand_key(tf_name, direction, htf_s)] = cand
                    sweep_lvl = new_lvl
                    logger.info(
                        f"detect:   -> кандидат пересвип [{htf_s}] {direction}: "
                        f"sweep {old_lvl:.1f}→{new_lvl:.1f} ext {old_ext:.1f}→{new_ext:.1f}"
                    )

        trigger_idx = _resolve_cand_trigger_idx(df, cand)
        if trigger_idx is None:
            _drop_sweep_candidate(tf_name, direction, htf_s, "trigger вне окна df")
            skipped_cand_drop += 1
            continue
        try:
            trigger_extreme = float(cand["trigger_extreme"])
        except (TypeError, ValueError, KeyError):
            _drop_sweep_candidate(tf_name, direction, htf_s, "нет trigger кандидата")
            skipped_cand_drop += 1
            continue

        last_closed = _last_closed_bar_iloc(df)
        if last_closed >= 0 and det.is_extremum_updated(
            df, trigger_idx, last_closed, is_bearish,
        ):
            eff = _deepest_bar_iloc(df, trigger_idx, last_closed, is_bearish)
            _sync_cand_trigger(cand, df, eff, is_bearish)
            state.sweep_candidates[_cand_key(tf_name, direction, htf_s)] = cand
            trigger_idx = eff
            trigger_extreme = float(cand["trigger_extreme"])
            logger.info(
                f"detect:   -> кандидат trigger сдвинут [{htf_s}] {direction}: "
                f"tr={cand['trigger_time']} ext={trigger_extreme:.1f}"
            )

        if min_sweep_atr > 0 and not sweep_min_atr_ok(
            df,
            trigger_idx,
            sweep_lvl,
            is_bearish,
            min_ratio=min_sweep_atr,
            atr14=sweep_atr14,
        ):
            skipped_small_sweep += 1
            atr_r = (
                sweep_atr_ratio_fn(
                    df, trigger_idx, sweep_lvl, is_bearish, atr14=sweep_atr14,
                )
                if sweep_atr_ratio_fn is not None else None
            )
            atr_txt = f"{atr_r:.2f}" if atr_r is not None else "n/a"
            _queue_pre_signal_filter_skip(
                tf_name=tf_name,
                direction=direction,
                category="skipped_sweep_atr",
                filter_title="sweep/ATR",
                trigger_time=str(cand.get("trigger_time") or df.index[trigger_idx]),
                htf_time=htf_s,
                sweep_level=sweep_lvl,
                trigger_extreme=trigger_extreme,
                detail=f"sweep/ATR = {atr_txt} < min {min_sweep_atr:.2f}",
                symbol_key=str(cand.get("symbol_key") or active_symbol_key()),
            )
            _drop_sweep_candidate(
                tf_name, direction, htf_s, "sweep/ATR мал",
                symbol_key=str(cand.get("symbol_key") or active_symbol_key()),
            )
            continue

        skip_cat, prior_touches_n, soft_dow = _apply_vol_or_touches_gate(
            df=df,
            trigger_idx=trigger_idx,
            direction=direction,
            sweep_level=sweep_lvl,
            htf_time=htf_s,
            htf_ratio=htf_ratio,
            trigger_extreme=trigger_extreme,
            tf_name=tf_name,
            d_enabled=d_enabled,
            vol_enabled=vol_enabled,
            vol_max=vol_max,
            vol_ratios=vol_ratios,
            vol_ma=vol_ma,
            touch_atr14=touch_atr14,
            trigger_vol_max_ok=trigger_vol_max_ok,
        )
        if skip_cat == "skipped_soft_dow_touches":
            skipped_soft_touches += 1
            _drop_sweep_candidate(tf_name, direction, htf_s, "soft-DOW touches")
            continue
        if skip_cat == "skipped_trigger_vol":
            skipped_high_vol += 1
            _drop_sweep_candidate(tf_name, direction, htf_s, "trigger vol высокий")
            continue

        lock_k = _htf_sweep_lock_key(tf_name, direction, sweep_lvl)
        lock = state.htf_sweep_lock.get(lock_k)
        if lock is not None:
            if _is_resweep_extreme(direction, trigger_extreme, lock["trigger_extreme"]):
                logger.info(
                    f"detect:   -> пересвип {direction} [{htf_s}]: "
                    f"lock={lock['trigger_extreme']:.1f} fresh={trigger_extreme:.1f}"
                )
                _clear_htf_sweep_lock_entry(tf_name, direction, lock)
            else:
                skipped_resweep_wait += 1
                logger.info(
                    f"detect:   -> ждём пересвип [{htf_s}] {direction}: "
                    f"lock={lock['trigger_extreme']:.1f} now={trigger_extreme:.1f} "
                    f"sweep={sweep_lvl:.1f}"
                )
                continue

        # Ищем серию свечей и получаем cisd_level
        if is_bearish:
            series = det.find_bullish_series(df, trigger_idx)
            if not series["found"] or series["min_open"] is None:
                skipped_no_series += 1
                logger.info(f"detect:   -> нет серии (found={series['found']})")
                continue
            cisd_level = float(series["min_open"])
            start_idx  = series["start_index"]
        else:
            series = det.find_bearish_series(df, trigger_idx)
            if not series["found"] or series["max_open"] is None:
                skipped_no_series += 1
                logger.info(f"detect:   -> нет серии (found={series['found']})")
                continue
            cisd_level = float(series["max_open"])
            start_idx  = series["start_index"]

        if start_idx is None:
            skipped_no_series += 1
            continue

        # База и фибоначчи
        base_high, base_low = det.compute_projection_base(
            df, int(start_idx), trigger_idx, is_bearish, "wick"
        )
        if base_high <= base_low:
            skipped_bad += 1
            logger.info(f"detect:   -> base_high({base_high:.1f}) <= base_low({base_low:.1f})")
            continue

        fib_prices = det._fib_prices(base_high, base_low, is_bearish)

        entry = cisd_level
        stop  = base_low  if direction == "LONG" else base_high
        tp    = _tp_1r(direction, entry, stop)

        mss_on_ltf = df_mss is not df
        mss_trigger = (
            _map_htf_ts_to_ltf_iloc(df_mss, df.index[trigger_idx])
            if mss_on_ltf else trigger_idx
        )
        mss_start = (
            _map_htf_ts_to_ltf_iloc(df_mss, df.index[int(start_idx)])
            if mss_on_ltf and start_idx is not None else start_idx
        )
        confirm_idx = det.find_confirmation(
            df_mss, mss_trigger, cisd_level, is_bearish, mss_start,
            htf_anchor=htf_anchor,
        )
        if confirm_idx is not None:
            last_closed_mss = _last_closed_bar_iloc(df_mss)
            if last_closed_mss < 0 or int(confirm_idx) > last_closed_mss:
                logger.info(
                    f"detect:   -> MSS confirm на формирующейся свече "
                    f"({(confirm_tf or tf_cfg.get('timeframe', '?')) if mss_on_ltf else tf_cfg.get('timeframe', '?')} "
                    f"idx={confirm_idx}, last_closed={last_closed_mss}) — ждём close"
                )
                confirm_idx = None
        if confirm_idx is None:
            skipped_no_confirm += 1

        confirm_on_sweep = False
        confirm_close = 0.0
        one_bar_sweep_cisd = False
        late_retest = False
        retest_geom = _sweep_cisd_retest_limit(direction, sweep_lvl, cisd_level)
        tf4_bar3_limit = False
        mss_ok = False

        mss_extremum_hit = False
        confirm_series_iloc = trigger_idx
        if confirm_idx is not None:
            if mss_on_ltf:
                confirm_series_iloc = _map_ltf_ts_to_series_iloc(
                    df, df_mss.index[int(confirm_idx)],
                )
                mss_extremum_hit = det.is_extremum_updated(
                    df, trigger_idx, confirm_series_iloc, is_bearish,
                )
            else:
                mss_extremum_hit = det.is_extremum_updated(
                    df_mss, mss_trigger, int(confirm_idx), is_bearish,
                )
            if mss_extremum_hit:
                series_tf = str(tf_cfg.get("timeframe") or "?")
                end_iloc = (
                    confirm_series_iloc if mss_on_ltf else int(confirm_idx)
                )
                logger.info(
                    f"detect:   -> MSS confirm отклонён: экстремум обновлён на "
                    f"{series_tf if mss_on_ltf else (confirm_tf or series_tf)} "
                    f"(tr={trigger_idx}..{end_iloc})"
                )
        if confirm_idx is not None and not mss_extremum_hit:
            mss_ok = True
            confirm_close = float(df_mss.iloc[int(confirm_idx)]["close"])
            cf_bar = df_mss.iloc[int(confirm_idx)]
            if mss_on_ltf:
                confirm_on_sweep = _ltf_bar_in_htf_bucket(
                    df_mss.index[int(confirm_idx)], df.index[trigger_idx], htf_bar_m,
                )
            else:
                confirm_on_sweep = int(confirm_idx) == int(trigger_idx)
            late_retest = _late_retest_entry(direction, cisd_level, confirm_close)

        ltf_mss_early = mss_on_ltf and mss_ok

        sweep_close_idx = det.find_first_sweep_close_confirm_bar(
            df, trigger_idx, sweep_lvl, is_bearish, htf_anchor=htf_anchor,
        )
        if sweep_close_idx is None:
            skipped_no_sweep_close += 1
            logger.info(
                f"detect:   -> нет close-свипа на {tf_cfg.get('timeframe', '?')} "
                f"(tr={trigger_idx} sweep={sweep_lvl:.1f} htf={htf_s})"
                + (
                    f"; {confirm_tf} MSS есть (close={confirm_close:.1f}), ждём 5m close-свип"
                    if ltf_mss_early else ""
                )
            )
            continue

        logger.info(
            f"detect: свип {direction} sweep={sweep_lvl:.1f} "
            f"trigger_idx={trigger_idx} close_arm={sweep_close_idx} "
            f"htf={htf_s}"
        )
        if sweep_close_idx != trigger_idx:
            logger.info(
                f"detect:   -> close-свип на баре {sweep_close_idx}, "
                f"trigger на {trigger_idx}"
            )

        # close-свип уже валидирован find_first_sweep_close_confirm_bar (окно htf_anchor).
        # Не фильтруем по recent_from — иначе бар на границе HTF (22:50→23:00) теряется.
        if det.is_extremum_updated(
            df, trigger_idx, int(sweep_close_idx), is_bearish,
        ):
            skipped_extremum += 1
            logger.info(
                f"detect:   -> экстремум обновлён между trigger={trigger_idx} "
                f"и close-свип={sweep_close_idx}"
            )
            continue

        sweep_close_close = float(df.iloc[int(sweep_close_idx)]["close"])

        if mss_ok:
            if mss_on_ltf:
                one_bar_sweep_cisd = (
                    int(confirm_idx) == int(mss_trigger)
                    and _ltf_bar_in_htf_bucket(
                        df_mss.index[int(confirm_idx)],
                        df.index[int(sweep_close_idx)],
                        htf_bar_m,
                    )
                )
            else:
                one_bar_sweep_cisd = int(sweep_close_idx) == int(confirm_idx)

        if confirm_idx is not None and not mss_extremum_hit:
            cf_bar = df_mss.iloc[int(confirm_idx)]
            if one_bar_sweep_cisd:
                logger.info(
                    "detect:   -> one-bar sweep+cisd: пересечены sweep и CISD на одном баре "
                    f"(idx={confirm_idx}) → LIMIT @ CISD (ретест после confirm)"
                )
            elif retest_geom:
                logger.info(
                    f"detect:   -> sweep {'ниже' if direction == 'SHORT' else 'выше'} CISD "
                    f"(sweep={sweep_lvl:.1f} cisd={cisd_level:.1f}) → LIMIT retest"
                )
            elif late_retest:
                wick_ok = _confirm_wick_past_sweep(
                    direction,
                    float(cf_bar["high"]),
                    float(cf_bar["low"]),
                    sweep_lvl,
                )
                body_ok = _confirm_close_past_sweep(direction, confirm_close, sweep_lvl)
                if body_ok:
                    cf_tf = confirm_tf if mss_on_ltf else str(tf_cfg.get("timeframe") or "?")
                    logger.info(
                        f"detect:   -> CISD confirm {cf_tf} "
                        f"(close={confirm_close:.1f} "
                        f"{'≥' if direction == 'LONG' else '≤'} {cisd_level:.1f}) "
                        f"→ LIMIT @ CISD (ретест)"
                    )
                elif wick_ok:
                    logger.info(
                        f"detect:   -> CISD confirm (wick, close={confirm_close:.1f}, "
                        f"cisd={cisd_level:.1f}) → LIMIT @ CISD (ретест)"
                    )
                else:
                    logger.info(
                        f"detect:   -> confirm за CISD (close={confirm_close:.1f}, "
                        f"cisd={cisd_level:.1f}) → LIMIT @ CISD (ретест)"
                    )
            elif confirm_on_sweep:
                logger.info(
                    f"detect:   -> confirm на баре свипа: лимит на CISD {cisd_level:.1f}"
                )
        elif retest_geom:
            logger.info(
                f"detect:   -> sweep {'ниже' if direction == 'SHORT' else 'выше'} CISD "
                f"(sweep={sweep_lvl:.1f} cisd={cisd_level:.1f}) → LIMIT retest"
            )
        else:
            logger.info(
                f"detect:   -> close-свип OK, ждём пробой CISD "
                f"(close={sweep_close_close:.1f} cisd={cisd_level:.1f}) → STOP-LIMIT"
            )

        if mss_ok and _is_tf4_early_two_bar_pattern(
            tf_name, recent_from, trigger_idx, confirm_idx, sweep_close_idx,
        ):
            bar3_idx = recent_from + 2
            last_closed = _last_closed_bar_iloc(df)
            if last_closed < bar3_idx:
                logger.info(
                    f"detect:   -> tf4 early-2bar: ждём close бара 3 HTF "
                    f"(last_closed={last_closed}, need={bar3_idx})"
                )
                continue
            ok_b3, b3_reason = _tf4_bar3_confirms_direction(
                df, direction, recent_from,
            )
            if not ok_b3:
                skipped_tf4_bar3 += 1
                sig_hash_skip = _sig_hash_stable(
                    direction, htf_s, sweep_lvl, cisd_level, stop, tp,
                )
                processed.add(sig_hash_skip)
                logger.info(
                    f"detect:   -> tf4 bar3 не подтвердил: {b3_reason} → пропуск"
                )
                state.sweep_candidates.pop(
                    _cand_key(tf_name, direction, htf_s), None,
                )
                continue
            tf4_bar3_limit = True
            one_bar_sweep_cisd = False
            late_retest = False
            logger.info(
                f"detect:   -> tf4 bar3 подтвердил: {b3_reason} → LIMIT retest CISD"
            )

        if any(v is None or (v != v) for v in [entry, stop, tp]):
            skipped_bad += 1
            continue
        if stop == 0:
            skipped_bad += 1
            continue
        if direction == "LONG"  and (entry <= stop or tp <= entry):
            skipped_bad += 1
            logger.info(f"detect:   -> bad R:R LONG entry={entry:.1f} stop={stop:.1f} tp={tp:.1f}")
            continue
        if direction == "SHORT" and (stop <= entry or entry <= tp):
            skipped_bad += 1
            logger.info(f"detect:   -> bad R:R SHORT entry={entry:.1f} stop={stop:.1f} tp={tp:.1f}")
            continue

        sweep5m_idx = int(sweep_close_idx)
        # v6: fib-stretch не меняет TP и не переводит вход в MARKET.
        tp, fib_stretch_market, fib_stretch_reason, fib_market_mode = (
            _resolve_retest_geom_fib_market(
                direction, retest_geom, mss_ok, df, sweep5m_idx,
                float(cisd_level), fib_prices, tp,
                series_start_idx=int(start_idx),
            )
        )
        if fib_stretch_market:
            logger.info(f"detect:   -> {fib_stretch_reason} (игнор, TP=1R LIMIT)")

        entry_kind_pre = "LIMIT"
        rr_entry = float(cisd_level)
        ok_rr, rr_val, rr_reason = _passes_min_rr(direction, rr_entry, stop, tp)
        if not ok_rr:
            skipped_bad += 1
            logger.info(
                f"detect:   -> min_rr {direction} {rr_reason} "
                f"entry={rr_entry:.1f} stop={stop:.1f} tp={tp:.1f}"
            )
            continue

        idx = df.index[trigger_idx]

        sig_hash = _sig_hash_stable(
            direction, htf_s, sweep_lvl, cisd_level, stop, tp,
        )
        if not mss_ok:
            skipped_no_mss_entry += 1
            logger.info(
                f"detect:   -> нет MSS confirm — сигнал не создаём "
                f"(close-свип={sweep_close_close:.1f} cisd={cisd_level:.1f})"
            )
            continue

        if sig_hash in processed:
            skipped_dup += 1
            logger.info(f"detect:   -> дубликат hash={sig_hash}")
            continue

        phys_keys = _sig_physical_dedup_keys_for_emit(
            direction, tf_name,
            str(pd.Timestamp(df.index[int(trigger_idx)])),
            float(trigger_extreme), sweep_lvl,
        )
        if any(k in seen_physical for k in phys_keys):
            skipped_physical_dup += 1
            processed.add(sig_hash)
            state.sweep_candidates.pop(_cand_key(tf_name, direction, htf_s), None)
            logger.info(f"detect:   -> дубликат physical {phys_keys[0]}")
            continue
        seen_physical.update(phys_keys)

        rr_log = rr_val if rr_val is not None else (abs(tp - rr_entry) / abs(rr_entry - stop))
        q_feat: dict = {
            "quality_score": 0.0,
            "quality_size_mult": 1.0,
            "start_n": 0,
            "never": False,
            "unreclaim": False,
            "no_start_fvg": True,
            "no_conf_fvg": True,
            "bars1": 0,
            "start_range_atr": None,
        }
        if _quality_size_enabled() or _quality_stop_enabled():
            try:
                from backtest.quality_size import compute_quality_features

                atr_q = float("nan")
                if sweep_atr14 is not None and 0 <= int(trigger_idx) < len(sweep_atr14):
                    atr_q = float(sweep_atr14.iloc[int(trigger_idx)])
                conf_5m = (
                    int(confirm_series_iloc)
                    if mss_ok and mss_on_ltf
                    else (int(confirm_idx) if confirm_idx is not None else int(trigger_idx))
                )
                conf_t = (
                    str(pd.Timestamp(df_mss.index[int(confirm_idx)]))
                    if confirm_idx is not None else str(pd.Timestamp(df.index[int(trigger_idx)]))
                )
                q_feat = compute_quality_features(
                    df,
                    direction=direction,
                    trigger_idx=int(trigger_idx),
                    start_idx=int(start_idx) if start_idx is not None else None,
                    confirm_idx_5m=conf_5m,
                    level=float(sweep_lvl),
                    atr=atr_q,
                    df1=df_mss if mss_on_ltf else None,
                    trigger_bar_time=str(pd.Timestamp(df.index[int(trigger_idx)])),
                    confirm_bar_time=conf_t,
                )
            except Exception as e:
                logger.warning(f"detect: quality_size failed: {e}")
        if _psl_overlay_enabled():
            try:
                from backtest.psl_size import apply_psl_sizing
                from backtest.touch_filter import prior_touches_at_trigger

                psl_touches = prior_touches_n
                if psl_touches is None:
                    psl_touches = prior_touches_at_trigger(
                        df,
                        direction=direction,
                        level=float(sweep_lvl),
                        htf_time=htf_s,
                        trigger_idx=int(trigger_idx),
                        htf_minutes=htf_ratio,
                        atr14=touch_atr14,
                    )
                psl_sw_atr = (
                    sweep_atr_ratio_fn(
                        df, int(trigger_idx), float(sweep_lvl),
                        direction == "SHORT", atr14=sweep_atr14,
                    )
                    if sweep_atr_ratio_fn is not None else None
                )
                psl_vol_ratio = None
                if vol_ratios is not None and 0 <= int(trigger_idx) < len(vol_ratios):
                    raw_vr = vol_ratios.iloc[int(trigger_idx)]
                    if not pd.isna(raw_vr):
                        psl_vol_ratio = float(raw_vr)
                q_feat.update(apply_psl_sizing(
                    float(q_feat.get("quality_size_mult") or 1.0),
                    {
                        **q_feat,
                        "sw_atr": psl_sw_atr,
                        "prior_touches": psl_touches,
                        "vol_ratio": psl_vol_ratio,
                    },
                ))
                q_feat["quality_size_mult"] = q_feat["psl_size_mult"]
                q_feat["prior_touches"] = psl_touches
            except Exception as e:
                logger.warning(f"detect: PSL overlay failed; raw QSZ kept: {e}")
        logger.info(
            f"detect:   -> СИГНАЛ entry={_fmt_px(entry)} stop={_fmt_px(stop)} tp={_fmt_px(tp)} "
            f"R:R={rr_log:.2f} (rr_entry={_fmt_px(rr_entry)} kind={entry_kind_pre} "
            f"q={q_feat.get('quality_score')}×{q_feat.get('quality_size_mult')} "
            f"pSL={q_feat.get('psl_probability', 'off')})"
        )
        signals.append({
            "hash":            sig_hash,
            "symbol_key":      active_symbol_key(),
            "direction":       direction,
            "entry":           entry,
            "stop":            stop,
            "tp":              tp,
            "confirm_on_sweep": confirm_on_sweep,
            "confirm_close": confirm_close,
            "sweep_close_close": sweep_close_close,
            "sweep_close_idx": int(sweep_close_idx),
            "late_retest": late_retest,
            "one_bar_sweep_cisd": one_bar_sweep_cisd,
            "tf4_bar3_limit_retest": tf4_bar3_limit,
            "fib_stretch_market": fib_stretch_market,
            "fib_market_mode": fib_market_mode,
            "sweep_confirm_5m_time": str(pd.Timestamp(df.index[sweep5m_idx])),
            "cisd_level":      float(cisd_level),
            "htf_time":        htf_s,
            "trigger_idx":     int(trigger_idx),
            "trigger_extreme": float(trigger_extreme),
            "base_high":       float(base_high),
            "base_low":        float(base_low),
            "htf_sweep_level": float(sweep_lvl),
            "fib_1x":          _safe_float(fib_prices[0]),
            "fib_2x":          _safe_float(fib_prices[1]),
            "fib_2_5x":        _safe_float(fib_prices[2]) if len(fib_prices) > 2 else None,
            "fib_4x":          _safe_float(fib_prices[3]) if len(fib_prices) > 3 else None,
            "fib_4_5x":        _safe_float(fib_prices[4]) if len(fib_prices) > 4 else None,
            "timestamp":       idx,
            "confirm_idx":     int(confirm_idx) if confirm_idx is not None else -1,
            "confirm_bar_time": (
                str(pd.Timestamp(df_mss.index[int(confirm_idx)]))
                if confirm_idx is not None else ""
            ),
            "confirm_timeframe": confirm_tf if mss_on_ltf and confirm_idx is not None else "",
            "sweep_close_bar_time": str(pd.Timestamp(df.index[int(sweep_close_idx)])),
            "trigger_bar_time": str(pd.Timestamp(df.index[int(trigger_idx)])),
            "prior_touches": q_feat.get("prior_touches", prior_touches_n),
            "soft_dow": soft_dow,
            "quality_score": float(q_feat.get("quality_score") or 0.0),
            "quality_size_mult": float(q_feat.get("quality_size_mult") or 1.0),
            "psl_probability": q_feat.get("psl_probability"),
            "psl_quartile": q_feat.get("psl_quartile"),
            "psl_adjustment": q_feat.get("psl_adjustment"),
            "psl_model_version": q_feat.get("psl_model_version"),
            "quality": {
                "start_n": int(q_feat.get("start_n") or 0),
                "never": bool(q_feat.get("never")),
                "unreclaim": bool(q_feat.get("unreclaim")),
                "no_start_fvg": bool(q_feat.get("no_start_fvg")),
                "no_conf_fvg": bool(q_feat.get("no_conf_fvg")),
                "bars1": int(q_feat.get("bars1") or 0),
                "start_range_atr": (
                    None if q_feat.get("start_range_atr") is None
                    or (
                        isinstance(q_feat.get("start_range_atr"), float)
                        and not math.isfinite(float(q_feat.get("start_range_atr")))
                    )
                    else float(q_feat.get("start_range_atr"))
                ),
            },
            "detect_filters": {
                "atr": False,
                "vol": False,
                "d": False,
            },
        })

        # Сигнал собран → кандидат закрыт
        state.sweep_candidates.pop(_cand_key(tf_name, direction, htf_s), None)

    logger.info(
        f"detect: итог — сигналов={len(signals)}, отсев: старых={skipped_old}, "
        f"нет_close_свипа={skipped_no_sweep_close}, нет_серии={skipped_no_series}, "
        f"нет_confirm={skipped_no_confirm}, extremum={skipped_extremum}, "
        f"кандидат_снят={skipped_cand_drop}, "
        f"ждём_пересвипа={skipped_resweep_wait}, "
        f"tf4_bar3={skipped_tf4_bar3}, "
        f"нет_mss={skipped_no_mss_entry}, "
        f"малый_свип={skipped_small_sweep}, "
        f"vol_выс={skipped_high_vol}, "
        f"soft_touches={skipped_soft_touches}, "
        f"плохие={skipped_bad}, дубли={skipped_dup}, "
        f"physical_dup={skipped_physical_dup}"
    )
    return signals


# ============================================================
# PRICE STREAM
# ============================================================
async def price_stream():
    """REST-поллинг цены. WebSocket для MEXC futures в ccxt.pro нестабилен
    (лезет в spot API при инициализации) — используем только REST."""
    await _price_rest_poll()


async def _price_rest_poll():
    """REST-поллинг цен всех активных пар каждые 4с."""
    logger.info("REST price poll: запущен (10 пар)")
    keys = list(ACTIVE_SYMBOL_KEYS)
    i = 0
    while True:
        # за цикл обновляем все пары, по 1 тикеру за итерацию пачки
        batch = keys[i:i + 5] or keys[:5]
        i = (i + 5) % len(keys)
        for sk in batch:
            p = await _get_price_rest(sk)
            if p:
                slot = _price_slot(sk)
                slot["last"] = p
                slot["ts"] = time.time()
        await asyncio.sleep(2)


async def price_stale_watchdog():
    """
    Алерт если цена не обновлялась дольше порога.
    Максимум одно сообщение в Telegram в 5 минут чтобы не спамить.
    """
    last_alert = 0.0
    ALERT_INTERVAL = 300   # секунд между Telegram-алертами

    while True:
        await asyncio.sleep(CONFIG["price_stale_s"])
        ages = []
        for sk in ACTIVE_SYMBOL_KEYS:
            slot = _price_slot(sk)
            if slot["ts"]:
                ages.append(time.time() - slot["ts"])
        age = max(ages) if ages else 999.0

        if age > CONFIG["price_stale_s"] * 3:   # алерт только после 30с
            logger.warning(f"Цена устарела {age:.0f}с")
            now_ts = time.time()
            if (
                state.tasks_live.is_set()
                and now_ts - last_alert >= ALERT_INTERVAL
            ):
                await send_telegram(
                    f"⚠️ Цены устарели {age:.0f}с — проблема с подключением Bybit"
                )
                last_alert = now_ts


_price_rest_errors = 0

async def _get_price_rest(symbol_key: Optional[str] = None) -> Optional[float]:
    global _price_rest_errors
    try:
        loop = asyncio.get_event_loop()
        sym = symbol_profile(symbol_key)["symbol"]
        ticker = await loop.run_in_executor(None, lambda s=sym: exchange.fetch_ticker(s))
        _price_rest_errors = 0
        return float(ticker["last"])
    except Exception as e:
        _price_rest_errors += 1
        lvl = logging.WARNING if _price_rest_errors <= 3 else logging.ERROR
        logger.log(lvl, f"REST price ошибка #{_price_rest_errors}: {e}")
        return None


def get_price(symbol_key: Optional[str] = None) -> Optional[float]:
    slot = _price_slot(symbol_key)
    if slot["last"] is None:
        return None
    if time.time() - slot["ts"] > CONFIG["price_stale_s"] * 3:
        return None
    return slot["last"]


# ============================================================
# ОРДЕРА
# ============================================================
def _order_params(direction: str, reduce_only: bool) -> dict:
    params = {"positionIdx": _position_idx(direction)}
    if reduce_only:
        params["reduceOnly"] = True
    return params


def _mexc_entry_external_oid(pl: "PendingLimit") -> str:
    """Идемпотентный ключ для входного ордера (MEXC max 32 символа)."""
    seed = f"ENTRY|{pl.id}|{pl.trade_num}|{pl.created_at}"
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


def _close_side_for(direction: str) -> str:
    """Сторона ордера для закрытия позиции (reduceOnly)."""
    return "sell" if direction == "LONG" else "buy"


async def set_leverage(symbol_key: Optional[str] = None):
    if state.paper:
        if _hedge_mode_config():
            state.exchange_hedge_mode = True
        return
    sym = symbol_profile(symbol_key)["symbol"]
    loop = asyncio.get_event_loop()
    want_hedge = _hedge_mode_config()
    try:
        await loop.run_in_executor(
            None, lambda h=want_hedge: exchange.set_position_mode(h, sym)
        )
    except Exception as e:
        logger.warning(f"set_position_mode: {e}")
    try:
        mode = await loop.run_in_executor(
            None, lambda: exchange.fetch_position_mode(sym)
        )
        hedged = bool((mode or {}).get("hedged"))
        state.exchange_hedge_mode = hedged
        label = "Hedge" if hedged else "One-Way"
        logger.info(f"Position mode: {label} ({sym})")
        if want_hedge and not hedged:
            logger.error(
                f"hedge_mode=True, но биржа в One-Way ({sym}). "
                "Закрой все позиции/ордера и перезапусти, или выключи hedge_mode."
            )
    except Exception as e:
        logger.warning(f"fetch_position_mode: {e}")
        state.exchange_hedge_mode = False
    try:
        await loop.run_in_executor(
            None, lambda: exchange.set_margin_mode("isolated", sym)
        )
        logger.info(f"Margin mode isolated ({sym})")
    except Exception as e:
        logger.warning(f"set_margin_mode isolated: {e}")
    try:
        await loop.run_in_executor(
            None,
            lambda: exchange.set_leverage(
                CONFIG["leverage"],
                sym,
                {
                    "buyLeverage": str(CONFIG["leverage"]),
                    "sellLeverage": str(CONFIG["leverage"]),
                },
            ),
        )
        logger.info(f"Плечо {CONFIG['leverage']}x isolated ({sym})")
    except Exception as e:
        logger.warning(f"set_leverage: {e}")


async def set_leverage_all():
    if state.paper:
        return
    for sk in ACTIVE_SYMBOL_KEYS:
        await set_leverage(sk)


async def get_balance() -> float:
    if state.paper:
        return state.paper_balance
    det = await get_balance_details()
    if det.get("equity") is not None:
        return float(det["equity"])
    if det.get("total") is not None:
        return float(det["total"])
    return float(det.get("free") or 0.0)


def _parse_mexc_usdt_balance(bal: dict) -> dict:
    """USDT equity / available — Bybit unified или ccxt-поля."""
    def _f(x) -> Optional[float]:
        try:
            if x is None or x == "":
                return None
            return float(x)
        except (TypeError, ValueError):
            return None

    free = _f((bal.get("free") or {}).get("USDT")) or _f((bal.get("USDT") or {}).get("free"))
    wallet_total = _f((bal.get("total") or {}).get("USDT")) or _f((bal.get("USDT") or {}).get("total"))
    equity = unrealized = margin = None
    info = bal.get("info") or {}
    result = info.get("result") if isinstance(info.get("result"), dict) else {}
    rows = result.get("list") if isinstance(result, dict) else None
    if isinstance(rows, list):
        for acc in rows:
            coins = acc.get("coin") if isinstance(acc, dict) else None
            if not isinstance(coins, list):
                continue
            for row in coins:
                if str(row.get("coin") or "").upper() != "USDT":
                    continue
                equity = _f(row.get("equity") or row.get("walletBalance"))
                unrealized = _f(row.get("unrealisedPnl") or row.get("unrealizedPnl"))
                margin = _f(row.get("totalPositionIM") or row.get("positionMargin"))
                avail = _f(row.get("availableToWithdraw") or row.get("availableBalance") or row.get("walletBalance"))
                if avail is not None:
                    free = avail
                break
    return {
        "free": free,
        "available": free,
        "total": equity if equity is not None else wallet_total,
        "equity": equity,
        "unrealized": unrealized,
        "margin": margin,
    }


async def get_balance_details() -> dict:
    """free=доступно, total/equity=общий баланс фьючерсного счёта (с uPnL)."""
    if state.paper:
        return {
            "free": state.paper_balance,
            "available": state.paper_balance,
            "total": state.paper_balance,
            "equity": state.paper_balance,
            "unrealized": 0.0,
            "margin": 0.0,
        }
    loop = asyncio.get_event_loop()
    try:
        bal = await loop.run_in_executor(None, exchange.fetch_balance)
        return _parse_mexc_usdt_balance(bal)
    except Exception as e:
        logger.error(f"Баланс details: {e}")
        return {"free": None, "total": None, "equity": None}


def _extract_order_id(order: dict) -> str:
    """Bybit / ccxt: id или info.orderId."""
    if not order:
        return ""
    raw = order.get("id")
    if raw not in (None, ""):
        if isinstance(raw, str) and raw.startswith("{"):
            try:
                import ast
                d = ast.literal_eval(raw)
                oid = d.get("orderId") or d.get("orderLinkId") or ""
                if oid:
                    return str(oid)
            except Exception:
                pass
        return str(raw)
    info = order.get("info") or {}
    oid = info.get("orderId") or info.get("orderLinkId")
    return str(oid) if oid else ""


def _plain_limit_crosses_market(direction: str, entry_price: float, price_now: float) -> bool:
    """Обычный limit исполнится сразу по рынку (taker), а не по цене заявки."""
    if price_now <= 0 or entry_price <= 0:
        return False
    if direction == "LONG":
        return price_now <= entry_price   # BUY limit: рынок на/ниже цены → немедленный fill
    return price_now >= entry_price       # SELL limit: рынок на/выше цены


def _plan_trigger_active(direction: str, entry: float, price: float) -> bool:
    """Условие триггера planorder уже выполнено → немедленное срабатывание."""
    if price <= 0 or entry <= 0:
        return False
    if direction == "LONG":
        return price >= entry   # triggerType 1: >= entry
    return price <= entry       # triggerType 2: <= entry


def _entry_kind_is_plan(kind: str) -> bool:
    return str(kind or "").upper().startswith("STOP")


def _entry_kind_display(kind: str) -> str:
    """Единый лейбл для TG/логов (legacy STOP-MARKET → STOP-LIMIT)."""
    k = str(kind or "").upper()
    if k == "STOP-MARKET":
        return "STOP-LIMIT"
    return kind or ""


def _bar_reaches_fib1_not_fib2(
    direction: str,
    bar_high: float,
    bar_low: float,
    fib1: float,
    fib2: float,
    eps: float = 1e-8,
) -> bool:
    """5m бар подтверждения свипа: коснулся fib 1.0x, но не fib 2.0x."""
    if any(v is None or v != v or v <= 0 for v in (fib1, fib2)):
        return False
    if direction == "SHORT":
        if fib2 >= fib1:
            return False
        return (
            float(bar_low) <= float(fib1) + eps
            and float(bar_low) > float(fib2) + eps
        )
    if direction == "LONG":
        if fib2 <= fib1:
            return False
        return (
            float(bar_high) >= float(fib1) - eps
            and float(bar_high) < float(fib2) - eps
        )
    return False


def _bar_missed_fib1(
    direction: str,
    bar_high: float,
    bar_low: float,
    fib1: float,
    eps: float = 1e-8,
) -> bool:
    """5m confirm-бар не дошёл до fib 1.0x."""
    if fib1 is None or fib1 != fib1 or fib1 <= 0:
        return False
    if direction == "SHORT":
        return float(bar_low) > float(fib1) + eps
    if direction == "LONG":
        return float(bar_high) < float(fib1) - eps
    return False


def _bar_confirm_past_cisd(
    direction: str,
    bar_close: float,
    cisd_level: float,
    eps: float = 1e-8,
) -> bool:
    """Close 5m confirm-бара уже за CISD (ретест к CISD маловероятен)."""
    if bar_close <= 0 or cisd_level <= 0:
        return False
    if direction == "LONG":
        return float(bar_close) >= float(cisd_level) - eps
    return float(bar_close) <= float(cisd_level) + eps


def _confirm_bar_for_retest_market(
    df: pd.DataFrame,
    sweep5m_idx: int,
) -> tuple[float, float, float, str]:
    """5m close-свип бар для MARKET-check при retest_geom."""
    row = df.iloc[int(sweep5m_idx)]
    return (
        float(row["high"]),
        float(row["low"]),
        float(row["close"]),
        "5m sweep",
    )


def _detect_fib_stretch_market_entry(
    direction: str,
    retest_geom: bool,
    bar_high: float,
    bar_low: float,
    fib_prices: list,
    *,
    bar_label: str = "confirm",
) -> tuple[bool, str]:
    """
    retest_geom: confirm-бар дошёл до fib1, не до fib2 → MARKET, TP fib 2.5x.
    """
    if not retest_geom or len(fib_prices) < 3:
        return False, ""
    fib1, fib2 = float(fib_prices[0]), float(fib_prices[1])
    if not _bar_reaches_fib1_not_fib2(direction, bar_high, bar_low, fib1, fib2):
        return False, ""
    return True, (
        f"retest_geom {bar_label} H={bar_high:.1f} L={bar_low:.1f}: "
        f"fib1={fib1:.1f} да, fib2={fib2:.1f} нет → MARKET, TP fib2.5={float(fib_prices[2]):.1f}"
    )


def _detect_retest_geom_market_entry(
    direction: str,
    retest_geom: bool,
    bar_high: float,
    bar_low: float,
    bar_close: float,
    cisd_level: float,
    fib_prices: list,
    *,
    bar_label: str = "confirm",
) -> tuple[bool, str]:
    """
    sweep выше/ниже CISD: CISD уже пройден на confirm, fib1 не достигнут → MARKET, TP fib 2.0x.
    """
    if not retest_geom or len(fib_prices) < 2:
        return False, ""
    fib1 = float(fib_prices[0])
    fib2 = float(fib_prices[1])
    if not _bar_confirm_past_cisd(direction, bar_close, cisd_level):
        return False, ""
    if not _bar_missed_fib1(direction, bar_high, bar_low, fib1):
        return False, ""
    return True, (
        f"retest_geom {bar_label} C={bar_close:.1f} {'≥' if direction == 'LONG' else '≤'} "
        f"cisd={cisd_level:.1f}, H={bar_high:.1f} L={bar_low:.1f}: "
        f"fib1={fib1:.1f} нет → MARKET, TP fib2={fib2:.1f}"
    )


def _detect_post_cisd_no_fib1_market_entry(
    direction: str,
    retest_geom: bool,
    bar_high: float,
    bar_low: float,
    bar_close: float,
    cisd_level: float,
    fib_prices: list,
    *,
    bar_label: str = "confirm",
) -> tuple[bool, str]:
    """Alias для совместимости."""
    return _detect_retest_geom_market_entry(
        direction, retest_geom, bar_high, bar_low, bar_close, cisd_level, fib_prices,
        bar_label=bar_label,
    )


def _resolve_retest_geom_fib_market(
    direction: str,
    retest_geom: bool,
    mss_ok: bool,
    df: pd.DataFrame,
    sweep_close_idx: int,
    cisd_level: float,
    fib_prices: list,
    tp_default: float,
    *,
    series_start_idx: int | None = None,
) -> tuple[float, bool, str, str]:
    """v6: TP всегда 1R, fib-stretch MARKET выключен. Сигнатура сохранена."""
    _ = (direction, retest_geom, mss_ok, df, sweep_close_idx, cisd_level,
         fib_prices, series_start_idx)
    return float(tp_default), False, "", ""


def _sig_sweep_fib1_stretched(sig: dict) -> tuple[bool, str]:
    """Свип↔CISD растянут ≥ плечо CISD→fib 1.0x — пропуск (риск/геометрия)."""
    cisd = float(sig.get("cisd_level") or sig.get("entry") or 0)
    sweep = _safe_float(sig.get("htf_sweep_level"))
    fib1 = _safe_float(sig.get("fib_1x"))
    direction = str(sig.get("direction") or "")
    if cisd <= 0 or sweep is None or sweep <= 0 or fib1 is None or fib1 <= 0:
        return False, ""

    if direction == "LONG":
        gap = cisd - sweep
        arm = fib1 - cisd
        if gap <= 0 or arm <= 0:
            return False, ""
        if gap >= arm:
            return True, (
                f"LONG stretch: sweep→cisd {gap:.1f} ≥ fib1-arm {arm:.1f} "
                f"(sweep={sweep:.1f} cisd={cisd:.1f} fib1={fib1:.1f})"
            )
    elif direction == "SHORT":
        gap = sweep - cisd
        arm = cisd - fib1
        if gap <= 0 or arm <= 0:
            return False, ""
        if gap >= arm:
            return True, (
                f"SHORT stretch: sweep→cisd {gap:.1f} ≥ fib1-arm {arm:.1f} "
                f"(sweep={sweep:.1f} cisd={cisd:.1f} fib1={fib1:.1f})"
            )
    return False, ""


def _resolve_entry_order_kind(
    direction: str,
    entry_price: float,
    price_ref: float,
    *,
    cisd_level: float = 0.0,
    sweep_level: float = 0.0,
    force_market: bool = False,
    force_limit_retest: bool = False,
) -> tuple[str, dict, float]:
    """v6: только LIMIT на cisd_level (без MARKET и STOP-LIMIT входа)."""
    del force_market, force_limit_retest, sweep_level, price_ref, direction
    cisd = _cisd_limit_price(entry_price, cisd_level)
    return "LIMIT", {}, cisd


def _trade_signal_category(
    entry_kind: str = "",
    *,
    pos_id: str = "",
    exit_reason: str = "",
) -> str:
    """normal — MARKET (cross) / STOP-LIMIT (ждём пробой); limit_retest — LIMIT откат."""
    if pos_id.startswith("X") or exit_reason in ("closed_sync", "closed_manual"):
        return "abnormal"
    if entry_kind == "MARKET":
        return "normal"
    if entry_kind == "LIMIT":
        return "limit_retest"
    return "normal"


def _pending_entry_kind(pl: "PendingLimit") -> str:
    if pl.entry_kind:
        return pl.entry_kind
    if getattr(pl, "force_limit_retest", False):
        return "LIMIT"
    if getattr(pl, "force_market", False):
        return "MARKET"
    px_ref = _pending_entry_price_ref(pl)
    cisd = pl.cisd_level or pl.entry_price
    kind, _, _ = _resolve_entry_order_kind(
        pl.direction, pl.entry_price, px_ref,
        cisd_level=cisd, sweep_level=float(pl.sweep_level or 0),
        force_market=bool(getattr(pl, "force_market", False)),
        force_limit_retest=bool(getattr(pl, "force_limit_retest", False)),
    )
    return kind


def _trade_log_path_for(dt: datetime) -> str:
    return os.path.join(TRADE_LOG_DIR, f"trades_{dt.strftime('%Y-%m')}.jsonl")


def _maybe_archive_previous_trade_log(now: datetime) -> None:
    global _trade_log_month
    cur = now.strftime("%Y-%m")
    if _trade_log_month and _trade_log_month != cur:
        prev_path = _trade_log_path_for(
            datetime.strptime(f"{_trade_log_month}-01", "%Y-%m-%d")
        )
        if os.path.isfile(prev_path):
            os.makedirs(TRADE_LOG_ARCHIVE_DIR, exist_ok=True)
            arc_path = os.path.join(
                TRADE_LOG_ARCHIVE_DIR, f"trades_{_trade_log_month}.jsonl.gz"
            )
            if not os.path.isfile(arc_path):
                with open(prev_path, "rb") as f_in, gzip.open(arc_path, "wb") as f_out:
                    f_out.writelines(f_in)
                logger.info(f"Trade log archived → {arc_path}")
    _trade_log_month = cur


def _append_trade_journal(record: dict) -> None:
    os.makedirs(TRADE_LOG_DIR, exist_ok=True)
    now = utcnow()
    _maybe_archive_previous_trade_log(now)
    record.setdefault("logged_at", now.isoformat())
    path = _trade_log_path_for(now)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _pending_journal_record(pl: "PendingLimit", event: str, **extra) -> dict:
    entry_kind = _pending_entry_kind(pl)
    cat = extra.pop("category", _trade_signal_category(entry_kind))
    rec = {
        "event": event,
        "category": cat,
        "mode": _mode_tag(),
        "id": pl.id,
        "trade_num": pl.trade_num,
        "tf": pl.tf,
        "symbol": _pos_symbol_key(pl),
        "direction": pl.direction,
        "signal_time": getattr(pl, "confirm_bar_time", "") or pl.htf_time or None,
        "htf_time": pl.htf_time or None,
        "vwap_dev": float(getattr(pl, "vwap_dev", 0) or 0),
        "pending_created_at": pl.created_at.isoformat(),
        "pending_timeout_at": pl.timeout_at.isoformat(),
        "position_timeout_at": (
            (pl.created_at + timedelta(hours=pl.exit_h)).isoformat()
            if pl.created_at else None
        ),
        "position_timeout_h": pl.exit_h,
        "signal_entry": pl.entry_price,
        "stop": pl.stop_price,
        "tp": pl.tp_price,
        "contracts": pl.contracts,
        "entry_kind": entry_kind,
        "price_at_creation": pl.price_at_creation or None,
        "cisd_level": pl.cisd_level or None,
        "sweep_level": pl.sweep_level,
        "fib_1x": pl.fib_1x,
        "confirm_on_sweep": pl.confirm_on_sweep,
        "sig_hash": pl.sig_hash or None,
        "order_id": pl.order_id,
        "defer_entry": pl.defer_entry,
        "quality_score": pl.quality_score,
        "quality_stop_original": pl.quality_stop_original,
        "quality_stop_mult": pl.quality_stop_mult,
        "quality_stop_model": pl.quality_stop_model or None,
    }
    if pl.trigger_bar_at:
        rec["trigger_bar_at"] = pl.trigger_bar_at.isoformat()
    rec.update(extra)
    return rec


def _position_journal_record(pos: Position, event: str = "closed", **extra) -> dict:
    exit_reason = extra.get("exit_reason") or pos.status
    entry_kind = pos.entry_kind or ""
    cat = extra.pop(
        "category",
        pos.signal_category or _trade_signal_category(
            entry_kind, pos_id=pos.id, exit_reason=exit_reason,
        ),
    )
    rec = {
        "event": event,
        "category": cat,
        "mode": _mode_tag(),
        "id": pos.id,
        "trade_num": pos.trade_num,
        "tf": pos.tf,
        "symbol": _pos_symbol_key(pos),
        "direction": pos.direction,
        "signal_time": getattr(pos, "confirm_bar_time", "") or pos.htf_time or None,
        "htf_time": pos.htf_time or None,
        "vwap_dev": float(getattr(pos, "vwap_dev", 0) or 0),
        "pending_created_at": (
            pos.pending_created_at.isoformat() if pos.pending_created_at else None
        ),
        "entry_time": pos.entry_time.isoformat(),
        "position_timeout_at": pos.exit_time.isoformat(),
        "exit_time": extra.get("exit_time") or utcnow().isoformat(),
        "signal_entry": pos.signal_entry if pos.signal_entry is not None else pos.entry_price,
        "entry_price": pos.entry_price,
        "close_price": pos.close_price,
        "stop": pos.stop_price,
        "tp": pos.tp_price,
        "contracts": pos.contracts,
        "pnl": pos.pnl,
        "fees": pos.fees,
        "pnl_net": pos.pnl_net,
        "exit_reason": exit_reason,
        "entry_kind": entry_kind or None,
        "price_at_creation": pos.price_at_creation or None,
        "cisd_level": pos.cisd_level or None,
        "sweep_level": pos.sweep_level,
        "fib_1x": pos.fib_1x,
        "confirm_on_sweep": pos.confirm_on_sweep,
        "sig_hash": pos.sig_hash or None,
        "quality_score": pos.quality_score,
        "quality_stop_original": pos.quality_stop_original,
        "quality_stop_mult": pos.quality_stop_mult,
        "quality_stop_model": pos.quality_stop_model or None,
    }
    rec.update(extra)
    return rec


def _copy_pending_meta_to_position(pl: "PendingLimit", pos: Position) -> None:
    entry_kind = _pending_entry_kind(pl)
    pos.entry_kind = entry_kind
    pos.signal_category = _trade_signal_category(entry_kind)
    pos.signal_entry = pl.entry_price
    pos.price_at_creation = pl.price_at_creation
    pos.cisd_level = pl.cisd_level
    pos.sweep_level = pl.sweep_level
    pos.fib_1x = pl.fib_1x
    pos.confirm_on_sweep = pl.confirm_on_sweep
    pos.htf_time = pl.htf_time
    pos.sig_hash = pl.sig_hash
    pos.pending_created_at = pl.created_at
    pos.symbol_key = _pos_symbol_key(pl)
    pos.quality_score = pl.quality_score
    pos.quality_stop_original = pl.quality_stop_original
    pos.quality_stop_mult = pl.quality_stop_mult
    pos.quality_stop_model = pl.quality_stop_model
    pos.vwap_dev = float(getattr(pl, "vwap_dev", 0) or 0)
    pos.confirm_bar_time = str(getattr(pl, "confirm_bar_time", "") or "")


def _journal_log_pending(pl: "PendingLimit", event: str, **extra) -> None:
    try:
        _append_trade_journal(_pending_journal_record(pl, event, **extra))
    except Exception as e:
        logger.error(f"trade_journal: {e}")


def _journal_log_pending_cancelled(pl: "PendingLimit") -> None:
    if pl.status in ("pending", "filled"):
        return
    _journal_log_pending(
        pl, "pending_cancelled",
        cancel_reason=pl.status,
        cancelled_at=utcnow().isoformat(),
    )
    # Cancel без позиции → снять one-shot HTF lock (можно взять сетап снова).
    _clear_htf_taken_if_idle(pl)


def _journal_log_signal_skipped(
    sig: dict, tf_name: str, skip_reason: str, category: str,
) -> None:
    try:
        _append_trade_journal({
            "event": "signal_skipped",
            "category": category,
            "mode": _mode_tag(),
            "tf": tf_name,
            "direction": sig.get("direction"),
            "signal_time": sig.get("htf_time"),
            "signal_entry": sig.get("entry"),
            "stop": sig.get("stop"),
            "tp": sig.get("tp"),
            "cisd_level": sig.get("cisd_level"),
            "sweep_level": sig.get("htf_sweep_level"),
            "fib_1x": sig.get("fib_1x"),
            "skip_reason": skip_reason,
            "sig_hash": sig.get("hash"),
        })
    except Exception as e:
        logger.error(f"trade_journal skip: {e}")


def _journal_on_trade_closed(pos: Position) -> None:
    try:
        _append_trade_journal(_position_journal_record(pos, event="closed"))
    except Exception as e:
        logger.error(f"trade_journal close: {e}")


def _should_defer_entry(
    direction: str, entry_kind: str, entry: float, price: float,
    *, cisd_level: float = 0.0,
) -> bool:
    """Не ставим ордер, пока plan/taker сработает не так, как задумано."""
    cisd = _cisd_limit_price(entry, cisd_level)
    if (entry_kind or "").upper() == "LIMIT" and _is_retrace_at_creation(direction, cisd, price):
        return False
    if entry_kind == "MARKET":
        return False
    if entry_kind == "LIMIT":
        return _plain_limit_crosses_market(direction, entry, price)
    if _entry_kind_is_plan(entry_kind):
        return _plan_trigger_active(direction, entry, price)
    return False


async def place_entry_order(direction: str, entry_price: float,
                           stop_price: float, tp_price: float,
                           contracts: int,
                           price_at_creation: float = 0.0,
                           cisd_level: float = 0.0,
                           sweep_level: float = 0.0,
                           force_market: bool = False,
                           force_limit_retest: bool = False,
                           *,
                           external_oid: Optional[str] = None,
                           symbol_key: Optional[str] = None) -> Optional[dict]:
    if state.paper:
        logger.error("place_entry_order: SHADOW — ордера на биржу запрещены")
        return None
    sk = symbol_key or active_symbol_key()
    side      = "buy" if direction == "LONG" else "sell"
    params    = _order_params(direction, False)
    if external_oid:
        params.setdefault("clientOrderId", external_oid)
        params.setdefault("orderLinkId", external_oid)
    cisd = _cisd_limit_price(entry_price, cisd_level or entry_price)
    limit_px = _round_price(cisd, sk)
    params.setdefault("timeInForce", "PostOnly")
    qty = _qty_ex(contracts, sk)
    loop = asyncio.get_event_loop()
    sym = symbol_profile(sk)["symbol"]
    for attempt in range(3):
        try:
            order = await loop.run_in_executor(
                None,
                lambda p=params, s=side, c=qty, lp=limit_px, sy=sym: exchange.create_order(
                    sy, "limit", s, c, lp, p
                ),
            )
            oid = _extract_order_id(order)
            logger.info(
                f"LIMIT {direction} {side} {contracts}@{limit_px} "
                f"stop={stop_price} tp={tp_price} {sk} → {oid}"
            )
            return order
        except Exception as e:
            logger.error(f"entry_order attempt {attempt + 1}: {e}")
            await asyncio.sleep(2 ** (attempt + 1))
    return None


async def place_mexc_plan_order(
    direction: str,
    side: str,
    contracts: int,
    trigger_price: float,
    *,
    trigger_type: int,
    order_type_mexc: int,
    limit_price: Optional[float] = None,
    label: str = "PLAN",
) -> Optional[dict]:
    """Условный planorder (legacy; вход STOP-LIMIT).

    trigger_type: 1 = цена >= trigger, 2 = цена <= trigger
    order_type_mexc: 1 = limit, 5 = market
    """
    qty = _qty_ex(contracts)
    loop = asyncio.get_event_loop()
    params = _order_params(direction, reduce_only=True)
    params["triggerPrice"] = trigger_price
    params["triggerDirection"] = trigger_type

    ccxt_type = "limit" if order_type_mexc == 1 else "market"
    price = limit_price if order_type_mexc == 1 else None

    for attempt in range(3):
        try:
            order = await loop.run_in_executor(
                None,
                lambda p=params, t=ccxt_type, s=side, c=qty, pr=price, sym=active_symbol(): exchange.create_order(
                    sym, t, s, c, pr, p
                ),
            )
            oid = _extract_order_id(order)
            logger.info(
                f"PLAN-{label} {direction} {side} {contracts} trigger={trigger_price:.1f} "
                f"type={trigger_type} orderType={order_type_mexc} → {oid}"
            )
            return order
        except Exception as e:
            logger.error(f"plan_order attempt {attempt + 1}: {e}")
            await asyncio.sleep(2 ** (attempt + 1))
    return None


async def _adopt_exchange_protection_by_price(pos: "Position") -> bool:
    """Подхват SL/TP по направлению и цене — не дублировать plan на одну ногу."""
    if pos.status != "open" or state.paper:
        return False
    rows, api_ok = await _list_mexc_planorders_tracked(states="1", page_size=100)
    if api_ok is False:
        return False
    adopted = False
    known = {
        str(oid) for oid in (pos.stop_order_id, pos.tp_order_id) if oid
    }
    for row in rows:
        oid = _planorder_row_id(row)
        if not oid or oid in known:
            continue
        otype = _planorder_row_order_type(row)
        if (
            pos.stop_price > 0
            and not pos.stop_order_id
            and otype == 5
            and _planorder_row_matches_direction_price(
                row, pos.direction, pos.stop_price, order_type_mexc=5,
            )
        ):
            pos.stop_order_id = oid
            adopted = True
            known.add(oid)
        elif (
            pos.tp_price > 0
            and not pos.tp_order_id
            and otype == 1
            and _planorder_row_matches_direction_price(
                row, pos.direction, pos.tp_price, order_type_mexc=1,
            )
        ):
            pos.tp_order_id = oid
            adopted = True
            known.add(oid)
    if adopted:
        logger.info(
            f"#{pos.trade_num} {pos.direction}: подхват SL/TP по цене "
            f"SL={pos.stop_order_id or '-'} TP={pos.tp_order_id or '-'}"
        )
    return adopted


async def place_sl_tp_for_position(pos: "Position") -> tuple[bool, bool]:
    """SL+TP через stoporder/place (как в UI MEXC): market SL + limit TP."""
    if state.paper:
        return True, True

    if pos.stop_price > 0:
        pos.stop_price = _round_protection_price(pos.stop_price, _pos_symbol_key(pos))
    if pos.tp_price > 0:
        pos.tp_price = _round_protection_price(pos.tp_price, _pos_symbol_key(pos))

    await _adopt_exchange_stoporder_tpsl(pos)
    if not pos.tpsl_order_id:
        await _adopt_exchange_protection_by_price(pos)
        await _adopt_exchange_protection_orders(pos)

    sl_ok = tp_ok = False

    if pos.tpsl_order_id:
        info = await _get_stoporder_status(pos.tpsl_order_id)
        if info and _stoporder_protection_is_active(info):
            row = info.get("info") or {}
            await _apply_exchange_protection_prices(pos, row, notify=True)
            sl_ok, tp_ok = await _stoporder_protection_ok(pos)
            if sl_ok and tp_ok:
                return sl_ok, tp_ok
        elif info and _stoporder_is_executed(info):
            return True, True
        else:
            pos.tpsl_order_id = None
            sl_ok = tp_ok = False

    # Legacy: старые plan SL/TP (до миграции)
    if pos.stop_order_id and not pos.tpsl_order_id:
        info = await get_order_status(pos.stop_order_id)
        if info is None or _protection_order_is_active(info) or _order_is_filled(info):
            sl_ok = True
        else:
            pos.stop_order_id = None
    if pos.tp_order_id and not pos.tpsl_order_id:
        info = await get_order_status(pos.tp_order_id)
        if info is None or _protection_order_is_active(info) or _order_is_filled(info):
            tp_ok = True
        else:
            pos.tp_order_id = None
    if sl_ok and tp_ok and (pos.stop_order_id or pos.tp_order_id):
        return sl_ok, tp_ok

    if not pos.exchange_position_id:
        await _backfill_exchange_position_id(pos)
    if not pos.exchange_position_id:
        pos.exchange_position_id = _synthetic_position_id(
            _pos_symbol_key(pos), pos.direction
        )
        logger.info(
            f"#{pos.trade_num} {pos.direction}: synthetic positionId "
            f"{pos.exchange_position_id}"
        )

    await _cancel_legacy_plan_protection(pos)

    need_sl = pos.stop_price > 0 and not sl_ok
    need_tp = pos.tp_price > 0 and not tp_ok
    if not need_sl and not need_tp:
        return sl_ok, tp_ok

    return await _ensure_stoporder_sl_tp(pos)


async def _cancel_legacy_plan_protection(pos: "Position") -> None:
    """Снять старые plan SL/TP перед stoporder/place."""
    if pos.stop_order_id:
        await cancel_order(pos.stop_order_id, _pos_symbol_key(pos))
        pos.stop_order_id = None
    if pos.tp_order_id:
        await cancel_order(pos.tp_order_id, _pos_symbol_key(pos))
        pos.tp_order_id = None
    targets: list[float] = []
    if pos.stop_price > 0:
        targets.append(pos.stop_price)
    if pos.tp_price > 0:
        targets.append(pos.tp_price)
    if not targets:
        return
    skip_ids = _other_open_protection_order_ids(pos)
    rows, _ = await _list_mexc_planorders_tracked(states="1", page_size=100)
    for row in rows:
        oid = _planorder_row_id(row)
        if not oid or oid in skip_ids:
            continue
        if not _planorder_row_matches_position(row, pos):
            continue
        trig = _planorder_row_price(row)
        if trig is None:
            continue
        if not any(abs(trig - t) / max(t, 1.0) <= 0.0008 for t in targets):
            continue
        await _cancel_mexc_planorder(oid)


async def _mexc_find_position_meta(
    direction: str,
    position_id: Optional[str] = None,
    symbol_key: Optional[str] = None,
) -> dict:
    """positionId + openType (1=isolated, 2=cross margin; не open/close — close = side 2/4)."""
    try:
        loop = asyncio.get_event_loop()
        sym_ccxt = symbol_profile(symbol_key)["symbol"]
        raw = await loop.run_in_executor(
            None, lambda: _fetch_positions_linear([sym_ccxt]),
        )
    except Exception:
        raw = None
    best: dict = {}
    for p in raw or []:
        side = str(p.get("side") or "").upper()
        if side != direction:
            continue
        info = p.get("info") or {}
        pid = _exchange_position_id_from_raw(p)
        if position_id is not None and str(pid) != str(position_id):
            continue
        open_type = info.get("tradeMode") or info.get("openType") or info.get("open_type")
        best = {
            "positionId": pid,
            "openType": open_type,
            "info": info,
        }
        if position_id is not None:
            return best
        break
    return best


async def mexc_close_position_market(
    direction: str,
    contracts: int,
    *,
    price_hint: Optional[float] = None,
    position_id: Optional[str] = None,
    symbol_key: Optional[str] = None,
) -> Optional[dict]:
    """Close Bybit linear: reduceOnly market + positionIdx."""
    if state.paper:
        return None
    sym_key = symbol_key or active_symbol_key()
    sym = symbol_profile(sym_key)["symbol"]
    qty = _qty_ex(contracts, sym_key)
    side = _close_side_for(direction)
    params = _order_params(direction, True)
    loop = asyncio.get_event_loop()
    try:
        resp = await loop.run_in_executor(
            None,
            lambda: exchange.create_market_order(sym, side, qty, None, params),
        )
        logger.info(
            f"BYBIT CLOSE {direction} qty={qty} idx={params.get('positionIdx')} "
            f"pid={position_id} → {_extract_order_id(resp)}"
        )
        return resp
    except Exception as e:
        logger.error(f"mexc_close_position_market: {e}")
        return None


def _mexc_market_id(symbol_key: Optional[str] = None) -> str:
    return exchange.market(symbol_profile(symbol_key)["symbol"])["id"]


def _extract_stoporder_id(resp: Optional[dict]) -> Optional[str]:
    if not resp or not (resp.get("success") is True or resp.get("code") == 0):
        return None
    data = resp.get("data")
    if data is None:
        return None
    if isinstance(data, (str, int)):
        return str(data)
    if isinstance(data, dict):
        oid = data.get("id") or data.get("orderId")
        return str(oid) if oid is not None else None
    if isinstance(data, list) and data:
        oid = data[0].get("id") or data[0].get("orderId")
        return str(oid) if oid is not None else None
    return None


def _stoporder_row_status(row: dict) -> str:
    """MEXC stoporder state: 1=active, 2=cancelled, 3=executed."""
    try:
        st = int(row.get("state") or 0)
    except (TypeError, ValueError):
        return "unknown"
    if st == 1:
        return "open"
    if st == 2:
        return "cancelled"
    if st == 3:
        return "closed"
    return "unknown"


def _stoporder_row_to_info(row: dict) -> dict:
    return {
        "id": str(row.get("id") or ""),
        "status": _stoporder_row_status(row),
        "info": row,
        "_src": "stoporder",
    }


def _stoporder_is_executed(info: Optional[dict]) -> bool:
    if not info:
        return False
    row = info.get("info") if isinstance(info.get("info"), dict) else {}
    try:
        return int(row.get("state") or 0) == 3
    except (TypeError, ValueError):
        return str(info.get("status") or "").lower() == "closed"


def _stoporder_protection_is_active(info: Optional[dict]) -> bool:
    if not info:
        return False
    return str(info.get("status") or "").lower() in ("open", "new", "pending")


def _round_protection_price(px: float, symbol_key: Optional[str] = None) -> float:
    """Округление SL/TP под tick MEXC для активной или указанной пары."""
    return _round_price(px, symbol_key)


def _stoporder_tp_price(row: dict) -> float:
    try:
        return float(
            row.get("takeProfitOrderPrice") or row.get("takeProfitPrice") or 0
        )
    except (TypeError, ValueError):
        return 0.0


def _stoporder_sl_price(row: dict) -> float:
    try:
        return float(
            row.get("stopLossOrderPrice") or row.get("stopLossPrice") or 0
        )
    except (TypeError, ValueError):
        return 0.0


def _stoporder_has_sl(row: dict) -> bool:
    return _stoporder_sl_price(row) > 0


def _stoporder_has_tp(row: dict) -> bool:
    if _stoporder_tp_price(row) > 0:
        return True
    try:
        # MEXC limit-TP (type 1) в list/orders часто без takeProfitOrderPrice
        tpt = int(row.get("takeProfitType") if row.get("takeProfitType") is not None else -1)
    except (TypeError, ValueError):
        return False
    return tpt in (1, 2)  # 1=limit TP, 2=market TP


def _sync_pos_prices_from_stoporder_row(pos: "Position", row: dict) -> tuple[bool, bool]:
    """Подтянуть локальные SL/TP с биржи. True = цена реально сдвинулась."""
    sk = _pos_symbol_key(pos)
    sl_ch = tp_ch = False
    ex_sl = _stoporder_sl_price(row)
    ex_tp = _stoporder_tp_price(row)
    if ex_sl > 0:
        if pos.stop_price <= 0 or not _protection_price_near(pos.stop_price, ex_sl):
            pos.stop_price = _round_protection_price(ex_sl, sk)
            sl_ch = True
    if ex_tp > 0:
        if pos.tp_price <= 0 or not _protection_price_near(pos.tp_price, ex_tp):
            pos.tp_price = _round_protection_price(ex_tp, sk)
            tp_ch = True
    return sl_ch, tp_ch


async def _notify_manual_protection_move(
    pos: "Position",
    *,
    old_sl: float,
    old_tp: float,
    sl_changed: bool,
    tp_changed: bool,
) -> None:
    if not (sl_changed or tp_changed) or state.paper or pos.status != "open":
        return
    now_ts = time.time()
    cooldown = float(CONFIG.get("sl_tp_manual_alert_cooldown_s", 60))
    last = state._sl_tp_manual_alert_ts.get(pos.id, 0.0)
    if now_ts - last < cooldown:
        return
    state._sl_tp_manual_alert_ts[pos.id] = now_ts
    sk = _pos_symbol_key(pos)
    lines = [f"🖐 #{pos.trade_num} {pos.direction}: ручной сдвиг защиты"]
    if sl_changed:
        lines.append(
            f"🛑 SL: {_fmt_px(old_sl, sk)} → {_fmt_px(pos.stop_price, sk)}"
        )
    if tp_changed:
        lines.append(
            f"💰 TP: {_fmt_px(old_tp, sk)} → {_fmt_px(pos.tp_price, sk)}"
        )
    lines.append("(бот принял уровни с биржи, не переставляет)")
    await send_telegram("\n".join(lines))


async def _apply_exchange_protection_prices(
    pos: "Position",
    row: dict,
    *,
    notify: bool = True,
) -> bool:
    """Синк локальных SL/TP с stoporder. True если что-то обновили."""
    old_sl, old_tp = float(pos.stop_price or 0), float(pos.tp_price or 0)
    sl_ch, tp_ch = _sync_pos_prices_from_stoporder_row(pos, row)
    if not (sl_ch or tp_ch):
        return False
    logger.info(
        f"#{pos.trade_num} {pos.direction}: защита с биржи "
        f"SL={old_sl:.4g}→{pos.stop_price:.4g} TP={old_tp:.4g}→{pos.tp_price:.4g}"
    )
    save_positions(state.positions)
    if notify:
        await _notify_manual_protection_move(
            pos,
            old_sl=old_sl,
            old_tp=old_tp,
            sl_changed=sl_ch,
            tp_changed=tp_ch,
        )
    return True


async def _stoporder_protection_ok(pos: "Position") -> tuple[bool, bool]:
    if not pos.tpsl_order_id:
        return False, False
    info = await _get_stoporder_status(pos.tpsl_order_id)
    if not info or not _stoporder_protection_is_active(info):
        return False, False
    row = info.get("info") or {}
    # Есть на бирже = ок (цена может отличаться от локальной — ручной сдвиг)
    sl_ok = pos.stop_price <= 0 or _stoporder_has_sl(row)
    tp_ok = pos.tp_price <= 0 or _stoporder_has_tp(row)
    return sl_ok, tp_ok


async def _mexc_amend_stoporder_tpsl(
    pos: "Position",
    *,
    fill_sl: bool = False,
    fill_tp: bool = False,
) -> bool:
    """Bybit: переставить TPSL через set_trading_stop (обе ноги сразу)."""
    if not fill_sl and not fill_tp:
        return False
    return await _mexc_place_stoporder_tpsl(pos)


async def _wait_stoporder_protection_ok(
    pos: "Position",
    *,
    attempts: int = 4,
    delay_s: float = 0.45,
) -> tuple[bool, bool]:
    """После place list/orders иногда без TP-полей — короткий retry до amend."""
    sl_ok = tp_ok = False
    for i in range(max(1, attempts)):
        sl_ok, tp_ok = await _stoporder_protection_ok(pos)
        if sl_ok and tp_ok:
            return sl_ok, tp_ok
        if i + 1 < attempts:
            await asyncio.sleep(delay_s)
    return sl_ok, tp_ok


async def _ensure_stoporder_sl_tp(pos: "Position") -> tuple[bool, bool]:
    """Place/amend stoporder; вернуть факт SL/TP на бирже (не слепой True).

    Ручные уровни на бирже не перезаписываем: sync local ← exchange,
    amend только если ноги реально нет (и всегда оба поля в body).
    """
    if pos.tpsl_order_id:
        info = await _get_stoporder_status(pos.tpsl_order_id)
        if info and _stoporder_protection_is_active(info):
            row = info.get("info") or {}
            await _apply_exchange_protection_prices(pos, row, notify=True)
            sl_ok = pos.stop_price <= 0 or _stoporder_has_sl(row)
            tp_ok = pos.tp_price <= 0 or _stoporder_has_tp(row)
            if sl_ok and tp_ok:
                return True, True
            fill_sl = pos.stop_price > 0 and not sl_ok
            fill_tp = pos.tp_price > 0 and not tp_ok
            if fill_sl or fill_tp:
                if await _mexc_amend_stoporder_tpsl(
                    pos, fill_sl=fill_sl, fill_tp=fill_tp,
                ):
                    return await _wait_stoporder_protection_ok(pos)
            return sl_ok, tp_ok

    sl_ok, tp_ok = await _stoporder_protection_ok(pos)
    if sl_ok and tp_ok:
        return sl_ok, tp_ok

    if not pos.tpsl_order_id:
        if not await _mexc_place_stoporder_tpsl(pos):
            return sl_ok, tp_ok
        sl_ok, tp_ok = await _wait_stoporder_protection_ok(pos)
        if sl_ok and tp_ok:
            return sl_ok, tp_ok
        fill_sl = pos.stop_price > 0 and not sl_ok
        fill_tp = pos.tp_price > 0 and not tp_ok
        if fill_sl or fill_tp:
            if await _mexc_amend_stoporder_tpsl(pos, fill_sl=fill_sl, fill_tp=fill_tp):
                return await _wait_stoporder_protection_ok(pos)

    sl_ok, tp_ok = await _stoporder_protection_ok(pos)
    if pos.tpsl_order_id and ((pos.stop_price > 0 and not sl_ok) or (pos.tp_price > 0 and not tp_ok)):
        logger.warning(
            f"#{pos.trade_num} {pos.direction}: SL/TP неполные на бирже "
            f"SL={'ok' if sl_ok else 'miss'} TP={'ok' if tp_ok else 'miss'}"
        )
    return sl_ok, tp_ok


def _stoporder_prices_match_pos(row: dict, pos: "Position") -> bool:
    if pos.stop_price <= 0 and pos.tp_price <= 0:
        return False
    sl_ok = tp_ok = True
    if pos.stop_price > 0:
        try:
            sl_ok = _protection_price_near(pos.stop_price, _stoporder_sl_price(row))
        except (TypeError, ValueError):
            sl_ok = False
    if pos.tp_price > 0:
        try:
            tp_ok = _protection_price_near(pos.tp_price, _stoporder_tp_price(row))
        except (TypeError, ValueError):
            tp_ok = False
    return sl_ok and tp_ok


def _stoporder_close_reason_and_price(
    pos: "Position", row: dict, *, fill_price: float = 0.0,
) -> tuple[str, float]:
    """triggerSide: 0=none, 1=TP, 2=SL. Без fill не доверяем triggerSide=1 (MEXC врёт)."""
    live = get_price() or pos.entry_price
    price = fill_price or live
    if fill_price > 0:
        inferred = _infer_close_reason_from_price(pos, fill_price)
        if inferred:
            return inferred, fill_price
        inferred = _infer_close_reason_from_entry(pos, fill_price)
        if inferred:
            return inferred, fill_price
    try:
        trigger = int(row.get("triggerSide") or 0)
    except (TypeError, ValueError):
        trigger = 0
    if trigger == 2:
        if fill_price > 0:
            return "closed_sl", fill_price
        try:
            px = float(row.get("stopLossPrice") or pos.stop_price or price)
        except (TypeError, ValueError):
            px = float(pos.stop_price or price)
        return "closed_sl", px if px > 0 else price
    if trigger == 1:
        # MEXC часто ставит triggerSide=1 и при SL — без fill не берём takeProfitPrice
        if fill_price > 0:
            inferred = _infer_close_reason_from_price(pos, fill_price)
            if inferred:
                return inferred, fill_price
            inferred = _infer_close_reason_from_entry(pos, fill_price)
            if inferred == "closed_sl":
                return "closed_sl", fill_price
            return "closed_tp", fill_price
        inferred = _infer_close_reason_from_price(pos, live) or _infer_close_reason_from_entry(
            pos, live,
        )
        if inferred:
            return inferred, live
        return "closed_sync", live
    place_oid = row.get("placeOrderId")
    if place_oid:
        inferred = _infer_close_reason_from_price(pos, price)
        if inferred:
            return inferred, price
    if pos.stop_price > 0 and pos.tp_price > 0:
        return _infer_close_reason_from_price(pos, price) or "closed_sync", price
    return "closed_sync", price


def _reconcile_close_reason(
    pos: "Position", reason: str, close_price: float,
) -> str:
    """После факта closeAvgPrice/PnL поправить TP↔SL, если биржа соврала в triggerSide."""
    if reason not in ("closed_tp", "closed_sl") or close_price <= 0:
        return reason
    fixed = (
        _infer_close_reason_from_price(pos, close_price)
        or _infer_close_reason_from_entry(pos, close_price)
    )
    if fixed and fixed != reason:
        logger.warning(
            f"close reason corrected #{pos.trade_num} {reason} → {fixed} "
            f"@ {close_price:.4f} (entry={pos.entry_price:.4f} "
            f"sl={pos.stop_price:.4f} tp={pos.tp_price:.4f})"
        )
        return fixed
    return reason


async def _resolve_stoporder_close(
    pos: "Position", row: dict,
) -> tuple[str, float]:
    """Факт fill placeOrderId важнее triggerSide (MEXC иногда triggerSide=1 при SL)."""
    fallback = get_price() or pos.entry_price
    place_oid = row.get("placeOrderId")
    deal: Optional[dict] = None
    px = 0.0
    if place_oid:
        deal = await get_order_status(str(place_oid))
        if deal:
            px = _order_fill_price(deal, 0.0)
    if px > 0:
        reason = _infer_close_reason_from_price(pos, px)
        if reason:
            return reason, px
        row_info = deal.get("info") if isinstance(deal, dict) else {}
        if isinstance(row_info, dict):
            try:
                profit = float(row_info.get("profit") or 0)
                if profit < -1e-9:
                    return "closed_sl", px
                if profit > 1e-9:
                    return "closed_tp", px
            except (TypeError, ValueError):
                pass
    return _stoporder_close_reason_and_price(pos, row, fill_price=px)


async def _list_mexc_stoporders(
    *,
    is_finished: int = 0,
    page_size: int = 100,
    symbol_key: Optional[str] = None,
) -> tuple[list[dict], bool]:
    """Bybit attached TPSL → синтетические stoporder-строки."""
    if int(is_finished) == 1:
        return [], True
    loop = asyncio.get_event_loop()
    sk = symbol_key or active_symbol_key()
    sym = symbol_profile(sk)["symbol"]
    try:
        raw = await loop.run_in_executor(
                    None, lambda: _fetch_positions_linear([sym])
        )
    except Exception as e:
        logger.warning(f"stoporder list: {e}")
        return [], False
    rows: list[dict] = []
    for p in raw or []:
        info = p.get("info") or {}
        sl = info.get("stopLoss") or p.get("stopLossPrice") or p.get("stopLoss")
        tp = info.get("takeProfit") or p.get("takeProfitPrice") or p.get("takeProfit")
        try:
            slf = float(sl) if sl not in (None, "", "0", 0) else 0.0
        except (TypeError, ValueError):
            slf = 0.0
        try:
            tpf = float(tp) if tp not in (None, "", "0", 0) else 0.0
        except (TypeError, ValueError):
            tpf = 0.0
        if slf <= 0 and tpf <= 0:
            continue
        side = (p.get("side") or "").upper()
        if side not in ("LONG", "SHORT"):
            continue
        pid = _exchange_position_id_from_raw(p)
        rows.append({
            "id": _tpsl_synthetic_id(sk, side),
            "state": 1,
            "positionId": pid,
            "stopLossPrice": slf,
            "takeProfitOrderPrice": tpf,
            "vol": _from_ex_qty(p.get("contracts") or info.get("size") or 0, sk),
        })
    return rows, True


async def _get_stoporder_status(order_id: str) -> Optional[dict]:
    for finished in (0, 1):
        rows, ok = await _list_mexc_stoporders_tracked(is_finished=finished)
        if not ok:
            continue
        for row in rows:
            if str(row.get("id") or "") == str(order_id):
                return _stoporder_row_to_info(row)
    return None


async def _cancel_mexc_stoporder(order_id: str) -> bool:
    oid = str(order_id)
    loop = asyncio.get_event_loop()
    for pos in list(state.positions):
        if pos.status != "open":
            continue
        syn = _tpsl_synthetic_id(_pos_symbol_key(pos), pos.direction)
        if oid not in (syn, str(pos.tpsl_order_id or "")):
            continue
        sym = symbol_profile(_pos_symbol_key(pos))["symbol"]
        try:
            await loop.run_in_executor(
                None,
                lambda s=sym, idx=_position_idx(pos.direction): exchange.set_trading_stop(
                    s,
                    "0",
                    "0",
                    None,
                    None,
                    {"positionIdx": idx, "tpslMode": "Full"},
                ),
            )
            logger.info(f"CANCEL stoporder {oid}")
            return True
        except Exception as e:
            logger.warning(f"cancel_stoporder({oid}): {e}")
            return False
    try:
        for key in _tracked_symbol_keys():
            sym = symbol_profile(key)["symbol"]
            await loop.run_in_executor(None, lambda s=sym: exchange.cancel_order(oid, s))
            logger.info(f"CANCEL stoporder/order {oid}")
            return True
    except Exception as e:
        logger.warning(f"cancel_stoporder({oid}): {e}")
    return False


async def _mexc_place_stoporder_tpsl(pos: "Position") -> bool:
    """Bybit set_trading_stop: market SL + limit TP на ногу."""
    sk = _pos_symbol_key(pos)
    sym = symbol_profile(sk)["symbol"]
    idx = _position_idx(pos.direction)
    params: dict = {
        "positionIdx": idx,
        "tpslMode": "Full",
        "slOrderType": "Market",
        "tpOrderType": "Limit",
    }
    sl = tp = None
    if pos.stop_price > 0:
        sl = str(_round_protection_price(pos.stop_price, sk))
    if pos.tp_price > 0:
        tp = str(_round_protection_price(pos.tp_price, sk))
        params["tpLimitPrice"] = tp
    if sl is None and tp is None:
        return False
    loop = asyncio.get_event_loop()
    for attempt in range(3):
        try:
            await loop.run_in_executor(
                None,
                lambda: exchange.set_trading_stop(sym, sl, tp, None, None, params),
            )
            oid = _tpsl_synthetic_id(sk, pos.direction)
            pos.tpsl_order_id = oid
            pos.stop_order_id = None
            pos.tp_order_id = None
            logger.info(
                f"TPSL #{pos.trade_num} {pos.direction} "
                f"SL={pos.stop_price:.1f} TP={pos.tp_price:.1f} "
                f"idx={idx} → {oid}"
            )
            return True
        except Exception as e:
            logger.error(f"stoporder/place attempt {attempt + 1}: {e}")
            await asyncio.sleep(2 ** (attempt + 1))
    return False


async def _adopt_exchange_stoporder_tpsl(pos: "Position") -> bool:
    """Подхват stoporder/place с биржи (в т.ч. выставленного вручную в UI).

    Цены с биржи всегда синкаем в локальную позицию — ручной сдвиг SL/TP ок.
    """
    if pos.status != "open" or state.paper:
        return False
    rows, ok = await _list_mexc_stoporders(is_finished=0)
    if not ok:
        return False
    skip_ids = _other_open_protection_order_ids(pos)
    for row in rows:
        if int(row.get("state") or 0) != 1:
            continue
        oid = str(row.get("id") or "")
        if not oid or oid in skip_ids:
            continue
        pid = row.get("positionId")
        if pos.exchange_position_id and str(pid) == str(pos.exchange_position_id):
            matched = True
        elif _stoporder_prices_match_pos(row, pos):
            matched = True
        else:
            matched = False
        if not matched:
            continue
        adopted = False
        if pos.tpsl_order_id != oid:
            pos.tpsl_order_id = oid
            pos.stop_order_id = None
            pos.tp_order_id = None
            if pid and not pos.exchange_position_id:
                pos.exchange_position_id = str(pid)
            logger.info(
                f"#{pos.trade_num} {pos.direction}: подхват stoporder TPSL → {oid}"
            )
            adopted = True
        await _apply_exchange_protection_prices(pos, row, notify=True)
        return True if adopted else bool(pos.tpsl_order_id)
    return bool(pos.tpsl_order_id)


async def _list_mexc_planorders(
    *,
    states: str = "1",
    page_size: int = 100,
    lookback_days: int = 7,
    symbol_key: Optional[str] = None,
) -> tuple[list[dict], bool]:
    """Открытые ордера Bybit (limit + conditional) в форме planorder-строк."""
    loop = asyncio.get_event_loop()
    sk = symbol_key or active_symbol_key()
    sym = symbol_profile(sk)["symbol"]
    orders: list = []
    try:
        regular = await loop.run_in_executor(
            None, lambda: exchange.fetch_open_orders(sym)
        )
        orders.extend(regular or [])
    except Exception as e:
        logger.warning(f"planorder list regular: {e}")
        return [], False
    try:
        stops = await loop.run_in_executor(
            None,
            lambda: exchange.fetch_open_orders(sym, None, None, {"stop": True}),
        )
        orders.extend(stops or [])
    except Exception:
        try:
            stops = await loop.run_in_executor(
                None,
                lambda: exchange.fetch_open_orders(
                    sym, None, None, {"orderFilter": "StopOrder"}
                ),
            )
            orders.extend(stops or [])
        except Exception as e:
            logger.warning(f"planorder list stop: {e}")
    rows = [_ccxt_order_to_plan_row(o, sk) for o in orders]
    want = {s.strip() for s in str(states).split(",") if s.strip()}
    if want and want != {"1", "2", "3", "4", "5"}:
        rows = [r for r in rows if str(r.get("state")) in want]
    return rows, True


def _ccxt_order_to_plan_row(order: dict, symbol_key: str) -> dict:
    info = order.get("info") or {}
    st = str(order.get("status") or "").lower()
    state = 1
    if st in ("canceled", "cancelled", "rejected"):
        state = 2
    elif st in ("closed", "filled"):
        state = 3
    side_s = str(order.get("side") or "").lower()
    reduce = bool(order.get("reduceOnly") or info.get("reduceOnly"))
    if reduce:
        mexc_side = 4 if side_s == "sell" else 2
    else:
        mexc_side = 1 if side_s == "buy" else 3
    otype = str(order.get("type") or info.get("orderType") or "limit").lower()
    order_type = 5 if "market" in otype else 1
    trig = order.get("triggerPrice") or order.get("stopPrice") or info.get("triggerPrice")
    px = order.get("price") or trig or 0
    amount = float(order.get("amount") or info.get("qty") or 0)
    filled = float(order.get("filled") or 0)
    avg = float(order.get("average") or 0)
    oid = _extract_order_id(order)
    return {
        "id": oid,
        "orderId": oid,
        "state": state,
        "side": mexc_side,
        "orderType": order_type,
        "price": px,
        "triggerPrice": trig or px,
        "vol": _from_ex_qty(amount, symbol_key),
        "dealVol": _from_ex_qty(filled, symbol_key),
        "dealAvgPrice": avg,
        "symbol": _mexc_market_id(symbol_key),
        "_src": "bybit",
    }


async def _list_mexc_planorders_tracked(
    *,
    states: str = "1",
    page_size: int = 100,
    lookback_days: int = 7,
) -> tuple[list[dict], bool]:
    rows: list[dict] = []
    api_ok = True
    for key in _tracked_symbol_keys():
        part, ok = await _list_mexc_planorders(
            states=states,
            page_size=page_size,
            lookback_days=lookback_days,
            symbol_key=key,
        )
        rows.extend(part)
        api_ok = api_ok and ok
    return rows, api_ok


async def _list_mexc_stoporders_tracked(
    *,
    is_finished: int = 0,
    page_size: int = 100,
) -> tuple[list[dict], bool]:
    rows: list[dict] = []
    api_ok = True
    for key in _tracked_symbol_keys():
        part, ok = await _list_mexc_stoporders(
            is_finished=is_finished, page_size=page_size, symbol_key=key,
        )
        rows.extend(part)
        api_ok = api_ok and ok
    return rows, api_ok


def _planorder_row_status(row: dict) -> str:
    """MEXC planorder state: 1=active trigger, 2=cancelled, 3=executed."""
    try:
        st = int(row.get("state") or 0)
    except Exception:
        return "unknown"
    if st == 1:
        return "open"
    if st == 3:
        return "closed"
    if st in (2, 4, 5):
        return "canceled"
    return "unknown"


def _planorder_side_is_open_entry(row: dict) -> bool:
    """MEXC planorder side: 1=open long, 3=open short (2/4 = close leg)."""
    try:
        return int(row.get("side") or 0) in (1, 3)
    except (TypeError, ValueError):
        return False


def _planorder_row_has_deal(row: dict, order_info: Optional[dict] = None) -> bool:
    oi = order_info or {}
    try:
        filled = float(oi.get("filled") or row.get("dealVol") or 0)
    except (TypeError, ValueError):
        filled = 0.0
    try:
        avg = float(oi.get("average") or row.get("dealAvgPrice") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    return filled > 0 or avg > 0


def _planorder_row_id(row: dict) -> str:
    oid = row.get("id") or row.get("orderId")
    return str(oid) if oid is not None else ""


def _order_is_filled(
    order_info: Optional[dict],
    expected_contracts: Optional[int] = None,
) -> bool:
    """Ордер исполнен (regular + MEXC planorder state=3).

    Не считаем fill при status=open и filled>0 без average — типичный баг MEXC plan/trigger.
    """
    if not order_info:
        return False
    row = order_info.get("info") if isinstance(order_info.get("info"), dict) else {}

    if order_info.get("_src") == "stoporder":
        try:
            return int(row.get("state") or 0) == 3
        except (TypeError, ValueError):
            return str(order_info.get("status") or "").lower() == "closed"

    if order_info.get("_src") == "planorder" or (row and row.get("state") is not None):
        try:
            st = int(row.get("state") or 0)
        except Exception:
            st = 0
        if st != 3:
            return False
        filled = float(order_info.get("filled") or row.get("dealVol") or 0)
        avg = float(order_info.get("average") or row.get("dealAvgPrice") or 0)
        # STOP-LIMIT вход: state=3 = сработал триггер, лимитка может ещё висеть
        if _planorder_side_is_open_entry(row):
            return filled > 0 or avg > 0
        return filled > 0 or avg > 0 or st == 3

    status = str(order_info.get("status") or "").lower()
    filled = float(order_info.get("filled") or 0)
    amount = float(order_info.get("amount") or 0)
    avg    = float(order_info.get("average") or 0)

    if status in ("open", "new", "pending"):
        if avg > 0 and filled > 0:
            exp = expected_contracts or 0
            ref = amount if amount > 0 else float(exp or filled)
            if ref > 0 and filled >= max(1, ref * 0.9):
                return True
        return False

    if status in ("closed", "filled") and (filled > 0 or avg > 0):
        return True
    if filled > 0 and status in ("closed", "canceled", "cancelled") and avg > 0:
        return True
    exp = expected_contracts or 0
    if exp > 0 and status in ("closed", "filled") and avg > 0:
        ref = amount if amount > 0 else float(exp)
        if filled >= max(1, ref * 0.9):
            return True
    return False


def _order_fill_price(info: dict, fallback: float) -> float:
    """Средняя цена исполнения; triggerPrice/price заявки не подставляем."""
    try:
        avg = float(info.get("average") or 0)
        if avg > 0:
            return avg
    except Exception:
        pass
    row = info.get("info") if isinstance(info.get("info"), dict) else {}
    for key in ("dealAvgPrice", "avgPrice", "averagePrice"):
        try:
            v = float(row.get(key) or 0)
            if v > 0:
                return v
        except Exception:
            continue
    if fallback > 0:
        logger.warning(
            f"fill_price: нет average/dealAvgPrice в ответе биржи, fallback={fallback:.1f}"
        )
    return fallback


def _planorder_row_price(row: dict) -> Optional[float]:
    for key in ("triggerPrice", "price"):
        v = row.get(key)
        if v is None:
            continue
        try:
            f = float(v)
            if f > 0:
                return f
        except Exception:
            continue
    return None


def _planorder_cancel_ok(resp: Optional[dict]) -> bool:
    if not resp:
        return False
    data = resp.get("data")
    rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    if not rows:
        return bool(resp.get("success"))
    for row in rows:
        err = str(row.get("errorMsg") or row.get("message") or "")
        code = str(row.get("errorCode") or row.get("code") or "")
        if err and err.lower() != "success":
            if code in ("2041", "2040") or "cannot be cancelled" in err.lower() or "not exist" in err.lower():
                continue
            return False
    return True


async def _cancel_mexc_planorder(order_id: str, symbol_key: Optional[str] = None) -> bool:
    """Снять limit/conditional ордер Bybit."""
    oid = str(order_id)
    if oid.startswith("tpsl:"):
        return await _cancel_mexc_stoporder(oid)
    keys = [symbol_key] if symbol_key else list(_tracked_symbol_keys())
    loop = asyncio.get_event_loop()
    for sk in keys:
        sym = symbol_profile(sk)["symbol"]
        try:
            await loop.run_in_executor(None, lambda s=sym: exchange.cancel_order(oid, s))
            logger.info(f"CANCEL planorder {oid}")
            return True
        except Exception as e:
            logger.warning(f"cancel_planorder({oid}) {sym}: {e}")
    return False


async def _cancel_mexc_planorders_all(symbol_key: Optional[str] = None) -> bool:
    """Снять все открытые ордера по символу."""
    sk = symbol_key or active_symbol_key()
    sym = symbol_profile(sk)["symbol"]
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: exchange.cancel_all_orders(sym))
        logger.info(f"CANCEL planorder_all {sym}")
        return True
    except Exception as e:
        logger.warning(f"cancel_planorder_all: {e}")
        return False


async def _exchange_order_still_open(order_id: str) -> bool:
    open_ids = await _fetch_exchange_open_order_ids()
    return str(order_id) in open_ids


async def _confirm_order_cancelled(
    order_id: str,
    symbol_key: Optional[str] = None,
    *,
    delays: tuple[float, ...] = (0.5, 1.5, 3.0, 6.0),
) -> bool:
    """True если ордер снят: нет в open_orders или terminal status (MEXC лагает ~1–15 с)."""
    oid = str(order_id)
    for i, delay in enumerate((0.0,) + delays):
        if i > 0:
            await asyncio.sleep(delay)
        if not await _exchange_order_still_open(oid):
            return True
        info = await get_order_status(oid, symbol_key)
        if info:
            st = str(info.get("status") or "").lower()
            if st in ("closed", "filled", "canceled", "cancelled"):
                logger.info(f"cancel confirm: {oid} status={st}")
                return True
    return False


async def cancel_order(order_id: str, symbol_key: Optional[str] = None) -> bool:
    """Снять ордер с биржи. True — ордера больше нет среди активных.

    Сначала planorder/cancel (trigger, SL/TP), затем order/cancel (обычные лимитки).
    """
    oid = str(order_id)

    await _cancel_mexc_planorder(oid, symbol_key)
    if await _confirm_order_cancelled(oid, symbol_key):
        return True

    keys = [symbol_key] if symbol_key else list(_tracked_symbol_keys())
    loop = asyncio.get_event_loop()
    for sk in keys:
        sym = symbol_profile(sk)["symbol"]
        try:
            await loop.run_in_executor(None, lambda s=sym: exchange.cancel_order(oid, s))
            logger.info(f"CANCEL regular {oid} ({sym})")
            break
        except Exception as e:
            logger.warning(f"cancel({oid}) {sym}: {e}")

    if await _confirm_order_cancelled(oid, symbol_key):
        return True

    logger.error(f"CANCEL FAILED: {oid} всё ещё активен на бирже")
    return False


async def _pending_entry_is_plan(pl: "PendingLimit") -> bool:
    """STOP-LIMIT вход на MEXC — planorder; для старых pending без флага — lookup."""
    if pl.entry_is_plan:
        return True
    if not pl.order_id:
        return False
    rows, _ = await _list_mexc_planorders_tracked(states="1", page_size=100)
    for row in rows:
        oid = row.get("id") or row.get("orderId")
        if oid is not None and str(oid) == str(pl.order_id):
            pl.entry_is_plan = True
            return True
    return False


async def _cancel_pending_entry(pl: "PendingLimit") -> bool:
    """Снять entry-ордер pending-лимитки. False — ордер остался на бирже."""
    if not pl.order_id:
        return True
    oid = str(pl.order_id)

    if await _pending_entry_is_plan(pl):
        # Только entry planorder — не cancel_all (снесёт SL/TP открытых позиций).
        sk = _pos_symbol_key(pl)
        for attempt in range(2):
            await _cancel_mexc_planorder(oid, sk)
            if await _confirm_order_cancelled(oid, sk):
                pl.cancel_fail_alerted = False
                return True
            if attempt == 0:
                await asyncio.sleep(0.5)
        return False

    ok = await cancel_order(oid, _pos_symbol_key(pl))
    if ok:
        pl.cancel_fail_alerted = False
        return True
    return False


async def _refresh_ohlc_extremum(tf: str):
    """Обновить low/high последнего закрытого бара (не ждать минутный scanner)."""
    tf_cfg = CONFIG.get(tf, CONFIG[state.active_tf])
    df = await fetch_ohlcv(tf_cfg["timeframe"], limit=3)
    if df is not None and len(df) >= 2:
        last_bar = df.iloc[-2]
        state.last_ohlcv_low = float(last_bar["low"])
        state.last_ohlcv_high = float(last_bar["high"])


async def _refresh_forming_extremum(tf: str) -> tuple[Optional[float], Optional[float]]:
    """Low/high формирующегося бара (cisd_cross: стоп не инвалидировать закрытым свип-баром)."""
    tf_cfg = CONFIG.get(tf, CONFIG[state.active_tf])
    df = await fetch_ohlcv(tf_cfg["timeframe"], limit=2)
    if df is not None and len(df) >= 1:
        bar = df.iloc[-1]
        return float(bar["low"]), float(bar["high"])
    return None, None


async def _last_closed_bar_ohlc(tf: str) -> tuple[str, float, float, float]:
    """Время, high, low, close последнего закрытого LTF-бара."""
    tf_cfg = CONFIG.get(tf, CONFIG[state.active_tf])
    df = await fetch_ohlcv(tf_cfg["timeframe"], limit=3)
    if df is None or len(df) < 2:
        return "", 0.0, 0.0, 0.0
    bar = df.iloc[-2]
    return (
        str(pd.Timestamp(bar.name)),
        float(bar["high"]),
        float(bar["low"]),
        float(bar["close"]),
    )


async def _last_closed_bar_close(tf: str) -> tuple[str, float]:
    """Время и close последнего закрытого бара LTF."""
    bar_t, _, _, close = await _last_closed_bar_ohlc(tf)
    return bar_t, close


def _pending_pattern_extreme(pl: "PendingLimit") -> float:
    """Экстремум паттерна для инвалидации pending (до QSTOP, если ужали SL)."""
    orig = getattr(pl, "quality_stop_original", None)
    if orig is not None:
        try:
            o = float(orig)
            if math.isfinite(o) and o > 0:
                return o
        except (TypeError, ValueError):
            pass
    return float(pl.stop_price)


def _pending_extreme_hit(pl: "PendingLimit", price: Optional[float],
                         ohlc_low: Optional[float], ohlc_high: Optional[float],
                         forming_low: Optional[float] = None,
                         forming_high: Optional[float] = None) -> tuple[bool, str, float]:
    """Пробой экстремума: live price (сразу) или low/high бара.

    Порог — original trigger extreme (quality_stop_original), не ужатый QSTOP SL.
    Иначе QSTOP ×0.85 сразу убивает pending о high/low своего триггер-бара.

    cisd_cross_market: только live + forming-бар (не закрытый свип-бар iloc[-2]).
    """
    extreme = _pending_pattern_extreme(pl)
    if getattr(pl, "cisd_cross_market", False):
        bar_low, bar_high = forming_low, forming_high
    else:
        bar_low, bar_high = ohlc_low, ohlc_high
    if pl.direction == "LONG":
        if price is not None and price < extreme:
            return True, "<", float(price)
        if bar_low is not None and bar_low < extreme:
            return True, "<", float(bar_low)
    else:
        if price is not None and price > extreme:
            return True, ">", float(price)
        if bar_high is not None and bar_high > extreme:
            return True, ">", float(bar_high)
    return False, "", 0.0


async def _alert_cancel_fail(pl: "PendingLimit", msg: str):
    if getattr(pl, "cancel_fail_alerted", False):
        return
    pl.cancel_fail_alerted = True
    await send_telegram(msg)


async def _notify_cancel_false_alarm_resolved(pl: "PendingLimit", reason: str) -> None:
    if not getattr(pl, "cancel_fail_alerted", False):
        return
    pl.cancel_fail_alerted = False
    prefix = _mode_prefix() + " "
    tfl = tf_label(pl.tf)
    await send_telegram(
        f"{prefix}✅ ЛИМИТКА #{pl.trade_num} — ордер снят (ложный алерт) [{tfl}]\n"
        f"ID: {pl.id}  |  order: {pl.order_id}\n"
        f"{reason}"
    )


async def get_order_status(order_id: str, symbol_key: Optional[str] = None) -> Optional[dict]:
    keys = [symbol_key] if symbol_key else list(_tracked_symbol_keys())
    loop = asyncio.get_event_loop()
    raw = None
    for sk in keys:
        sym = symbol_profile(sk)["symbol"]
        try:
            raw = await loop.run_in_executor(
                None, lambda s=sym: exchange.fetch_order(order_id, s)
            )
        except Exception as e:
            logger.warning(f"fetch_order({order_id}) {sym}: {e}")
            continue

        if raw:
            st = str(raw.get("status") or "").lower()
            filled = float(raw.get("filled") or 0)
            avg = float(raw.get("average") or 0)
            # open + filled без avg — ложный fill у plan/trigger; идём в planorder list
            if st in ("open", "new", "pending") and filled > 0 and avg <= 0:
                pass
            elif st and st not in ("", "none"):
                return raw
            elif filled > 0 and avg > 0:
                return raw

    # Fallback: MEXC planorder (STOP-LIMIT вход, SL/TP)
    try:
        rows, ok = await _list_mexc_planorders_tracked(states="1,2,3,4,5", page_size=100)
        if not ok:
            return None
        for row in rows:
            if _planorder_row_id(row) != str(order_id):
                continue
            try:
                filled = float(row.get("dealVol") or row.get("filled") or row.get("vol") or 0)
            except Exception:
                filled = 0.0
            try:
                avg = float(row.get("dealAvgPrice") or row.get("avgPrice") or row.get("averagePrice") or 0)
            except Exception:
                avg = 0.0
            status = _planorder_row_status(row)
            if status == "closed" and filled <= 0 and not _planorder_side_is_open_entry(row):
                try:
                    filled = float(row.get("orderVol") or row.get("vol") or 0)
                except Exception:
                    pass
            if (
                _planorder_side_is_open_entry(row)
                and int(row.get("state") or 0) == 3
                and not _planorder_row_has_deal(row)
            ):
                status = "open"
            if status == "unknown" and (filled > 0 or avg > 0):
                status = "closed"
            return {
                "id": str(order_id),
                "status": status,
                "filled": filled,
                "average": avg,
                "info": row,
                "_src": "planorder",
            }
    except Exception as e2:
        logger.warning(f"planorder_status({order_id}): {e2}")

    # Fallback: MEXC stoporder (TP/SL в UI)
    try:
        info = await _get_stoporder_status(str(order_id))
        if info:
            return info
    except Exception as e3:
        logger.warning(f"stoporder_status({order_id}): {e3}")

    return None


def _protection_order_is_active(info: Optional[dict]) -> bool:
    """SL/TP ещё висит на бирже (stoporder или legacy plan)."""
    if not info:
        return False
    if info.get("_src") == "stoporder":
        return _stoporder_protection_is_active(info)
    st = str(info.get("status") or "").lower()
    return st in ("open", "new", "pending")


def _planorder_row_is_executed(row: dict) -> bool:
    try:
        return int(row.get("state") or 0) == 3
    except (TypeError, ValueError):
        return False


def _planorder_row_fill_price(row: dict, fallback: float = 0.0) -> float:
    for key in ("dealAvgPrice", "avgPrice", "averagePrice", "price"):
        try:
            v = float(row.get(key) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return fallback if fallback > 0 else 0.0


def _infer_close_reason_from_entry(pos: "Position", close_price: float) -> Optional[str]:
    """LONG ниже entry / SHORT выше entry — SL; иначе TP (если не breakeven)."""
    if close_price <= 0 or pos.entry_price <= 0:
        return None
    eps = max(pos.entry_price, 1.0) * 1e-6
    if pos.direction == "LONG":
        if close_price < pos.entry_price - eps:
            return "closed_sl"
        if close_price > pos.entry_price + eps:
            return "closed_tp"
    else:
        if close_price > pos.entry_price + eps:
            return "closed_sl"
        if close_price < pos.entry_price - eps:
            return "closed_tp"
    return None


def _infer_close_reason_from_price(pos: "Position", close_price: float) -> Optional[str]:
    """Эвристика: цена выхода рядом со stop/tp (допускает проскальзывание stop-market)."""
    if close_price <= 0:
        return None
    ref = max(pos.entry_price, 1.0)
    tol = ref * 0.0025
    sl_hit = pos.stop_price > 0 and abs(close_price - pos.stop_price) <= tol
    tp_hit = pos.tp_price > 0 and abs(close_price - pos.tp_price) <= tol
    if sl_hit and not tp_hit:
        return "closed_sl"
    if tp_hit and not sl_hit:
        return "closed_tp"
    if sl_hit and tp_hit:
        if abs(close_price - pos.stop_price) <= abs(close_price - pos.tp_price):
            return "closed_sl"
        return "closed_tp"
    return _infer_close_reason_from_entry(pos, close_price)


async def _scan_filled_protection_orders(
    pos: "Position",
    *,
    only_ids: Optional[set[str]] = None,
) -> Optional[tuple[str, float]]:
    """Исполненный SL/TP: stoporder (приоритет) или legacy planorder."""
    if state.paper:
        return None

    known = only_ids if only_ids is not None else _position_protection_order_ids(pos)
    if pos.entry_kind == "sync_orphan" and not known:
        return None
    can_scan_stoporders = bool(known or pos.exchange_position_id)
    if can_scan_stoporders:
        for finished in (0, 1):
            rows, ok = await _list_mexc_stoporders(is_finished=finished)
            if not ok:
                continue
            for row in rows:
                oid = str(row.get("id") or "")
                if only_ids is not None and oid not in known:
                    continue
                if only_ids is None and known and oid not in known:
                    continue
                if int(row.get("state") or 0) != 3:
                    continue
                row_pid = str(row.get("positionId") or "")
                if pos.exchange_position_id and row_pid and row_pid != str(pos.exchange_position_id):
                    if known and oid in known:
                        pass
                    else:
                        continue
                elif pos.exchange_position_id and row_pid != str(pos.exchange_position_id):
                    if known and oid in known and not row_pid:
                        pass
                    elif not _stoporder_prices_match_pos(row, pos):
                        continue
                elif not pos.exchange_position_id and oid not in known:
                    continue
                reason, px = await _resolve_stoporder_close(pos, row)
                logger.info(
                    f"scan stoporder #{pos.trade_num} {reason} oid={oid} @ {px:.1f}"
                )
                return reason, px
    else:
        logger.info(
            f"scan stoporder #{pos.trade_num} {pos.direction}: "
            f"skip unbound scan (no positionId/order ids)"
        )

    if only_ids is None and (pos.stop_order_id or pos.tp_order_id) and not pos.tpsl_order_id:
        pass  # legacy scan below
    elif only_ids is None and pos.tpsl_order_id:
        return None
    elif only_ids is None and (pos.stop_order_id or pos.tp_order_id):
        return None
    entry_ms = int(pos.entry_time.timestamp() * 1000) if pos.entry_time else 0
    skip_ids = _other_open_protection_order_ids(pos)
    rows, _ = await _list_mexc_planorders_tracked(states="1,2,3,4,5", page_size=100)
    for row in rows:
        if not _planorder_row_is_executed(row):
            continue
        oid = _planorder_row_id(row)
        if only_ids is not None and oid in only_ids:
            otype = _planorder_row_order_type(row)
            trig = _planorder_row_price(row)
            fill_px = _planorder_row_fill_price(row, trig or 0.0)
            if otype == 5 and pos.stop_price > 0:
                px = fill_px or pos.stop_price or trig or 0.0
                if px > 0:
                    logger.info(
                        f"scan protection SL #{pos.trade_num} oid={oid} fill={px:.1f}"
                    )
                    return "closed_sl", px
            if otype == 1 and pos.tp_price > 0:
                px = fill_px or pos.tp_price or trig or 0.0
                if px > 0:
                    logger.info(
                        f"scan protection TP #{pos.trade_num} oid={oid} fill={px:.1f}"
                    )
                    return "closed_tp", px
            continue
        if only_ids is not None and oid not in only_ids:
            continue
        if oid in skip_ids:
            continue
        if str(row.get("side") or "") != str(_mexc_close_side_int(pos.direction)):
            continue
        try:
            vol = float(row.get("vol") or row.get("orderVol") or 0)
        except (TypeError, ValueError):
            continue
        if abs(vol - float(pos.contracts)) > 0.01:
            continue
        if entry_ms > 0:
            created = _planorder_row_create_ms(row)
            if created > 0 and created < entry_ms - 60_000:
                continue
        trig = _planorder_row_price(row)
        otype = _planorder_row_order_type(row)
        fill_px = _planorder_row_fill_price(row, trig or 0.0)
        ent = float(pos.entry_price or 0)
        if otype == 5 and pos.stop_price > 0 and _protection_price_exact(
            pos.stop_price, trig, entry=ent,
        ):
            px = fill_px or pos.stop_price
            logger.info(
                f"scan protection SL #{pos.trade_num} oid={oid} fill={px:.1f}"
            )
            return "closed_sl", px
        if otype == 1 and pos.tp_price > 0 and _protection_price_exact(
            pos.tp_price, trig, entry=ent,
        ):
            px = fill_px or pos.tp_price
            logger.info(
                f"scan protection TP #{pos.trade_num} oid={oid} fill={px:.1f}"
            )
            return "closed_tp", px
    return None


async def _recent_close_fill_price(pos: "Position", *, lookback_min: Optional[int] = None) -> Optional[float]:
    """Средняя цена недавнего close-fill на бирже."""
    if state.paper:
        return None
    if lookback_min is None:
        lookback_min = int(CONFIG.get("close_deal_lookback_min", 360))
    since_ms = int((utcnow() - timedelta(minutes=lookback_min)).timestamp() * 1000)
    sym_ccxt = symbol_profile(_pos_symbol_key(pos))["symbol"]
    loop = asyncio.get_event_loop()
    try:
        trades = await loop.run_in_executor(
            None,
            lambda: exchange.fetch_my_trades(sym_ccxt, since=since_ms, limit=80),
        )
    except Exception as e:
        logger.warning(f"close_fill_price #{pos.trade_num}: {e}")
        return None
    need_vol = max(1.0, pos.contracts * 0.45)
    vol_sum = 0.0
    px_vol = 0.0
    for t in trades or []:
        info = t.get("info") or {}
        if not _mexc_trade_is_close_fill(info, pos.direction, t):
            continue
        vol = _trade_vol_contracts(t, _pos_symbol_key(pos))
        if vol < need_vol:
            continue
        try:
            px = float(
                info.get("dealAvgPrice")
                or info.get("avgPrice")
                or t.get("average")
                or t.get("price")
                or info.get("price")
                or 0
            )
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            continue
        vol_sum += vol
        px_vol += px * vol
    if vol_sum > 0:
        return px_vol / vol_sum
    return None


def _position_protection_order_ids(pos: "Position") -> set[str]:
    if pos.tpsl_order_id:
        return {str(pos.tpsl_order_id)}
    return {str(x) for x in (pos.stop_order_id, pos.tp_order_id) if x}


async def _try_finalize_filled_protection(pos: "Position") -> bool:
    """SL/TP уже исполнен — закрыть в стейте, не перевыставлять защиту."""
    if pos.status != "open" or state.paper:
        return False
    price = get_price() or pos.entry_price

    if pos.tpsl_order_id:
        info = await _get_stoporder_status(pos.tpsl_order_id)
        if info and _stoporder_is_executed(info):
            row = info.get("info") or {}
            reason, px = await _resolve_stoporder_close(pos, row)
            logger.info(
                f"stoporder filled #{pos.trade_num} {reason} "
                f"oid={pos.tpsl_order_id} px={px:.1f}"
            )
            await _finalize_position_close(pos, reason, px)
            return True

    checks = (
        (pos.stop_order_id, "closed_sl", pos.stop_price or price),
        (pos.tp_order_id, "closed_tp", pos.tp_price or price),
    )
    for oid, reason, fallback in checks:
        if not oid:
            continue
        info = await get_order_status(str(oid))
        if _order_is_filled(info):
            px = _order_fill_price(info, fallback)
            logger.info(
                f"protection filled #{pos.trade_num} {reason} oid={oid} px={px:.1f}"
            )
            await _finalize_position_close(pos, reason, px)
            return True
    known = _position_protection_order_ids(pos)
    if known:
        scanned = await _scan_filled_protection_orders(pos, only_ids=known)
        if scanned:
            logger.info(
                f"protection filled #{pos.trade_num} {scanned[0]} "
                f"(scan oid) px={scanned[1]:.1f}"
            )
            await _finalize_position_close(pos, scanned[0], scanned[1])
            return True
    scanned = await _scan_filled_protection_orders(pos)
    if scanned:
        await _finalize_position_close(pos, scanned[0], scanned[1])
        return True
    return False


def _position_protection_fully_confirmed(pos: "Position", sl_ok: bool, tp_ok: bool) -> bool:
    return (pos.stop_price <= 0 or sl_ok) and (pos.tp_price <= 0 or tp_ok)


async def _notify_position_protected_after_alert(
    pos: "Position",
    sl_ok: bool,
    tp_ok: bool,
) -> bool:
    """Однократный TG, когда после тревоги SL/TP всё-таки подтверждены."""
    if state.paper or pos.status != "open":
        return False
    if not pos.protection_alert_sent or pos.protection_ok_alert_sent:
        return False
    if not _position_protection_fully_confirmed(pos, sl_ok, tp_ok):
        return False

    pos.protection_ok_alert_sent = True
    oid = pos.tpsl_order_id or pos.stop_order_id or pos.tp_order_id or "-"
    logger.info(
        f"protection ok alert #{pos.trade_num} {pos.direction}: "
        f"SL={pos.stop_price:.1f} TP={pos.tp_price:.1f} oid={oid}"
    )
    await send_telegram(
        f"✅ #{pos.trade_num} {pos.direction}: позиция защищена\n"
        f"SL: {pos.stop_price:.1f} ✅\n"
        f"TP: {pos.tp_price:.1f} ✅"
    )
    return True


def _mexc_close_side_int(direction: str) -> int:
    """MEXC futures: 4=close long, 2=close short."""
    return 4 if direction == "LONG" else 2


def _planorder_row_matches_position(row: dict, pos: "Position") -> bool:
    """Plan-order относится к SL/TP этой позиции (не к другой open-ноге)."""
    if str(row.get("side") or "") != str(_mexc_close_side_int(pos.direction)):
        return False
    try:
        vol = float(row.get("vol") or row.get("orderVol") or 0)
    except Exception:
        return False
    return abs(vol - float(pos.contracts)) <= 1.0


def _planorder_row_matches_direction_price(
    row: dict, direction: str, target_price: float, *, order_type_mexc: int,
) -> bool:
    """Тот же close-side и trigger-цена (без привязки к объёму — одна нога на бирже)."""
    if str(row.get("side") or "") != str(_mexc_close_side_int(direction)):
        return False
    if _planorder_row_order_type(row) != int(order_type_mexc):
        return False
    trig = _planorder_row_price(row)
    return _protection_price_near(float(target_price), trig)


def _other_open_protection_order_ids(pos: "Position") -> set[str]:
    out: set[str] = set()
    for p in state.positions:
        if p.status != "open" or p.id == pos.id:
            continue
        if p.tpsl_order_id:
            out.add(str(p.tpsl_order_id))
        if p.stop_order_id:
            out.add(str(p.stop_order_id))
        if p.tp_order_id:
            out.add(str(p.tp_order_id))
    return out


def _sl_tp_restore_lock(pos_id: str) -> asyncio.Lock:
    lock = state._sl_tp_restore_locks.get(pos_id)
    if lock is None:
        lock = asyncio.Lock()
        state._sl_tp_restore_locks[pos_id] = lock
    return lock


def _position_protection_frozen(pos_id: str) -> bool:
    """SL/TP не трогаем: идёт force close или finalize."""
    return (
        pos_id in state._close_in_progress
        or pos_id in state._force_close_in_progress
    )


def _protection_price_near(target: float, actual: Optional[float]) -> bool:
    if actual is None or target <= 0:
        return False
    return abs(actual - target) / max(target, 1.0) <= 0.0008


def _protection_price_exact(
    target: float, actual: Optional[float], *, entry: float = 0.0,
) -> bool:
    """Строгое совпадение trigger с stop/tp (для scan истории — не цеплять чужие plan)."""
    if actual is None or target <= 0:
        return False
    ref = max(target, 1.0)
    tol = 0.00012
    if entry > 0:
        dist = abs(target - entry)
        if dist > 0:
            tol = min(tol, (dist / ref) * 0.35)
    return abs(actual - target) / ref <= tol


def _planorder_row_create_ms(row: dict) -> int:
    for key in ("createTime", "create_time", "updateTime"):
        try:
            v = int(row.get(key) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return 0


def _planorder_row_order_type(row: dict) -> int:
    try:
        return int(row.get("orderType") or 0)
    except (TypeError, ValueError):
        return 0


async def _adopt_exchange_protection_orders(
    pos: "Position",
    *,
    plan_rows: Optional[list[dict]] = None,
    plan_api_ok: Optional[bool] = None,
) -> bool:
    """Подхватить уже висящие plan SL/TP на бирже — не дублировать при restore."""
    if pos.status != "open" or state.paper:
        return False
    if plan_rows is None:
        plan_rows, plan_api_ok = await _list_mexc_planorders_tracked(states="1", page_size=100)
    if plan_api_ok is False:
        return False
    adopted = False
    skip_ids = _other_open_protection_order_ids(pos)
    for row in plan_rows:
        oid = _planorder_row_id(row)
        if not oid or oid in skip_ids:
            continue
        if not _planorder_row_matches_position(row, pos):
            continue
        trig = _planorder_row_price(row)
        otype = _planorder_row_order_type(row)
        if otype == 5 and pos.stop_price > 0 and _protection_price_near(pos.stop_price, trig):
            cur = pos.stop_order_id
            if cur and str(cur) != oid:
                info = await get_order_status(str(cur))
                if _protection_order_is_active(info):
                    continue
            if str(cur or "") != oid:
                pos.stop_order_id = oid
                adopted = True
        elif otype == 1 and pos.tp_price > 0 and _protection_price_near(pos.tp_price, trig):
            cur = pos.tp_order_id
            if cur and str(cur) != oid:
                info = await get_order_status(str(cur))
                if _protection_order_is_active(info):
                    continue
            if str(cur or "") != oid:
                pos.tp_order_id = oid
                adopted = True
    if adopted:
        logger.info(
            f"Позиция #{pos.trade_num} {pos.direction}: подхвачены SL/TP с биржи "
            f"SL={pos.stop_order_id or '-'} TP={pos.tp_order_id or '-'}"
        )
    return adopted


async def _position_sl_tp_needs_restore(pos: "Position") -> bool:
    """True если у open-позиции нет активного SL и/или TP на бирже.

    Расхождение цен (ручной сдвиг) — НЕ повод restore: уровни синкаем с биржи.
    """
    if pos.tpsl_order_id:
        info = await _get_stoporder_status(pos.tpsl_order_id)
        if info is None:
            return True
        if _stoporder_is_executed(info):
            return False
        if _stoporder_protection_is_active(info):
            row = info.get("info") or {}
            await _apply_exchange_protection_prices(pos, row, notify=True)
            need_sl = pos.stop_price > 0 and not _stoporder_has_sl(row)
            need_tp = pos.tp_price > 0 and not _stoporder_has_tp(row)
            return need_sl or need_tp
        pos.tpsl_order_id = None

    need_sl = need_tp = False
    status_unknown = False
    if pos.stop_price > 0:
        if not pos.stop_order_id:
            need_sl = True
        else:
            info = await get_order_status(pos.stop_order_id)
            if info is None:
                status_unknown = True
            elif _order_is_filled(info):
                return False
            elif not _protection_order_is_active(info):
                pos.stop_order_id = None
                need_sl = True
    if pos.tp_price > 0:
        if not pos.tp_order_id:
            need_tp = True
        else:
            info = await get_order_status(pos.tp_order_id)
            if info is None:
                status_unknown = True
            elif _order_is_filled(info):
                return False
            elif not _protection_order_is_active(info):
                pos.tp_order_id = None
                need_tp = True
    if status_unknown and (pos.tpsl_order_id or pos.stop_order_id or pos.tp_order_id):
        logger.warning(
            f"#{pos.trade_num} {pos.direction}: статус SL/TP не проверен (API) — "
            f"restore отложен"
        )
        return False
    return need_sl or need_tp


async def _restore_position_sl_tp(pos: "Position", *, alert: bool = True) -> bool:
    """Переставить SL/TP если отсутствуют или сняты. True если что-то восстановлено.

    Ручной сдвиг цен не трогаем (sync local←exchange). Restore только если ноги нет.
    Короткий grace — UI MEXC при edit кратко снимает stoporder.
    """
    if pos.status != "open" or _position_protection_frozen(pos.id):
        return False
    async with _sl_tp_restore_lock(pos.id):
        if await _try_finalize_filled_protection(pos):
            return False
        if await _adopt_exchange_stoporder_tpsl(pos):
            save_positions(state.positions)
        plan_rows, plan_ok = await _list_mexc_planorders_tracked(states="1", page_size=100)
        if plan_ok:
            if await _adopt_exchange_protection_orders(
                pos, plan_rows=plan_rows, plan_api_ok=True,
            ):
                save_positions(state.positions)
        elif not pos.tpsl_order_id:
            logger.warning(
                f"#{pos.trade_num} {pos.direction}: planorder list недоступен — "
                f"restore пропущен (без дублей SL/TP)"
            )
            return False
        if await _try_finalize_filled_protection(pos):
            return False
        if not await _position_sl_tp_needs_restore(pos):
            state._sl_tp_incomplete_since.pop(pos.id, None)
            return False
        grace = float(CONFIG.get("sl_tp_restore_grace_s", 25))
        now_ts = time.time()
        since = state._sl_tp_incomplete_since.get(pos.id)
        if since is None:
            state._sl_tp_incomplete_since[pos.id] = now_ts
            logger.info(
                f"#{pos.trade_num} {pos.direction}: SL/TP неполные — "
                f"ждём {grace:.0f}s (ручной edit / лаг MEXC)"
            )
            return False
        if now_ts - since < grace:
            return False
        if pos.status != "open" or _position_protection_frozen(pos.id):
            return False
        sl_ok, tp_ok = await place_sl_tp_for_position(pos)
        if sl_ok or tp_ok:
            save_positions(state.positions)
        if await _position_sl_tp_needs_restore(pos):
            return False
        state._sl_tp_incomplete_since.pop(pos.id, None)
        logger.warning(
            f"Позиция #{pos.trade_num} {pos.direction}: SL/TP восстановлены "
            f"(SL={'✅' if sl_ok else '❌'} TP={'✅' if tp_ok else '❌'})"
        )
        if alert:
            notified = await _notify_position_protected_after_alert(pos, sl_ok, tp_ok)
            if not notified:
                cooldown = float(CONFIG.get("sl_tp_restore_alert_cooldown_s", 300))
                last = state._sl_tp_restore_alert_ts.get(pos.id, 0.0)
                if now_ts - last >= cooldown:
                    state._sl_tp_restore_alert_ts[pos.id] = now_ts
                    await send_telegram(
                        f"⚠️ #{pos.trade_num} {pos.direction}: SL/TP отсутствовали на бирже\n"
                        f"Автоматически переставлены — SL {'✅' if sl_ok else '❌'}  "
                        f"TP {'✅' if tp_ok else '❌'}"
                    )
            else:
                save_positions(state.positions)
        return True
    return False


async def _detect_position_close_reason(pos: "Position") -> tuple[str, float]:
    """По исполненным stoporder/plan SL/TP, сделкам на бирже или цене — причина закрытия."""
    price = get_price() or pos.entry_price
    if pos.tpsl_order_id:
        info = await _get_stoporder_status(pos.tpsl_order_id)
        if info and _stoporder_is_executed(info):
            row = info.get("info") or {}
            reason, px = await _resolve_stoporder_close(pos, row)
            return reason, px
    if pos.stop_order_id:
        info_sl = await get_order_status(pos.stop_order_id)
        if _order_is_filled(info_sl):
            return "closed_sl", _order_fill_price(info_sl, pos.stop_price or price)
    if pos.tp_order_id:
        info_tp = await get_order_status(pos.tp_order_id)
        if _order_is_filled(info_tp):
            return "closed_tp", _order_fill_price(info_tp, pos.tp_price or price)
    known = _position_protection_order_ids(pos)
    if known:
        scanned = await _scan_filled_protection_orders(pos, only_ids=known)
        if scanned:
            logger.info(
                f"close detect #{pos.trade_num}: {scanned[0]} from plan scan "
                f"{scanned[1]:.1f}"
            )
            return scanned
    scanned = await _scan_filled_protection_orders(pos)
    if scanned:
        return scanned
    has_deal = await _has_recent_close_deal(pos)
    if has_deal:
        deal_px = await _recent_close_fill_price(pos)
        if deal_px:
            inferred = _infer_close_reason_from_price(pos, deal_px)
            prot_filled = bool(known and await _scan_filled_protection_orders(pos, only_ids=known))
            if inferred in ("closed_sl", "closed_tp") and not prot_filled:
                logger.info(
                    f"close detect #{pos.trade_num}: closed_manual from deal "
                    f"{deal_px:.1f} (reduceOnly, no protection fill)"
                )
                return "closed_manual", deal_px
            if inferred:
                logger.info(
                    f"close detect #{pos.trade_num}: {inferred} from deal {deal_px:.1f}"
                )
                return inferred, deal_px
            return "closed_manual", deal_px
    if has_deal and known:
        scanned = await _scan_filled_protection_orders(pos, only_ids=known)
        if scanned:
            logger.info(
                f"close detect #{pos.trade_num}: {scanned[0]} from plan retry "
                f"{scanned[1]:.1f} (close-deal lag)"
            )
            return scanned
    deal_px = await _recent_close_fill_price(pos) if has_deal else None
    return "closed_sync", deal_px or price


async def _cancel_position_sl_tp_plans(pos: "Position") -> None:
    """Снять stoporder TPSL и legacy plan SL/TP."""
    if pos.tpsl_order_id:
        await _cancel_mexc_stoporder(pos.tpsl_order_id)
        pos.tpsl_order_id = None
    if pos.stop_order_id:
        await cancel_order(pos.stop_order_id, _pos_symbol_key(pos))
        pos.stop_order_id = None
    if pos.tp_order_id:
        await cancel_order(pos.tp_order_id, _pos_symbol_key(pos))
        pos.tp_order_id = None
    targets: list[float] = []
    if pos.stop_price > 0:
        targets.append(pos.stop_price)
    if pos.tp_price > 0:
        targets.append(pos.tp_price)
    if not targets:
        return
    known_ids = {
        str(oid) for oid in (pos.tpsl_order_id, pos.stop_order_id, pos.tp_order_id) if oid
    }
    skip_ids = _other_open_protection_order_ids(pos)
    rows, _ = await _list_mexc_planorders_tracked(states="1", page_size=100)
    for row in rows:
        oid = _planorder_row_id(row)
        if not oid or oid in skip_ids or oid in known_ids:
            continue
        if not _planorder_row_matches_position(row, pos):
            continue
        trig = _planorder_row_price(row)
        if trig is None:
            continue
        if not any(abs(trig - t) / max(t, 1.0) <= 0.0008 for t in targets):
            continue
        await _cancel_mexc_planorder(oid)


async def _finalize_position_close(
    pos: "Position",
    reason: str,
    close_price: float,
    *,
    notify: bool = True,
) -> None:
    if pos.status != "open":
        return
    if pos.id in state._close_in_progress:
        return
    state._close_in_progress.add(pos.id)
    try:
        if reason == "closed_sync" and not state.paper:
            if not _position_exchange_confirmed(pos):
                logger.warning(
                    f"closed_sync отложен #{pos.trade_num} {pos.direction}: "
                    f"позиция ни разу не была видна на бирже"
                )
                return
            ro = await _fetch_real_open_positions()
            if _position_matches_exchange(pos, ro):
                _maybe_mark_exchange_seen(pos, ro)
                logger.warning(
                    f"closed_sync отменён #{pos.trade_num} {pos.direction}: "
                    f"нога всё ещё на бирже"
                )
                return
            if not await _confirm_closed_sync(pos):
                logger.warning(
                    f"closed_sync отложен #{pos.trade_num} {pos.direction}: "
                    f"нет подтверждения закрытия — SL/TP не трогаем"
                )
                return
        if pos.status != "open":
            return
        # Сразу помечаем закрытой — иначе position_monitor и sync_exchange шлют два TG
        pos.status = reason
        pos.close_price = close_price
        if reason in ("closed_tp", "closed_sl", "closed_time", "closed_manual"):
            _record_recent_close(pos)
            state.htf_sweep_lock.pop(
                _setup_leg_lock_key(
                    pos.tf, pos.direction, pos.stop_price, pos.tp_price,
                ),
                None,
            )
        save_positions(state.positions)

        had_known_protection = bool(_position_protection_order_ids(pos))
        if not state.paper:
            await _cancel_position_sl_tp_plans(pos)

        gross, fees, net = await _resolve_close_pnl(pos, close_price, reason)
        close_price = float(pos.close_price or close_price)
        fixed = _reconcile_close_reason(pos, reason, close_price)
        if fixed != reason:
            reason = fixed
            pos.status = reason
            save_positions(state.positions)
        _archive_trade(pos)
        save_positions(state.positions)

        if (
            not state.paper
            and reason in ("closed_tp", "closed_sl")
            and had_known_protection
            and CONFIG.get("ghost_cleanup_enabled", True)
        ):
            asyncio.create_task(
                _cleanup_ghost_after_protection_close(pos),
                name=f"ghost_after_{pos.trade_num}",
            )

        if not notify:
            return

        tfl = tf_label(pos.tf)
        arrow = "📈" if pos.direction == "LONG" else "📉"
        margin = (
            pos.entry_price * pos.contracts * _contract_value(_pos_symbol_key(pos))
            / CONFIG["leverage"]
        )
        ico = {"closed_tp": "🟢", "closed_sl": "🔴", "closed_sync": "⚪", "closed_time": "⏰"}.get(reason, "⚪")
        reason_str = {
            "closed_tp": "ТЕЙК ПРОФИТ",
            "closed_sl": "СТОП ЛОСС",
            "closed_sync": "ЗАКРЫТА НА БИРЖЕ",
            "closed_time": "ТАЙМАУТ",
        }.get(reason, "ЗАКРЫТА НА БИРЖЕ")
        sk = _pos_symbol_key(pos)
        await send_telegram(
            f"{_mode_prefix()} {ico} #{pos.trade_num} {reason_str} {arrow} {pos.direction}\n"
            f"Инструмент: {symbol_profile(sk)['label']}\n"
            f"ТФ: {tfl}\n"
            f"Вход: {_fmt_px(pos.entry_price, sk)}  |  Выход: {_fmt_px(close_price, sk)}\n"
            f"{_format_close_pnl_lines(gross, fees, net, margin)}"
        )
    finally:
        state._close_in_progress.discard(pos.id)


# ============================================================
# PAPER TRADING: детальный отчёт
# ============================================================
async def send_paper_signal(sig: dict, tf_name: str, tf_cfg: dict, trade_num: int = 0):
    direction = sig["direction"]
    entry, stop, tp = sig["entry"], sig["stop"], sig["tp"]
    sl_pct = abs(stop - entry) / entry * 100
    tp_pct = abs(tp   - entry) / entry * 100
    rr     = tp_pct / sl_pct if sl_pct > 0 else 0

    tfl      = tf_label(tf_name)
    arrow    = "📈" if direction == "LONG" else "📉"
    htf_name = tf_htf_name(tf_name)

    sk = str(sig.get("symbol_key") or "") or active_symbol_key()
    if sk not in SYMBOL_PROFILES:
        sk = active_symbol_key()
    sweep = _fmt_px(sig["htf_sweep_level"], sk) if sig.get("htf_sweep_level") else "—"
    bh    = _fmt_px(sig["base_high"], sk) if sig.get("base_high") else "—"
    bl    = _fmt_px(sig["base_low"], sk) if sig.get("base_low") else "—"

    fib_lines = ""
    for label, key in [
        ("1.0x", "fib_1x"),
        ("2.0x", "fib_2x"),
        ("2.5x", "fib_2_5x"),
        ("4.0x",      "fib_4x"),
        ("4.5x",      "fib_4_5x"),
    ]:
        v = sig.get(key)
        if v is not None:
            fib_lines += f"\n  {label}: {_fmt_px(v, sk)}"
    risk_usdt = abs(float(entry) - float(stop)) * 1.0
    # риск в USDT уточнится при размере; здесь карточка лимитки
    msg = (
        f"{_mode_prefix()} {arrow} {direction} #{trade_num} — лимитка\n"
        f"Инструмент: {symbol_profile(sk)['label']}\n"
        f"ТФ: {tfl}\n"
        f"Сигнал: {_utc_iso_short(sig.get('confirm_bar_time') or sig.get('timestamp'))}"
        f" (HTF {_utc_iso_short(sig.get('htf_time'))})\n"
        f"Вход: {_fmt_px(entry, sk)} | Стоп: {_fmt_px(stop, sk)} | Тейк: {_fmt_px(tp, sk)}\n"
        f"vd={float(sig.get('vwap_dev') or 0):.2f}  R:R={rr:.2f}\n"
        f"Ожидание входа: {_fmt_h(tf_cfg['limit_h'])}  |  позиция: {_fmt_h(tf_cfg['position_h'])}"
    )
    logger.info(
        f"[PAPER] {sk} {direction} [{tf_name}] sweep={sweep} entry={_fmt_px(entry, sk)} "
        f"stop={_fmt_px(stop, sk)} tp={_fmt_px(tp, sk)} R:R={rr:.2f}"
    )
    await send_telegram(msg)


# ============================================================
# SLOPE EMA ФИЛЬТР (профиль по HTF активного ТФ)
# ============================================================
def _slope_ema_span_overrides() -> dict[str, int]:
    raw = CONFIG.get("slope_ema_spans") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            ratio = int(k)
            if ratio in SLOPE_EMA_PROFILES:
                out[str(ratio)] = max(1, int(v))
        except (TypeError, ValueError):
            pass
    return out


def _slope_effective_span(ratio: int) -> int:
    base = SLOPE_EMA_PROFILES.get(ratio, {}).get("span", 1)
    ov = _slope_ema_span_overrides().get(str(ratio))
    return max(1, int(ov)) if ov is not None else max(1, int(base))


def _slope_tfs_for_ratio(ratio: int) -> list[str]:
    return [CONFIG[k]["label"] for k in TF_KEYS if int(CONFIG[k].get("htf_ratio") or 0) == ratio]


def _parse_prog_ema_number(raw: str) -> tuple[Optional[int], Optional[float]]:
    """Один аргумент: целое ≥1 → span EMA; 0 / дробь → порог %."""
    s = raw.strip().replace(",", ".")
    val = float(s)
    if s == "0" or "." in s:
        return None, val
    if val >= 1 and val == int(val):
        return max(1, int(val)), None
    return None, val


def _set_slope_ema_span(target: int | str, span: int) -> list[int]:
    """target: htf_ratio, 'all' или 'active' (→ ratio активного ТФ)."""
    span = max(1, int(span))
    overrides = dict(_slope_ema_span_overrides())
    if target == "all":
        ratios = list(SLOPE_EMA_PROFILES.keys())
    elif target == "active":
        prof = _slope_profile_for_tf(state.active_tf)
        if not prof:
            raise ValueError("no_profile")
        ratios = [int(prof["htf_ratio"])]
    else:
        ratios = [int(target)]
    for ratio in ratios:
        if ratio not in SLOPE_EMA_PROFILES:
            continue
        overrides[str(ratio)] = span
        ohlcv_tf = SLOPE_EMA_PROFILES[ratio]["ohlcv_tf"]
        _slope_ohlcv_cache.pop(ohlcv_tf, None)
    CONFIG["slope_ema_spans"] = overrides
    return ratios


def _slope_active_tf_summary(tf_name: Optional[str] = None) -> tuple[str, Optional[dict]]:
    """Краткое описание slope-настроек для ТФ."""
    tf_name = tf_name or state.active_tf
    tfl = CONFIG[tf_name]["label"]
    prof = _slope_profile_for_tf(tf_name)
    if not prof:
        return f"⚠️ У [{tfl}] нет slope-фильтра", None
    th = _slope_ema_threshold()
    th_txt = "0%" if th <= 0 else f"{th:g}%"
    flat = "" if th <= 0 else " (мёртвая зона вкл)"
    siblings = _slope_tfs_for_ratio(int(prof["htf_ratio"]))
    shared = ""
    if len(siblings) > 1:
        shared = f"\nТак же для: {', '.join(siblings)}"
    text = (
        f"📏 [{tfl}] — текущие настройки\n"
        f"Slope {_slope_ema_label(prof['span'])} @ {prof['label']}, порог {th_txt}{flat}"
        f"{shared}\n\n"
        f"👇 Нажми кнопку ниже\n"
        f"или отправь: /prog_ema 2 0"
    )
    return text, prof


def _prog_ema_keyboard() -> Optional[InlineKeyboardMarkup]:
    prof = _slope_profile_for_tf(state.active_tf)
    if not prof:
        return None
    cur = prof["span"]
    th = _slope_ema_threshold()
    def _ema_btn(n: int) -> InlineKeyboardButton:
        mark = "✅ " if cur == n and th <= 0 else ""
        return InlineKeyboardButton(f"{mark}EMA{n} · 0%", callback_data=f"prog_ema:{n}:0")
    return InlineKeyboardMarkup([
        [_ema_btn(1), _ema_btn(2), _ema_btn(3)],
        [
            InlineKeyboardButton(
                f"{'✅ ' if th == 0.02 else ''}порог 0.02%",
                callback_data="prog_ema:_:0.02",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if th <= 0 else ''}только порог 0%",
                callback_data="prog_ema:_:0",
            ),
        ],
    ])


def _apply_prog_ema_settings(
    tf_name: str,
    span: Optional[int] = None,
    threshold: Optional[float] = None,
) -> tuple[bool, str]:
    tfl = CONFIG[tf_name]["label"]
    prof = _slope_profile_for_tf(tf_name)
    if not prof:
        return False, f"⚠️ У [{tfl}] нет slope-фильтра.\nВыбери другой ТФ: /tf"
    if threshold is not None and threshold < 0:
        return False, "⚠️ Порог не может быть отрицательным"
    parts: list[str] = []
    if span is not None:
        _set_slope_ema_span("active", span)
        parts.append(f"EMA{span} @ {prof['label']}")
    if threshold is not None:
        CONFIG["slope_ema_threshold_pct"] = threshold
        parts.append("порог 0%" if threshold <= 0 else f"порог {threshold:g}%")
    if not parts:
        return False, "⚠️ Нечего менять"
    save_bot_state()
    prof = _slope_profile_for_tf(tf_name)
    ema_lbl = _slope_ema_label(prof["span"]) if prof else "EMA?"
    th = _slope_ema_threshold()
    th_txt = "0%" if th <= 0 else f"{th:g}%"
    return True, (
        f"✅ [{tfl}] {', '.join(parts)}\n"
        f"Сейчас: {ema_lbl} @ {prof['label'] if prof else '?'}, порог {th_txt}"
    )


def _slope_profile_for_tf(tf_name: str) -> Optional[dict]:
    """EMA span + OHLCV ТФ для slope-фильтра; None если для ТФ фильтр не задан."""
    ratio = int(CONFIG.get(tf_name, {}).get("htf_ratio") or 0)
    base = SLOPE_EMA_PROFILES.get(ratio)
    if not base:
        return None
    return {**base, "span": _slope_effective_span(ratio), "htf_ratio": ratio}


def _slope_ema_label(span: int) -> str:
    return f"EMA{span}"


def _slope_ema_threshold() -> float:
    try:
        return float(CONFIG.get("slope_ema_threshold_pct", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _slope_is_flat(slope_pct: float, threshold: Optional[float] = None) -> bool:
    th = _slope_ema_threshold() if threshold is None else threshold
    return th > 0 and abs(slope_pct) < th


def _slope_timing_mode() -> str:
    mode = str(CONFIG.get("slope_timing_mode") or "hermes").strip().lower()
    return mode if mode in ("hermes", "trigger") else "hermes"


HERMES_SLOPE_OFFSETS_H = [0, -1, -2, -3]


def _slope_hermes_series(df: pd.DataFrame, span: int) -> pd.Series:
    ema = df["close"].ewm(span=span, adjust=False).mean()
    prev = ema.shift(1)
    return ((ema - prev) / prev * 100).dropna()


def _hermes_slope_lookup(slope_1h: pd.Series, htf_time, offsets: list[int]) -> Optional[float]:
    try:
        htf_floor = pd.Timestamp(htf_time).floor("1h")
    except Exception:
        return None
    for off in offsets:
        c = htf_floor + pd.Timedelta(hours=off)
        if c in slope_1h.index:
            v = slope_1h.loc[c]
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                return float(v)
    return None


def _slope_trend_label(slope_pct: Optional[float], threshold: Optional[float] = None) -> str:
    if slope_pct is None:
        return "нет данных"
    if _slope_is_flat(slope_pct, threshold):
        return "боковик"
    if slope_pct > 0:
        return "вверх"
    if slope_pct < 0:
        return "вниз"
    return "нейтрально"


def _slope_filter_ok_hermes(
    direction: str,
    slope_pct: Optional[float],
    threshold: Optional[float] = None,
) -> bool:
    if slope_pct is None:
        return True
    th = _slope_ema_threshold() if threshold is None else threshold
    if th == 0:
        if (slope_pct > 0 and direction != "LONG") or (slope_pct < 0 and direction != "SHORT"):
            return False
        return True
    if abs(slope_pct) < th:
        return True
    if slope_pct > th and direction != "LONG":
        return False
    if slope_pct < -th and direction != "SHORT":
        return False
    return True


def _ohlcv_bar_timedelta(timeframe: str) -> pd.Timedelta:
    tf = str(timeframe or "").strip().lower()
    if tf.endswith("h"):
        return pd.Timedelta(hours=int(tf[:-1] or 1))
    if tf.endswith("m"):
        return pd.Timedelta(minutes=int(tf[:-1] or 1))
    if tf.endswith("d"):
        return pd.Timedelta(days=int(tf[:-1] or 1))
    return pd.Timedelta(hours=1)


def _closed_ohlcv_before(
    df: Optional[pd.DataFrame], as_of, bar_delta: pd.Timedelta,
) -> Optional[pd.DataFrame]:
    """Бары OHLCV, полностью закрытые на момент as_of (open + bar_delta <= as_of)."""
    if df is None or len(df) < 1:
        return None
    try:
        ts = pd.Timestamp(as_of)
    except Exception:
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    mask = idx + bar_delta <= ts
    closed = df.loc[mask]
    return closed if len(closed) >= 1 else None


def _slope_signal_as_of(sig: dict) -> pd.Timestamp:
    """Момент триггера сигнала — для slope не сдвигаем на время постановки ордера."""
    raw = sig.get("trigger_bar_time") or sig.get("timestamp") or sig.get("htf_time")
    if not raw:
        return pd.Timestamp(utcnow())
    return pd.Timestamp(raw)


async def _slope_filter_ok_for_sig(
    direction: str,
    sig: dict,
    ohlcv_tf: str,
    span: int,
    threshold: Optional[float] = None,
) -> tuple[bool, Optional[float], str, pd.Timestamp]:
    th = _slope_ema_threshold() if threshold is None else threshold
    if _slope_timing_mode() == "hermes":
        raw_htf = sig.get("htf_time") or sig.get("trigger_bar_time") or sig.get("timestamp")
        if not raw_htf:
            return True, None, "нет htf", pd.Timestamp(utcnow())
        as_of = pd.Timestamp(raw_htf).floor("1h")
        need = span + 8
        df = await fetch_ohlcv(ohlcv_tf, limit=max(need, 48))
        if df is None or len(df) < span + 2:
            return True, None, "нет данных", as_of
        slope_1h = _slope_hermes_series(df, span)
        slope_pct = _hermes_slope_lookup(slope_1h, raw_htf, HERMES_SLOPE_OFFSETS_H)
        trend = _slope_trend_label(slope_pct, th)
        ok = _slope_filter_ok_hermes(direction, slope_pct, th)
        return ok, slope_pct, trend, as_of
    as_of = _slope_signal_as_of(sig)
    need = span + 4
    df = await fetch_ohlcv(ohlcv_tf, limit=max(need, 24))
    bar_delta = _ohlcv_bar_timedelta(ohlcv_tf)
    closed = _closed_ohlcv_before(df, as_of, bar_delta)
    ok, slope_pct, trend = _slope_filter_ok(direction, closed, span, threshold)
    return ok, slope_pct, trend, as_of


def _calc_slope_ema(
    df: Optional[pd.DataFrame], span: int, threshold: Optional[float] = None,
) -> tuple[Optional[float], str]:
    """Наклон EMA по двум последним закрытым барам OHLCV."""
    need = span + 2
    if df is None or len(df) < need:
        return None, "нет данных"
    ema = df["close"].ewm(span=span, adjust=False).mean()
    prev, cur = float(ema.iloc[-3]), float(ema.iloc[-2])
    if prev <= 0:
        return None, "нет данных"
    slope_pct = (cur - prev) / prev * 100
    if _slope_is_flat(slope_pct, threshold):
        return slope_pct, "боковик"
    if slope_pct > 0:
        return slope_pct, "вверх"
    if slope_pct < 0:
        return slope_pct, "вниз"
    return slope_pct, "нейтрально"


def _slope_allowed_directions(slope_pct: Optional[float], threshold: Optional[float] = None) -> str:
    if slope_pct is None:
        return "—"
    if _slope_is_flat(slope_pct, threshold):
        return "LONG + SHORT"
    if slope_pct > 0:
        return "только LONG"
    if slope_pct < 0:
        return "только SHORT"
    return "LONG + SHORT"


def _slope_filter_ok(
    direction: str,
    df: Optional[pd.DataFrame],
    span: int,
    threshold: Optional[float] = None,
) -> tuple[bool, Optional[float], str]:
    slope_pct, trend = _calc_slope_ema(df, span, threshold)
    if slope_pct is None:
        return True, None, trend
    if _slope_is_flat(slope_pct, threshold):
        return True, slope_pct, trend
    if direction == "LONG" and slope_pct > 0:
        return True, slope_pct, trend
    if direction == "SHORT" and slope_pct < 0:
        return True, slope_pct, trend
    return False, slope_pct, trend


async def _get_slope_ohlcv_cached(ohlcv_tf: str, span: int) -> Optional[pd.DataFrame]:
    cache_s = 90
    now = time.time()
    slot = _slope_ohlcv_cache.setdefault(ohlcv_tf, {"df": None, "ts": 0.0})
    cached = slot.get("df")
    if cached is not None and now - float(slot.get("ts") or 0) < cache_s:
        return cached
    df = await fetch_ohlcv(ohlcv_tf, limit=span + 4)
    if df is not None:
        slot["df"] = df
        slot["ts"] = now
    return df


def _slope_filter_desc(tf_name: str) -> str:
    prof = _slope_profile_for_tf(tf_name)
    if not prof:
        return "нет профиля"
    th = _slope_ema_threshold()
    th_s = f", порог {th:g}%" if th > 0 else ", порог 0%"
    mode_s = "hermes" if _slope_timing_mode() == "hermes" else "trigger"
    return f"{_slope_ema_label(prof['span'])} {prof['label']}{th_s} ({mode_s})"


async def _slope_status_block(tf_name: str) -> tuple[str, Optional[float], str, Optional[dict]]:
    """Текст наклона + slope/trend + профиль для TG-команд."""
    prof = _slope_profile_for_tf(tf_name)
    if not prof:
        return "Slope: нет профиля для этого ТФ", None, "—", None
    df = await _get_slope_ohlcv_cached(prof["ohlcv_tf"], prof["span"])
    th = _slope_ema_threshold()
    if _slope_timing_mode() == "hermes" and df is not None and len(df) >= prof["span"] + 2:
        slope_1h = _slope_hermes_series(df, prof["span"])
        slope_pct = _hermes_slope_lookup(slope_1h, utcnow(), HERMES_SLOPE_OFFSETS_H)
        trend = _slope_trend_label(slope_pct, th)
    else:
        slope_pct, trend = _calc_slope_ema(df, prof["span"], th)
    ema_lbl = _slope_ema_label(prof["span"])
    tf_lbl = prof["label"]
    if slope_pct is None:
        block = f"Наклон: нет данных ({trend})"
    else:
        block = f"Наклон {ema_lbl}: {slope_pct:+.4f}%/{tf_lbl}  ({trend})"
    return block, slope_pct, trend, prof


def _format_signal_tg_brief(sig: dict, tf_name: str) -> str:
    direction = str(sig.get("direction") or "?")
    entry = float(sig.get("entry") or 0)
    stop = float(sig.get("stop") or 0)
    tp = float(sig.get("tp") or 0)
    tfl = tf_label(tf_name)
    arrow = "📈" if direction == "LONG" else "📉"
    sweep = f"{sig['htf_sweep_level']:.1f}" if sig.get("htf_sweep_level") else "—"
    lines = [
        f"{arrow} {direction} [{tfl}]",
        f"Entry: {entry:.1f}  Stop: {stop:.1f}  TP: {tp:.1f}",
        f"Свип: {sweep}",
    ]
    ts = sig.get("timestamp") or sig.get("htf_time")
    if ts:
        try:
            dt = pd.Timestamp(ts).to_pydatetime().replace(tzinfo=None)
            msk_dt = msk(dt)
            if msk_dt:
                lines.append(f"HTF: {msk_dt.strftime('%Y-%m-%d %H:%M')} МСК")
        except Exception:
            pass
    return "\n".join(lines)


# ============================================================
# СОЗДАНИЕ ОЖИДАЮЩЕГО ОРДЕРА
# ============================================================
def _min_contracts_for_notional(entry: float) -> int:
    """Минимум контрактов для min_notional_usdt на MEXC."""
    cv = _contract_value()
    mn = float(CONFIG["min_notional_usdt"])
    floor_ctr = int(CONFIG["min_contracts"])
    if entry <= 0 or cv <= 0:
        return floor_ctr
    return max(floor_ctr, int(math.ceil(mn / (entry * cv))))


def _calc_position_contracts(
    entry: float,
    stop: float,
    free: float,
    total: float,
    symbol_key: Optional[str] = None,
    quality_size_mult: float = 1.0,
) -> tuple[int, float, float, float, int]:
    """
    Размер позиции: риск + size_mult × quality_size_mult, с подъёмом до биржевого минимума.
    Returns: contracts, notional, required_margin, avail_margin, sized_before_floor.
    """
    cv = _contract_value(symbol_key)
    reserve = free * CONFIG["margin_reserve_pct"] / 100
    avail_margin = free - reserve
    risk_usdt = max(total, free) * CONFIG["risk_per_trade_pct"] / 100
    stop_pct = abs(stop - entry) / entry if entry > 0 else 0.0
    if stop_pct <= 0:
        return 0, 0.0, 0.0, avail_margin, 0

    max_notional = avail_margin * CONFIG["leverage"]
    pos_notional = min(risk_usdt / stop_pct, max_notional)
    contracts = round(pos_notional / entry / cv)
    try:
        sm = float(CONFIG.get("size_mult", 1.0))
    except Exception:
        sm = 1.0
    try:
        qm = float(quality_size_mult)
    except Exception:
        qm = 1.0
    if not math.isfinite(qm) or qm <= 0:
        qm = 1.0
    if not _quality_size_enabled():
        qm = 1.0
    mult = sm * qm
    if mult > 0 and mult != 1.0:
        contracts = max(1, int(round(contracts * mult)))
    sized = int(contracts)
    contracts = max(sized, _min_contracts_for_notional(entry))
    notional = contracts * entry * cv
    required_margin = notional / CONFIG["leverage"]
    return int(contracts), float(notional), float(required_margin), float(avail_margin), sized


def _sig_physical_dedup_key(sig: dict, tf_name: str) -> str:
    """Один trigger-бар + направление = одна нога (не плодить сигналы из разных HTF-окон)."""
    direction = str(sig.get("direction") or "")
    raw = sig.get("trigger_bar_time") or sig.get("timestamp") or ""
    try:
        tr = str(pd.Timestamp(raw)) if raw else ""
    except Exception:
        tr = str(raw) if raw else ""
    return f"{active_symbol_key()}|{tf_name}|{direction}|{tr}"


def _sig_extreme_dedup_key(
    direction: str,
    tf_name: str,
    trigger_extreme: float,
    sweep_level: float,
) -> str:
    """Тот же wick-extreme + sweep bucket = та же нога (tie-break right без пересвипа)."""
    sk = active_symbol_key()
    sweep_r = _round_sweep_level(sweep_level, sk)
    dec = _price_decimals(symbol_profile(sk)["price_tick"])
    return (
        f"{tf_name}|{direction}|ext={_round_price(trigger_extreme, sk):.{dec}f}"
        f"|sw={sweep_r:.0f}"
    )


def _sig_physical_dedup_keys_for_emit(
    direction: str,
    tf_name: str,
    trigger_bar_time: str,
    trigger_extreme: float,
    sweep_level: float,
) -> list[str]:
    keys = [
        _sig_physical_dedup_key(
            {"direction": direction, "trigger_bar_time": trigger_bar_time},
            tf_name,
        ),
    ]
    keys.append(
        _sig_extreme_dedup_key(direction, tf_name, trigger_extreme, sweep_level),
    )
    return keys


def _msk_sig_ts(raw) -> str:
    if not raw:
        return "—"
    try:
        if isinstance(raw, datetime):
            dt = raw
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", ""))
        m = msk(dt)
        return m.strftime("%Y-%m-%d %H:%M") if m else str(raw)[:16]
    except Exception:
        return str(raw)[:16]


def _format_signal_context(sig: dict, tf_name: str) -> str:
    """Карточка сетапа для skip-сообщений: пара, UTC и МСК."""
    direction = str(sig.get("direction") or "?")
    tfl = tf_label(tf_name)
    arrow = "📈" if direction == "LONG" else "📉"
    sk = str(sig.get("symbol_key") or "") or active_symbol_key()
    if sk not in SYMBOL_PROFILES:
        sk = active_symbol_key()
    lbl = symbol_profile(sk)["label"]
    htf_name = tf_htf_name(tf_name)
    entry = float(sig.get("entry") or 0)
    stop = float(sig.get("stop") or 0)
    tp = float(sig.get("tp") or 0)
    cisd = float(sig.get("cisd_level") or entry)
    sl_pct = abs(stop - entry) / entry * 100 if entry > 0 else 0
    tp_pct = abs(tp - entry) / entry * 100 if entry > 0 else 0
    rr = tp_pct / sl_pct if sl_pct > 0 else 0
    sweep = _fmt_px(sig["htf_sweep_level"], sk) if sig.get("htf_sweep_level") else "—"
    bh = _fmt_px(sig["base_high"], sk) if sig.get("base_high") else "—"
    bl = _fmt_px(sig["base_low"], sk) if sig.get("base_low") else "—"
    tr_ext = _safe_float(sig.get("trigger_extreme"))
    tr_ext_s = _fmt_px(tr_ext, sk) if tr_ext is not None else "—"
    entry_kind = _entry_kind_for_signal(sig)
    trig_raw = sig.get("trigger_bar_time") or sig.get("timestamp")

    lines = [
        f"Инструмент: {lbl}",
        f"{arrow} {direction} [{tfl}]",
        f"Сигнал: {_fmt_when_utc_msk(trig_raw)}",
        f"HTF-окно ({htf_name}): {_fmt_when_utc_msk(sig.get('htf_time'))}",
        f"Sweep: {sweep}  Ext: {tr_ext_s}",
        f"CISD: {_fmt_px(cisd, sk)}  |  вход {entry_kind}",
        f"Stop: {_fmt_px(stop, sk)} ({sl_pct:.2f}%)  |  "
        f"TP: {_fmt_px(tp, sk)} ({tp_pct:.2f}%)  |  R:R {rr:.2f}",
        f"База: H={bh}  L={bl}",
    ]
    if sig.get("confirm_bar_time"):
        ctf = str(sig.get("confirm_timeframe") or "")
        ctf_s = f" ({ctf})" if ctf else ""
        lines.append(
            f"MSS confirm: {_fmt_when_utc_msk(sig.get('confirm_bar_time'))}{ctf_s}"
        )
    h = str(sig.get("hash") or "")
    if h:
        lines.append(f"hash: {h[:16]}")
    return "\n".join(lines)


def _consume_sig_sweep_leg(sig: dict, tf_name: str) -> None:
    """Закрыть HTF-ногу после обработки сигнала (в т.ч. skip) — не плодить повторы."""
    tr_ext = _safe_float(sig.get("trigger_extreme"))
    sweep = float(sig.get("htf_sweep_level") or 0)
    if tr_ext is None or sweep <= 0:
        return
    htf = str(sig.get("htf_time") or "")
    if not htf:
        ratio = int(CONFIG.get(tf_name, {}).get("htf_ratio") or 60)
        htf = _htf_window_start(utcnow(), ratio).isoformat()
    _mark_htf_sweep_consumed(
        tf_name,
        str(sig.get("direction") or ""),
        htf,
        trigger_extreme=float(tr_ext),
        sweep_level=sweep,
        stop=float(sig.get("stop") or 0),
        tp=float(sig.get("tp") or 0),
        trigger_idx=int(sig.get("trigger_idx") or -1),
    )


async def _notify_signal_skip(
    sig: dict,
    tf_name: str,
    category: str,
    *,
    header: str,
    detail: str = "",
    telegram: bool = True,
    consume_leg: bool = True,
) -> None:
    """Журнал + processed; TG — не чаще одного раза на category+physical trigger."""
    if consume_leg:
        _consume_sig_sweep_leg(sig, tf_name)

    sep = "─" * 34
    parts = [header.rstrip(), sep, _format_signal_context(sig, tf_name)]
    if detail.strip():
        parts.extend([sep, detail.strip()])
    msg = "\n".join(parts)

    reason = msg.replace("\n", " | ")
    _journal_log_signal_skipped(sig, tf_name, reason, category)
    h = str(sig.get("hash") or "")
    if h:
        _mark_signal_skipped(h)
    if not telegram:
        return
    phys = _sig_physical_dedup_key(sig, tf_name)
    ext_k = _sig_extreme_dedup_key(
        str(sig.get("direction") or ""),
        tf_name,
        float(_safe_float(sig.get("trigger_extreme")) or 0),
        float(sig.get("htf_sweep_level") or 0),
    )
    keys = [f"{category}:{phys}", f"{category}:{ext_k}"]
    if any(k in state.skip_tg_keys for k in keys):
        return
    state.skip_tg_keys.update(keys)
    if len(state.skip_tg_keys) > 400:
        state.skip_tg_keys = set(list(state.skip_tg_keys)[-200:])
    ok = await send_telegram(msg)
    if ok is None and _tg_online and _tg_app is not None:
        for k in keys:
            _release_skip_tg_key(k)


def _format_sig_timestamp(sig: dict) -> str:
    raw = sig.get("timestamp") or sig.get("trigger_bar_time") or sig.get("htf_time")
    if not raw:
        return "?"
    try:
        if isinstance(raw, datetime):
            dt = raw
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", ""))
        return msk(dt).strftime("%d.%m %H:%M")
    except Exception:
        return str(raw)[:16]


def _pair_busy(symbol_key: str) -> bool:
    """У пары уже есть open-позиция или pending-лимитка (любой ТФ)."""
    for p in state.positions:
        if p.status == "open" and _pos_symbol_key(p) == symbol_key:
            return True
    for pl in state.pending_limits:
        if pl.status == "pending" and _pos_symbol_key(pl) == symbol_key:
            return True
    return False


def _open_pending_count() -> int:
    n_open = sum(1 for p in state.positions if p.status == "open")
    n_pend = sum(1 for p in state.pending_limits if p.status == "pending")
    return n_open + n_pend


def _vwap_gate(df: pd.DataFrame, sig: dict) -> tuple[bool, float, str]:
    """Причинный vwap-фильтр на scan-баре: SHORT vd≤0, LONG vd≤−3."""
    from backtest.vwap_filter import daily_session_vwap
    from backtest.sweep_atr_filter import compute_atr14

    scan_raw = sig.get("confirm_bar_time") or sig.get("timestamp")
    df_cut = df
    if scan_raw:
        try:
            ts = pd.Timestamp(scan_raw)
            if getattr(ts, "tzinfo", None) is not None:
                ts = ts.tz_localize(None) if ts.tzinfo else ts.tz_convert(None).tz_localize(None)
            df_cut = df.loc[:ts]
        except Exception:
            df_cut = df.iloc[:-1] if len(df) >= 2 else df
    elif len(df) >= 2:
        df_cut = df.iloc[:-1]
    if df_cut is None or len(df_cut) < 15:
        return True, 0.0, "vwap: мало баров — фильтр не применён"
    vwap = daily_session_vwap(df_cut)
    atr = compute_atr14(df_cut)
    close = float(df_cut.iloc[-1]["close"])
    vw = float(vwap.iloc[-1])
    at = float(atr.iloc[-1])
    if not (at > 0) or pd.isna(vw) or pd.isna(at):
        return True, 0.0, "vwap: ATR/VWAP недоступен"
    vd = (close - vw) / at
    direction = str(sig.get("direction") or "")
    ok = (direction == "SHORT" and vd <= 0.0) or (direction == "LONG" and vd <= -3.0)
    reason = f"vd={vd:.2f}  close={close:.6g} vwap={vw:.6g} ATR14={at:.6g}"
    if not ok:
        need = "≤ 0" if direction == "SHORT" else "≤ −3"
        reason += f"  ({direction} нужно {need})"
    return ok, vd, reason


def _utc_iso_short(raw) -> str:
    if not raw:
        return "—"
    try:
        ts = pd.Timestamp(raw)
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return ts.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(raw)[:16]


def _format_position_taken_tg(
    direction: str,
    trade_num: int,
    symbol_key: str,
    tf_name: str,
    entry: float,
    stop: float,
    tp: float,
    risk_usdt: float,
    *,
    signal_time: str = "",
    htf_time: str = "",
) -> str:
    arrow = "📈" if direction == "LONG" else "📉"
    sk_lbl = symbol_profile(symbol_key)["label"]
    tfl = tf_label(tf_name)
    risk_pct = float(CONFIG.get("risk_per_trade_pct") or 1.0)
    sig_s = _utc_iso_short(signal_time)
    htf_s = _utc_iso_short(htf_time)
    htf_part = f" (HTF {htf_s})" if htf_time else ""
    return (
        f"{_mode_prefix()} {arrow} {direction} #{trade_num}\n"
        f"Инструмент: {sk_lbl}\n"
        f"ТФ: {tfl}\n"
        f"Сигнал: {sig_s}{htf_part}\n"
        f"Вход: {_fmt_px(entry, symbol_key)} | Стоп: {_fmt_px(stop, symbol_key)} | "
        f"Тейк: {_fmt_px(tp, symbol_key)}\n"
        f"Риск: {risk_usdt:.2f} USDT ({risk_pct:.1f}%)"
    )


async def create_pending_limit(sig: dict, tf_name: str, trade_num: int = 0) -> bool:
    tf_cfg  = CONFIG[tf_name]
    direction = str(sig.get("direction") or "")
    sk = active_symbol_key()
    sig.setdefault("symbol_key", sk)

    if _pair_busy(sk):
        logger.info(f"SKIP pair busy: {sk} {direction} [{tf_name}]")
        await _notify_signal_skip(
            sig, tf_name, "skipped_pair_busy",
            header=f"⛔ Пропуск {direction} [{tf_label(tf_name)}] — пара {symbol_profile(sk)['label']} занята",
        )
        return False
    if _open_pending_count() >= int(CONFIG.get("max_positions") or 7):
        logger.info(f"SKIP max positions: {direction} [{tf_name}]")
        await _notify_signal_skip(
            sig, tf_name, "skipped_max_positions",
            header=f"⛔ Пропуск {direction} [{tf_label(tf_name)}] — лимит 7 позиций",
        )
        return False

    entry_px = float(sig.get("entry") or 0)
    stop_px = float(sig.get("stop") or 0)
    if entry_px > 0 and stop_px > 0:
        stop_pct = abs(stop_px - entry_px) / entry_px * 100.0
        min_stop = float(CONFIG.get("min_stop_pct") or 0.25)
        if stop_pct < min_stop:
            logger.info(f"SKIP min_stop: {stop_pct:.3f}% < {min_stop}%")
            await _notify_signal_skip(
                sig, tf_name, "skipped_min_stop",
                header=f"⛔ Пропуск {direction} [{tf_label(tf_name)}] — стоп {stop_pct:.2f}% < {min_stop}%",
            )
            return False

    cisd = float(sig.get("cisd_level") or entry_px)
    price_ref = _signal_entry_price_ref(sig)
    if price_ref <= 0:
        price_ref = get_price(sk) or 0.0
    if cisd > 0 and price_ref > 0 and not _is_retrace_at_creation(direction, cisd, price_ref):
        logger.info(
            f"SKIP implicit MARKET: {direction} [{tf_name}] "
            f"ref={price_ref} уже за cisd={cisd}"
        )
        await _notify_signal_skip(
            sig, tf_name, "skipped_implicit_market",
            header=(
                f"⛔ Пропуск {direction} [{tf_label(tf_name)}] — цена уже за уровнем, "
                "неявный MARKET"
            ),
            detail=f"ref={_fmt_px(price_ref, sk)}  cisd={_fmt_px(cisd, sk)}",
        )
        return False

    parent_pos = _find_open_position_for_pyramid(direction, tf_name)
    is_pyramid = parent_pos is not None

    # Frozen quality-stop применяется только к новой ноге; pyramid наследует SL родителя.
    if not is_pyramid:
        _apply_quality_stop_to_signal(sig, tf_name)

    if not is_pyramid and not _allow_both_directions() and _has_opposite_open_position(direction):
        opp = "SHORT" if direction == "LONG" else "LONG"
        logger.info(
            f"SKIP OPPOSITE: {direction} [{tf_name}] — open/pending {opp} (one-way)"
        )
        return False

    # Ручной бан сетапа (после /close): до конца HTF-окна и только по SL/TP.
    # Храним в processed, чтобы работало надёжно и переживало рестарты.
    if not state.paper:
        htf_time = str(sig.get("htf_time") or "")
        if not htf_time:
            ratio = int(tf_cfg.get("htf_ratio") or 60)
            htf_time = _htf_window_start(utcnow(), ratio).isoformat()
        ban_h = _manual_setup_ban_hash(
            tf=tf_name,
            direction=direction,
            htf_time=htf_time,
            sl=float(sig.get("stop") or 0),
            tp=float(sig.get("tp") or 0),
        )
        if ban_h in state.processed:
            logger.info(f"MANUAL BAN HIT: {ban_h} tf={tf_name} dir={sig.get('direction')} htf={htf_time} sl/tp={sig.get('stop')}/{sig.get('tp')}")
            return False

        if is_pyramid:
            if _has_pyramid_pending(direction, tf_name):
                logger.info(
                    f"SKIP PYRAMID: {direction} [{tf_name}] — уже есть pending доливка"
                )
                return False
        else:
            # Один триггер на HTF-окно (любое направление — opposite/2nd CISD skip).
            conflict = _same_htf_open_or_pending(direction, htf_time, tf_name)
            if conflict:
                logger.info(
                    f"SKIP HTF ONE-SHOT: {sig.get('direction')} [{tf_name}] "
                    f"HTF {htf_time} уже использовано ({conflict})"
                )
                used = conflict.startswith("USED ")
                header = (
                    f"⛔ Пропуск {sig.get('direction')} [{tf_label(tf_name)}] — "
                    + (
                        f"HTF-окно уже использовано ({conflict})"
                        if used else
                        f"HTF занят ({conflict})"
                    )
                )
                await _notify_signal_skip(
                    sig,
                    tf_name,
                    "skipped_htf_one_shot",
                    header=header,
                )
                return False

        if not is_pyramid and _duplicate_active_setup(sig, tf_name):
            logger.info(
                f"SKIP DUP SETUP: {sig.get('direction')} tf={tf_name} "
                f"entry={sig.get('entry')} hash={sig.get('hash', '')[:8]}"
            )
            return False

        setup_conflict = _active_same_setup_conflict(sig, tf_name)
        if setup_conflict and not is_pyramid:
            logger.info(
                f"SKIP SAME LEG: {sig.get('direction')} tf={tf_name} "
                f"sl/tp={sig.get('stop')}/{sig.get('tp')} ({setup_conflict})"
            )
            return False

    # Дедупликация pending: то же направление + HTF или близкий entry (любой HTF).
    async with _create_pending_lock:
        sig_htf = _htf_time_for_sig(sig, tf_name)
        if _has_pending_for_htf(tf_name, str(sig.get("direction") or ""), sig_htf):
            logger.info(
                f"Дубль пропущен: pending {sig.get('direction')} [{tf_name}] "
                f"HTF {sig_htf} уже есть"
            )
            return False
        near = _find_near_pending_duplicate(
            tf_name, str(sig.get("direction") or ""),
            float(sig["entry"]), float(sig["stop"]),
        )
        if near is not None:
            logger.info(
                f"Дубль пропущен: уже есть {near.direction} pending "
                f"@ {near.entry_price:.1f} (HTF {_htf_time_for_pending(near, tf_name)}, "
                f"новый HTF {sig_htf})"
            )
            return False

    confirm_close = _safe_float(sig.get("confirm_close")) or 0.0
    rr_stop = float(parent_pos.stop_price) if is_pyramid and parent_pos else float(sig["stop"])
    rr_tp = float(parent_pos.tp_price) if is_pyramid and parent_pos else float(sig["tp"])

    if not _sig_has_mss_confirm(sig):
        logger.info(f"SKIP no MSS: {sig.get('direction')} [{tf_name}]")
        await _notify_signal_skip(
            sig,
            tf_name,
            "skipped_no_mss",
            header=f"⛔ Пропуск {sig.get('direction')} [{tf_label(tf_name)}] — нет MSS confirm",
        )
        return False

    if not is_pyramid:
        tp_hit, tp_detail = await _hist_tp_already_touched(
            direction=str(sig.get("direction") or ""),
            tp=float(sig.get("tp") or 0),
            tf_name=tf_name,
            confirm_bar_time=str(sig.get("confirm_bar_time") or ""),
            trigger_bar_time=str(sig.get("trigger_bar_time") or ""),
        )
        if tp_hit:
            logger.info(
                f"SKIP TP already hit: {sig.get('direction')} [{tf_name}] {tp_detail}"
            )
            await _notify_signal_skip(
                sig,
                tf_name,
                "skipped_tp_already_hit",
                header=(
                    f"⛔ Пропуск {sig.get('direction')} [{tf_label(tf_name)}] — "
                    f"TP уже был до входа"
                ),
            )
            htf_time = str(sig.get("htf_time") or "")
            _ban_setup_after_tp_miss(
                htf_time,
                tf=tf_name,
                direction=str(sig.get("direction") or ""),
                sl=float(sig.get("stop") or 0),
                tp=float(sig.get("tp") or 0),
                sig_hash=str(sig.get("hash") or ""),
            )
            if htf_time:
                _mark_htf_taken(
                    tf_name, htf_time,
                    direction=str(sig.get("direction") or ""),
                )
            return False

    cisd = float(sig.get("cisd_level") or sig["entry"])
    tf4_bar3_limit = bool(sig.get("tf4_bar3_limit_retest", False))
    entry_kind_pre = _entry_kind_for_signal(sig)
    price_ref = _signal_entry_price_ref(sig)
    rr_entry = _entry_price_for_rr(entry_kind_pre, cisd, price_ref)
    ok_rr, rr_val, rr_reason = _passes_min_rr(
        sig["direction"], rr_entry, rr_stop, rr_tp,
    )
    if not ok_rr:
        # Важно: RR считается по rr_stop/rr_tp (в пирамидинге может быть от родителя),
        # не по sig['stop']/sig['tp'] — в логе печатаем именно то, что проверяли.
        logger.info(
            f"SKIP min_rr: {sig['direction']} {rr_reason} "
            f"entry={rr_entry:.1f} stop={rr_stop:.1f} tp={rr_tp:.1f} "
            f"(sig_stop={float(sig['stop']):.1f} sig_tp={float(sig['tp']):.1f} kind={entry_kind_pre})"
        )
        tfl = tf_label(tf_name)
        entry_lbl = f"{rr_entry:.1f} ({entry_kind_pre})"
        header = (
            f"⛔ Пропуск {sig['direction']} [{tfl}] — невалидная геометрия"
            if "невалидная геометрия" in (rr_reason or "")
            else f"⛔ Пропуск {sig['direction']} [{tfl}] — R:R ниже мин."
        )
        await _notify_signal_skip(
            sig,
            tf_name,
            "skipped_min_rr",
            header=header,
            detail=(
                f"{rr_reason}\n"
                f"Entry: {entry_lbl}\n"
                f"Stop: {rr_stop:.1f}  TP: {rr_tp:.1f}\n"
                f"(sig Stop: {float(sig['stop']):.1f}  sig TP: {float(sig['tp']):.1f})"
            ),
        )
        return False

    gate_ok, gate_reason, gate_metrics = _economic_gate_decision(
        tf_name,
        sig["direction"],
        rr_entry,
        rr_stop,
        rr_tp,
        entry_kind_pre,
    )
    if gate_reason:
        mode = gate_metrics["mode"]
        logger.info(
            f"{'SKIP' if not gate_ok else 'SHADOW'} economic_gate: "
            f"{sig['direction']} [{tf_name}] kind={entry_kind_pre} {gate_reason} "
            f"entry={rr_entry:.4f} stop={rr_stop:.4f} tp={rr_tp:.4f}"
        )
        if not gate_ok:
            await _notify_signal_skip(
                sig,
                tf_name,
                "skipped_economic_gate",
                header=(
                    f"⛔ Пропуск {sig['direction']} [{tf_label(tf_name)}] — "
                    "economic gate"
                ),
                detail=(
                    f"{gate_reason}\n"
                    f"Entry: {_fmt_px(rr_entry)} ({entry_kind_pre})  "
                    f"Stop: {_fmt_px(rr_stop)}  TP: {_fmt_px(rr_tp)}"
                ),
            )
            return False

    price_live = get_price() or 0.0

    if entry_kind_pre == "LIMIT":
        stretched, stretch_reason = _sig_sweep_fib1_stretched(sig)
        if stretched:
            logger.info(f"SKIP fib1 (limit retest): {stretch_reason}")
            tfl = tf_label(tf_name)
            await _notify_signal_skip(
                sig,
                tf_name,
                "skipped_fib1",
                header=f"⛔ Пропуск LIMIT {sig['direction']} [{tfl}] — структура ≥ fib 1.0x",
                detail=stretch_reason,
            )
            return False

    bal = await get_balance_details()
    free  = float(bal.get("free")  or 0)
    total = float(bal.get("total") or 0)
    if max(free, total) < CONFIG["min_balance_usdt"]:
        logger.warning(
            f"Баланс total={total:.2f} free={free:.2f} < мин {CONFIG['min_balance_usdt']}"
        )
        await _notify_signal_skip(
            sig,
            tf_name,
            "skipped_min_balance",
            header=f"⚠️ Пропуск {sig['direction']}: баланс ниже минимума",
            detail=(
                f"Total: {total:.2f}  Free: {free:.2f}  "
                f"< {CONFIG['min_balance_usdt']:.2f}"
            ),
        )
        return False

    contracts, actual_notional, required_margin, avail_margin, sized = _calc_position_contracts(
        float(sig["entry"]), float(sig["stop"]), free, total,
        quality_size_mult=float(sig.get("quality_size_mult") or 1.0),
    )
    if contracts <= 0:
        return False

    qsm = float(sig.get("quality_size_mult") or 1.0)
    if _quality_size_enabled() and (
        abs(qsm - 1.0) > 1e-6 or sig.get("psl_probability") is not None
    ):
        psl_txt = ""
        if sig.get("psl_probability") is not None:
            psl_txt = (
                f" pSL={float(sig['psl_probability']):.3f}"
                f"/Q{sig.get('psl_quartile')}"
                f" adj×{float(sig.get('psl_adjustment') or 1.0):.2f}"
                f" model={sig.get('psl_model_version')}"
            )
        logger.info(
            f"SIZE Q: ×{qsm:.3f} (score={sig.get('quality_score')}) "
            f"→ {contracts} ctr (pre-floor sized={sized}){psl_txt}"
        )

    if contracts > sized:
        logger.info(
            f"SIZE BUMP: {sized}→{contracts} ctr "
            f"(min {CONFIG['min_notional_usdt']} USDT, notional={actual_notional:.1f})"
        )

    if required_margin > avail_margin:
        min_ctr = _min_contracts_for_notional(float(sig["entry"]))
        logger.warning(
            f"Маржи не хватает на мин. позицию: need={required_margin:.2f} "
            f"avail={avail_margin:.2f} ({contracts} ctr)"
        )
        await _notify_signal_skip(
            sig,
            tf_name,
            "skipped_min_margin",
            header=f"⚠️ Пропуск {sig['direction']}: не хватает маржи на мин. позицию",
            detail=(
                f"Нужно: {required_margin:.1f} USDT  |  Доступно: {avail_margin:.1f}\n"
                f"Мин. позиция: {contracts} контр. / {actual_notional:.1f} USDT\n"
                f"Увеличьте депозит или уменьшите margin_reserve_pct"
            ),
        )
        return False

    now = utcnow()
    limit_h = float(tf_cfg["limit_h"])
    timeout_at = now + timedelta(hours=limit_h)

    pl  = PendingLimit(
        lid         = f"L{uuid.uuid4().hex[:8]}",
        direction   = sig["direction"],
        entry_price = float(sig.get("cisd_level") or sig["entry"]),
        stop_price  = sig["stop"],
        tp_price    = sig["tp"],
        contracts   = contracts,
        created_at  = now,
        timeout_at  = timeout_at,
        exit_h      = tf_cfg["position_h"],
        tf          = tf_name,
        trade_num   = trade_num or state.next_trade_num(),
    )
    pl.symbol_key = active_symbol_key()
    ts = sig.get("trigger_bar_time") or sig.get("series_start_time") or ""
    if ts:
        pl.trigger_bar_at = _bar_time_to_utc(str(ts))
    pl.sig_hash = sig.get("hash", "")
    pl.htf_time = str(sig.get("htf_time") or "")
    pl.fib_1x   = _safe_float(sig.get("fib_1x"))
    pl.price_at_creation = price_live
    pl.confirm_close = confirm_close
    pl.confirm_bar_time = str(sig.get("confirm_bar_time") or "")
    pl.sweep_close_close = float(sig.get("sweep_close_close") or 0)
    pl.confirm_on_sweep = bool(sig.get("confirm_on_sweep", False))
    pl.cisd_level = float(sig.get("cisd_level") or sig["entry"])
    pl.sweep_level = _safe_float(sig.get("htf_sweep_level"))
    pl.cand_trigger_time = str(sig.get("cand_trigger_time") or "")
    pl.force_limit_retest = True
    pl.force_market = False
    pl.cisd_cross_market = False
    pl.entry_kind = "LIMIT"
    pl.defer_entry = False
    pl.entry_is_plan = False
    pl.vwap_dev = float(sig.get("vwap_dev") or 0)
    pl.quality_score = float(sig.get("quality_score") or 0)
    pl.quality_stop_original = _safe_float(sig.get("quality_stop_original"))
    pl.quality_stop_mult = float(sig.get("quality_stop_mult") or 1)
    pl.quality_stop_model = str(sig.get("quality_stop_model") or "")
    if is_pyramid and parent_pos:
        pl.pyramid_parent_id = parent_pos.id
        pl.stop_price = float(parent_pos.stop_price)
        pl.tp_price = float(parent_pos.tp_price)
    async with _create_pending_lock:
        sig_htf = _htf_time_for_sig(sig, tf_name)
        if not is_pyramid:
            race_htf = _same_htf_open_or_pending(pl.direction, sig_htf, tf_name)
            if race_htf:
                logger.info(
                    f"Дубль пропущен (race HTF): {pl.direction} [{tf_name}] "
                    f"HTF {sig_htf} ({race_htf})"
                )
                return False
        if _has_pending_for_htf(tf_name, pl.direction, sig_htf):
            logger.info(
                f"Дубль пропущен (race): pending {pl.direction} [{tf_name}] HTF {sig_htf}"
            )
            return False
        near = _find_near_pending_duplicate(
            tf_name, pl.direction, pl.entry_price, pl.stop_price,
        )
        if near is not None:
            logger.info(
                f"Дубль пропущен (race): {near.direction} pending "
                f"@ {near.entry_price:.1f} (HTF {_htf_time_for_pending(near, tf_name)})"
            )
            return False
        if not is_pyramid and _active_same_setup_conflict(sig, tf_name):
            logger.info(
                f"Дубль пропущен (race): setup {pl.direction} [{tf_name}] "
                f"sl/tp={pl.stop_price:.1f}/{pl.tp_price:.1f}"
            )
            return False
        state.pending_limits.append(pl)
        save_pending(state.pending_limits)
        if not is_pyramid and sig_htf:
            _mark_htf_taken(
                tf_name,
                sig_htf,
                direction=pl.direction,
                trade_num=pl.trade_num,
            )
    _journal_log_pending(pl, "pending_created")
    # Отмечаем сигнал обработанным ТОЛЬКО после успешного создания pending.
    # Иначе при ошибке постановки/кнопок /start сигнал пропадёт как «дубликат».
    if pl.sig_hash:
        state.processed.add(pl.sig_hash)
        save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])

    htf_lock_t = str(sig.get("htf_time") or pl.htf_time or "")
    if not htf_lock_t:
        ratio = int(tf_cfg.get("htf_ratio") or 60)
        htf_lock_t = _htf_window_start(utcnow(), ratio).isoformat()
    tr_ext = _safe_float(sig.get("trigger_extreme"))
    if tr_ext is not None:
        _mark_htf_sweep_consumed(
            tf_name,
            str(sig.get("direction") or pl.direction),
            htf_lock_t,
            trigger_extreme=float(tr_ext),
            sweep_level=float(sig.get("htf_sweep_level") or pl.sweep_level or 0),
            stop=float(sig.get("stop") or pl.stop_price),
            tp=float(sig.get("tp") or pl.tp_price),
            trigger_idx=int(sig.get("trigger_idx") or -1),
        )

    sl_pct   = abs(rr_stop - rr_entry) / rr_entry * 100 if rr_entry > 0 else 0
    tp_pct   = abs(rr_tp   - rr_entry) / rr_entry * 100 if rr_entry > 0 else 0
    tfl = tf_label(tf_name)

    if is_pyramid and parent_pos:
        logger.info(
            f"PYRAMID PENDING {sig['direction']} [{tfl}] → #{parent_pos.trade_num}: "
            f"entry={_fmt_px(sig['entry'])} +{contracts}ctr | "
            f"SL/TP родителя {_fmt_px(parent_pos.stop_price)}/{_fmt_px(parent_pos.tp_price)}"
        )
    else:
        logger.info(
            f"PENDING {sig['direction']} [{tfl}]: "
            f"entry={_fmt_px(sig['entry'])} stop={_fmt_px(sig['stop'])} "
            f"tp={_fmt_px(sig['tp'])} | {contracts} ctr"
        )

    if not state.paper:
        px_chk = price_live or get_price() or 0.0
        if _should_defer_entry(
            pl.direction, entry_kind_pre, pl.entry_price, px_chk,
            cisd_level=pl.cisd_level or pl.entry_price,
        ):
            pl.defer_entry = True
            save_pending(state.pending_limits)
        defer_pre = (
            "\n⏳ Жду откат (триггер уже выполнен — ордер не на бирже)"
            if pl.defer_entry else ""
        )
        lim_note_pre = ""
        kind_lbl_pre = pl.entry_kind or "LIMIT"
        cisd_note = pl.cisd_level or pl.entry_price
        sk = pl.symbol_key
        if kind_lbl_pre == "MARKET" and bool(sig.get("fib_stretch_market")):
            mode = str(sig.get("fib_market_mode") or "")
            if mode == "post_cisd_no_fib1":
                lim_note_pre = (
                    "\nMARKET @ market (retest_geom: CISD пройден, fib1 не достигнут; "
                    "TP fib 2.0x, taker)"
                )
            else:
                lim_note_pre = (
                    "\nMARKET @ market (confirm 5m → fib1, не fib2; TP fib 2.5x, taker)"
                )
        elif kind_lbl_pre == "MARKET":
            lim_note_pre = "\nMARKET @ market (taker fee)"
        elif kind_lbl_pre == "LIMIT":
            if bool(sig.get("tf4_bar3_limit_retest")):
                lim_note_pre = (
                    f"\nLIMIT @ {_fmt_px(pl.entry_price, sk)} (tf4 bar3 → ретест CISD)"
                )
            elif _sweep_cisd_retest_limit(
                pl.direction, float(pl.sweep_level or 0), float(cisd_note),
            ):
                sg = "ниже" if pl.direction == "SHORT" else "выше"
                lim_note_pre = (
                    f"\nLIMIT @ {_fmt_px(pl.entry_price, sk)} "
                    f"(ретест CISD, sweep {sg} CISD, maker fee)"
                )
            else:
                lim_note_pre = (
                    f"\nLIMIT @ {_fmt_px(pl.entry_price, sk)} "
                    f"(ретест CISD после confirm, maker fee)"
                )
        elif kind_lbl_pre in ("STOP-LIMIT", "STOP-MARKET"):
            lim_note_pre = (
                f"\nSTOP-LIMIT @ {_fmt_px(pl.entry_price, sk)} "
                f"(planorder: триггер CISD → limit @ CISD, maker fee)"
            )
        confirm_note = " (confirm на баре свипа)" if pl.confirm_on_sweep else ""
        kind_lbl_show = _entry_kind_display(kind_lbl_pre)
        if is_pyramid and parent_pos:
            hdr = (
                f"📌 ДОЛИВКА #{pl.trade_num} → #{parent_pos.trade_num}  "
                f"{sig['direction']} [{tfl}]\n"
            )
            sl_tp_note = (
                f"Stop/TP: от #{parent_pos.trade_num} "
                f"({_fmt_px(parent_pos.stop_price, sk)} / "
                f"{_fmt_px(parent_pos.tp_price, sk)})\n"
            )
        else:
            hdr = (
                f"📌 NEW {'MARKET' if kind_lbl_pre == 'MARKET' else 'LIMIT'} "
                f"#{pl.trade_num}  {sig['direction']} [{tfl}]\n"
            )
            sl_tp_note = ""
        qstop_note = ""
        if pl.quality_stop_mult < 1.0 and pl.quality_stop_original is not None:
            qstop_note = (
                f"QSTOP: score {pl.quality_score:.3f}, SL ×{pl.quality_stop_mult:.3f} "
                f"({_fmt_px(pl.quality_stop_original, sk)} → {_fmt_px(pl.stop_price, sk)})\n"
            )
        rr_line = f"R:R:   {tp_pct / sl_pct:.1f}" if sl_pct > 0 else "R:R:   —"
        await send_telegram(
            f"{hdr}"
            f"ID: {pl.id}  |  {contracts} ctr\n"
            f"Entry: {_fmt_px(pl.entry_price, sk)}{confirm_note}{lim_note_pre}{defer_pre}\n"
            f"Entry type: {kind_lbl_show}\n"
            f"{sl_tp_note}"
            f"Stop:  {_fmt_px(pl.stop_price, sk)}  ({sl_pct:.2f}%)  [STOP-MARKET after fill]\n"
            f"TP:    {_fmt_px(pl.tp_price, sk)}  ({tp_pct:.2f}%)  [LIMIT after fill]\n"
            f"{qstop_note}"
            f"{rr_line}"
        )
        if not pl.defer_entry:
            await _try_place_pending_entry(pl)
        if pl.order_id and pl.status == "pending":
            ek = _entry_kind_display(pl.entry_kind or kind_lbl_pre)
            await send_telegram(
                f"✅ На бирже: {pl.order_id}  (#{pl.trade_num} {pl.direction}, {ek})"
            )
    return True


async def _try_place_pending_entry(pl: "PendingLimit") -> bool:
    """Поставить entry-ордер на биржу сразу (live). True если order_id есть."""
    if state.paper or pl.status != "pending" or pl.order_id:
        return bool(pl.order_id)

    # До постановки: TP уже ходили после confirm → не входим.
    tp_hit, tp_detail = await _hist_tp_already_touched(
        direction=pl.direction,
        tp=float(pl.tp_price or 0),
        tf_name=pl.tf,
        confirm_bar_time=str(getattr(pl, "confirm_bar_time", "") or ""),
        trigger_bar_time=(
            pl.trigger_bar_at.isoformat() if pl.trigger_bar_at else
            str(getattr(pl, "cand_trigger_time", "") or "")
        ),
    )
    if tp_hit:
        logger.info(
            f"SKIP place TP already hit #{pl.trade_num} {pl.id[:8]}: {tp_detail}"
        )
        await _cancel_pending_tp_already_hit(pl, tp_detail)
        return False

    px_now = get_price() or pl.price_at_creation or pl.entry_price
    px_ref = _pending_entry_price_ref(pl)
    cisd = pl.cisd_level or pl.entry_price
    kind_now, _, _ = _resolve_entry_order_kind(
        pl.direction, pl.entry_price, px_ref,
        cisd_level=cisd, sweep_level=float(pl.sweep_level or 0),
        force_market=bool(getattr(pl, "force_market", False)),
        force_limit_retest=bool(getattr(pl, "force_limit_retest", False)),
    )
    pl.entry_kind = kind_now

    if _should_defer_entry(
        pl.direction, kind_now, pl.entry_price, px_now, cisd_level=cisd,
    ):
        pl.defer_entry = True
        save_pending(state.pending_limits)
        return False

    pl.defer_entry = False
    order = await place_entry_order(
        pl.direction, pl.entry_price,
        pl.stop_price, pl.tp_price, pl.contracts,
        price_at_creation=px_ref,
        cisd_level=cisd,
        sweep_level=float(pl.sweep_level or 0),
        force_market=bool(getattr(pl, "force_market", False)),
        force_limit_retest=bool(getattr(pl, "force_limit_retest", False)),
        external_oid=_mexc_entry_external_oid(pl),
        symbol_key=_pos_symbol_key(pl),
    )
    if not order:
        save_pending(state.pending_limits)
        return False

    pl.order_id = _extract_order_id(order)
    pl.order_placed_at = utcnow()
    # Таймаут входа — с момента ордера на бирже, не с создания pending.
    pl.timeout_at = pl.order_placed_at + timedelta(
        hours=float(CONFIG.get(pl.tf, {}).get("limit_h", 1))
    )
    kind_place, _, _ = _resolve_entry_order_kind(
        pl.direction, pl.entry_price, px_ref,
        cisd_level=cisd, sweep_level=float(pl.sweep_level or 0),
        force_market=bool(getattr(pl, "force_market", False)),
        force_limit_retest=bool(getattr(pl, "force_limit_retest", False)),
    )
    pl.entry_is_plan = _entry_kind_is_plan(kind_place)
    pl.entry_kind = kind_place
    save_pending(state.pending_limits)
    logger.info(
        f"ENTRY placed #{pl.trade_num} {pl.id[:8]} order={pl.order_id} kind={pl.entry_kind}"
    )
    return True


async def _try_immediate_market_entry(pl: PendingLimit) -> bool:
    """v6: MARKET-вход запрещён."""
    return False
    if pl.status != "pending" or pl.order_id is not None:
        return False
    kind = _pending_entry_kind(pl)
    if kind != "MARKET":
        return False
    if getattr(pl, "cisd_cross_market", False) and pl.cand_trigger_time:
        tf_cfg = CONFIG.get(pl.tf, CONFIG[state.active_tf])
        df = await fetch_ohlcv(tf_cfg["timeframe"], tf_cfg.get("ohlcv", 500))
        if df is not None and len(df) >= 3:
            det = CISDDetector(
                htf_ratio=int(tf_cfg["htf_ratio"]),
                htf_confirm_windows=int(tf_cfg.get("htf_confirm_windows", 2)),
            )
            if not _recalc_cisd_cross_pending_levels(pl, df, det):
                pl.status = "cancelled_extreme"
                _journal_log_pending_cancelled(pl)
                htf_t = pl.htf_time or _htf_time_for_pending(pl, pl.tf)
                if htf_t:
                    _drop_sweep_candidate(
                        pl.tf, pl.direction, htf_t,
                        "cisd_cross recalc: confirm low пробил stop",
                    )
                logger.info(
                    f"cisd_cross CANCEL #{pl.trade_num}: confirm пробил stop "
                    f"{pl.stop_price:.1f}"
                )
                save_pending(state.pending_limits)
                return False
    px_now = get_price() or pl.price_at_creation or pl.entry_price
    cisd = pl.cisd_level or pl.entry_price
    if getattr(pl, "cisd_cross_market", False) and not _cisd_price_crossed(
        pl.direction, cisd, px_now,
    ):
        return False
    ok_rr, _, rr_reason = _passes_min_rr(
        pl.direction, px_now, pl.stop_price, pl.tp_price,
    )
    if not ok_rr:
        logger.info(f"SKIP min_rr immediate #{pl.trade_num}: {rr_reason} @ {px_now:.1f}")
        await _cancel_pending_for_min_rr(pl, px_now, rr_reason)
        return False
    if _should_defer_entry(
        pl.direction, kind, pl.entry_price, px_now,
        cisd_level=pl.cisd_level or pl.entry_price,
    ):
        pl.defer_entry = True
        save_pending(state.pending_limits)
        return False

    now = utcnow()
    if state.paper:
        if not px_now:
            return False
        await _finalize_limit_fill(pl, float(px_now), pl.contracts, now)
        return True

    order = await place_entry_order(
        pl.direction, pl.entry_price,
        pl.stop_price, pl.tp_price, pl.contracts,
        price_at_creation=_pending_entry_price_ref(pl),
        cisd_level=pl.cisd_level or pl.entry_price,
        force_market=bool(getattr(pl, "force_market", False)),
        force_limit_retest=bool(getattr(pl, "force_limit_retest", False)),
        external_oid=_mexc_entry_external_oid(pl),
        symbol_key=_pos_symbol_key(pl),
    )
    if not order:
        logger.warning(
            f"MARKET immediate #{pl.trade_num}: ордер не создан — fallback limit_monitor"
        )
        return False

    pl.order_id = _extract_order_id(order)
    pl.order_placed_at = utcnow()
    pl.entry_kind = "MARKET"
    pl.entry_is_plan = False
    pl.defer_entry = False

    await asyncio.sleep(0.5)
    oi = await get_order_status(pl.order_id, _pos_symbol_key(pl))
    if oi and _order_is_filled(oi, pl.contracts):
        fill_px = _order_fill_price(oi, px_now or pl.entry_price)
        ctr = max(1, int(float(oi.get("filled") or pl.contracts)))
        await _finalize_limit_fill(pl, fill_px, ctr, now)
        return True

    real_open = await _fetch_real_open_positions()
    ex = _exchange_confirms_pending_entry(pl, real_open)
    if ex:
        await _finalize_limit_fill(
            pl, float(ex["entry"]),
            max(1, int(ex["contracts"])), now,
        )
        return True

    save_pending(state.pending_limits)
    logger.info(
        f"MARKET immediate #{pl.trade_num}: ордер на бирже, fill дожмёт limit_monitor"
    )
    return False


# ============================================================
# МОНИТОР ЛИМИТОК
# ============================================================
async def _fetch_real_open_positions() -> list[dict]:
    try:
        loop = asyncio.get_event_loop()
        raw  = await loop.run_in_executor(
            None,
            lambda: _fetch_positions_linear(),
        )
        return _parse_exchange_open_positions(raw)
    except Exception as e:
        logger.warning(f"fetch_positions: {e}")
        return []


def _order_info_is_cancelled(order_info: Optional[dict]) -> bool:
    if not order_info:
        return False
    return str(order_info.get("status") or "").lower() in ("canceled", "cancelled")


def _pending_entry_absent_on_exchange(
    pl: "PendingLimit",
    open_ids: set[str],
    open_orders: list[dict],
    real_open: list[dict],
) -> bool:
    """Ордера нет среди активных на бирже (в т.ч. отменён вручную в приложении)."""
    if not pl.order_id:
        return False
    oid = str(pl.order_id)
    if oid in open_ids:
        return False
    if _match_exchange_order_for_pending(pl, open_orders):
        return False
    if _exchange_match_for_pending(pl, real_open):
        return False
    return True


def _finalize_pending_removed_manual(pl: "PendingLimit", *, log_tag: str = "") -> None:
    pl.status = "cancelled_manual"
    _journal_log_pending_cancelled(pl)
    _mark_signal_skipped(pl.sig_hash)
    tag = f" {log_tag}" if log_tag else ""
    logger.info(f"PENDING #{pl.trade_num} {pl.id}: снято с учёта{tag}")


def _pending_trigger_zone(pl: "PendingLimit", price: Optional[float], ohlc_low: Optional[float], ohlc_high: Optional[float]) -> bool:
    """True если цена уже касалась entry в сторону исполнения (опасная зона миграции plan->regular)."""
    try:
        entry = float(pl.entry_price)
    except Exception:
        return False
    if pl.direction == "LONG":
        return bool(
            (price is not None and price >= entry) or
            (ohlc_high is not None and ohlc_high >= entry)
        )
    return bool(
        (price is not None and price <= entry) or
        (ohlc_low is not None and ohlc_low <= entry)
    )


def _exchange_fill_entry_tol_pct() -> float:
    return float(CONFIG.get("exchange_fill_entry_tol_pct", 0.0008))


def _contracts_near(ex_ctr: float, pl_ctr: int, *, pct: float = 0.25) -> bool:
    return abs(float(ex_ctr) - int(pl_ctr)) <= max(1, int(pl_ctr) * pct)


def _exchange_match_for_pending(pl: PendingLimit, real_open: list[dict]) -> Optional[dict]:
    """Позиция на бирже, соответствующая pending-лимитке (entry + объём)."""
    tol = _exchange_fill_entry_tol_pct()
    near = [
        r for r in real_open
        if r["direction"] == pl.direction
        and _entry_near(r["entry"], pl.entry_price, tol)
        and _contracts_near(r["contracts"], pl.contracts)
    ]
    if near:
        return near[0]
    return None


def _exchange_confirms_pending_entry(
    pl: PendingLimit, real_open: list[dict],
) -> Optional[dict]:
    """Fill pending: точное совпадение или рост суммарного объёма (MEXC one-way)."""
    ex = _exchange_match_for_pending(pl, real_open)
    if ex:
        return ex
    others = [p for p in _bot_open_in_direction(pl.direction) if p.status == "open"]
    if not others:
        return None
    ex_ctr = _exchange_contracts_sum(real_open, pl.direction)
    need = sum(p.contracts for p in others) + pl.contracts
    if ex_ctr < need - 1:
        return None
    same_dir = [r for r in real_open if r["direction"] == pl.direction]
    if not same_dir:
        return None
    return {
        "direction": pl.direction,
        "entry": pl.entry_price,
        "contracts": pl.contracts,
    }


def _entry_near(a: float, b: float, pct: Optional[float] = None) -> bool:
    if pct is None:
        pct = _exchange_fill_entry_tol_pct()
    return abs(float(a) - float(b)) / max(float(b), 1.0) < float(pct)


def _pending_matches_exchange_fill(pl: "PendingLimit", entry_price: float) -> bool:
    """MATch pending↔биржа: signal entry, ref-цена, MARKET fill ≠ signal entry."""
    if _entry_near(pl.entry_price, entry_price):
        return True
    ref = _pending_entry_price_ref(pl)
    if ref > 0 and _entry_near(ref, entry_price):
        return True
    pac = float(pl.price_at_creation or 0)
    if pac > 0 and _entry_near(pac, entry_price):
        return True
    if (pl.entry_kind or _pending_entry_kind(pl)) == "MARKET":
        return True
    return False


def _find_pending_for_exchange(direction: str, entry_price: float) -> Optional["PendingLimit"]:
    pending_same = [
        pl for pl in state.pending_limits
        if pl.status == "pending" and pl.direction == direction
    ]
    matched = None
    for pl in pending_same:
        if _pending_matches_exchange_fill(pl, entry_price):
            matched = pl
            break
    return matched


def _fill_in_progress_for_exchange(direction: str, entry_price: float) -> bool:
    for pl in state.pending_limits:
        if pl.id not in state._fill_in_progress:
            continue
        if pl.direction != direction:
            continue
        if _pending_matches_exchange_fill(pl, entry_price):
            return True
    return False


def _filled_pending_without_position(direction: str, entry_price: float) -> Optional["PendingLimit"]:
    """Pending filled, Position ещё не в стейте — только свежее окно (гонка finalize)."""
    for pl in state.pending_limits:
        if pl.status != "filled" or pl.direction != direction:
            continue
        if not _pending_matches_exchange_fill(pl, entry_price):
            continue
        if any(p.status == "open" and p.id == pl.id for p in state.positions):
            return None
        if _filled_pending_stale(pl):
            return None
        return pl
    return None


async def _resize_position_sl_tp(pos: "Position") -> tuple[bool, bool]:
    """Перевыставить plan SL/TP на актуальный объём (после доливки)."""
    await _cancel_position_sl_tp_plans(pos)
    pos.stop_order_id = None
    pos.tp_order_id = None
    return await place_sl_tp_for_position(pos)


async def _finalize_pyramid_fill(
    pl: PendingLimit, avg_price: float, actual_ctr: int, now: datetime,
) -> None:
    """Доливка: pending → +контракты в родительскую Position, SL/TP родителя."""
    parent_id = getattr(pl, "pyramid_parent_id", "") or ""
    parent = _position_by_id(parent_id)
    if not parent or parent.status != "open":
        logger.error(
            f"PYRAMID fill #{pl.trade_num}: parent {parent_id[:8]} не open — отмена"
        )
        pl.status = "cancelled_manual"
        _journal_log_pending_cancelled(pl)
        return

    pl.status = "filled"
    old_ctr = int(parent.contracts)
    add_ctr = max(1, int(actual_ctr))
    new_ctr = old_ctr + add_ctr
    old_entry = float(parent.entry_price)
    new_entry = _weighted_entry_price(old_entry, old_ctr, avg_price, add_ctr)

    if not state.paper:
        real_open = await _fetch_real_open_positions()
        ex_ctr = _exchange_contracts_sum(real_open, parent.direction)
        if ex_ctr < new_ctr - 1:
            logger.warning(
                f"PYRAMID fill #{pl.trade_num}: биржа {ex_ctr:.0f}ctr "
                f"< ожидали {new_ctr} — доливка не подтверждена"
            )
            pl.status = "pending"
            return

    parent.contracts = new_ctr
    parent.entry_price = new_entry
    sl_ok, tp_ok = await _resize_position_sl_tp(parent)
    save_positions(state.positions)
    save_pending(state.pending_limits)

    _journal_log_pending(
        pl, "pyramid_filled",
        entry_price=avg_price,
        entry_time=now.isoformat(),
        parent_trade_num=parent.trade_num,
        parent_contracts_after=new_ctr,
        parent_entry_after=new_entry,
        sl_placed=sl_ok,
        tp_placed=tp_ok,
    )

    tfl = tf_label(pl.tf)
    arrow = "📈" if pl.direction == "LONG" else "📉"
    sl_pct = abs(parent.stop_price - new_entry) / max(new_entry, 1) * 100
    tp_pct = abs(parent.tp_price - new_entry) / max(new_entry, 1) * 100
    rr = tp_pct / sl_pct if sl_pct > 0 else 0
    ek = _entry_kind_display(pl.entry_kind or _pending_entry_kind(pl))
    logger.info(
        f"PYRAMID {pl.id[:8]} +{add_ctr}@{avg_price:.1f} → "
        f"#{parent.trade_num} {new_ctr}ctr avg={new_entry:.1f}"
    )
    await send_telegram(
        f"➕ {arrow} ДОЛИВКА #{pl.trade_num} → #{parent.trade_num} [{tfl}]\n"
        f"{'─' * 34}\n"
        f"+{add_ctr} контр. @ {avg_price:.1f}  ({ek})\n"
        f"Итого: {new_ctr} контр.  avg={new_entry:.1f}\n"
        f"{'─' * 34}\n"
        f"🛑 Стоп #{parent.trade_num}: {parent.stop_price:.1f} ({sl_pct:.2f}%)"
        f"{' ✅' if sl_ok else ' ❌'}\n"
        f"💰 Тейк #{parent.trade_num}: {parent.tp_price:.1f} ({tp_pct:.2f}%)"
        f"{' ✅' if tp_ok else ' ❌'}\n"
        f"⚖️  R:R = {rr:.2f}  |  Таймаут: {pl.exit_h}ч"
    )
    if not sl_ok or not tp_ok:
        await send_telegram(
            f"🚨 Доливка #{pl.trade_num}: SL/TP не обновлены на {new_ctr}ctr! Проверь Bybit"
        )


async def _finalize_limit_fill(pl: PendingLimit, avg_price: float,
                               actual_ctr: int, now: datetime):
    """Pending → Position + SL/TP (идемпотентно)."""
    if pl.status != "pending":
        return
    if pl.id in state._fill_in_progress:
        return
    state._fill_in_progress.add(pl.id)
    try:
        if getattr(pl, "pyramid_parent_id", ""):
            await _finalize_pyramid_fill(pl, avg_price, actual_ctr, now)
            return
        pl.status = "filled"
        fill_note = ""
        if abs(avg_price - pl.entry_price) < 0.01:
            fill_note = " (avg с биржи не пришёл — проверь dealAvgPrice)"
        logger.info(
            f"FILL {pl.id[:8]} {pl.direction} #{pl.trade_num}: "
            f"{actual_ctr} @ avg={avg_price:.1f}{fill_note}"
        )

        pos = Position(
            pos_id      = pl.id,
            direction   = pl.direction,
            entry_price = avg_price,
            stop_price  = _round_protection_price(pl.stop_price, _pos_symbol_key(pl)),
            tp_price    = _round_protection_price(pl.tp_price, _pos_symbol_key(pl)),
            contracts   = actual_ctr,
            entry_time  = now,
            exit_time   = now + timedelta(hours=pl.exit_h),
            tf          = pl.tf,
            trade_num   = pl.trade_num,
        )
        _copy_pending_meta_to_position(pl, pos)
        pos.exchange_position_id = await _resolve_exchange_position_id_for_fill(
            pl, avg_price, actual_ctr,
        )
        if pos.exchange_position_id:
            logger.info(
                f"positionId #{pl.trade_num} {pl.direction}: {pos.exchange_position_id}"
            )
        if not state.paper:
            if await _await_position_on_exchange(pos):
                if pos.exchange_position_id:
                    save_positions(state.positions)
            else:
                logger.warning(
                    f"#{pl.trade_num} {pl.direction}: позиция не видна на бирже "
                    f"— SL/TP отложены до exchange_seen"
                )
        sl_ok, tp_ok = (False, False)
        if state.paper or _position_exchange_confirmed(pos):
            sl_ok, tp_ok = await place_sl_tp_for_position(pos)

        if not state.paper and pl.htf_time:
            ban_h = _manual_setup_ban_hash(
                tf=pl.tf,
                direction=pl.direction,
                htf_time=str(pl.htf_time),
                sl=float(pl.stop_price),
                tp=float(pl.tp_price),
            )
            state.processed.add(ban_h)
            save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])

        state.positions = [
            p for p in state.positions
            if not (
                p.status == "open"
                and p.id.startswith("X")
                and p.direction == pos.direction
                and abs(p.entry_price - avg_price) / max(avg_price, 1) < 0.005
            )
        ]
        state.positions.append(pos)
        save_positions(state.positions)
        save_pending(state.pending_limits)
        _journal_log_pending(
            pl, "entry_filled",
            entry_price=avg_price,
            entry_time=now.isoformat(),
            sl_placed=sl_ok,
            tp_placed=tp_ok,
        )

        sl_pct = abs(pl.stop_price - avg_price) / avg_price * 100
        tp_pct = abs(pl.tp_price   - avg_price) / avg_price * 100
        tfl    = tf_label(pl.tf)
        rr     = tp_pct / sl_pct if sl_pct > 0 else 0
        arrow  = "📈" if pl.direction == "LONG" else "📉"
        sk = _pos_symbol_key(pl)
        sl_line = (
            f"🛑 Стоп: {_fmt_px(pl.stop_price, sk)} ({sl_pct:.2f}%) — TP/SL ✅"
            if sl_ok else
            f"🛑 Стоп: {_fmt_px(pl.stop_price, sk)} ({sl_pct:.2f}%) — ❌ НЕ выставлен!"
        )
        tp_line = (
            f"💰 Тейк: {_fmt_px(pl.tp_price, sk)} ({tp_pct:.2f}%) — TP/SL ✅"
            if tp_ok else
            f"💰 Тейк: {_fmt_px(pl.tp_price, sk)} ({tp_pct:.2f}%) — ❌ НЕ выставлен!"
        )
        ek = _entry_kind_display(pl.entry_kind or _pending_entry_kind(pl))
        cv = _contract_value(sk)
        risk_usdt = abs(float(avg_price) - float(pl.stop_price)) * actual_ctr * cv
        await send_telegram(
            _format_position_taken_tg(
                pl.direction, pl.trade_num, sk, pl.tf,
                avg_price, pl.stop_price, pl.tp_price, risk_usdt,
                signal_time=getattr(pl, "confirm_bar_time", "") or "",
                htf_time=pl.htf_time or "",
            )
            + (f"\n{sl_line}\n{tp_line}" if not (sl_ok and tp_ok) else "")
        )
        if not sl_ok:
            pos.protection_alert_sent = True
            await send_telegram(
                f"🚨 #{pl.trade_num} SL не встал! Закрой вручную или /close"
            )
        if not tp_ok:
            pos.protection_alert_sent = True
            await send_telegram(
                f"🚨 #{pl.trade_num} TP не встал! Проверь Bybit или дождись restore"
            )
        if pos.protection_alert_sent:
            save_positions(state.positions)
    finally:
        state._fill_in_progress.discard(pl.id)


async def _try_arm_cisd_cross_candidates(now: datetime) -> None:
    """После close-свипа + MSS: armed pending с той же fib/MARKET логикой, что detect.

    Для синтетического 10m (5m×2): arm только когда в 10m-бакете ≥2 закр. 5m.
    До close-свипа на LTF не армим (variant A).
    """
    if state.paper or not state.running.is_set():
        return
    tf_name = state.active_tf
    tf_cfg = CONFIG[tf_name]
    cands = _cands_for_symbol(tf_name)
    if not cands:
        return
    df = await fetch_ohlcv(tf_cfg["timeframe"], tf_cfg.get("ohlcv", 500))
    if df is None or len(df) < 3:
        return
    eval_iloc = await _cisd_cross_eval_iloc(df, tf_cfg["timeframe"], now)
    if eval_iloc is None:
        return
    htf_confirm_windows = int(tf_cfg.get("htf_confirm_windows", 2))
    det = CISDDetector(
        htf_ratio=int(tf_cfg["htf_ratio"]),
        htf_confirm_windows=htf_confirm_windows,
    )
    df_htf = det.resample_to_htf(df)
    sweeps = det.detect_htf_sweeps(df_htf, df)
    df_confirm = await _fetch_confirm_ohlcv(tf_name, tf_cfg)
    confirm_tf = _confirm_timeframe_for(tf_name)
    htf_bar_m = _tf_to_minutes(str(tf_cfg.get("timeframe") or "15m"))
    df_mss = df
    if confirm_tf and df_confirm is not None and len(df_confirm) >= 2:
        sliced = _slice_confirm_df(df_confirm, df, htf_bar_m)
        if sliced is not None and len(sliced) >= 2:
            df_mss = sliced
    mss_on_ltf = df_mss is not df
    price = get_price()
    if price is None:
        return

    for cand in cands:
        direction = str(cand["direction"])
        is_bearish = direction == "SHORT"
        sweep_lvl = float(cand.get("sweep_level") or 0)
        htf_s = str(cand.get("htf_time") or "")
        if sweep_lvl <= 0 or not htf_s:
            continue
        if _is_slope_cisd_arm_blocked(tf_name, direction, htf_s, sweep_lvl):
            logger.info(
                f"cisd_cross arm SKIP slope-ban [{htf_s}] {direction} "
                f"sweep={sweep_lvl:.1f}"
            )
            continue
        if _has_cisd_cross_pending(tf_name, direction, htf_s):
            continue
        if _find_sweep_for_cand(sweeps, cand) is None:
            continue

        cand_trigger_idx = _resolve_cand_trigger_idx(df, cand)
        if cand_trigger_idx is None:
            continue
        last_closed = _last_closed_bar_iloc(df)
        if cand_trigger_idx > last_closed:
            continue

        try:
            htf_anchor = pd.Timestamp(htf_s)
        except Exception:
            htf_anchor = None

        pre_lv = _levels_from_trigger(
            det, df, cand_trigger_idx, direction, is_bearish,
        )
        if pre_lv is None:
            continue

        # Геометрия только от deepest trigger (как detect): не склеивать
        # CISD/fib от eff с MSS/close-свип/fib-stretch от старого cand.
        orig_cand_idx = int(cand_trigger_idx)
        eff_trigger_idx = _deepest_bar_iloc(
            df, cand_trigger_idx, last_closed, is_bearish,
        )
        if int(eff_trigger_idx) != orig_cand_idx:
            _sync_cand_trigger(cand, df, int(eff_trigger_idx), is_bearish)
            state.sweep_candidates[_cand_key(tf_name, direction, htf_s)] = cand
            logger.info(
                f"cisd_cross deepen [{htf_s}] {direction}: "
                f"tr={cand.get('trigger_time')} "
                f"ext={float(cand.get('trigger_extreme') or 0):.1f}"
            )
        anchor_idx = int(eff_trigger_idx)

        lv = _levels_from_trigger(
            det, df, anchor_idx, direction, is_bearish,
        )
        if lv is None:
            continue

        entry = lv["entry"]
        stop = lv["stop"]
        tp = lv["tp"]
        fib_prices = lv["fib_prices"]
        start_idx = int(lv["start_idx"])

        mss_trigger = (
            _map_htf_ts_to_ltf_iloc(df_mss, df.index[anchor_idx])
            if mss_on_ltf else anchor_idx
        )
        mss_start = (
            _map_htf_ts_to_ltf_iloc(df_mss, df.index[start_idx])
            if mss_on_ltf else start_idx
        )
        mss_confirm_idx = det.find_confirmation(
            df_mss, mss_trigger, entry, is_bearish, mss_start,
            htf_anchor=htf_anchor,
        )
        mss_ok = False
        confirm_close = 0.0
        confirm_on_sweep = False
        if mss_confirm_idx is not None:
            last_closed_mss = _last_closed_bar_iloc(df_mss)
            if last_closed_mss >= 0 and int(mss_confirm_idx) <= last_closed_mss:
                if mss_on_ltf:
                    confirm_series_iloc = _map_ltf_ts_to_series_iloc(
                        df, df_mss.index[int(mss_confirm_idx)],
                    )
                    mss_extremum_hit = det.is_extremum_updated(
                        df, anchor_idx, confirm_series_iloc, is_bearish,
                    )
                else:
                    mss_extremum_hit = det.is_extremum_updated(
                        df_mss, mss_trigger, int(mss_confirm_idx), is_bearish,
                    )
                if not mss_extremum_hit:
                    mss_ok = True
                    confirm_close = float(df_mss.iloc[int(mss_confirm_idx)]["close"])
                    confirm_bar = df_mss.iloc[int(mss_confirm_idx)]
                    if mss_on_ltf:
                        confirm_on_sweep = _ltf_bar_in_htf_bucket(
                            df_mss.index[int(mss_confirm_idx)],
                            df.index[anchor_idx],
                            htf_bar_m,
                        )
                    else:
                        confirm_on_sweep = int(mss_confirm_idx) == int(anchor_idx)
        if not mss_ok:
            continue

        confirm_low = float(confirm_bar["low"])
        confirm_high = float(confirm_bar["high"])
        if is_bearish and confirm_high > stop:
            _drop_sweep_candidate(
                tf_name, direction, htf_s,
                f"confirm high {confirm_high:.1f} > stop {stop:.1f}",
            )
            continue
        if not is_bearish and confirm_low < stop:
            _drop_sweep_candidate(
                tf_name, direction, htf_s,
                f"confirm low {confirm_low:.1f} < stop {stop:.1f}",
            )
            continue

        eff_extreme = _trigger_extreme_at(df, anchor_idx, is_bearish)
        lock_k = _htf_sweep_lock_key(tf_name, direction, sweep_lvl)
        lock = state.htf_sweep_lock.get(lock_k)
        if lock is not None and not _is_resweep_extreme(
            direction, eff_extreme, lock["trigger_extreme"],
        ):
            continue

        sweep_close_idx = det.find_first_sweep_close_confirm_bar(
            df, anchor_idx, sweep_lvl, is_bearish, htf_anchor=htf_anchor,
        )
        if sweep_close_idx is None:
            logger.info(
                f"cisd_cross arm WAIT close-свип [{htf_s}] {direction} "
                f"sweep={sweep_lvl:.1f} (MSS close={confirm_close:.1f})"
            )
            continue
        if det.is_extremum_updated(
            df, anchor_idx, int(sweep_close_idx), is_bearish,
        ):
            continue

        sweep_close_close = float(df.iloc[int(sweep_close_idx)]["close"])
        one_bar = int(sweep_close_idx) == int(mss_confirm_idx)
        retest_geom = _sweep_cisd_retest_limit(direction, sweep_lvl, entry)
        tp, fib_stretch_market, fib_stretch_reason, fib_market_mode = (
            _resolve_retest_geom_fib_market(
                direction, retest_geom, mss_ok, df, int(sweep_close_idx),
                float(entry), fib_prices, tp,
                series_start_idx=start_idx,
            )
        )
        if fib_stretch_market:
            logger.info(f"cisd_cross arm: {fib_stretch_reason} (игнор, TP=1R LIMIT)")

        sig_hash = _sig_hash_stable(direction, htf_s, sweep_lvl, entry, stop, tp)
        if sig_hash in state.processed:
            continue
        rr_entry = float(entry)
        ok_rr, _, rr_reason = _passes_min_rr(direction, rr_entry, stop, tp)
        if not ok_rr:
            logger.info(f"cisd_cross arm SKIP min_rr: {rr_reason}")
            continue

        sig = {
            "hash": sig_hash,
            "symbol_key": active_symbol_key(),
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "cisd_level": entry,
            "htf_sweep_level": sweep_lvl,
            "htf_time": htf_s,
            "fib_1x": _safe_float(fib_prices[0]),
            "fib_2x": _safe_float(fib_prices[1]),
            "fib_2_5x": _safe_float(fib_prices[2]) if len(fib_prices) > 2 else None,
            "one_bar_sweep_cisd": one_bar,
            "confirm_on_sweep": confirm_on_sweep,
            "confirm_close": confirm_close,
            "confirm_idx": int(mss_confirm_idx),
            "confirm_bar_time": str(pd.Timestamp(df_mss.index[int(mss_confirm_idx)])),
            "confirm_timeframe": confirm_tf if mss_on_ltf else "",
            "sweep_close_idx": int(sweep_close_idx),
            "sweep_close_close": sweep_close_close,
            "sweep_close_bar_time": str(pd.Timestamp(df.index[int(sweep_close_idx)])),
            "trigger_extreme": eff_extreme,
            "trigger_idx": anchor_idx,
            "cand_trigger_time": str(pd.Timestamp(df.index[orig_cand_idx])),
            "trigger_bar_time": str(pd.Timestamp(df.index[anchor_idx])),
            "fib_stretch_market": fib_stretch_market,
            "fib_market_mode": fib_market_mode,
            "cisd_cross_arm": True,
        }
        logger.info(
            f"cisd_cross ARM {direction} [{htf_s}] cisd={entry:.1f} "
            f"cand_tr={df.index[orig_cand_idx]} eff_tr={df.index[anchor_idx]} "
            f"close_sweep={df.index[int(sweep_close_idx)]} "
            f"confirm={df_mss.index[int(mss_confirm_idx)]} stop={stop:.1f} "
            f"kind=LIMIT price={price:.1f}"
        )
        await create_pending_limit(sig, tf_name)


async def limit_monitor():
    while True:
        await state.running.wait()   # пауза если /stop

        now = utcnow()

        active = [p for p in state.pending_limits if p.status == "pending"]
        if not active:
            await asyncio.sleep(CONFIG["limit_check_s"])
            continue

        forming_by_tf: dict[str, tuple[Optional[float], Optional[float]]] = {}

        for pl in active:
            if not state.running.is_set():
                break

            sk = _pos_symbol_key(pl)
            price = get_price(sk)
            cached = state.ohlcv_closed.get(f"{sk}|{pl.tf}") or {}
            ohlc_low = cached.get("low")
            ohlc_high = cached.get("high")

            # Таймаут лимитки — только если ордер уже на бирже (paper: не defer)
            armed = bool(pl.order_id) or (state.paper and not pl.defer_entry)
            if now >= pl.timeout_at and armed:
                if pl.order_id and not await _cancel_pending_entry(pl):
                    await _alert_cancel_fail(
                        pl,
                        f"🚨 ЛИМИТКА #{pl.trade_num} — не удалось снять с биржи!\n"
                        f"ID: {pl.id}  |  order: {pl.order_id}\n"
                        f"Отмени вручную на Bybit или /close"
                    )
                    continue
                pl.status = "cancelled_timeout"
                _journal_log_pending_cancelled(pl)
                tfl       = tf_label(pl.tf)
                htf_name  = tf_htf_name(pl.tf)
                limit_h   = CONFIG[pl.tf]["limit_h"]
                elapsed_h = (now - (pl.order_placed_at or pl.created_at)).total_seconds() / 3600
                prefix    = _mode_prefix() + " "
                sk = getattr(pl, "symbol_key", None)
                await send_telegram(
                    f"{prefix}⏰ ЛИМИТКА #{pl.trade_num} ОТМЕНЕНА — таймаут [{tfl}]\n"
                    f"ID: {pl.id}  |  {pl.direction}\n"
                    f"Прошло {elapsed_h:.1f}ч из {_fmt_h(limit_h)} "
                    f"(от постановки {msk(pl.order_placed_at or pl.created_at).strftime('%H:%M')} МСК, {htf_name})\n"
                    f"Вход не случился: {_fmt_px(pl.entry_price, sk)}"
                )
                continue

            # Доливка: pending не должен жить дольше родителя.
            parent_id = str(getattr(pl, "pyramid_parent_id", "") or "")
            if parent_id:
                parent = _position_by_id(parent_id)
                if parent is None or getattr(parent, "status", "") != "open":
                    if pl.order_id and not state.paper and not await _cancel_pending_entry(pl):
                        await _alert_cancel_fail(
                            pl,
                            f"🚨 ЛИМИТКА #{pl.trade_num} — родитель закрыт, но ордер НЕ снят!\n"
                            f"ID: {pl.id}  |  order: {pl.order_id}\n"
                            f"Отмени вручную на Bybit",
                        )
                        continue
                    pl.status = "cancelled_parent_closed"
                    _journal_log_pending_cancelled(pl)
                    tfl = tf_label(pl.tf)
                    prefix = _mode_prefix() + " "
                    await send_telegram(
                        f"{prefix}🗑 ЛИМИТКА #{pl.trade_num} ОТМЕНЕНА — родитель закрыт [{tfl}]\n"
                        f"ID: {pl.id}  |  {pl.direction}\n"
                        f"Доливка больше не актуальна"
                    )
                    continue

                # Доливка отменяется, если цена уже дошла до fib 1.0x родителя (движение состоялось без ретеста).
                fib1_parent = _safe_float(getattr(parent, "fib_1x", None))
                if fib1_parent and fib1_parent > 0:
                    fib1_hit = False
                    if price is not None:
                        fib1_hit = (
                            (pl.direction == "LONG" and float(price) >= fib1_parent) or
                            (pl.direction == "SHORT" and float(price) <= fib1_parent)
                        )
                    if not fib1_hit and ohlc_high is not None and ohlc_low is not None:
                        fib1_hit = _confirm_extreme_touched_fib1(
                            pl.direction,
                            float(ohlc_high),
                            float(ohlc_low),
                            float(fib1_parent),
                        )
                    if fib1_hit:
                        if pl.order_id and not state.paper and not await _cancel_pending_entry(pl):
                            await _alert_cancel_fail(
                                pl,
                                f"🚨 ЛИМИТКА #{pl.trade_num} — fib 1.0x родителя достигнут, но ордер НЕ снят!\n"
                                f"ID: {pl.id}  |  order: {pl.order_id}\n"
                                f"Fib1: {fib1_parent:.1f}\n"
                                f"Отмени вручную на Bybit",
                            )
                            continue
                        pl.status = "cancelled_parent_fib1"
                        _journal_log_pending_cancelled(pl)
                        tfl = tf_label(pl.tf)
                        prefix = _mode_prefix() + " "
                        await send_telegram(
                            f"{prefix}🗑 ЛИМИТКА #{pl.trade_num} ОТМЕНЕНА — fib 1.0x родителя достигнут [{tfl}]\n"
                            f"ID: {pl.id}  |  {pl.direction}\n"
                            f"Fib1: {fib1_parent:.1f}"
                        )
                        continue

            # Инвалидация: live price + OHLC (cisd_cross — forming-бар, иначе закрытый)
            fl, fh = forming_by_tf.get(pl.tf, (None, None))
            extreme_hit, cmp, ref_price = _pending_extreme_hit(
                pl, price, ohlc_low, ohlc_high, forming_low=fl, forming_high=fh,
            )
            if extreme_hit:
                tfl    = tf_label(pl.tf)
                prefix = _mode_prefix() + " "
                pattern_ext = _pending_pattern_extreme(pl)
                if pl.order_id and not state.paper and not await _cancel_pending_entry(pl):
                    await _alert_cancel_fail(
                        pl,
                        f"🚨 ЛИМИТКА #{pl.trade_num} — экстремум пробит, но ордер НЕ снят!\n"
                        f"ID: {pl.id}  |  order: {pl.order_id}\n"
                        f"OHLC {cmp} экстремум: {ref_price:.1f} vs {pattern_ext:.1f}\n"
                        f"Отмени вручную на Bybit"
                    )
                    continue
                pl.status = "cancelled_extreme"
                _journal_log_pending_cancelled(pl)
                htf_t = pl.htf_time or _htf_time_for_pending(pl, pl.tf)
                if htf_t:
                    _drop_sweep_candidate(
                        pl.tf, pl.direction, htf_t,
                        f"extreme hit {ref_price:.1f} vs ext {pattern_ext:.1f}",
                        symbol_key=sk,
                    )
                if float(pl.sweep_level or 0) > 0:
                    state.htf_sweep_lock.pop(
                        _htf_sweep_lock_key(
                            pl.tf, pl.direction, float(pl.sweep_level), symbol_key=sk,
                        ),
                        None,
                    )
                state.htf_sweep_lock.pop(
                    _setup_leg_lock_key(pl.tf, pl.direction, pl.stop_price, pl.tp_price),
                    None,
                )
                logger.info(
                    f"EXTREME HIT [{tfl}] {pl.direction} #{pl.trade_num}: "
                    f"OHLC {cmp} {ref_price:.1f} vs ext {pattern_ext:.1f}"
                )
                await send_telegram(
                    f"{prefix}❌ ЛИМИТКА #{pl.trade_num} ОТМЕНЕНА — экстремум пробит [{tfl}]\n"
                    f"ID: {pl.id}  |  {pl.direction}\n"
                    f"OHLC {cmp} экстремум: {ref_price:.1f} vs {pattern_ext:.1f}\n"
                    f"Паттерн CISD недействителен"
                )
                continue

            # Выставляем ордер на бирже (если ещё нет) — live
            if not state.paper and pl.order_id is None:
                await _try_place_pending_entry(pl)
                continue

            # ── PAPER MODE: проверяем цену вместо ордера ──────────────
            if state.paper:
                cisd_p = pl.cisd_level or pl.entry_price
                # SHADOW: fill по касанию уровня в OHLC закрытого бара (как бэктест)
                # плюс live-цена, если тикер уже дошёл до лимитки.
                if pl.direction == "LONG":
                    entry_hit = (
                        (ohlc_low is not None and float(ohlc_low) <= float(pl.entry_price))
                        or (price is not None and float(price) <= float(pl.entry_price))
                    )
                else:
                    entry_hit = (
                        (ohlc_high is not None and float(ohlc_high) >= float(pl.entry_price))
                        or (price is not None and float(price) >= float(pl.entry_price))
                    )
                if not entry_hit:
                    continue
                px_ref_p = _pending_entry_price_ref(pl)
                kind_paper, _, _ = _resolve_entry_order_kind(
                    pl.direction, pl.entry_price, px_ref_p,
                    cisd_level=cisd_p, sweep_level=float(pl.sweep_level or 0),
                    force_market=bool(getattr(pl, "force_market", False)),
                    force_limit_retest=bool(getattr(pl, "force_limit_retest", False)),
                )
                # Симулируем вход
                pl.status  = "filled"
                avg_price  = pl.entry_price
                actual_ctr = pl.contracts
                sl_pct     = abs(pl.stop_price - avg_price) / avg_price * 100
                tp_pct     = abs(pl.tp_price   - avg_price) / avg_price * 100
                rr         = tp_pct / sl_pct if sl_pct > 0 else 0
                tfl        = tf_label(pl.tf)
                arrow      = "📈" if pl.direction == "LONG" else "📉"
                pos        = Position(
                    pos_id      = pl.id,
                    direction   = pl.direction,
                    entry_price = avg_price,
                    stop_price  = pl.stop_price,
                    tp_price    = pl.tp_price,
                    contracts   = actual_ctr,
                    entry_time  = now,
                    exit_time   = now + timedelta(hours=pl.exit_h),
                    tf          = pl.tf,
                    trade_num   = pl.trade_num,
                )
                _copy_pending_meta_to_position(pl, pos)
                state.positions.append(pos)
                save_positions(state.positions)
                save_pending(state.pending_limits)
                _journal_log_pending(
                    pl, "entry_filled",
                    entry_price=avg_price,
                    entry_time=now.isoformat(),
                    sl_placed=True,
                    tp_placed=True,
                )
                sk = _pos_symbol_key(pl)
                cv = _contract_value(sk)
                risk_usdt = abs(float(avg_price) - float(pl.stop_price)) * actual_ctr * cv
                await send_telegram(
                    _format_position_taken_tg(
                        pl.direction, pl.trade_num, sk, pl.tf,
                        avg_price, pl.stop_price, pl.tp_price, risk_usdt,
                        signal_time=getattr(pl, "confirm_bar_time", "") or "",
                        htf_time=pl.htf_time or "",
                    )
                )
                continue
            # ── LIVE MODE ──────────────────────────────────────────────
            avg_price  = None
            actual_ctr = None
            order_info = None

            if pl.order_id:
                order_info = await get_order_status(pl.order_id, _pos_symbol_key(pl))
                if order_info:
                    status = order_info.get("status", "open")
                    filled = float(order_info.get("filled") or 0)
                    now_ts = time.time()
                    if not hasattr(pl, '_last_order_log') or now_ts - pl._last_order_log > 30:
                        pl._last_order_log = now_ts
                        logger.info(
                            f"ORDER {pl.id[:8]} status={status} filled={filled} "
                            f"avg={order_info.get('average', '?')}"
                        )
                    if _order_is_filled(order_info, pl.contracts):
                        avg_price  = _order_fill_price(order_info, pl.entry_price)
                        actual_ctr = max(1, int(float(order_info.get("filled") or pl.contracts)))

            # Запасной путь: ордер не читается / planorder — смотрим позицию на бирже
            if avg_price is None and pl.order_id:
                real_open = await _fetch_real_open_positions()
                ex = _exchange_confirms_pending_entry(pl, real_open)
                if ex:
                    logger.info(
                        f"FILL via exchange position {pl.id[:8]}: "
                        f"{ex['direction']} {int(ex['contracts'])}@{ex['entry']:.1f}"
                    )
                    avg_price  = ex["entry"]
                    actual_ctr = max(1, int(ex["contracts"]))

            if avg_price is not None and actual_ctr is not None:
                await _finalize_limit_fill(pl, avg_price, actual_ctr, now)
                continue

            # Вход не случился, но цена дошла до fib 2.0x (TP) → отменяем pending.
            if avg_price is None and not state.paper and pl.order_id:
                if _pending_fib2_touched_without_fill(pl, price, ohlc_low, ohlc_high):
                    tp_lvl = float(pl.tp_price)
                    if not await _cancel_pending_entry(pl):
                        await _alert_cancel_fail(
                            pl,
                            f"🚨 ЛИМИТКА #{pl.trade_num} — тейк (fib 2.0x) достигнут, но ордер НЕ снят!\n"
                            f"ID: {pl.id}  |  order: {pl.order_id}\n"
                            f"TP: {tp_lvl:.1f}  Entry: {pl.entry_price:.1f}\n"
                            f"Отмени вручную на Bybit"
                        )
                        continue
                    pl.status = "cancelled_tp_hit"
                    _journal_log_pending_cancelled(pl)
                    # Поведение как /close: не перевыставлять тот же сетап (SL/TP) в этом HTF окне
                    _mark_signal_skipped(pl.sig_hash)
                    if pl.htf_time:
                        ban_h = _manual_setup_ban_hash(
                            tf=pl.tf,
                            direction=pl.direction,
                            htf_time=str(pl.htf_time),
                            sl=float(pl.stop_price),
                            tp=float(pl.tp_price),
                        )
                        state.processed.add(ban_h)
                        save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])
                    tfl = tf_label(pl.tf)
                    kind = pl.entry_kind or _pending_entry_kind(pl)
                    if _pending_is_limit_retest(pl):
                        why = "limit retest"
                    else:
                        why = f"{kind} без fill"
                    await send_telegram(
                        f"🗑 ЛИМИТКА #{pl.trade_num} отменена — fib 2.0x без входа [{tfl}]\n"
                        f"ID: {pl.id}  |  {pl.direction}  |  {why}\n"
                        f"Entry: {pl.entry_price:.1f}  |  TP: {tp_lvl:.1f}"
                    )
                    continue

            # Биржа вернула canceled — снимаем с учёта (open_ids может врать)
            if (
                pl.order_id
                and avg_price is None
                and order_info
                and not _pending_in_exchange_grace(pl)
                and _order_info_is_cancelled(order_info)
                and not _order_is_filled(order_info, pl.contracts)
            ):
                # Если цена уже была на entry/через entry — это может быть миграция plan->regular.
                # В этой зоне НЕ считаем "снято вручную", иначе ловим ложные отмены.
                if _pending_trigger_zone(pl, price, ohlc_low, ohlc_high):
                    open_orders = await _fetch_exchange_open_orders_compact()
                    matched_id = _match_exchange_order_for_pending(pl, open_orders)
                    if matched_id and str(matched_id) != str(pl.order_id):
                        pl.order_id = matched_id
                        if not pl.order_placed_at:
                            pl.order_placed_at = now
                        save_pending(state.pending_limits)
                        logger.info(
                            f"PENDING #{pl.trade_num} {pl.id}: plan->regular order_id обновлён → {matched_id}"
                        )
                    continue
                real_open = await _fetch_real_open_positions()
                if not _exchange_match_for_pending(pl, real_open):
                    pl.status = "cancelled_manual"
                    _journal_log_pending_cancelled(pl)
                    _mark_signal_skipped(pl.sig_hash)
                    tfl = tf_label(pl.tf)
                    logger.info(
                        f"PENDING #{pl.trade_num} {pl.id}: ордер отменён на бирже"
                    )
                    await send_telegram(
                        f"🗑 ЛИМИТКА #{pl.trade_num} снята с биржи [{tfl}]\n"
                        f"ID: {pl.id}  |  {pl.direction}\n"
                        f"Entry: {pl.entry_price:.1f} — убрано из учёта бота"
                    )
                    continue

            # Ордер снят вручную на бирже (только если реально нет на бирже)
            if pl.order_id and avg_price is None:
                if _pending_in_exchange_grace(pl):
                    continue

                if await _exchange_order_still_open(str(pl.order_id)):
                    continue

                open_orders = await _fetch_exchange_open_orders_compact()
                matched_id = _match_exchange_order_for_pending(pl, open_orders)
                if matched_id:
                    pl.order_id = matched_id
                    if not pl.order_placed_at:
                        pl.order_placed_at = now
                    save_pending(state.pending_limits)
                    logger.info(
                        f"PENDING #{pl.trade_num} {pl.id}: order_id обновлён → {matched_id}"
                    )
                    continue

                open_ids_lm = await _fetch_exchange_open_order_ids()
                open_orders_lm = await _fetch_exchange_open_orders_compact()
                real_open_lm = await _fetch_real_open_positions()

                if _pending_entry_absent_on_exchange(pl, open_ids_lm, open_orders_lm, real_open_lm):
                    if not _exchange_match_for_pending(pl, real_open_lm):
                        pl.status = "cancelled_manual"
                        _journal_log_pending_cancelled(pl)
                        _mark_signal_skipped(pl.sig_hash)
                        tfl = tf_label(pl.tf)
                        logger.info(
                            f"PENDING #{pl.trade_num} {pl.id}: ордер снят с биржи (подтверждено)"
                        )
                        if getattr(pl, "cancel_fail_alerted", False):
                            await _notify_cancel_false_alarm_resolved(
                                pl, "Отмена подтверждена в limit_monitor"
                            )
                        else:
                            await send_telegram(
                                f"🗑 ЛИМИТКА #{pl.trade_num} снята с биржи [{tfl}]\n"
                                f"ID: {pl.id}  |  {pl.direction}\n"
                                f"Entry: {pl.entry_price:.1f} — убрано из учёта бота"
                            )
                        continue

                info = await get_order_status(pl.order_id, _pos_symbol_key(pl))
                if info is None:
                    continue
                st = str(info.get("status") or "").lower()
                if st in ("open", "new", "unknown", ""):
                    continue
                if _order_is_filled(info, pl.contracts):
                    continue
                if st not in ("canceled", "cancelled", "closed"):
                    continue

                # Цена уже была на entry/через entry → вероятна миграция plan->regular или задержка позиции.
                if _pending_trigger_zone(pl, price, ohlc_low, ohlc_high):
                    open_orders = await _fetch_exchange_open_orders_compact()
                    matched_id = _match_exchange_order_for_pending(pl, open_orders)
                    if matched_id and str(matched_id) != str(pl.order_id):
                        pl.order_id = matched_id
                        if not pl.order_placed_at:
                            pl.order_placed_at = now
                        save_pending(state.pending_limits)
                        logger.info(
                            f"PENDING #{pl.trade_num} {pl.id}: plan->regular order_id обновлён → {matched_id}"
                        )
                    continue

                real_open = await _fetch_real_open_positions()
                if _exchange_match_for_pending(pl, real_open):
                    continue

                # Финальная проверка перед снятием с учёта
                if await _exchange_order_still_open(str(pl.order_id)):
                    continue

                pl.status = "cancelled_manual"
                _journal_log_pending_cancelled(pl)
                _mark_signal_skipped(pl.sig_hash)
                tfl = tf_label(pl.tf)
                logger.info(
                    f"PENDING #{pl.trade_num} {pl.id}: ордер снят с биржи (подтверждено)"
                )
                await send_telegram(
                    f"🗑 ЛИМИТКА #{pl.trade_num} снята с биржи [{tfl}]\n"
                    f"ID: {pl.id}  |  {pl.direction}\n"
                    f"Entry: {pl.entry_price:.1f} — убрано из учёта бота"
                )
                continue

        save_pending(state.pending_limits)
        await asyncio.sleep(CONFIG["limit_check_s"])


# ============================================================
# МОНИТОР ПОЗИЦИЙ
# ============================================================
async def position_monitor():
    while True:
        if not state.tasks_live.is_set():
            await asyncio.sleep(5)
            continue
        # Позиции мониторим ВСЕГДА (даже на паузе сканера — деньги на бирже!)
        open_pos = [p for p in state.positions if p.status == "open"]
        if not open_pos:
            await asyncio.sleep(CONFIG["position_check_s"])
            continue

        now   = utcnow()
        # Факт с биржи: если позиция уже закрыта (TP/SL/ручное), снимем хвосты и уведомим
        real_open = []
        if not state.paper:
            real_open = await _fetch_real_open_positions()

        backfilled_pid = False
        for p in open_pos:
            if not state.paper and not p.exchange_position_id:
                if await _backfill_exchange_position_id(p):
                    backfilled_pid = True
        if backfilled_pid:
            save_positions(state.positions)

        for p in open_pos:
            cv   = p.contracts * _contract_value(_pos_symbol_key(p))
            sign = 1 if p.direction == "LONG" else -1
            price = get_price(_pos_symbol_key(p))

            # ── PAPER MODE: проверяем цену напрямую ───────────────────
            if state.paper:
                sk = _pos_symbol_key(p)
                if price is None:
                    continue
                tfl = tf_label(p.tf)
                cached = state.ohlcv_closed.get(f"{sk}|{p.tf}") or {}
                bar_high = cached.get("high")
                bar_low = cached.get("low")

                tp_hit = (
                    (p.direction == "LONG"  and (
                        price >= p.tp_price or (bar_high is not None and bar_high >= p.tp_price)
                    )) or
                    (p.direction == "SHORT" and (
                        price <= p.tp_price or (bar_low is not None and bar_low <= p.tp_price)
                    ))
                )
                sl_hit = (
                    (p.direction == "LONG"  and (
                        price <= p.stop_price or (bar_low is not None and bar_low <= p.stop_price)
                    )) or
                    (p.direction == "SHORT" and (
                        price >= p.stop_price or (bar_high is not None and bar_high >= p.stop_price)
                    ))
                )
                timeout_hit = now >= p.exit_time

                if tp_hit:
                    close_price, close_reason = p.tp_price,    "closed_tp"
                elif sl_hit:
                    close_price, close_reason = p.stop_price,  "closed_sl"
                elif timeout_hit:
                    close_price, close_reason = price,          "closed_time"
                else:
                    continue

                p.status      = close_reason
                p.close_price = close_price
                gross, fees, net = _apply_close_pnl(p, close_price, close_reason)
                state.paper_balance += net
                _archive_trade(p)
                save_positions(state.positions)

                margin = p.entry_price * cv / CONFIG["leverage"]
                arrow  = "📈" if p.direction == "LONG" else "📉"

                labels = {
                    "closed_tp":   ("🟢", "ТЕЙК ПРОФИТ"),
                    "closed_sl":   ("🔴", "СТОП ЛОСС"),
                    "closed_time": ("⏰", "ТАЙМАУТ — закрыт по рынку"),
                }
                ico, reason_str = labels[close_reason]

                sk = _pos_symbol_key(p)
                await send_telegram(
                    f"{_mode_prefix()} {ico} #{p.trade_num} {reason_str} {arrow} {p.direction}\n"
                    f"Инструмент: {symbol_profile(sk)['label']}\n"
                    f"ТФ: {tfl}\n"
                    f"Вход: {_fmt_px(p.entry_price, sk)}  |  Выход: {_fmt_px(close_price, sk)}\n"
                    f"{_format_close_pnl_lines(gross, fees, net, margin)}\n"
                    f"💼 Баланс: {state.paper_balance:.2f} USDT"
                )
                continue
            # ── LIVE MODE ─────────────────────────────────────────────
            # stoporder TPSL → затем «позиции нет на бирже»

            if not _position_exchange_confirmed(p):
                if await _try_confirm_position_on_exchange(p, real_open):
                    save_positions(state.positions)
                    needs_sl = (
                        p.stop_price > 0
                        and not p.tpsl_order_id
                        and not p.stop_order_id
                    )
                    needs_tp = (
                        p.tp_price > 0
                        and not p.tpsl_order_id
                        and not p.tp_order_id
                    )
                    if needs_sl or needs_tp:
                        sl_ok, tp_ok = await place_sl_tp_for_position(p)
                        notified = await _notify_position_protected_after_alert(p, sl_ok, tp_ok)
                        if sl_ok or tp_ok or notified:
                            save_positions(state.positions)
                else:
                    await _maybe_alert_unconfirmed_position(p)
                    continue

            if p.stop_order_id:
                info_sl = await get_order_status(p.stop_order_id)
                if _order_is_filled(info_sl):
                    await _finalize_position_close(
                        p, "closed_sl",
                        _order_fill_price(info_sl, p.stop_price or price or p.entry_price),
                    )
                    continue

            if p.tp_order_id:
                info_tp = await get_order_status(p.tp_order_id)
                if _order_is_filled(info_tp):
                    await _finalize_position_close(
                        p, "closed_tp",
                        _order_fill_price(info_tp, p.tp_price or price or p.entry_price),
                    )
                    continue

            if await _try_finalize_filled_protection(p):
                continue

            if await _position_absent_on_exchange(p, real_open):
                reason, close_price = await _detect_position_close_reason(p)
                await _finalize_position_close(p, reason, close_price)
                continue

            # ── Защита 1: экстренное закрытие если цена за стопом ─────
            # Срабатывает при гэпах когда стоп-ордер не заполнился
            if price:
                emg_pct    = CONFIG["emergency_stop_pct"] / 100
                emg_breach = (
                    p.stop_price > 0 and (
                        (p.direction == "LONG"  and price <= p.stop_price * (1 - emg_pct)) or
                        (p.direction == "SHORT" and price >= p.stop_price * (1 + emg_pct))
                    )
                )
                if emg_breach:
                    tfl   = tf_label(p.tf)
                    arrow = "📈" if p.direction == "LONG" else "📉"
                    slip  = abs(price - p.stop_price)
                    margin = p.entry_price * cv / CONFIG["leverage"]
                    if state.paper:
                        if p.stop_order_id:
                            await cancel_order(p.stop_order_id)
                        if p.tp_order_id:
                            await cancel_order(p.tp_order_id)
                        p.status      = "closed_sl"
                        p.close_price = price
                        gross, fees, net = _apply_close_pnl(p, price, "closed_sl")
                        _archive_trade(p)
                        await send_telegram(
                            f"🚨 #{p.trade_num} ЭКСТРЕННЫЙ СТОП {arrow} {p.direction} [{tfl}]\n"
                            f"{'─' * 34}\n"
                            f"Стоп-ордер не сработал — принудительное закрытие!\n"
                            f"Стоп-уровень: {p.stop_price:.1f}  |  Закрыт: {price:.1f}\n"
                            f"Проскальзывание: {slip:.1f}\n"
                            f"{_format_close_pnl_lines(gross, fees, net, margin)}"
                        )
                        save_positions(state.positions)
                    else:
                        if await _live_force_close_position(
                            p, "closed_sl", price, notify=False,
                            fail_msg=(
                                f"🚨 #{p.trade_num} ЭКСТРЕННЫЙ СТОП: close на бирже не прошёл [{tfl}]\n"
                                f"Стоп {p.stop_price:.1f}  |  цена {price:.1f}"
                            ),
                        ):
                            await send_telegram(
                                f"🚨 #{p.trade_num} ЭКСТРЕННЫЙ СТОП {arrow} {p.direction} [{tfl}]\n"
                                f"{'─' * 34}\n"
                                f"Стоп-ордер не сработал — принудительное закрытие!\n"
                                f"Стоп-уровень: {p.stop_price:.1f}  |  Закрыт: {price:.1f}\n"
                                f"Проскальзывание: {slip:.1f}\n"
                                f"{_format_close_pnl_lines(p.pnl or 0, p.fees or 0, p.pnl_net or 0, margin)}"
                            )
                    continue

            # ── Защита 2: SL/TP пропали или сняты → переставить ───────
            if p.stop_price > 0 and not (now >= p.exit_time):
                if await _try_finalize_filled_protection(p):
                    continue
                if await _restore_position_sl_tp(p):
                    continue

            # Таймаут позиции
            if now >= p.exit_time:
                tfl    = tf_label(p.tf)
                arrow  = "📈" if p.direction == "LONG" else "📉"
                margin = p.entry_price * cv / CONFIG["leverage"]
                close_px = price or p.entry_price
                if state.paper:
                    if p.stop_order_id:
                        await cancel_order(p.stop_order_id)
                    if p.tp_order_id:
                        await cancel_order(p.tp_order_id)
                    await _finalize_position_close(p, "closed_time", close_px, notify=False)
                    await send_telegram(
                        f"⏰ #{p.trade_num} ТАЙМАУТ — закрыт по рынку {arrow} {p.direction} [{tfl}]\n"
                        f"{'─' * 34}\n"
                        f"Вход:  {p.entry_price:.1f}  |  Выход: {p.close_price:.1f}\n"
                        f"{_format_close_pnl_lines(p.pnl or 0, p.fees or 0, p.pnl_net or 0, margin)}"
                    )
                else:
                    if await _live_force_close_position(
                        p, "closed_time", close_px, notify=False,
                        fail_msg=(
                            f"⏰ #{p.trade_num} ТАЙМАУТ: не удалось закрыть на бирже [{tfl}]\n"
                            f"Позиция может остаться открытой — проверь Bybit."
                        ),
                    ):
                        await send_telegram(
                            f"⏰ #{p.trade_num} ТАЙМАУТ — закрыт по рынку {arrow} {p.direction} [{tfl}]\n"
                            f"{'─' * 34}\n"
                            f"Вход:  {p.entry_price:.1f}  |  Выход: {p.close_price:.1f}\n"
                            f"{_format_close_pnl_lines(p.pnl or 0, p.fees or 0, p.pnl_net or 0, margin)}"
                        )
                continue

        save_positions(state.positions)
        await asyncio.sleep(CONFIG["position_check_s"])


# ============================================================
# СИНХРОНИЗАЦИЯ ПОЗИЦИЙ ПРИ СТАРТЕ
# ============================================================
async def sync_paper_positions_on_start():
    """
    Paper-режим: при старте проверяем открытые позиции по текущей цене.
    Если цена уже за стопом/тейком — закрываем.
    Если таймаут прошёл — закрываем по рынку.
    Это покрывает случай когда бот был выключен во время движения цены.
    """
    open_pos = [p for p in state.positions if p.status == "open"]
    if not open_pos:
        return

    # Ждём цену (даётся до 15 секунд)
    price = None
    for _ in range(15):
        price = get_price()
        if price:
            break
        await asyncio.sleep(1)

    if price is None:
        logger.warning("Paper sync: цена недоступна, пропускаем проверку")
        return

    now     = utcnow()
    closed  = []

    for p in open_pos:
        if _pos_symbol_key(p) != active_symbol_key():
            continue
        cv   = p.contracts * _contract_value(_pos_symbol_key(p))
        sign = 1 if p.direction == "LONG" else -1

        tp_hit      = (p.direction == "LONG" and price >= p.tp_price) or \
                      (p.direction == "SHORT" and price <= p.tp_price)
        sl_hit      = (p.direction == "LONG" and price <= p.stop_price) or \
                      (p.direction == "SHORT" and price >= p.stop_price)
        timeout_hit = now >= p.exit_time

        if sl_hit:
            close_price, reason = p.stop_price, "closed_sl"
            note = f"стоп {p.stop_price:.1f} пробит (текущая {price:.1f})"
        elif tp_hit:
            close_price, reason = p.tp_price, "closed_tp"
            note = f"тейк {p.tp_price:.1f} пробит (текущая {price:.1f})"
        elif timeout_hit:
            close_price, reason = price, "closed_time"
            note = f"таймаут {msk(p.exit_time).strftime('%H:%M МСК')}"
        else:
            continue

        p.status        = reason
        p.close_price   = close_price
        gross, fees, net = _apply_close_pnl(p, close_price, reason)
        state.paper_balance += net
        _archive_trade(p)
        closed.append((p, reason, note, gross, fees, net))

    if closed:
        save_positions(state.positions)
        lines = []
        for p, reason, note, gross, fees, net in closed:
            tfl      = tf_label(p.tf)
            ico      = {"closed_tp": "🟢", "closed_sl": "🔴", "closed_time": "⏰"}[reason]
            lines.append(
                f"{ico} #{p.trade_num} {p.direction} [{tfl}]  net {net:+.2f} USDT\n"
                f"   Причина: {note}"
            )
        await send_telegram(
            f"🔄 Paper-синхронизация при старте\n"
            f"Закрыто {len(closed)} позиций пока бот был выключен:\n"
            f"{'─' * 32}\n" +
            "\n".join(lines) +
            f"\n{'─' * 32}\n"
            f"💼 Баланс: {state.paper_balance:.2f} USDT"
        )
        logger.info(f"Paper sync: закрыто {len(closed)} позиций по текущей цене")


async def sync_positions_on_start():
    if state.paper:
        await sync_paper_positions_on_start()
        return

    # Сначала сверяемся с биржей
    await sync_exchange_state()

    issues = []
    restored = []
    for pos in state.positions:
        if pos.status != "open":
            continue
        for attr, label in [("stop_order_id", "стоп"), ("tp_order_id", "тейк")]:
            oid = getattr(pos, attr)
            if oid:
                info = await get_order_status(oid)
                if not _protection_order_is_active(info):
                    logger.warning(
                        f"Позиция {pos.id}: {label}-ордер {oid} не активен "
                        f"({info.get('status') if info else 'missing'})"
                    )
                    setattr(pos, attr, None)
                    issues.append(f"{pos.id} [{pos.direction}]: {label}-ордер потерян")
        if await _restore_position_sl_tp(pos, alert=False):
            restored.append(f"#{pos.trade_num} {pos.direction}")
    if issues or restored:
        save_positions(state.positions)
    msgs = []
    if issues:
        msgs.append("⚠️ Синхронизация при старте:\n" + "\n".join(issues))
    if restored:
        msgs.append("🔄 SL/TP восстановлены:\n" + "\n".join(restored))
    if msgs:
        await send_telegram("\n\n".join(msgs))
    n = sum(1 for p in state.positions if p.status == "open")
    logger.info(f"Синхронизация завершена. Открытых: {n}")


# ============================================================
# СКАНЕР СИГНАЛОВ
# ============================================================
async def _autotrade_signals(signals: list, tf_name: str) -> int:
    """Автовход по сигналам. Слоты и занятость пары проверяет create_pending_limit."""
    if not signals:
        return 0
    tf_cfg = CONFIG[tf_name]
    placed = 0
    for sig in signals:
        if _open_pending_count() >= int(CONFIG.get("max_positions") or 7):
            break
        num = state.next_trade_num()
        await send_paper_signal(sig, tf_name, tf_cfg, trade_num=num)
        ok = await create_pending_limit(sig, tf_name, trade_num=num)
        if ok:
            placed += 1
    return placed


async def _run_detect_and_trade(
    tf_name: str,
    df: pd.DataFrame,
    df_confirm: Optional[pd.DataFrame] = None,
    skip_invalidate: bool = False,
) -> None:
    tf_cfg = CONFIG[tf_name]
    if not skip_invalidate:
        await _invalidate_pending_no_htf_inter_sweep(tf_name, df)
    signals = detect_signals(
        df, state.processed,
        htf_ratio=tf_cfg["htf_ratio"], tf_name=tf_name,
        df_confirm=df_confirm,
        min_sweep_atr=_min_sweep_atr(),
    )
    if signals:
        signals.sort(key=lambda s: s.get("timestamp"), reverse=True)
    kept = []
    for sig in signals or []:
        ok, vd, reason = _vwap_gate(df, sig)
        sig["vwap_dev"] = vd
        sig["symbol_key"] = active_symbol_key()
        if not ok:
            logger.info(
                f"vwap skip {active_symbol_key()} {sig.get('direction')} "
                f"[{tf_name}] {reason}"
            )
            await _notify_signal_skip(
                sig, tf_name, "skipped_vwap",
                header=(
                    f"{_mode_prefix()} ⛔ Пропуск {sig.get('direction')} "
                    f"[{tf_label(tf_name)}] {symbol_profile()['label']} — vwap-фильтр"
                ),
                detail=reason,
            )
            continue
        kept.append(sig)
    if not kept:
        logger.info(f"{active_symbol_key()} {tf_name}: сигналов нет (после vwap)")
        return
    logger.info(f"{active_symbol_key()} {tf_name}: {len(kept)} сигнал(ов)")
    await _autotrade_signals(kept, tf_name)


def _store_closed_ohlc(symbol_key: str, tf_name: str, df: pd.DataFrame) -> None:
    if df is None or len(df) < 2:
        return
    last = df.iloc[-2]
    state.ohlcv_closed[f"{symbol_key}|{tf_name}"] = {
        "low": float(last["low"]),
        "high": float(last["high"]),
        "close": float(last["close"]),
    }
    state.last_ohlcv_low = float(last["low"])
    state.last_ohlcv_high = float(last["high"])


async def _scan_symbol(
    sk: str, tf8_due: bool, skip_invalidate: bool = False,
) -> None:
    with _use_symbol(sk):
        df5 = await fetch_ohlcv("5m", OHLCV_5M_BARS)
        if df5 is None or len(df5) < 50:
            logger.warning(f"{sk}: нет 5m данных")
            return
        state.df_cache[f"{sk}|tf7"] = df5
        _store_closed_ohlc(sk, "tf7", df5)
        await _run_detect_and_trade(
            "tf7", df5, df_confirm=None, skip_invalidate=skip_invalidate,
        )

        df30 = _resample_ohlcv(df5, "30m")
        if df30 is not None and len(df30) >= 2:
            state.df_cache[f"{sk}|tf8"] = df30
            _store_closed_ohlc(sk, "tf8", df30)
        if tf8_due and df30 is not None and len(df30) >= 20:
            await _run_detect_and_trade(
                "tf8", df30, df_confirm=df5, skip_invalidate=skip_invalidate,
            )


async def signal_scanner():
    state.processed = set(load_json(SIGNALS_CACHE, []))
    logger.info(
        f"Загружено {len(state.processed)} обработанных сигналов | "
        f"сканер {len(ACTIVE_SYMBOL_KEYS)} пар × {', '.join(ACTIVE_TF_KEYS)}"
    )
    last_5m_forming = None
    warmup = True

    while True:
        await state.running.wait()
        try:
            peek = await fetch_ohlcv(
                "5m", 3, symbol=SYMBOL_PROFILES["BTC"]["symbol"],
            )
            if peek is None or len(peek) < 1:
                await asyncio.sleep(5)
                continue
            forming = peek.index[-1]
            if last_5m_forming is not None and forming == last_5m_forming:
                await asyncio.sleep(5)
                continue
            # Новый 5m forming-бар = предыдущий закрыт. tf8 — каждый 6-й (граница 30m).
            tf8_due = int(pd.Timestamp(forming).minute) % 30 == 0
            last_5m_forming = forming
            if warmup:
                logger.info(
                    f"Скан 5m close forming={forming}  tf8={'да' if tf8_due else 'нет'} "
                    f"(прогрев — без HTF-инвалидаций)"
                )
            else:
                logger.info(
                    f"Скан 5m close forming={forming}  tf8={'да' if tf8_due else 'нет'}"
                )
            for sk in ACTIVE_SYMBOL_KEYS:
                if not state.running.is_set():
                    break
                try:
                    await _scan_symbol(sk, tf8_due, skip_invalidate=warmup)
                except Exception as e:
                    logger.error(f"scan {sk}: {e}", exc_info=True)
            if warmup:
                logger.info("сканер: прогрев завершён, HTF-инвалидации включены")
                warmup = False
            save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])
        except Exception as e:
            logger.error(f"Scanner: {e}", exc_info=True)
            await asyncio.sleep(60)



# ============================================================
# CTL / DASHBOARD — общий control-слой (TG + HTTP)
# ============================================================
CTL_TOKEN_FILE = os.path.join(BASE_DIR, ".ctl_token")


def ctl_health() -> dict:
    n_open = sum(1 for p in state.positions if p.status == "open")
    n_pending = sum(1 for p in state.pending_limits if p.status == "pending")
    return {
        "running": state.running.is_set(),
        "tasks_live": state.tasks_live.is_set(),
        "paper": bool(state.paper),
        "tg_online": bool(_tg_online),
        "active_tf": state.active_tf,
        "tf_label": tf_label(state.active_tf),
        "symbol": symbol_profile()["label"],
        "n_open": n_open,
        "n_pending": n_pending,
    }


async def ctl_status() -> dict:
    """Статус для dashboard / CLI (тот же текст, что /status)."""
    bal_det = await get_balance_details()
    balance = await get_balance()
    price = get_price()
    n_open = sum(1 for p in state.positions if p.status == "open")
    n_pending = sum(1 for p in state.pending_limits if p.status == "pending")

    positions = []
    pos_lines = ""
    for p in state.positions:
        if p.status != "open":
            continue
        tfl = tf_label(p.tf)
        pnl_str = ""
        upnl = None
        if price and _pos_symbol_key(p) == active_symbol_key():
            cv = p.contracts * _contract_value(_pos_symbol_key(p))
            sign = 1 if p.direction == "LONG" else -1
            upnl = (price - p.entry_price) * cv * sign
            pnl_str = f"  uPnL: {upnl:+.2f}$"
        positions.append({
            "trade_num": p.trade_num,
            "direction": p.direction,
            "tf": p.tf,
            "contracts": p.contracts,
            "entry_price": p.entry_price,
            "upnl": upnl,
        })
        pos_lines += (
            f"\n  #{p.trade_num} {symbol_profile(_pos_symbol_key(p))['label']} "
            f"{p.direction} [{tfl}] {p.contracts}ctr "
            f"@ {_fmt_px(p.entry_price, _pos_symbol_key(p))}{pnl_str}"
        )

    pendings = []
    pend_lines = ""
    for p in state.pending_limits:
        if p.status != "pending":
            continue
        pendings.append({
            "trade_num": p.trade_num,
            "direction": p.direction,
            "tf": p.tf,
            "entry_price": p.entry_price,
        })
        pend_lines += (
            f"\n  #{p.trade_num} {symbol_profile(_pos_symbol_key(p))['label']} "
            f"{p.direction} [{tf_label(p.tf)}] "
            f"@ {_fmt_px(p.entry_price, _pos_symbol_key(p))}"
        )

    dec = _price_decimals(symbol_profile()["price_tick"])
    price_str = f"{price:,.{dec}f}" if price else "—"
    bal_extra = ""
    if not state.paper:
        avail = bal_det.get("available") if bal_det.get("available") is not None else bal_det.get("free")
        upnl_bal = bal_det.get("unrealized")
        parts = []
        if avail is not None:
            parts.append(f"доступно {avail:.2f}")
        if upnl_bal is not None:
            parts.append(f"uPnL {upnl_bal:+.2f}")
        if parts:
            bal_extra = f"  ({', '.join(parts)})"

    tf_cfg = CONFIG[state.active_tf]
    text = (
        f"📊 Статус CISD BOT\n"
        f"{'─' * 30}\n"
        f"{state.mode_str()}\n"
        f"Вход: LIMIT @ CISD  TP=1R  vwap-фильтр\n"
        f"⏱ Таймауты:  вход {_fmt_h(tf_cfg['limit_h'])}  |  "
        f"выход {_fmt_h(tf_cfg['position_h'])}  (/timeout)\n"
        f"Detect filters: {_trigger_filters_desc()}\n"
        f"{symbol_profile()['label']} цена:  {price_str}\n"
        f"Баланс:    {balance:.2f} USDT{bal_extra}\n"
        f"Fees:      maker {_fee_rate_to_pct_str(CONFIG['maker_fee'])}%  "
        f"taker {_fee_rate_to_pct_str(CONFIG['taker_fee'])}%  (/fee)\n"
        f"{'─' * 30}\n"
        f"Открытых позиций: {n_open}"
        + (pos_lines or "  —")
        + f"\nPending лимиток: {n_pending}"
        + (pend_lines or "  —")
    )
    return {
        "text": text,
        "balance": balance,
        "price": price,
        "price_str": price_str,
        "n_open": n_open,
        "n_pending": n_pending,
        "positions": positions,
        "pendings": pendings,
        "paper": bool(state.paper),
        "running": state.running.is_set(),
        "tasks_live": state.tasks_live.is_set(),
        "tg_online": bool(_tg_online),
        "active_tf": state.active_tf,
        "tf_label": tf_label(state.active_tf),
        "symbol": symbol_profile()["label"],
    }


async def ctl_start() -> dict:
    """Возобновить торговлю без TG confirm UI (сканер сам подхватит сетапы)."""
    state.positions = load_positions()
    fresh_pending = load_pending()
    existing_ids = {p.id for p in state.pending_limits}
    added = 0
    for p in fresh_pending:
        if p.id not in existing_ids and p.status == "pending":
            state.pending_limits.append(p)
            added += 1

    was_running = state.running.is_set()
    state.start_confirm_until_ts = 0.0
    state._start_banned_only = False
    state.tasks_live.set()
    state.running.set()
    save_bot_state()

    sync_closed, sync_pending_rm = 0, 0
    if not state.paper:
        sync_closed, sync_pending_rm = await sync_exchange_state()
        _reload_pending_merged()

    n_open = sum(1 for p in state.positions if p.status == "open")
    n_pending = sum(1 for p in state.pending_limits if p.status == "pending")
    mode = _mode_prefix()
    tfl = tf_label(state.active_tf)
    sync_note = ""
    if sync_closed:
        sync_note += f"\n🔄 Сверка: снято {sync_closed} поз. (закрыты на бирже)"
    if sync_pending_rm:
        sync_note += f"\n🔄 Снято {sync_pending_rm} pending (ордеров нет на бирже)"
    text = (
        f"▶ Бот запущен (CTL)\n"
        f"Режим: {mode} | {tfl}\n"
        f"{'─' * 28}\n"
        f"Открытых позиций: {n_open}\n"
        f"Pending лимиток:  {n_pending}"
        + sync_note
        + (f" (+{added} из файла)" if added else "")
        + ("\n\n⚡ Уже работал — продолжаем" if was_running else "")
        + "\n\nConfirm-кнопки TG пропущены — сканер в обычном режиме."
    )
    logger.info(
        f"CTL /start: running=True, paper={state.paper}, added_pending={added}"
    )
    return {
        "ok": True,
        "text": text,
        "n_open": n_open,
        "n_pending": n_pending,
        "added_pending": added,
        "was_running": was_running,
    }


async def ctl_stop(mode: str = "pause") -> dict:
    mode = (mode or "pause").lower()
    if mode == "halt":
        n_open, n_pending = await _apply_stop_halt()
        text = (
            f"🛑 Полная остановка задач (CTL)\n"
            f"{'─' * 28}\n"
            f"Выключено: сканер, лимитки, монитор позиций, sync биржи\n"
            f"На бирже: open {n_open}, pending {n_pending} — только вручную\n\n"
            f"Возобновление: Start / /resume"
        )
        logger.info("CTL /stop halt: running=False, tasks_live=False")
    else:
        n_open, n_pending = await _apply_stop_pause()
        text = (
            f"⏸ Мониторинг приостановлен (CTL)\n"
            f"{'─' * 28}\n"
            f"Открытых позиций: {n_open} — отслеживаются\n"
            f"Pending лимиток:  {n_pending} — заморожены\n\n"
            f"Возобновление: Start / /resume"
        )
        logger.info("CTL /stop pause: running=False, tasks_live=True")
    return {"ok": True, "mode": mode, "text": text, "n_open": n_open, "n_pending": n_pending}


# ============================================================
# TELEGRAM КОМАНДЫ
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запустить/возобновить торговлю + подхватить старые pending (/resume)."""
    if not _tg_owner(update):
        return
    state.positions = load_positions()
    # Перечитываем pending из файла (подхватываем накопленные)
    fresh_pending = load_pending()
    existing_ids = {p.id for p in state.pending_limits}
    added = 0
    for p in fresh_pending:
        if p.id not in existing_ids and p.status == "pending":
            state.pending_limits.append(p)
            added += 1

    was_running = state.running.is_set()

    mode = _mode_prefix()
    tf_name = state.active_tf
    tf_cfg  = CONFIG[tf_name]
    tfl     = tf_label(tf_name)

    # Скан ДО running.set() — иначе signal_scanner успевает автопоставить лимитку
    await update.message.reply_text(f"🔍 Сканирую рынок ({tfl})...")
    df = await fetch_ohlcv(tf_cfg["timeframe"], tf_cfg.get("ohlcv", 500))
    df_confirm = await _fetch_confirm_ohlcv(tf_name, tf_cfg)
    signals = []
    if df is not None and len(df) >= 50:
        signals = detect_signals(
            df, state.processed,
            htf_ratio=tf_cfg["htf_ratio"], tf_name=tf_name,
            df_confirm=df_confirm,
            min_sweep_atr=_min_sweep_atr(),
        )
        if signals:
            signals.sort(key=lambda s: s.get("timestamp"), reverse=True)
    signals_raw = list(signals)

    need_confirm = False  # v6: без кнопок подтверждения
    if (not state.paper) and signals_raw:
        banned = 0
        check_n = min(3, len(signals_raw))
        for sig in signals_raw[:3]:
            if _find_active_work_for_signal(sig, tf_name):
                continue
            if _is_setup_banned(sig, tf_name):
                banned += 1
        state._start_banned_only = banned > 0 and banned >= check_n
    else:
        state._start_banned_only = False

    if need_confirm:
        for t in list(_start_confirm_tasks.values()):
            if not t.done():
                t.cancel()
        _start_confirm_tasks.clear()
        _pending_start_signals.clear()
        state.start_confirm_until_ts = time.time() + 65
        filtered = []
        for sig in signals[:3]:
            if _find_active_work_for_signal(sig, tf_name):
                continue
            if _is_setup_banned(sig, tf_name):
                continue
            filtered.append(sig)
        signals = filtered
        if not signals:
            state.start_confirm_until_ts = 0.0
        else:
            _pending_start_signals[signals[0]["hash"]] = signals[0]

    state.tasks_live.set()
    state.running.set()
    save_bot_state()

    sync_closed, sync_pending_rm = 0, 0
    if not state.paper:
        sync_closed, sync_pending_rm = await sync_exchange_state()
        _reload_pending_merged()

    n_open    = sum(1 for p in state.positions if p.status == "open")
    n_pending = sum(1 for p in state.pending_limits if p.status == "pending")

    sync_note = ""
    if sync_closed:
        sync_note += f"\n🔄 Сверка: снято {sync_closed} поз. (закрыты на бирже)"
    if sync_pending_rm:
        sync_note += f"\n🔄 Снято {sync_pending_rm} pending (ордеров нет на бирже)"
    text = (
        f"▶ Бот запущен\n"
        f"Режим: {mode} | {tfl}\n"
        f"{'─' * 28}\n"
        f"Открытых позиций: {n_open}\n"
        f"Pending лимиток:  {n_pending}"
        + sync_note
        + (f" (+{added} из файла)" if added else "")
        + ("\n\n⚡ Уже работал — продолжаем" if was_running else "")
    )
    await update.message.reply_text(text)

    if need_confirm and signals:
        await _reply_start_in_progress(update, tf_name, tfl, signals_raw)
        sig = signals[0]
        sig_hash = sig["hash"]
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Да", callback_data=f"start_sig:yes:{sig_hash}"),
            InlineKeyboardButton("❌ Нет", callback_data=f"start_sig:no:{sig_hash}"),
        ]])
        _pending_start_signals[sig_hash] = sig
        msg = await update.message.reply_text(
            f"{_format_signal_card(sig, tfl)}\n\nВыставить заявку? (60 сек)",
            reply_markup=keyboard,
        )

        async def auto_skip(h=sig_hash, m=msg):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                return
            try:
                if h not in _pending_start_signals:
                    return
                sig0 = _pending_start_signals.pop(h, None)
                _start_confirm_tasks.pop(h, None)
                if not _pending_start_signals:
                    state.start_confirm_until_ts = 0.0
                state.processed.add(h)
                if (not state.paper) and sig0:
                    ban_h = _manual_setup_ban_hash(
                        tf=tf_name,
                        direction=str(sig0.get("direction") or ""),
                        htf_time=str(sig0.get("htf_time") or ""),
                        sl=float(sig0.get("stop") or 0),
                        tp=float(sig0.get("tp") or 0),
                    )
                    state.processed.add(ban_h)
                save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])
                await m.edit_text(m.text + "\n⏰ Авто-пропуск")
            except Exception:
                pass

        _start_confirm_tasks[sig_hash] = asyncio.create_task(auto_skip())
    elif need_confirm and not signals and signals_raw:
        if not await _reply_start_in_progress(update, tf_name, tfl, signals_raw):
            sig = signals_raw[0]
            card = _format_signal_card(sig, tfl)
            if state._start_banned_only or _is_setup_banned(sig, tf_name):
                await update.message.reply_text(
                    f"{card}\n\n"
                    f"🚫 Этот сетап отменён вручную/по тейку (fib2) в текущем HTF-окне.\n"
                    f"Кнопки не показываю, жду новый сетап (другой SL/TP)."
                )
            else:
                await update.message.reply_text(
                    f"{card}\n\n"
                    f"⚠️ Сигнал найден, но не выставляю повторно.\n"
                    f"Жду новый сетап или проверь /status."
                )
    elif (need_confirm and not signals) or state._start_banned_only:
        try:
            df2 = await fetch_ohlcv(tf_cfg["timeframe"], tf_cfg.get("ohlcv", 500))
            df2_confirm = await _fetch_confirm_ohlcv(tf_name, tf_cfg)
            sigs2 = []
            if df2 is not None and len(df2) >= 50:
                sigs2 = detect_signals(
                    df2, set(),
                    htf_ratio=tf_cfg["htf_ratio"], tf_name=tf_name,
                    df_confirm=df2_confirm,
                    min_sweep_atr=_min_sweep_atr(),
                )
                if sigs2:
                    sigs2.sort(key=lambda s: s.get("timestamp"), reverse=True)
            if await _reply_start_in_progress(update, tf_name, tfl, sigs2 or signals_raw):
                pass
            elif sigs2:
                sig = sigs2[0]
                card = _format_signal_card(sig, tfl)
                await update.message.reply_text(
                    f"{card}\n\n"
                    f"🚫 Этот сетап отменён вручную/пo тейку (fib2) в текущем HTF-окне.\n"
                    f"Кнопки не показываю, жду новый сетап (другой SL/TP)."
                )
            else:
                await update.message.reply_text(
                    "⚠️ Сигнал(ы) найдены, но они были отменены вручную/пo тейку (fib2) в этом HTF-окне.\n"
                    "Кнопки не показываю, жду новый сетап (другой SL/TP)."
                )
        except Exception:
            if not await _reply_start_in_progress(update, tf_name, tfl, signals_raw):
                await update.message.reply_text(
                    "⚠️ Сигнал(ы) найдены, но они были отменены вручную/пo тейку (fib2) в этом HTF-окне.\n"
                    "Кнопки не показываю, жду новый сетап (другой SL/TP)."
                )

    logger.info(f"/resume: running=True, paper={state.paper}, added_pending={added}, signals={len(signals_raw)}")

def _stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⏸ Пауза сканера (позиции живут)",
            callback_data="stop:pause",
        )],
        [InlineKeyboardButton(
            "🛑 Полная остановка (без TG-спама)",
            callback_data="stop:halt",
        )],
    ])


async def _apply_stop_pause() -> tuple[int, int]:
    """Пауза: сканер и лимитки; position_monitor + sync биржи работают."""
    state.running.clear()
    save_bot_state()
    if not state.paper and state.tasks_live.is_set():
        await sync_exchange_state()
    n_open    = sum(1 for p in state.positions if p.status == "open")
    n_pending = sum(1 for p in state.pending_limits if p.status == "pending")
    return n_open, n_pending


async def _apply_stop_halt() -> tuple[int, int]:
    """Полная остановка торговых задач; Telegram-команды остаются."""
    state.running.clear()
    state.tasks_live.clear()
    save_bot_state()
    n_open    = sum(1 for p in state.positions if p.status == "open")
    n_pending = sum(1 for p in state.pending_limits if p.status == "pending")
    return n_open, n_pending


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пауза сканера или полная остановка фоновых задач."""
    await update.message.reply_text(
        "⏸ Что остановить?",
        reply_markup=_stop_keyboard(),
    )


async def callback_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action = (q.data or "").split(":", 1)[-1]

    if action == "pause":
        n_open, n_pending = await _apply_stop_pause()
        text = (
            f"⏸ Мониторинг приостановлен\n"
            f"{'─' * 28}\n"
            f"Открытых позиций: {n_open} — отслеживаются\n"
            f"Pending лимиток:  {n_pending} — заморожены\n\n"
            f"Возобновление: /resume"
        )
        logger.info("/stop pause: running=False, tasks_live=True")
    elif action == "halt":
        n_open, n_pending = await _apply_stop_halt()
        text = (
            f"🛑 Полная остановка задач\n"
            f"{'─' * 28}\n"
            f"Выключено: сканер, лимитки, монитор позиций, sync биржи\n"
            f"Нет алертов о падении задач и устаревшей цене\n"
            f"На бирже: open {n_open}, pending {n_pending} — только вручную\n\n"
            f"Возобновление: /resume"
        )
        logger.info("/stop halt: running=False, tasks_live=False")
    else:
        text = "Неизвестная команда"
    try:
        await q.edit_message_text(text)
    except Exception:
        await q.message.reply_text(text)


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SHADOW ↔ LIVE с подтверждением."""
    n_open = sum(1 for p in state.positions if p.status == "open")
    n_pend = sum(1 for p in state.pending_limits if p.status == "pending")
    if state.paper:
        await update.message.reply_text(
            f"Сейчас {_mode_prefix()}\n"
            f"Открыто: {n_open}  лимиток: {n_pend}\n\n"
            f"🔴 LIVE — реальные ордера на Bybit, риск 1% на сделку, плечо 20x.\n"
            f"Переключить?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔴 Да, LIVE", callback_data="mode:live")],
                [InlineKeyboardButton("↩ Отмена", callback_data="mode:cancel")],
            ]),
        )
        return
    if n_open > 0:
        await update.message.reply_text(
            f"⚠️ Нельзя уйти в SHADOW: есть {n_open} открытых LIVE-позиций.\n"
            f"Сначала закрой их."
        )
        return
    await update.message.reply_text(
        f"Сейчас {_mode_prefix()}\n"
        f"Вернуться в SHADOW? Ордера на биржу ставиться не будут.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧪 Да, SHADOW", callback_data="mode:shadow")],
            [InlineKeyboardButton("↩ Отмена", callback_data="mode:cancel")],
        ]),
    )


async def callback_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action = (q.data or "").split(":", 1)[-1]
    if action == "cancel":
        await q.edit_message_text("↩ Отменено")
        return
    if action == "live":
        n_open = sum(1 for p in state.positions if p.status == "open")
        if n_open > 0 and state.paper:
            await q.edit_message_text(
                f"⚠️ Сначала закрой {n_open} SHADOW-позиций (или /stop), "
                f"потом включай LIVE на чистом стейте."
            )
            return
        state.paper = False
        save_bot_state()
        await set_leverage_all()
        await q.edit_message_text(
            f"Режим → {_mode_prefix()}\n"
            f"Реальные ордера на Bybit. 10 пар × tf7+tf8, риск 1%, плечо 20x isolated."
        )
        logger.info("/mode LIVE")
        return
    if action == "shadow":
        state.paper = True
        save_bot_state()
        await q.edit_message_text(
            f"Режим → {_mode_prefix()}\n"
            f"Ордера на биржу не ставятся. Виртуальный баланс {state.paper_balance:.2f} USDT."
        )
        logger.info("/mode SHADOW")
        return
    await q.edit_message_text("Неизвестная команда")


async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список активных пар (все сканируются сразу)."""
    lines = []
    for k in ACTIVE_SYMBOL_KEYS:
        busy = " 🔒" if _pair_busy(k) else ""
        lines.append(f"• {SYMBOL_PROFILES[k]['label']}{busy}")
    await update.message.reply_text(
        f"{_mode_prefix()} активные пары ({len(ACTIVE_SYMBOL_KEYS)}):\n"
        + "\n".join(lines)
        + "\n\nСканер: все сразу, ТФ 5m→4H и 30m→8H.\n"
        f"Позиций: {_open_pending_count()} / {CONFIG['max_positions']}"
    )


async def cmd_slope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Slope EMA отключён в v5.2."""
    state.slope_filter_enabled = False
    await update.message.reply_text(
        "📐 Slope EMA фильтр отключён в этой версии бота.\n"
        "Вход только после MSS → STOP-LIMIT на CISD."
    )


async def cmd_slop_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📐 Slope EMA фильтр отключён (v5.2).")


async def cmd_prog_ema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📐 /prog_ema отключён — slope-фильтр снят (v5.2).")


async def callback_prog_ema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📐 Slope EMA отключён (v5.2).")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Текущий статус бота."""
    data = await ctl_status()
    await update.message.reply_text(data["text"])


# ============================================================
# СТАТИСТИКА
# ============================================================

def _trades_stats_epoch() -> Optional[datetime]:
    """Начало учётного периода /stats (UTC, 00:00). Файл trades_stats_epoch.txt, строка YYYY-MM-DD."""
    try:
        if not os.path.isfile(TRADES_STATS_EPOCH_FILE):
            return None
        raw = open(TRADES_STATS_EPOCH_FILE, encoding="utf-8").read().strip()
        if not raw:
            return None
        return datetime.strptime(raw[:10], "%Y-%m-%d")
    except Exception:
        return None


def _trade_record_closed_at(trade: dict) -> datetime:
    raw = trade.get("exit_time") or trade.get("entry_time") or ""
    try:
        return datetime.fromisoformat(str(raw).replace("Z", ""))
    except Exception:
        return datetime.min


def _journal_record_ts(record: dict) -> datetime:
    for key in ("logged_at", "exit_time", "pending_created_at", "signal_time"):
        raw = record.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw).replace("Z", ""))
        except Exception:
            continue
    return datetime.min


def archive_trades_before_epoch(epoch: datetime) -> dict:
    """
    Сделки с exit/entry до epoch → archives/trades_pre-YYYY-MM-DD.json;
    строки jsonl того же периода → trade_logs/archive/.
    trades_stats_epoch.txt создаётся/обновляется.
    """
    os.makedirs(TRADES_ARCHIVE_DIR, exist_ok=True)
    os.makedirs(TRADE_LOG_ARCHIVE_DIR, exist_ok=True)
    epoch_label = epoch.strftime("%Y-%m-%d")
    summary = {"epoch": epoch_label, "trades_kept": 0, "trades_archived": 0, "journal_archived": 0}

    trades = load_json(_trades_file(), [])
    keep, arch = [], []
    for t in trades:
        if _trade_record_closed_at(t) < epoch:
            arch.append(t)
        else:
            keep.append(t)
    if arch:
        arc_path = os.path.join(TRADES_ARCHIVE_DIR, f"trades_pre-{epoch_label}.json")
        existing = load_json(arc_path, []) if os.path.isfile(arc_path) else []
        save_json(arc_path, existing + arch)
        save_json(_trades_file(), keep)
    summary["trades_kept"] = len(keep)
    summary["trades_archived"] = len(arch)

    if os.path.isdir(TRADE_LOG_DIR):
        for name in sorted(os.listdir(TRADE_LOG_DIR)):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(TRADE_LOG_DIR, name)
            if not os.path.isfile(path):
                continue
            kept_lines, arch_lines = [], []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        kept_lines.append(line)
                        continue
                    if _journal_record_ts(rec) < epoch:
                        arch_lines.append(line)
                    else:
                        kept_lines.append(line)
            if arch_lines:
                arc_j = os.path.join(
                    TRADE_LOG_ARCHIVE_DIR,
                    f"{name[:-6]}_pre-{epoch_label}.jsonl",
                )
                with open(arc_j, "a", encoding="utf-8") as f:
                    for line in arch_lines:
                        f.write(line + "\n")
                summary["journal_archived"] += len(arch_lines)
                with open(path, "w", encoding="utf-8") as f:
                    for line in kept_lines:
                        f.write(line + "\n")

    with open(TRADES_STATS_EPOCH_FILE, "w", encoding="utf-8") as f:
        f.write(epoch_label + "\n")
    logger.info(
        f"Trades epoch {epoch_label}: archived {summary['trades_archived']} closed, "
        f"kept {summary['trades_kept']}; journal lines {summary['journal_archived']}"
    )
    return summary


# Периоды для inline-клавиатуры: (label, days)
_PERIODS = [
    # Дни
    [("1д", 1),   ("2д", 2),   ("3д", 3),   ("4д", 4),   ("5д", 5),  ("6д", 6)],
    # Недели
    [("1 нед", 7), ("2 нед", 14), ("3 нед", 21)],
    # Месяцы 1-6
    [("1 мес", 30), ("2 мес", 60), ("3 мес", 90),
     ("4 мес", 120), ("5 мес", 150), ("6 мес", 180)],
    # Месяцы 7-12
    [("7 мес", 210), ("8 мес", 240), ("9 мес", 270),
     ("10 мес", 300), ("11 мес", 330), ("12 мес", 365)],
]


def _stats_keyboard(selected_tf: str = "all") -> InlineKeyboardMarkup:
    rows = []
    # Строка фильтра по ТФ
    tf_opts = [
        ("Все ТФ", "all"),
        ("1m→1H", "tf3"),
        ("5m→1H", "tf0"),
        ("10m→1H", "tf4"),
        ("10m→2H", "tf5"),
        ("5m→4H", "tf7"),
        ("10m→4H", "tf6"),
        ("15m→4H", "tf1"),
        ("1H→Daily", "tf2"),
    ]
    rows.append([
        InlineKeyboardButton(
            ("✅ " if key == selected_tf else "") + lbl,
            callback_data=f"stats:tf:{key}"
        )
        for lbl, key in tf_opts
    ])
    # Строки периодов
    for row in _PERIODS:
        rows.append([
            InlineKeyboardButton(label, callback_data=f"stats:{days}:{selected_tf}")
            for label, days in row
        ])
    return InlineKeyboardMarkup(rows)


def _calc_stats(days: int, tf_filter: str = "all") -> dict:
    """Считает статистику из trades.json за последние N дней, опционально по ТФ."""
    trades = load_json(_trades_file(), [])
    cutoff = utcnow() - timedelta(days=days)
    epoch = _trades_stats_epoch()

    filtered = []
    for t in trades:
        try:
            closed_at = _trade_record_closed_at(t)
            if epoch and closed_at < epoch:
                continue
            if not (closed_at >= cutoff and t.get("status", "").startswith("closed")):
                continue
            if tf_filter != "all" and t.get("tf") != tf_filter:
                continue
            filtered.append(t)
        except Exception:
            continue

    total   = len(filtered)
    if total == 0:
        return {"total": 0, "days": days, "tf_filter": tf_filter}

    wins    = [t for t in filtered if t.get("status") == "closed_tp"]
    losses  = [t for t in filtered if t.get("status") == "closed_sl"]
    timeouts= [t for t in filtered if t.get("status") == "closed_time"]

    pnls    = [_trade_pnl_value(t) for t in filtered if t.get("pnl") is not None]
    total_pnl   = sum(pnls)
    avg_pnl     = total_pnl / len(pnls) if pnls else 0
    best        = max(pnls) if pnls else 0
    worst       = min(pnls) if pnls else 0

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss   = abs(sum(p for p in pnls if p < 0))
    pf           = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    # сохраняем для вывода в _format_stats
    _gp, _gl = gross_profit, gross_loss

    # Максимальная просадка за период (по кумулятивному PnL)
    equity  = 0.0
    peak    = 0.0
    max_dd  = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    per_tf_stats = {}
    for key in TF_KEYS:
        tr = [t for t in filtered if t.get("tf") == key]
        per_tf_stats[key] = {
            "count": len(tr),
            "pnl": sum(_trade_pnl_value(t) for t in tr if t.get("pnl") is not None),
        }

    per_pair = {}
    sum_r = 0.0
    r_n = 0
    for t in filtered:
        sk = t.get("symbol") or t.get("symbol_key") or ""
        if sk:
            rec = per_pair.setdefault(sk, {"count": 0, "pnl": 0.0})
            rec["count"] += 1
            rec["pnl"] += _trade_pnl_value(t) if t.get("pnl") is not None else 0.0
        entry = float(t.get("entry_price") or 0)
        stop = float(t.get("stop_price") or 0)
        close = float(t.get("close_price") or 0)
        if entry > 0 and stop > 0 and close > 0 and abs(entry - stop) > 0:
            sign = 1.0 if t.get("direction") == "LONG" else -1.0
            sum_r += sign * (close - entry) / abs(entry - stop)
            r_n += 1

    # Средний реальный R:R (только закрытые по TP и SL)
    rr_list = []
    for t in filtered:
        if t.get("status") not in ("closed_tp", "closed_sl"):
            continue
        entry = t.get("entry_price", 0)
        stop  = t.get("stop_price", 0)
        tp    = t.get("tp_price", 0)
        if entry and stop and tp and abs(entry - stop) > 0:
            rr_list.append(abs(tp - entry) / abs(entry - stop))
    avg_rr = sum(rr_list) / len(rr_list) if rr_list else 0

    return {
        "days":        days,
        "tf_filter":   tf_filter,
        "total":       total,
        "wins":        len(wins),
        "losses":      len(losses),
        "timeouts":    len(timeouts),
        "win_rate":    len(wins) / total * 100 if total else 0,
        "total_pnl":   total_pnl,
        "avg_pnl":     avg_pnl,
        "best":        best,
        "worst":       worst,
        "pf":          pf,
        "max_dd":      max_dd,
        "avg_rr":      avg_rr,
        "gross_profit": _gp,
        "gross_loss":   _gl,
        "sum_r": sum_r,
        "per_pair": per_pair,
        **{
            f"{k}_{fld}": per_tf_stats[k][fld]
            for k in TF_KEYS
            for fld in ("count", "pnl")
        },
    }


def _tf_filter_label(tf: str) -> str:
    if tf == "all":
        return "Все ТФ"
    return CONFIG.get(tf, {}).get("label", tf)


def _format_stats(s: dict) -> str:
    tf_filter = s.get("tf_filter", "all")
    tf_str    = _tf_filter_label(tf_filter)

    if s["total"] == 0:
        epoch = _trades_stats_epoch()
        epoch_note = f" (с {epoch.strftime('%d.%m.%Y')})" if epoch else ""
        return f"📊 Нет закрытых сделок за {s['days']} дн.{epoch_note} [{tf_str}]"

    days   = s["days"]
    label  = (
        f"{days} дн."        if days < 7
        else f"{days // 7} нед." if days < 30
        else f"{days // 30} мес."
    )
    pf_str       = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "∞"
    dd_str       = f"-{s['max_dd']:.2f}" if s["max_dd"] > 0 else "0.00"
    sign         = "+" if s["total_pnl"] >= 0 else ""
    gross_profit = s.get("gross_profit", 0.0)
    gross_loss   = s.get("gross_loss", 0.0)

    # Разбивка по ТФ (показываем только если фильтр "все")
    tf_breakdown = ""
    if tf_filter == "all":
        def _tf_line(key, lbl):
            cnt = s.get(f"{key}_count", 0)
            pnl = s.get(f"{key}_pnl", 0.0)
            if cnt == 0:
                return ""
            return f"\n  {lbl}: {cnt} сд.  {'+' if pnl>=0 else ''}{pnl:.2f} USDT"
        tf_breakdown = (
            f"{'─' * 32}\n"
            f"По ТФ:"
            + _tf_line("tf7", "5m→4H")
            + _tf_line("tf8", "30m→8H")
        )
        pair_lines = ""
        for sk, rec in (s.get("per_pair") or {}).items():
            lbl = SYMBOL_PROFILES.get(sk, {}).get("label", sk)
            pnl = rec.get("pnl", 0.0)
            pair_lines += (
                f"\n  {lbl}: {rec.get('count', 0)} сд.  "
                f"{'+' if pnl >= 0 else ''}{pnl:.2f} USDT"
            )
        if pair_lines:
            tf_breakdown += f"\nПо парам:{pair_lines}"

    epoch = _trades_stats_epoch()
    epoch_line = (
        f"Учёт с:      {epoch.strftime('%d.%m.%Y')}\n" if epoch else ""
    )
    return (
        f"📊 Статистика за {label}  [{tf_str}]\n"
        f"{epoch_line}"
        f"{'─' * 32}\n"
        f"Сделок:       {s['total']}\n"
        f"  🟢 TP:      {s['wins']}  ({s['win_rate']:.1f}%)\n"
        f"  🔴 SL:      {s['losses']}  ({s['losses']/s['total']*100:.1f}%)\n"
        f"  ⏰ Таймаут: {s['timeouts']}  ({s['timeouts']/s['total']*100:.1f}%)\n"
        f"{'─' * 32}\n"
        f"PnL итого:    {sign}{s['total_pnl']:.2f} USDT\n"
        f"SumR:         {s.get('sum_r', 0):+.2f}R\n"
        f"  Прибыль:   +{gross_profit:.2f} USDT\n"
        f"  Убыток:    -{gross_loss:.2f} USDT\n"
        f"Avg PnL:      {'+' if s['avg_pnl']>=0 else ''}{s['avg_pnl']:.2f} USDT\n"
        f"Лучшая:       +{s['best']:.2f} USDT\n"
        f"Худшая:       {s['worst']:.2f} USDT\n"
        f"{'─' * 32}\n"
        f"Profit Factor: {pf_str}\n"
        f"Avg R:R:       {s['avg_rr']:.2f}\n"
        f"Max Drawdown:  {dd_str} USDT"
        + (f"\n{tf_breakdown}" if tf_breakdown else "")
    )


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Текущая цена активной пары."""
    price = get_price()
    ts    = price_cache.get("ts", 0)
    age_s = int(time.time() - ts)
    lbl   = symbol_profile()["label"]
    dec   = _price_decimals(symbol_profile()["price_tick"])
    if price is None:
        await update.message.reply_text("⚠️ Цена недоступна — нет данных от биржи")
        return
    age_str = f"{age_s}с назад" if age_s < 60 else f"{age_s // 60}м {age_s % 60}с назад"
    await update.message.reply_text(
        f"💲 {lbl}\n"
        f"{'─' * 24}\n"
        f"Цена:    {price:,.{dec}f} USDT\n"
        f"Обновлено: {age_str}"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает клавиатуру выбора периода."""
    await update.message.reply_text(
        "📊 Выбери период статистики:",
        reply_markup=_stats_keyboard(),
    )


async def callback_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор периода / ТФ-фильтра в статистике."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")   # stats:days:tf  или  stats:tf:key

    if parts[1] == "tf":
        # Нажали на фильтр ТФ — обновляем только клавиатуру (период неизвестен, ждём выбора)
        selected_tf = parts[2]
        await query.edit_message_text(
            f"📊 Выбери период  [{_tf_filter_label(selected_tf)}]:",
            reply_markup=_stats_keyboard(selected_tf),
        )
        return

    days = int(parts[1])
    tf   = parts[2] if len(parts) > 2 else "all"
    s    = _calc_stats(days, tf)
    text = _format_stats(s)

    await query.edit_message_text(
        text=text,
        reply_markup=_stats_keyboard(tf),
    )


# ============================================================
# НАСТРОЙКА ТАЙМАУТОВ
# ============================================================
# Часы; для входа дополнительно 10/15/20 минут в начале списка.
_TIMEOUT_EXIT_PRESETS = [0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 36, 48]
_TIMEOUT_ENTRY_PRESETS = [10 / 60, 15 / 60, 20 / 60] + _TIMEOUT_EXIT_PRESETS
_TIMEOUT_PRESETS = _TIMEOUT_EXIT_PRESETS  # совместимость / внешние ссылки


def _timeout_tf_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key in TF_KEYS:
        lbl = CONFIG[key]["label"]
        rows.append([InlineKeyboardButton(lbl, callback_data=f"timeout:tf:{key}")])
    rows.append([InlineKeyboardButton("↩ Отмена", callback_data="timeout:cancel")])
    return InlineKeyboardMarkup(rows)


def _timeout_field_keyboard(tf: str) -> InlineKeyboardMarkup:
    lbl     = CONFIG[tf]["label"]
    limit_h = CONFIG[tf]["limit_h"]
    pos_h   = CONFIG[tf]["position_h"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"⏳ Ожидание ВХОДА  (сейчас {_fmt_h(limit_h)})",
            callback_data=f"timeout:field:{tf}:limit_h"
        )],
        [InlineKeyboardButton(
            f"📊 Ожидание ВЫХОДА (сейчас {_fmt_h(pos_h)})",
            callback_data=f"timeout:field:{tf}:position_h"
        )],
        [InlineKeyboardButton("↩ Назад", callback_data="timeout:back")],
    ])


def _timeout_value_keyboard(tf: str, field: str) -> InlineKeyboardMarkup:
    current = float(CONFIG[tf][field])
    presets = _TIMEOUT_ENTRY_PRESETS if field == "limit_h" else _TIMEOUT_EXIT_PRESETS
    rows = []
    row  = []
    for v in presets:
        mark = "✅ " if abs(float(v) - current) < 1e-6 else ""
        row.append(InlineKeyboardButton(
            f"{mark}{_fmt_h(v)}",
            callback_data=f"timeout:set:{tf}:{field}:{float(v):.8g}",
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("↩ Назад", callback_data=f"timeout:tf:{tf}")])
    return InlineKeyboardMarkup(rows)


async def cmd_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройка таймаутов входа/выхода по ТФ."""
    lines = []
    for tf in TF_KEYS:
        lbl = CONFIG[tf]["label"]
        lines.append(f"{lbl}:  вход {_fmt_h(CONFIG[tf]['limit_h'])}  |  выход {_fmt_h(CONFIG[tf]['position_h'])}")
    await update.message.reply_text(
        "⏱ Таймауты (текущие значения):\n" +
        "\n".join(lines) +
        "\n\nВыбери таймфрейм для изменения:",
        reply_markup=_timeout_tf_keyboard(),
    )


_FILTER_KEY_MAP = {}

_CUT_FILTERS_MSG = (
    "Фильтры ATR, VOL(SMA), D, QSZ, PSL, QSTOP вырезаны.\n"
    "Сейчас работает только vwap."
)


def _parse_on_off(raw: str) -> Optional[bool]:
    s = (raw or "").strip().lower()
    if s in ("on", "1", "true", "yes", "вкл", "включить", "enable", "enabled"):
        return True
    if s in ("off", "0", "false", "no", "выкл", "выключить", "disable", "disabled"):
        return False
    return None


async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_filters_status_text())


async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_CUT_FILTERS_MSG)


async def cmd_filter_cut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_CUT_FILTERS_MSG)


async def callback_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")   # timeout:action[:tf[:field[:value]]]

    action = parts[1]

    if action == "cancel":
        await query.edit_message_text("↩ Отменено")
        return

    if action == "back":
        lines = []
        for tf in TF_KEYS:
            lbl = CONFIG[tf]["label"]
            lines.append(f"{lbl}:  вход {_fmt_h(CONFIG[tf]['limit_h'])}  |  выход {_fmt_h(CONFIG[tf]['position_h'])}")
        await query.edit_message_text(
            "⏱ Таймауты:\n" + "\n".join(lines) + "\n\nВыбери таймфрейм:",
            reply_markup=_timeout_tf_keyboard(),
        )
        return

    if action == "tf":
        tf  = parts[2]
        lbl = CONFIG[tf]["label"]
        await query.edit_message_text(
            f"⏱ [{lbl}]\nЧто изменить?",
            reply_markup=_timeout_field_keyboard(tf),
        )
        return

    if action == "field":
        tf    = parts[2]
        field = parts[3]
        lbl   = CONFIG[tf]["label"]
        fname = "ожидания ВХОДА (лимитка)" if field == "limit_h" else "ожидания ВЫХОДА (позиция)"
        hint = "минутах/часах" if field == "limit_h" else "часах"
        await query.edit_message_text(
            f"⏱ [{lbl}] — таймаут {fname}\nВыбери значение в {hint}:",
            reply_markup=_timeout_value_keyboard(tf, field),
        )
        return

    if action == "set":
        tf    = parts[2]
        field = parts[3]
        value = float(parts[4])
        old   = CONFIG[tf][field]
        CONFIG[tf][field] = value
        save_bot_state()
        lbl   = CONFIG[tf]["label"]
        fname = "Вход" if field == "limit_h" else "Выход"
        logger.info(f"Таймаут [{lbl}] {fname}: {_fmt_h(old)} → {_fmt_h(value)}")
        await query.edit_message_text(
            f"✅ Таймаут обновлён\n"
            f"[{lbl}] {fname}: {_fmt_h(old)} → {_fmt_h(value)}\n\n"
            f"Что ещё изменить?",
            reply_markup=_timeout_field_keyboard(tf),
        )
        return


# ============================================================
# КОМИССИИ (/fee)
# ============================================================
_FEE_PRESETS_PCT = (0.0, 0.01, 0.02, 0.036, 0.04, 0.06, 0.08, 0.10)


def _fee_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Maker", callback_data="fee:type:maker"),
            InlineKeyboardButton("Taker", callback_data="fee:type:taker"),
        ],
        [InlineKeyboardButton("↩ Close", callback_data="fee:cancel")],
    ])


def _fee_value_keyboard(kind: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for pct in _FEE_PRESETS_PCT:
        row.append(InlineKeyboardButton(
            f"{pct:g}%", callback_data=f"fee:set:{kind}:{pct}",
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ Custom", callback_data=f"fee:custom:{kind}")])
    rows.append([
        InlineKeyboardButton("↩ Back", callback_data="fee:back"),
        InlineKeyboardButton("↩ Close", callback_data="fee:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _fee_summary_text() -> str:
    sym = symbol_profile()["label"]
    return (
        f"💰 Trading fees ({sym}, %)\n"
        f"Maker: {_fee_rate_to_pct_str(CONFIG['maker_fee'])}%\n"
        f"Taker: {_fee_rate_to_pct_str(CONFIG['taker_fee'])}%\n\n"
        "Select fee type to edit:"
    )


async def cmd_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("fee_pending", None)
    await update.message.reply_text(
        _fee_summary_text(),
        reply_markup=_fee_type_keyboard(),
    )


async def callback_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")  # fee:action[:kind[:value]]
    action = parts[1]

    if action == "cancel":
        context.user_data.pop("fee_pending", None)
        await query.edit_message_text("↩ Closed")
        return

    if action == "back":
        context.user_data.pop("fee_pending", None)
        await query.edit_message_text(_fee_summary_text(), reply_markup=_fee_type_keyboard())
        return

    if action == "type":
        kind = parts[2]
        label = "Maker" if kind == "maker" else "Taker"
        cur = _fee_rate_to_pct_str(CONFIG[f"{kind}_fee"])
        await query.edit_message_text(
            f"💰 {label} fee (now {cur}%)\nChoose value (% as on exchange):",
            reply_markup=_fee_value_keyboard(kind),
        )
        return

    if action == "custom":
        kind = parts[2]
        label = "Maker" if kind == "maker" else "Taker"
        context.user_data["fee_pending"] = kind
        await query.edit_message_text(
            f"✏️ {label}: send fee in % (e.g. 0.02 or 0.04)\n"
            f"Current: {_fee_rate_to_pct_str(CONFIG[f'{kind}_fee'])}%"
        )
        return

    if action == "set":
        kind = parts[2]
        pct = float(parts[3])
        key = f"{kind}_fee"
        old = CONFIG[key]
        CONFIG[key] = pct / 100.0
        _persist_active_symbol_fees()
        save_bot_state()
        logger.info(f"Fee {kind}: {_fee_rate_to_pct_str(old)}% → {pct:g}%")
        label = "Maker" if kind == "maker" else "Taker"
        await query.edit_message_text(
            f"✅ {label} fee: {_fee_rate_to_pct_str(old)}% → {pct:g}%\n\n"
            + _fee_summary_text(),
            reply_markup=_fee_type_keyboard(),
        )
        return


async def on_fee_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = context.user_data.get("fee_pending")
    if not kind:
        return
    rate = _parse_fee_percent_input(update.message.text or "")
    if rate is None:
        await update.message.reply_text(
            "⚠️ Invalid fee. Example: 0.02 or 0.04 (percent, as on Bybit)"
        )
        return
    key = f"{kind}_fee"
    old = CONFIG[key]
    CONFIG[key] = rate
    _persist_active_symbol_fees()
    save_bot_state()
    context.user_data.pop("fee_pending", None)
    label = "Maker" if kind == "maker" else "Taker"
    pct = _fee_rate_to_pct_str(rate)
    logger.info(f"Fee {kind} (custom): {_fee_rate_to_pct_str(old)}% → {pct}%")
    await update.message.reply_text(
        f"✅ {label} fee: {_fee_rate_to_pct_str(old)}% → {pct}%\n\n"
        + _fee_summary_text(),
        reply_markup=_fee_type_keyboard(),
    )


# ============================================================
# РУЧНОЕ ЗАКРЫТИЕ ПОЗИЦИИ
# ============================================================
# ============================================================
# ВЫБОР ТАЙМФРЕЙМА
# ============================================================
def _pair_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key, prof in SYMBOL_PROFILES.items():
        mark = "✅ " if key == active_symbol_key() else ""
        rows.append([
            InlineKeyboardButton(
                f"{mark}{prof['label']}",
                callback_data=f"pair:set:{key}",
            )
        ])
    rows.append([InlineKeyboardButton("↩ Отмена", callback_data="pair:cancel")])
    return InlineKeyboardMarkup(rows)


async def cmd_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор торговой пары для сканера."""
    cur = symbol_profile()["label"]
    maker, taker = _fee_rates_for()
    await update.message.reply_text(
        f"🪙 Активная пара: {cur}\n"
        f"Комиссии: maker {_fee_rate_to_pct_str(maker)}% / "
        f"taker {_fee_rate_to_pct_str(taker)}%\n\n"
        f"Выбери пару для новых сигналов:",
        reply_markup=_pair_keyboard(),
    )


async def callback_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")

    if parts[1] == "cancel":
        await query.edit_message_text("↩ Отменено")
        return

    new_key = parts[2]
    if new_key not in SYMBOL_PROFILES:
        await query.edit_message_text("⚠️ Неизвестная пара")
        return

    if new_key == active_symbol_key():
        await query.edit_message_text(f"Уже выбрано: {symbol_profile()['label']}")
        return

    old_label = symbol_profile()["label"]
    _apply_symbol_key(new_key)
    _persist_active_symbol_fees()
    save_bot_state()
    new_label = symbol_profile()["label"]
    maker, taker = _fee_rates_for()

    if not state.paper:
        await set_leverage(new_key)

    n_open = sum(1 for p in state.positions if p.status == "open")
    n_pend = sum(1 for pl in state.pending_limits if pl.status == "pending")
    note = ""
    if n_open or n_pend:
        note = (
            f"\n\nОткрытые позиции/лимитки ({n_open}/{n_pend}) "
            f"продолжают работать на своих парах."
        )

    msg = (
        f"🪙 Пара изменена\n"
        f"{old_label}  →  {new_label}\n"
        f"Комиссии: maker {_fee_rate_to_pct_str(maker)}% / "
        f"taker {_fee_rate_to_pct_str(taker)}%"
        f"{note}"
    )
    logger.info(f"Пара сменена: {old_label} → {new_label}")
    await query.edit_message_text(msg)
    await send_telegram(f"🪙 Сканер: {new_label}")


def _tf_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key in TF_KEYS:
        label = CONFIG[key]["label"]
        mark  = "✅ " if key == state.active_tf else ""
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"tf:set:{key}")])
    rows.append([InlineKeyboardButton("↩ Отмена", callback_data="tf:cancel")])
    return InlineKeyboardMarkup(rows)


async def cmd_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор активного таймфрейма сканера."""
    current = CONFIG[state.active_tf]["label"]
    await update.message.reply_text(
        f"📐 Активный ТФ: {current}\n\nВыбери таймфрейм для сканирования:",
        reply_markup=_tf_keyboard(),
    )


async def callback_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")

    if parts[1] == "cancel":
        await query.edit_message_text("↩ Отменено")
        return

    new_tf = parts[2]
    if new_tf not in TF_KEYS:
        await query.edit_message_text("⚠️ Неизвестный ТФ")
        return

    old_label = CONFIG[state.active_tf]["label"]
    state.active_tf = new_tf
    save_bot_state()
    new_label = CONFIG[new_tf]["label"]
    msg = (
        f"📐 Таймфрейм изменён\n"
        f"{old_label}  →  {new_label}\n"
        f"{'─' * 28}\n"
        f"Уже открытые позиции/лимитки с {old_label} "
        f"продолжают работать до закрытия."
    )
    logger.info(f"ТФ сменён: {old_label} → {new_label}")
    await query.edit_message_text(msg)
    await send_telegram(f"📐 Сканер переключён: {new_label}")


def _close_keyboard() -> Optional[InlineKeyboardMarkup]:
    """Позиции (маркет) + pending лимитки (отмена входа)."""
    open_pos = [p for p in state.positions if p.status == "open"]
    pending  = [pl for pl in state.pending_limits if pl.status == "pending"]
    if not open_pos and not pending:
        return None

    price = get_price()
    rows: list[list[InlineKeyboardButton]] = []

    for p in sorted(open_pos, key=lambda x: (x.direction, x.entry_price)):
        arrow = "📈" if p.direction == "LONG" else "📉"
        pnl_str = ""
        if price and _pos_symbol_key(p) == active_symbol_key():
            cv   = p.contracts * _contract_value(_pos_symbol_key(p))
            sign = 1 if p.direction == "LONG" else -1
            pnl_str = f"  PnL: {(price - p.entry_price) * cv * sign:+.2f}$"
        label = f"{arrow} {p.direction}  вход: {p.entry_price:.1f}{pnl_str}"
        rows.append([InlineKeyboardButton(label, callback_data=f"close:select:p:{p.id}")])

    for pl in sorted(pending, key=lambda x: (x.direction, x.entry_price)):
        arrow = "📈" if pl.direction == "LONG" else "📉"
        tfl   = tf_label(pl.tf)
        on_ex = "🟢" if pl.order_id else "⏳"
        label = f"📌 {on_ex} #{pl.trade_num} {arrow} {pl.direction} [{tfl}] @ {pl.entry_price:.1f}"
        rows.append([InlineKeyboardButton(label, callback_data=f"close:select:l:{pl.id}")])

    rows.append([InlineKeyboardButton("↩ Отмена", callback_data="close:cancel")])
    return InlineKeyboardMarkup(rows)


def _close_menu_text() -> str:
    n_pos = sum(1 for p in state.positions if p.status == "open")
    n_lim = sum(1 for pl in state.pending_limits if pl.status == "pending")
    mode  = _mode_prefix()
    lines = [f"📋 Управление [{mode}]"]
    if n_pos:
        lines.append(f"Позиций: {n_pos} — закрыть по маркету")
    if n_lim:
        lines.append(f"Лимиток: {n_lim} — отменить вход")
    lines.append("Выбери:")
    return "\n".join(lines)


def _close_confirm_keyboard(kind: str, item_id: str) -> InlineKeyboardMarkup:
    if kind == "l":
        ok_btn = "✅ Отменить лимитку"
        ok_cb  = f"close:confirm:l:{item_id}"
    else:
        ok_btn = "✅ Закрыть по маркету"
        ok_cb  = f"close:confirm:p:{item_id}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(ok_btn, callback_data=ok_cb),
        InlineKeyboardButton("↩ Назад", callback_data="close:back"),
    ]])


async def _manual_cancel_pending_limit(pl: PendingLimit) -> tuple[bool, str]:
    """Снять pending-лимитку с биржи и из учёта бота."""
    if pl.status != "pending":
        return False, "Лимитка уже не активна"

    if not state.paper and pl.order_id:
        if not await _cancel_pending_entry(pl):
            return (
                False,
                f"🚨 Не удалось снять лимитку с биржи\n"
                f"ID: {pl.id}  |  order: {pl.order_id}\n"
                f"Отмени вручную на Bybit или повтори /close",
            )

    pl.status = "cancelled_manual"
    _journal_log_pending_cancelled(pl)
    _mark_signal_skipped(pl.sig_hash)
    # Баним СЕТАП (SL/TP) до конца HTF-окна, чтобы не пересоздавалось на соседнем trigger_idx
    if not state.paper:
        ratio = int(CONFIG.get(pl.tf, {}).get("htf_ratio") or 60)
        htf_dt = _parse_iso_dt(getattr(pl, "htf_time", "") or "")
        if htf_dt is None:
            htf_dt = _htf_window_start(pl.created_at, ratio)
            pl.htf_time = htf_dt.isoformat()
        htf_time = str(pl.htf_time or htf_dt.isoformat())
        ban_h = _manual_setup_ban_hash(
            tf=pl.tf,
            direction=pl.direction,
            htf_time=htf_time,
            sl=float(pl.stop_price),
            tp=float(pl.tp_price),
        )
        state.processed.add(ban_h)
        save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])
    save_pending(state.pending_limits)
    tfl = tf_label(pl.tf)
    return True, (
        f"🗑 Лимитка #{pl.trade_num} отменена [{tfl}]\n"
        f"ID: {pl.id}  |  {pl.direction}\n"
        f"Entry: {pl.entry_price:.1f}"
    )


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Позиции — закрыть; pending лимитки — отменить вход."""
    if not state.paper:
        await sync_exchange_state()
    kb = _close_keyboard()
    if kb is None:
        await update.message.reply_text("📋 Нет открытых позиций и pending лимиток")
        return
    await update.message.reply_text(_close_menu_text(), reply_markup=kb)



async def callback_start_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения сигнала при /start."""
    query = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    action = parts[1]
    sig_hash = parts[2]
    _cancel_start_confirm_timer(sig_hash)

    if action == "yes":
        await query.edit_message_text(
            query.message.text.replace("Выставить заявку? (60 сек)", "⏳ Выставляю заявку...")
        )
        logger.info(f"start_sig: YES hash={sig_hash}")
        sig = _pending_start_signals.pop(sig_hash, None)
        if sig:
            state.start_confirm_until_ts = 0.0
            ban_h = _manual_setup_ban_hash(
                tf=state.active_tf,
                direction=str(sig.get("direction") or ""),
                htf_time=str(sig.get("htf_time") or ""),
                sl=float(sig.get("stop") or 0),
                tp=float(sig.get("tp") or 0),
            )
            if ban_h in state.processed:
                await query.edit_message_text(
                    query.message.text.replace(
                        "⏳ Выставляю заявку...",
                        "🚫 Не выставляю: этот сетап уже был отменён вручную/по тейку (fib2) в текущем HTF-окне",
                    )
                )
                return

            await create_pending_limit(sig, state.active_tf)
            await query.edit_message_text(
                query.message.text.replace("⏳ Выставляю заявку...", "✅ Заявка выставлена")
            )
        else:
            await query.edit_message_text(
                query.message.text.replace("⏳ Выставляю заявку...", "⚠️ Сигнал устарел, будет обработан при следующем скане")
            )
    else:
        sig = _pending_start_signals.pop(sig_hash, None)
        if not _pending_start_signals:
            state.start_confirm_until_ts = 0.0
        state.processed.add(sig_hash)
        if (not state.paper) and sig:
            ban_h = _manual_setup_ban_hash(
                tf=state.active_tf,
                direction=str(sig.get("direction") or ""),
                htf_time=str(sig.get("htf_time") or ""),
                sl=float(sig.get("stop") or 0),
                tp=float(sig.get("tp") or 0),
            )
            state.processed.add(ban_h)
        save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])
        await query.edit_message_text(
            query.message.text.replace("Выставить заявку? (60 сек)", "❌ Отменён пользователем")
        )
        logger.info(f"start_sig: NO hash={sig_hash}")


async def callback_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрытие позиций и отмена pending лимиток."""
    query = update.callback_query
    await query.answer()
    parts  = query.data.split(":")
    action = parts[1]

    if action in ("cancel", "none"):
        await query.edit_message_text("↩ Отменено")
        return

    if action == "back":
        if not state.paper:
            await sync_exchange_state()
        kb = _close_keyboard()
        if kb is None:
            await query.edit_message_text("📋 Нет открытых позиций и pending лимиток")
            return
        await query.edit_message_text(_close_menu_text(), reply_markup=kb)
        return

    if action == "select":
        kind    = parts[2] if len(parts) >= 4 else "p"
        item_id = parts[3] if len(parts) >= 4 else parts[2]

        if kind == "l" or (
            kind == "p"
            and not any(p.id == item_id and p.status == "open" for p in state.positions)
            and any(pl.id == item_id and pl.status == "pending" for pl in state.pending_limits)
        ):
            pl = next(
                (x for x in state.pending_limits if x.id == item_id and x.status == "pending"),
                None,
            )
            if pl is None:
                await query.edit_message_text("⚠️ Лимитка уже отменена или не найдена")
                return
            tfl   = tf_label(pl.tf)
            arrow = "📈" if pl.direction == "LONG" else "📉"
            ex    = f"ордер: {pl.order_id}" if pl.order_id else "ордер ещё не на бирже"
            await query.edit_message_text(
                f"📌 Лимитка #{pl.trade_num} {arrow} {pl.direction} [{tfl}]\n"
                f"Entry: {pl.entry_price:.1f}  |  {pl.contracts} ctr\n"
                f"Стоп:  {pl.stop_price:.1f}  |  Тейк: {pl.tp_price:.1f}\n"
                f"{ex}\n"
                f"{'─' * 28}\n"
                f"Отменить лимитку?",
                reply_markup=_close_confirm_keyboard("l", pl.id),
            )
            return

        pos = next((p for p in state.positions if p.id == item_id and p.status == "open"), None)
        if pos is None:
            await query.edit_message_text("⚠️ Позиция уже закрыта или не найдена")
            return
        price  = get_price()
        cv     = pos.contracts * _contract_value(_pos_symbol_key(pos))
        sign   = 1 if pos.direction == "LONG" else -1
        pnl_str = ""
        if price:
            pnl_str = f"\nТекущий PnL: {(price - pos.entry_price) * cv * sign:+.2f} USDT"
        arrow = "📈" if pos.direction == "LONG" else "📉"
        tfl = tf_label(pos.tf)
        await query.edit_message_text(
            f"{arrow} {pos.direction} [{tfl}]\n"
            f"Вход:  {pos.entry_price:.1f}\n"
            f"Стоп:  {pos.stop_price:.1f}\n"
            f"Тейк:  {pos.tp_price:.1f}\n"
            f"Контр: {pos.contracts}{pnl_str}\n"
            f"{'─' * 28}\n"
            f"Закрыть по маркету?",
            reply_markup=_close_confirm_keyboard("p", pos.id),
        )
        return

    if action == "confirm":
        kind    = parts[2] if len(parts) >= 4 else "p"
        item_id = parts[3] if len(parts) >= 4 else parts[2]

        if kind == "l":
            pl = next(
                (x for x in state.pending_limits if x.id == item_id and x.status == "pending"),
                None,
            )
            if pl is None:
                await query.edit_message_text("⚠️ Лимитка уже отменена")
                return
            ok, msg = await _manual_cancel_pending_limit(pl)
            prefix  = _mode_prefix() + " "
            await query.edit_message_text(f"{prefix}{msg}" if ok else msg)
            return

        pos = next((p for p in state.positions if p.id == item_id and p.status == "open"), None)
        if pos is None:
            await query.edit_message_text("⚠️ Позиция уже закрыта")
            return

        price = get_price()
        cv    = pos.contracts * _contract_value(_pos_symbol_key(pos))
        sign  = 1 if pos.direction == "LONG" else -1

        if state.paper:
            close_price       = price or pos.entry_price
            pos.status        = "closed_manual"
            pos.close_price   = close_price
            gross, fees, net = _apply_close_pnl(pos, close_price, "closed_manual")
            state.paper_balance += net
            _archive_trade(pos)
            save_positions(state.positions)
            margin = pos.entry_price * cv / CONFIG["leverage"]
            await query.edit_message_text(
                f"{_mode_prefix()} ✅ Позиция закрыта вручную\n"
                f"{'─' * 28}\n"
                f"{symbol_profile(_pos_symbol_key(pos))['label']} {pos.direction} [{tf_label(pos.tf)}]\n"
                f"вход: {_fmt_px(pos.entry_price, _pos_symbol_key(pos))}  "
                f"выход: {_fmt_px(close_price, _pos_symbol_key(pos))}\n"
                f"{_format_close_pnl_lines(gross, fees, net, margin)}\n"
                f"💼 Баланс: {state.paper_balance:.2f} USDT"
            )
        else:
            others = _other_open_on_same_exchange_pid(pos)
            if others:
                nums = ", ".join(f"#{p.trade_num}" for p in others)
                await query.edit_message_text(
                    f"🚨 Общий positionId {pos.exchange_position_id} с {nums}.\n"
                    f"Закрой вручную на Bybit."
                )
                return
            resp = await mexc_close_position_market(
                pos.direction, pos.contracts, price_hint=price,
                position_id=pos.exchange_position_id,
                symbol_key=_pos_symbol_key(pos),
            )
            if not resp:
                await query.edit_message_text(
                    "🚨 Не удалось закрыть позицию маркетом (API).\n"
                    "Позиция оставлена открытой, SL/TP не трогал.\n"
                    "Проверь маржу/лимиты и попробуй ещё раз."
                )
                return

            if pos.stop_order_id:
                await cancel_order(pos.stop_order_id, _pos_symbol_key(pos))
            if pos.tp_order_id:
                await cancel_order(pos.tp_order_id, _pos_symbol_key(pos))

            close_price     = price or pos.entry_price
            pos.status      = "closed_manual"
            pos.close_price = close_price
            gross, fees, net = await _resolve_close_pnl(pos, close_price, "closed_manual")
            close_price = float(pos.close_price or close_price)
            _archive_trade(pos)
            save_positions(state.positions)
            margin = pos.entry_price * cv / CONFIG["leverage"]
            await query.edit_message_text(
                f"✅ Позиция закрыта вручную\n"
                f"{'─' * 28}\n"
                f"{pos.direction}  вход: {pos.entry_price:.1f}  выход: {close_price:.1f}\n"
                f"{_format_close_pnl_lines(gross, fees, net, margin)}"
            )


# ============================================================
# СВЕРКА С БИРЖЕЙ (защита от рассинхрона)
# ============================================================
def _parse_exchange_open_positions(raw_list) -> list[dict]:
    """Активные позиции с биржи: direction, contracts, entry."""
    out = []
    for rp in raw_list or []:
        info = rp.get("info") or {}
        contracts = float(
            rp.get("contracts", 0) or info.get("size") or info.get("holdVol") or info.get("positionVol") or 0
        )
        if contracts <= 0:
            continue
        direction = (rp.get("side") or "").upper()
        if direction not in ("LONG", "SHORT"):
            pt = info.get("positionType") or info.get("positionIdx")
            if str(pt) in ("1",):
                direction = "LONG"
            elif str(pt) in ("2",):
                direction = "SHORT"
        if direction not in ("LONG", "SHORT"):
            continue
        entry_price = float(
            rp.get("entryPrice", 0) or rp.get("averagePrice", 0)
            or info.get("avgPrice") or info.get("openAvgPrice") or info.get("holdAvgPrice") or 0
        )
        if entry_price <= 0:
            continue
        sym_ccxt = str(rp.get("symbol") or info.get("symbol") or "")
        sk = _symbol_key_from_ccxt(sym_ccxt) if sym_ccxt else DEFAULT_SYMBOL_KEY
        bot_ctr = _from_ex_qty(contracts, sk)
        if bot_ctr <= 0:
            continue
        out.append({
            "direction": direction,
            "contracts": bot_ctr,
            "entry": entry_price,
            "position_id": _exchange_position_id_from_raw(rp),
            "symbol_key": sk,
        })
    return out


async def _fetch_exchange_open_order_ids() -> set[str]:
    """ID активных лимиток и planorder (STOP-LIMIT вход) на MEXC."""
    ids: set[str] = set()
    loop = asyncio.get_event_loop()
    for key in _tracked_symbol_keys():
        sym = symbol_profile(key)["symbol"]
        try:
            orders = await loop.run_in_executor(
                None, lambda s=sym: exchange.fetch_open_orders(s)
            )
            for o in orders or []:
                if o.get("id") is not None:
                    ids.add(str(o["id"]))
            try:
                stops = await loop.run_in_executor(
                    None,
                    lambda s=sym: exchange.fetch_open_orders(s, None, None, {"stop": True}),
                )
                for o in stops or []:
                    if o.get("id") is not None:
                        ids.add(str(o["id"]))
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"sync_pending: fetch_open_orders {sym}: {e}")

    rows, _ = await _list_mexc_planorders_tracked(states="1", page_size=100)
    for row in rows:
        oid = row.get("id") or row.get("orderId")
        if oid is not None:
            ids.add(str(oid))
    return ids


async def _fetch_exchange_open_orders_compact() -> list[dict]:
    """Список активных ордеров (обычные + planorder) в одном формате для матчинга."""
    out: list[dict] = []
    loop = asyncio.get_event_loop()

    # Regular open orders
    for key in _tracked_symbol_keys():
        sym = symbol_profile(key)["symbol"]
        try:
            orders = await loop.run_in_executor(
                None, lambda s=sym: exchange.fetch_open_orders(s)
            )
            for o in orders or []:
                oid = o.get("id")
                side = (o.get("side") or "").lower()
                price = o.get("price")
                amount = o.get("amount")
                if oid is None:
                    continue
                if side not in ("buy", "sell"):
                    continue
                try:
                    price_f = float(price) if price is not None else None
                    amt_f = float(amount) if amount is not None else None
                except Exception:
                    continue
                out.append({
                    "id": str(oid), "side": side, "price": price_f,
                    "amount": amt_f, "src": "open", "symbol_key": key,
                })
        except Exception as e:
            logger.warning(f"sync_pending: fetch_open_orders(compact) {sym}: {e}")

    # Plan orders (trigger / stop-limit)
    rows, _ = await _list_mexc_planorders_tracked(states="1", page_size=100)
    for row in rows:
        oid = row.get("id") or row.get("orderId")
        if oid is None:
            continue
        side_raw = str(row.get("side") or "")
        # MEXC futures: 1=open long (buy), 3=open short (sell), 2/4 are close.
        side = "buy" if side_raw == "1" else ("sell" if side_raw == "3" else "")
        if side not in ("buy", "sell"):
            continue
        try:
            price_f = _planorder_row_price(row)
            amt_f = float(row.get("vol") or 0) or None
        except Exception:
            continue
        out.append({"id": str(oid), "side": side, "price": price_f, "amount": amt_f, "src": "plan"})

    return out


def _match_exchange_order_for_pending(pl: PendingLimit, open_orders: list[dict]) -> Optional[str]:
    """Находит активный ордер на бирже, соответствующий pending, даже если order_id другой."""
    exp_side = "buy" if pl.direction == "LONG" else "sell"
    best_id = None
    for o in open_orders or []:
        if o.get("side") != exp_side:
            continue
        price = o.get("price")
        amount = o.get("amount")
        if price is None or amount is None:
            continue
        # Цена должна совпадать почти точно (entry в боте с десятыми)
        if abs(float(price) - float(pl.entry_price)) > max(2.0, float(pl.entry_price) * 0.0002):
            continue
        # Кол-во контрактов: допускаем +-1 (биржа/ccxt может округлить)
        try:
            if abs(float(amount) - float(pl.contracts)) > 1.0:
                continue
        except Exception:
            continue
        best_id = str(o.get("id"))
        break
    return best_id


def _mark_signal_skipped(sig_hash: str):
    """Считать сигнал обработанным (не перевыставлять)."""
    if not sig_hash:
        return
    state.processed.add(sig_hash)
    save_json(SIGNALS_CACHE, sorted(state.processed)[-500:])


def _parse_iso_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _htf_window_start(dt: datetime, ratio_min: int) -> datetime:
    ratio_min = max(1, int(ratio_min or 60))
    floored_min = (dt.minute // ratio_min) * ratio_min
    return dt.replace(minute=floored_min, second=0, microsecond=0)


def _htf_times_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    try:
        return pd.Timestamp(a) == pd.Timestamp(b)
    except Exception:
        return str(a) == str(b)


def _htf_time_for_sig(sig: dict, tf_name: str) -> str:
    htf = str(sig.get("htf_time") or "")
    if htf:
        return htf
    ratio = int(CONFIG[tf_name].get("htf_ratio") or 60)
    return _htf_window_start(utcnow(), ratio).isoformat()


def _htf_time_for_position(p: "Position") -> str:
    htf = str(getattr(p, "htf_time", "") or "")
    if htf:
        return htf
    ratio = int(CONFIG.get(p.tf, {}).get("htf_ratio") or 60)
    return _htf_window_start(p.entry_time, ratio).isoformat()


def _htf_time_for_pending(pl: "PendingLimit", tf_name: str) -> str:
    htf = str(getattr(pl, "htf_time", "") or "")
    if htf:
        return htf
    ratio = int(CONFIG[tf_name].get("htf_ratio") or 60)
    anchor = pl.created_at or utcnow()
    return _htf_window_start(anchor, ratio).isoformat()


def _htf_taken_key(tf_name: str, htf_time: str) -> str:
    try:
        ht = str(pd.Timestamp(htf_time))
    except Exception:
        ht = str(htf_time or "")
    return f"{tf_name}|{ht}"


def _mark_htf_taken(
    tf_name: str,
    htf_time: str,
    *,
    direction: str = "",
    trade_num: int | None = None,
) -> None:
    if not htf_time:
        return
    k = _htf_taken_key(tf_name, htf_time)
    state.htf_taken[k] = {
        "direction": str(direction or ""),
        "trade_num": trade_num,
        "at": utcnow().isoformat(),
    }
    save_bot_state()
    logger.info(
        f"HTF taken lock: {tf_name} [{htf_time}] dir={direction or '?'} "
        f"#{trade_num if trade_num is not None else '-'}"
    )


def _clear_htf_taken_if_idle(pl: "PendingLimit") -> None:
    """Снять HTF taken, если по окну нет open-позиции и других pending."""
    ht = pl.htf_time or _htf_time_for_pending(pl, pl.tf)
    if not ht:
        return
    if _same_htf_open_or_pending("", ht, pl.tf, check_taken=False):
        return
    k = _htf_taken_key(pl.tf, ht)
    if k not in state.htf_taken:
        return
    state.htf_taken.pop(k, None)
    save_bot_state()
    logger.info(
        f"HTF taken clear (cancel, no position): {pl.tf} [{ht}] "
        f"#{pl.trade_num} {pl.status}"
    )


def _reconcile_htf_taken_drop_orphans() -> None:
    """Убрать taken-локи без open/pending (старые cancel без fill, рестарт)."""
    drop: list[str] = []
    for k in list(state.htf_taken):
        parts = k.split("|", 1)
        if len(parts) < 2:
            continue
        tf_name, ht = parts[0], parts[1]
        if _same_htf_open_or_pending("", ht, tf_name, check_taken=False):
            continue
        drop.append(k)
    for k in drop:
        state.htf_taken.pop(k, None)
        logger.info(f"HTF taken orphan drop: {k}")
    if drop:
        save_bot_state()


def _prune_htf_taken(tf_name: str, keep_htf_times: set) -> None:
    """Снять one-shot lock для HTF-окон, ушедших из keep (если нет open/pending)."""
    if not keep_htf_times:
        return
    prefix = f"{tf_name}|"
    for k, meta in list(state.htf_taken.items()):
        if not k.startswith(prefix):
            continue
        lock_htf = k[len(prefix):]
        if _htf_time_in_keep_set(lock_htf, keep_htf_times):
            continue
        # ещё есть работа в этом окне — не трогаем
        if _same_htf_open_or_pending("", lock_htf, tf_name, check_taken=False):
            continue
        state.htf_taken.pop(k, None)
        logger.info(f"HTF taken prune: {tf_name} [{lock_htf}]")
    # bot_state сохраняется периодически; явный save при prune не обязателен


def _reconcile_htf_taken_from_live() -> None:
    """После рестарта: open/pending → htf_taken (one-shot на окно)."""
    for p in state.positions:
        if p.status != "open":
            continue
        ht = _htf_time_for_position(p)
        if not ht:
            continue
        k = _htf_taken_key(p.tf, ht)
        if k not in state.htf_taken:
            state.htf_taken[k] = {
                "direction": p.direction,
                "trade_num": p.trade_num,
                "at": utcnow().isoformat(),
            }
    for pl in state.pending_limits:
        active = (
            pl.status == "pending"
            or pl.id in state._fill_in_progress
            or (pl.status == "filled" and not _filled_pending_stale(pl))
        )
        if not active:
            continue
        ht = _htf_time_for_pending(pl, pl.tf)
        if not ht:
            continue
        k = _htf_taken_key(pl.tf, ht)
        if k not in state.htf_taken:
            state.htf_taken[k] = {
                "direction": pl.direction,
                "trade_num": pl.trade_num,
                "at": utcnow().isoformat(),
            }


def _same_htf_open_or_pending(
    direction: str,
    htf_time: str,
    tf_name: str,
    *,
    check_taken: bool = True,
) -> Optional[str]:
    """Блок если HTF-окно уже занято: open/pending/fill или one-shot taken (любое направление)."""
    _ = direction  # раньше фильтровали по dir; теперь 1 триггер на HTF
    if check_taken and htf_time:
        k = _htf_taken_key(tf_name, htf_time)
        meta = state.htf_taken.get(k)
        if meta:
            d0 = meta.get("direction") or "?"
            n0 = meta.get("trade_num")
            return f"USED {d0}" + (f" #{n0}" if n0 is not None else "")

    for p in state.positions:
        if p.status != "open" or p.tf != tf_name:
            continue
        p_htf = _htf_time_for_position(p)
        if _htf_times_match(htf_time, p_htf):
            return f"OPEN #{p.trade_num} {p.direction} htf={p_htf}"

    for pl in state.pending_limits:
        if pl.tf != tf_name:
            continue
        active = (
            pl.status == "pending"
            or pl.id in state._fill_in_progress
            or (pl.status == "filled" and not _filled_pending_stale(pl))
        )
        if not active:
            continue
        pl_htf = _htf_time_for_pending(pl, tf_name)
        if _htf_times_match(htf_time, pl_htf):
            return f"{pl.status.upper()} #{pl.trade_num} {pl.direction} {pl.id[:8]} htf={pl_htf}"
    return None


def _sig_setup_params(sig: dict, tf_name: str) -> dict:
    tf_cfg = CONFIG[tf_name]
    htf_time = str(sig.get("htf_time") or "")
    if not htf_time:
        ratio = int(tf_cfg.get("htf_ratio") or 60)
        htf_time = _htf_window_start(utcnow(), ratio).isoformat()
    return {
        "tf": tf_name,
        "direction": str(sig.get("direction") or ""),
        "htf_time": htf_time,
        "sl": float(sig.get("stop") or 0),
        "tp": float(sig.get("tp") or 0),
    }


def _setup_sl_tp_match(sl_a: float, tp_a: float, sl_b: float, tp_b: float) -> bool:
    return abs(sl_a - sl_b) < 0.05 and abs(tp_a - tp_b) < 0.05


def _find_active_work_for_signal(sig: dict, tf_name: str) -> Optional[str]:
    """Сетап уже в pending/open — краткое описание для /start."""
    sp = _sig_setup_params(sig, tf_name)
    conflict = _same_htf_open_or_pending(sp["direction"], sp["htf_time"], tf_name)
    if conflict:
        return conflict
    sig_hash = str(sig.get("hash") or "")

    for pl in state.pending_limits:
        if pl.status != "pending" or pl.tf != sp["tf"] or pl.direction != sp["direction"]:
            continue
        if sig_hash and pl.sig_hash == sig_hash:
            extra = f", ордер {pl.order_id}" if pl.order_id else ""
            return f"pending #{pl.trade_num} {pl.id}{extra}"
        pl_htf = _htf_time_for_pending(pl, tf_name)
        if _htf_times_match(pl_htf, sp["htf_time"]) and _setup_sl_tp_match(
            pl.stop_price, pl.tp_price, sp["sl"], sp["tp"],
        ):
            extra = f", ордер {pl.order_id}" if pl.order_id else ""
            return f"pending #{pl.trade_num} {pl.id}{extra}"

    for pos in state.positions:
        if pos.status != "open" or pos.tf != sp["tf"] or pos.direction != sp["direction"]:
            continue
        if sig_hash and getattr(pos, "sig_hash", "") == sig_hash:
            return f"OPEN #{pos.trade_num} @ {pos.entry_price:.1f}"
        pos_htf = _htf_time_for_position(pos)
        if _htf_times_match(pos_htf, sp["htf_time"]) and _setup_sl_tp_match(
            pos.stop_price, pos.tp_price, sp["sl"], sp["tp"],
        ):
            return f"OPEN #{pos.trade_num} @ {pos.entry_price:.1f}"
    return None


def _format_signal_card(sig: dict, tfl: str) -> str:
    direction = sig["direction"]
    arrow = "📈" if direction == "LONG" else "📉"
    entry = sig["entry"]
    stop = sig["stop"]
    tp = sig["tp"]
    sl_pct = abs(stop - entry) / entry * 100
    tp_pct = abs(tp - entry) / entry * 100
    rr = tp_pct / sl_pct if sl_pct > 0 else 0
    sig_time = msk(sig["timestamp"]).strftime("%H:%M") if sig.get("timestamp") else "?"
    entry_lbl = " (confirm на баре свипа)" if sig.get("confirm_on_sweep") else ""
    return (
        f"{arrow} Сигнал [{sig_time}] {direction} [{tfl}]\n"
        f"Вход: {_fmt_px(entry)}{entry_lbl}\n"
        f"Стоп: {_fmt_px(stop)} ({sl_pct:.2f}%)\n"
        f"Тейк: {_fmt_px(tp)} ({tp_pct:.2f}%)\n"
        f"R:R:  {rr:.2f}"
    )


def _pending_matches_setup(
    pl: "PendingLimit", sp: dict, sig_hash: str, tf_name: str,
) -> bool:
    if pl.direction != sp["direction"]:
        return False
    if sig_hash and pl.sig_hash == sig_hash:
        return True
    return (
        _htf_times_match(_htf_time_for_pending(pl, tf_name), sp["htf_time"])
        and _setup_sl_tp_match(pl.stop_price, pl.tp_price, sp["sl"], sp["tp"])
    )


def _position_matches_setup(
    pos: "Position", sp: dict, sig_hash: str, tf_name: str,
) -> bool:
    if pos.direction != sp["direction"]:
        return False
    if sig_hash and getattr(pos, "sig_hash", "") == sig_hash:
        return True
    return (
        _htf_times_match(_htf_time_for_position(pos), sp["htf_time"])
        and _setup_sl_tp_match(pos.stop_price, pos.tp_price, sp["sl"], sp["tp"])
    )


def _format_active_pending_card(pl: "PendingLimit", tfl: str, *, note: str) -> str:
    arrow = "📈" if pl.direction == "LONG" else "📉"
    oid = f"  |  ордер {pl.order_id}" if pl.order_id else ""
    return (
        f"{arrow} Pending #{pl.trade_num} {pl.direction} [{tfl}]\n"
        f"ID: {pl.id}{oid}\n"
        f"Entry: {pl.entry_price:.1f}  Stop: {pl.stop_price:.1f}  TP: {pl.tp_price:.1f}\n\n"
        f"✅ {note}"
    )


def _format_active_open_card(pos: "Position", tfl: str, *, note: str) -> str:
    arrow = "📈" if pos.direction == "LONG" else "📉"
    return (
        f"{arrow} OPEN #{pos.trade_num} {pos.direction} [{tfl}]\n"
        f"Entry: {pos.entry_price:.1f}  Stop: {pos.stop_price:.1f}  TP: {pos.tp_price:.1f}\n\n"
        f"✅ {note}"
    )


def _build_start_in_progress_blocks(tf_name: str, tfl: str, signals: list) -> list[str]:
    """Все сетапы в работе: match по сигналам скана + оставшиеся pending/open."""
    blocks: list[str] = []
    matched_pl: set[str] = set()
    matched_pos: set[str] = set()

    for sig in signals[:5]:
        active = _find_active_work_for_signal(sig, tf_name)
        if not active:
            continue
        if active.startswith("USED "):
            note = f"⏭ HTF-окно уже использовано: {active[5:]}"
        else:
            note = f"✅ Сетап уже в работе: {active}"
        blocks.append(f"{_format_signal_card(sig, tfl)}\n\n{note}")
        sp = _sig_setup_params(sig, tf_name)
        sig_hash = str(sig.get("hash") or "")
        for pl in state.pending_limits:
            if _pending_matches_setup(pl, sp, sig_hash, tf_name):
                matched_pl.add(pl.id)
        for pos in state.positions:
            if _position_matches_setup(pos, sp, sig_hash, tf_name):
                matched_pos.add(pos.id)

    for pl in state.pending_limits:
        if pl.status != "pending" or pl.tf != tf_name or pl.id in matched_pl:
            continue
        note = f"Уже в работе: pending #{pl.trade_num} {pl.id}"
        if pl.order_id:
            note += f", ордер {pl.order_id}"
        blocks.append(_format_active_pending_card(pl, tfl, note=note))

    for pos in state.positions:
        if pos.status != "open" or pos.tf != tf_name or pos.id in matched_pos:
            continue
        blocks.append(_format_active_open_card(
            pos, tfl, note=f"Уже в работе: OPEN #{pos.trade_num} @ {pos.entry_price:.1f}",
        ))

    return blocks


async def _reply_start_in_progress(update, tf_name: str, tfl: str, signals: list) -> bool:
    blocks = _build_start_in_progress_blocks(tf_name, tfl, signals)
    if not blocks:
        return False
    await update.message.reply_text(
        "\n\n".join(blocks) + "\n\nПродолжаю мониторинг — кнопки не нужны."
    )
    return True


def _is_setup_banned(sig: dict, tf_name: str) -> bool:
    sp = _sig_setup_params(sig, tf_name)
    return _manual_setup_ban_hash(**sp) in state.processed


def _manual_setup_ban_key(*, tf: str, direction: str, htf_time: str, sl: float, tp: float) -> str:
    # Только SL/TP (entry не участвует) + TF/направление + HTF окно
    sk = active_symbol_key()
    sl_r = _round_price(sl, sk)
    tp_r = _round_price(tp, sk)
    dec = _price_decimals(symbol_profile(sk)["price_tick"])
    return f"{tf}|{direction}|{htf_time}|sl={sl_r:.{dec}f}|tp={tp_r:.{dec}f}"


def _manual_setup_ban_hash(*, tf: str, direction: str, htf_time: str, sl: float, tp: float) -> str:
    """Короткий ключ для state.processed: бан сетапа до конца HTF окна.

    Включает htf_time → бан автоматически заканчивается на следующем HTF окне.
    Игнорирует trigger_idx и entry (только SL/TP).
    """
    key = _manual_setup_ban_key(tf=tf, direction=direction, htf_time=htf_time, sl=sl, tp=tp)
    return hashlib.md5(f"BAN_SETUP|{key}".encode()).hexdigest()[:16]


def _cleanup_manual_setup_bans(now_ts: Optional[float] = None):
    now_ts = float(now_ts or time.time())
    if not state.manual_setup_bans:
        return
    expired = [k for k, exp in state.manual_setup_bans.items() if float(exp or 0) <= now_ts]
    for k in expired:
        state.manual_setup_bans.pop(k, None)


async def _sync_pending_with_exchange(
    real_open: Optional[list[dict]] = None,
) -> int:
    """Снимает pending, если entry-ордер снят с биржи вручную."""
    if state.paper:
        return 0

    open_ids = await _fetch_exchange_open_order_ids()
    open_orders = await _fetch_exchange_open_orders_compact()
    if real_open is None:
        real_open = await _fetch_real_open_positions()

    removed = 0
    now = utcnow()
    for pl in state.pending_limits:
        if pl.status != "pending" or not pl.order_id:
            continue

        if _pending_in_exchange_grace(pl):
            continue

        oid = str(pl.order_id)

        if _exchange_match_for_pending(pl, real_open):
            continue  # исполнилось — fill обработает sync/limit_monitor

        if oid in open_ids:
            continue

        matched_id = _match_exchange_order_for_pending(pl, open_orders)
        if matched_id:
            pl.order_id = matched_id
            if not pl.order_placed_at:
                pl.order_placed_at = now
            save_pending(state.pending_limits)
            logger.info(f"sync_pending: #{pl.trade_num} {pl.id} order_id обновлён → {matched_id}")
            continue

        info = await get_order_status(oid)
        if info and _order_is_filled(info, pl.contracts):
            continue

        st = str((info or {}).get("status") or "").lower()
        if st in ("open", "new", "unknown", ""):
            continue

        # Нет ордера среди активных и не filled — снято (в т.ч. ручная отмена на бирже)
        if _pending_entry_absent_on_exchange(pl, open_ids, open_orders, real_open):
            await _notify_cancel_false_alarm_resolved(
                pl, "Отмена подтверждена при сверке с биржей"
            )
            _finalize_pending_removed_manual(pl, log_tag="(нет на бирже)")
            removed += 1
            continue

        if info and _order_info_is_cancelled(info) and not _order_is_filled(info, pl.contracts):
            if _pending_trigger_zone(pl, get_price(), None, None):
                continue
            await _notify_cancel_false_alarm_resolved(
                pl, f"Статус ордера: {st}"
            )
            _finalize_pending_removed_manual(pl, log_tag=f"(status={st})")
            removed += 1

    if removed:
        save_pending(state.pending_limits)
    return removed


async def sync_exchange_state() -> tuple[int, int]:
    """Сверка позиций и pending с биржей.

    Returns:
        (позиций снято с учёта, pending отменено как снятые с биржи)
    """
    if state.paper:
        return 0, 0

    _cleanup_stale_filled_pendings()

    try:
        loop = asyncio.get_event_loop()
        real_positions = await loop.run_in_executor(None, _fetch_positions_linear)
    except Exception as e:
        logger.warning(f"sync_exchange: fetch_positions error: {e}")
        return 0, await _sync_pending_with_exchange()

    real_open = _parse_exchange_open_positions(real_positions)

    for rp in real_open:
        contracts     = rp["contracts"]
        entry_price     = rp["entry"]
        direction       = rp["direction"]
        contracts_int   = int(contracts)
        rp_sym          = rp.get("symbol_key", DEFAULT_SYMBOL_KEY)

        found = False
        for pos in state.positions:
            if (
                pos.status == "open"
                and pos.direction == direction
                and _pos_symbol_key(pos) == rp_sym
            ):
                if _position_matches_exchange(pos, real_open):
                    found = True
                    if _maybe_mark_exchange_seen(pos, real_open):
                        save_positions(state.positions)
                    if (
                        pos.stop_price > 0
                        and not _position_protection_frozen(pos.id)
                        and await _position_sl_tp_needs_restore(pos)
                    ):
                        await _restore_position_sl_tp(pos, alert=True)
                    break

        if not found:
            if _fill_in_progress_for_exchange(direction, entry_price):
                logger.info(
                    f"sync_exchange: finalize in progress {direction} "
                    f"@{entry_price:.1f} — skip orphan"
                )
                continue

            stuck = _filled_pending_without_position(direction, entry_price)
            if stuck is not None:
                logger.info(
                    f"sync_exchange: filled pending {stuck.id} без open position "
                    f"— skip orphan, ждём finalize"
                )
                continue

            matched_pl = _find_pending_for_exchange(direction, entry_price)
            if matched_pl is not None:
                if matched_pl.status == "pending":
                    await _finalize_limit_fill(
                        matched_pl, entry_price, contracts_int, utcnow()
                    )
                    logger.info(
                        f"sync_exchange: pending {matched_pl.id} → filled "
                        f"({direction} {contracts_int}@{entry_price:.1f})"
                    )
                else:
                    logger.info(
                        f"sync_exchange: {direction} {contracts_int} @ {entry_price:.1f} — "
                        f"ждём limit_monitor"
                    )
                continue

            if _exchange_leg_matches_recent_close(direction, entry_price, contracts_int):
                logger.info(
                    f"sync_exchange: {direction} {contracts_int}ctr @ {entry_price:.1f} "
                    f"— skip orphan (недавно закрыли, лаг биржи)"
                )
                continue
            if await _has_recent_close_deal_for_leg(
                direction, contracts_int, lookback_min=5,
            ):
                logger.info(
                    f"sync_exchange: {direction} {contracts_int}ctr @ {entry_price:.1f} "
                    f"— skip orphan (close-deal на бирже)"
                )
                continue

            if _exchange_leg_covers_bot_open(direction, real_open):
                logger.info(
                    f"sync_exchange: {direction} {contracts_int}ctr @ {entry_price:.1f} "
                    f"— skip orphan (агрегат open бота на бирже)"
                )
                continue

            # Позиция есть на бирже, но не в стейте!
            tfl = tf_label(state.active_tf)
            pos = Position(
                pos_id      = f"X{uuid.uuid4().hex[:8]}",
                direction   = direction,
                entry_price = entry_price,
                stop_price  = 0.0,   # пока нет
                tp_price    = 0.0,
                contracts   = contracts_int,
                entry_time  = utcnow(),
                exit_time   = utcnow() + timedelta(hours=CONFIG[state.active_tf]["position_h"]),
                tf          = state.active_tf,
                trade_num   = state.next_trade_num(),
            )
            pos.signal_category = "abnormal"
            pos.entry_kind = "sync_orphan"
            pos.symbol_key = rp_sym
            for r in real_open:
                if (
                    r.get("direction") == direction
                    and r.get("symbol_key", DEFAULT_SYMBOL_KEY) == rp_sym
                    and _entry_near(r["entry"], entry_price)
                    and _contracts_near(r["contracts"], contracts_int)
                ):
                    rpid = r.get("position_id")
                    if rpid:
                        pos.exchange_position_id = str(rpid)
                    break
            state.positions.append(pos)
            save_positions(state.positions)
            logger.warning(
                f"sync_exchange: НАЙДЕНА чужая позиция! {direction} "
                f"{contracts_int}ctr @ {entry_price:.1f} → добавлена как {pos.id}"
            )
            await send_telegram(
                f"⚠️ ОБНАРУЖЕНА ПОЗИЦИЯ БЕЗ ВЕДОМА БОТА!\n"
                f"Направление: {direction}  |  {contracts_int} контр.\n"
                f"Вход: {entry_price:.1f}\n"
                f"Стоп и тейк НЕ выставлены — закрой вручную или дай команду!"
            )

    # Позиции в стейте, которых нет на бирже → закрыть + снять plan TP/SL + TG
    closed_n = 0
    for pos in state.positions:
        if pos.status != "open":
            continue
        if await _try_finalize_filled_protection(pos):
            if pos.status != "open":
                closed_n += 1
                logger.info(
                    f"sync_exchange: {pos.id} #{pos.trade_num} [{pos.direction}] "
                    f"@{pos.entry_price:.1f} → {pos.status} @ {pos.close_price:.1f}"
                )
            continue
        if not await _position_absent_on_exchange(pos, real_open):
            continue
        if pos.entry_kind == "sync_orphan" and _exchange_leg_matches_recent_close(
            pos.direction, pos.entry_price, pos.contracts,
        ):
            pos.status = "cancelled_phantom"
            save_positions(state.positions)
            closed_n += 1
            logger.info(
                f"sync_exchange: phantom {pos.id} #{pos.trade_num} снят "
                f"(дубль после закрытия, без TG)"
            )
            continue
        reason, close_price = await _detect_position_close_reason(pos)
        notify = not (
            pos.entry_kind == "sync_orphan" and reason == "closed_sync"
        )
        await _finalize_position_close(pos, reason, close_price, notify=notify)
        if pos.status == "open":
            logger.info(
                f"sync_exchange: {pos.id} #{pos.trade_num} [{pos.direction}] "
                f"@{pos.entry_price:.1f} — {reason} отложен (в стейте open)"
            )
            continue
        closed_n += 1
        logger.info(
            f"sync_exchange: {pos.id} #{pos.trade_num} [{pos.direction}] "
            f"@{pos.entry_price:.1f} → {pos.status} @ {close_price:.1f}"
        )

    ro_final = await _fetch_real_open_positions()
    for _dir in ("LONG", "SHORT"):
        _maybe_schedule_ghost_cleanup_sync(_dir, ro_final)

    pending_n = await _sync_pending_with_exchange(real_open)
    return closed_n, pending_n


async def exchange_sync_loop():
    """Фоновый цикл сверки с биржей каждые 30 секунд. В SHADOW не дергаем приватный API записи."""
    while True:
        if state.paper or not state.tasks_live.is_set():
            await asyncio.sleep(5)
            continue
        await asyncio.sleep(30)
        try:
            await sync_exchange_state()
        except Exception as e:
            logger.error(f"exchange_sync_loop: {e}")


# ============================================================
# MAIN
# ============================================================
async def main():
    global _tg_app, _trade_log_month

    mode_str = "SHADOW" if state.paper else "LIVE"
    logger.info("=" * 58)
    logger.info(
        f"CISD BOT v6.0-bybit — {len(ACTIVE_SYMBOL_KEYS)} пар × tf7+tf8 | {mode_str}"
    )
    logger.info(
        f"LIMIT-only TP=1R vwap | leverage {CONFIG['leverage']}x isolated | "
        f"max {CONFIG['max_positions']} pos"
    )
    logger.info("=" * 58)

    load_bot_state()
    try:
        await asyncio.get_event_loop().run_in_executor(None, exchange.load_markets)
    except Exception as e:
        logger.warning(f"load_markets: {e}")
    state.pending_limits = load_pending()
    state.positions      = load_positions()
    _reconcile_htf_taken_from_live()
    _reconcile_htf_taken_drop_orphans()
    n_pending = sum(1 for p in state.pending_limits if p.status == "pending")
    n_open    = sum(1 for p in state.positions if p.status == "open")
    logger.info(
        f"Загружено: {n_pending} pending, {n_open} open | ТФ: {tf_label(state.active_tf)} "
        f"| htf_taken={len(state.htf_taken)}"
    )

    _trade_log_month = utcnow().strftime("%Y-%m")
    os.makedirs(TRADE_LOG_DIR, exist_ok=True)

    await sync_positions_on_start()

    if not state.paper:
        await set_leverage_all()

    # Telegram: только сборка приложения, без сетевых вызовов
    _tg_app = _build_tg_application()
    logger.info("Торговые задачи стартуют сразу; Telegram подключится в фоне")

    ctl_server.configure(
        token_path=CTL_TOKEN_FILE,
        on_start=ctl_start,
        on_stop=ctl_stop,
        on_status=ctl_status,
        on_health=ctl_health,
    )
    await ctl_server.start_ctl_server()

    async def supervised(coro_fn, name: str):
        """Оборачивает задачу: при падении логирует, уведомляет и перезапускает через 30 сек."""
        while True:
            await state.tasks_live.wait()
            try:
                await coro_fn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.critical(f"Задача {name} упала: {exc}", exc_info=True)
                if not state.tasks_live.is_set():
                    logger.info(f"Задача {name}: halt — без TG и без перезапуска")
                    await state.tasks_live.wait()
                    continue
                now_ts = time.time()
                last_ts = _task_alert_ts.get(name, 0.0)
                if now_ts - last_ts >= 300:
                    _task_alert_ts[name] = now_ts
                    await send_telegram(
                        f"🚨 Task {name} crashed\n{exc}\n"
                        f"Restart in 30s..."
                    )
                await asyncio.sleep(30)
                logger.info(f"Перезапуск задачи {name}...")

    tasks = [
        asyncio.create_task(supervised(price_stream,          "price_stream"),    name="price_stream"),
        asyncio.create_task(supervised(price_stale_watchdog,  "price_watchdog"),  name="price_watchdog"),
        asyncio.create_task(supervised(signal_scanner,        "signal_scanner"),  name="signal_scanner"),
        asyncio.create_task(supervised(limit_monitor,         "limit_monitor"),   name="limit_monitor"),
        asyncio.create_task(supervised(position_monitor,      "position_monitor"), name="position_monitor"),
        asyncio.create_task(supervised(exchange_sync_loop,    "exchange_sync"),   name="exchange_sync"),
        asyncio.create_task(supervised(telegram_connect_loop, "telegram"),        name="telegram"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ctl_server.stop_ctl_server()
        await _tg_shutdown_safe()


if __name__ == "__main__":
    asyncio.run(main())
