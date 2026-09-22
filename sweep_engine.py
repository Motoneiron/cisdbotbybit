"""
Свип внутри байбит-бота. Bybit USDT linear, 10 пар, 4ч и 8ч.

Свип — старшая свеча высунула фитиль за экстремум прошлой и минутная
свеча закрылась обратно. Фитиль вверх — шорт, вниз — лонг. Берём только
короткий фитиль: глубина не больше четверти всех прошлых свипов этого
таймфрейма по всем парам. Пока своих свипов до сегодня меньше 200,
порог стоит на конце выборки: 0,174% на 4ч и 0,261% на 8ч.

На паре одна сделка. Кто подтвердился раньше, тот и занимает пару.
В одну минуту 4ч важнее 8ч. Лимит на цене минутного закрытия, 5 минут.
Цель +0,50%, стоп 0,20%, через 240 минут выход по рынку.

Риск 0,15% депозита на стоп. Стоп в размере позиции заложен как 0,40%
цены (ход 0,20% и комиссия входа и выхода). Плечо 10×, маржа изолированная
в учёте. Если свободной маржи меньше — берём сколько есть.
Ордеров на биржу нет, свой бумажный баланс 100 USDT.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import ccxt
import numpy as np
import pandas as pd

logger = logging.getLogger("cisd_bot.sweep")

PAIRS = ("BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL")
HTFS = (240, 480)
HTF_NAME = {240: "4ч", 480: "8ч"}
SEED_Q = {240: 0.1742, 480: 0.2607}
MIN_PAST = 200
TARGET_PCT = 0.50
STOP_PCT = 0.20
STOP_COST_PCT = 0.40
RISK_PCT = 0.15
LEVERAGE = 10
LIMIT_MIN = 5
POSITION_MIN = 240
MAKER = 0.00036
TAKER = 0.001
MIN_NOTIONAL = 5.0
PAPER_BALANCE = 100.0

FEES = {"maker_fee": MAKER, "taker_fee": TAKER}
SYMBOLS: dict[str, dict] = {
    "SOL":  {"symbol": "SOL/USDT:USDT",  "label": "SOL/USDT",  "step": 0.1,    "tick": 0.01},
    "BTC":  {"symbol": "BTC/USDT:USDT",  "label": "BTC/USDT",  "step": 0.001,  "tick": 0.1},
    "ETH":  {"symbol": "ETH/USDT:USDT",  "label": "ETH/USDT",  "step": 0.01,   "tick": 0.01},
    "DOGE": {"symbol": "DOGE/USDT:USDT", "label": "DOGE/USDT", "step": 1.0,    "tick": 0.00001},
    "KAS":  {"symbol": "KAS/USDT:USDT",  "label": "KAS/USDT",  "step": 10.0,   "tick": 0.00001},
    "ADA":  {"symbol": "ADA/USDT:USDT",  "label": "ADA/USDT",  "step": 1.0,    "tick": 0.0001},
    "BNB":  {"symbol": "BNB/USDT:USDT",  "label": "BNB/USDT",  "step": 0.01,   "tick": 0.1},
    "LINK": {"symbol": "LINK/USDT:USDT", "label": "LINK/USDT", "step": 0.1,    "tick": 0.001},
    "LTC":  {"symbol": "LTC/USDT:USDT",  "label": "LTC/USDT",  "step": 0.1,    "tick": 0.01},
    "XRP":  {"symbol": "XRP/USDT:USDT",  "label": "XRP/USDT",  "step": 0.1,    "tick": 0.0001},
}
for _p in SYMBOLS.values():
    _p.update(FEES)

Notify = Callable[[str], Awaitable[None]]
Flag = Callable[[], bool]

_notify: Optional[Notify] = None
_scanner_on: Flag = lambda: True
_tasks_on: Flag = lambda: True
_base_dir = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(_base_dir, "sweep_state.json")

_exchange: Optional[ccxt.bybit] = None


def bind(
    *,
    notify: Notify,
    scanner_on: Flag,
    tasks_on: Flag,
    base_dir: str,
) -> None:
    """Подключение к боту: куда слать текст, пауза сканера, полная остановка."""
    global _notify, _scanner_on, _tasks_on, _base_dir, STATE_PATH, STATE
    _notify = notify
    _scanner_on = scanner_on
    _tasks_on = tasks_on
    _base_dir = base_dir
    STATE_PATH = os.path.join(base_dir, "sweep_state.json")
    STATE = load_state()


def _empty_state() -> dict:
    return {
        "balance": PAPER_BALANCE,
        "next_id": 1,
        "sweeps": [],
        "pending": [],
        "positions": [],
        "trades": [],
        "seen": [],
        "born": datetime.now(timezone.utc).isoformat(),
        "small_note": {},
    }


def load_state() -> dict:
    if not os.path.isfile(STATE_PATH):
        return _empty_state()
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        base = _empty_state()
        base.update(data)
        return base
    except Exception as e:
        logger.error(f"sweep state load: {e}")
        return _empty_state()


def save_state(state: dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


STATE = load_state()
LOCK = asyncio.Lock()
BARS: dict[str, pd.DataFrame] = {}
PRICES: dict[str, tuple[float, float]] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t


def day_num(ts) -> int:
    return int(_ts(ts).timestamp() // 86400)


def bucket_start(ts, htf_min: int) -> pd.Timestamp:
    t = _ts(ts)
    span = htf_min * 60
    start = int(t.timestamp()) - (int(t.timestamp()) % span)
    return pd.Timestamp(start, unit="s", tz="UTC")


def tick_decimals(tick: float) -> int:
    if tick >= 1:
        return 0
    return max(0, int(round(-math.log10(tick))))


def fmt_px(px: float, key: str) -> str:
    dec = tick_decimals(SYMBOLS[key]["tick"])
    return f"{px:.{dec}f}"


def round_tick(px: float, key: str) -> float:
    tick = SYMBOLS[key]["tick"]
    dec = tick_decimals(tick)
    return round(math.floor(px / tick + 0.5) * tick, dec)


def floor_step(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    n = math.floor(qty / step + 1e-9)
    dec = tick_decimals(step) if step < 1 else 0
    if step >= 1 and abs(step - round(step)) < 1e-9:
        dec = 0
    return round(n * step, dec)


def mode_tag() -> str:
    return "🧪 SWEEP"


def past_sweeps(htf: int, today: int) -> list[float]:
    return [
        float(s["depth"])
        for s in STATE["sweeps"]
        if int(s["htf"]) == htf and int(s["day"]) < today
    ]


def threshold(htf: int, today: int) -> tuple[float, str]:
    depths = past_sweeps(htf, today)
    if len(depths) < MIN_PAST:
        return SEED_Q[htf], f"старт, своих до сегодня {len(depths)}/{MIN_PAST}"
    q = float(np.quantile(np.asarray(depths, dtype=float), 0.25))
    return q, f"четверть {len(depths)} прошлых свипов"


def is_short(depth: float, htf: int, today: int) -> tuple[bool, float, str]:
    q, how = threshold(htf, today)
    return depth <= q + 1e-9, q, how


def record_sweep(sym: str, htf: int, bucket: str, direction: str, depth: float, rej_iso: str) -> None:
    key = f"{sym}|{htf}|{bucket}|{direction}"
    day = day_num(rej_iso)
    for row in STATE["sweeps"]:
        if row.get("key") == key:
            row["depth"] = depth
            row["day"] = day
            row["rej"] = rej_iso
            return
    STATE["sweeps"].append({
        "key": key,
        "sym": sym,
        "htf": htf,
        "bucket": bucket,
        "direction": direction,
        "depth": float(depth),
        "day": day,
        "rej": rej_iso,
    })


def remember(key: str) -> bool:
    seen: list = STATE["seen"]
    if key in seen:
        return True
    seen.append(key)
    if len(seen) > 5000:
        del seen[: len(seen) - 4000]
    return False


def _window(bars: pd.DataFrame, start: pd.Timestamp, minutes: int) -> pd.DataFrame:
    end = start + pd.Timedelta(minutes=minutes)
    return bars[(bars.index >= start) & (bars.index < end)]


def _covered(w: pd.DataFrame, start: pd.Timestamp, minutes: int) -> bool:
    if w.empty:
        return False
    end = start + pd.Timedelta(minutes=minutes)
    if w.index[0] > start + pd.Timedelta(minutes=2):
        return False
    if w.index[-1] < end - pd.Timedelta(minutes=2):
        return False
    return len(w) >= int(minutes * 0.9)


def _side(window: pd.DataFrame, direction: str, level: float) -> Optional[dict]:
    if window.empty or level <= 0:
        return None
    if direction == "SHORT":
        extreme = float(window["high"].max())
        if extreme <= level:
            return None
        wick_ts = window["high"].idxmax()
        after = window.loc[wick_ts:]
        hit = after[after["close"] < level]
        depth = (extreme - level) / level * 100.0
    else:
        extreme = float(window["low"].min())
        if extreme >= level:
            return None
        wick_ts = window["low"].idxmin()
        after = window.loc[wick_ts:]
        hit = after[after["close"] > level]
        depth = (level - extreme) / level * 100.0
    if hit.empty:
        return None
    rej = hit.index[0]
    return {
        "direction": direction,
        "level": float(level),
        "extreme": float(extreme),
        "depth": float(depth),
        "wick": _ts(wick_ts).isoformat(),
        "rej": _ts(rej).isoformat(),
        "entry": float(hit.iloc[0]["close"]),
    }


def analyze_window(window: pd.DataFrame, prev_high: float, prev_low: float) -> list[dict]:
    out = []
    for direction, level in (("SHORT", prev_high), ("LONG", prev_low)):
        row = _side(window, direction, level)
        if row:
            out.append(row)
    return out


def closed_frame(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return bars
    close_at = _as_utc(bars.index[-1]) + pd.Timedelta(minutes=1)
    if utcnow() + pd.Timedelta(seconds=1) < close_at:
        return bars.iloc[:-1]
    return bars


def fresh_signals(bars: pd.DataFrame, htf: int) -> list[dict]:
    if bars.empty:
        return []
    last = bars.index[-1]
    cur_start = bucket_start(last, htf)
    prev_start = cur_start - pd.Timedelta(minutes=htf)
    prev = _window(bars, prev_start, htf)
    cur = bars[bars.index >= cur_start]
    if not _covered(prev, prev_start, htf) or cur.empty:
        return []
    signals = []
    for row in analyze_window(cur, float(prev["high"].max()), float(prev["low"].min())):
        if _ts(row["rej"]) != _ts(last):
            continue
        row["htf"] = htf
        row["bucket"] = cur_start.isoformat()
        signals.append(row)
    return signals


def closed_sweeps(bars: pd.DataFrame, htf: int) -> list[dict]:
    if bars.empty:
        return []
    last_bucket = bucket_start(bars.index[-1], htf)
    found = []
    start = last_bucket - pd.Timedelta(minutes=htf * 3)
    t = bucket_start(max(bars.index[0], start), htf)
    while t + pd.Timedelta(minutes=htf) <= last_bucket:
        prev_t = t - pd.Timedelta(minutes=htf)
        prev = _window(bars, prev_t, htf)
        cur = _window(bars, t, htf)
        if _covered(prev, prev_t, htf) and _covered(cur, t, htf):
            close = float(cur.iloc[-1]["close"])
            prev_high = float(prev["high"].max())
            prev_low = float(prev["low"].min())
            for row in analyze_window(cur, prev_high, prev_low):
                inside = close < prev_high if row["direction"] == "SHORT" else close > prev_low
                if inside:
                    row["htf"] = htf
                    row["bucket"] = t.isoformat()
                    found.append(row)
        t = t + pd.Timedelta(minutes=htf)
    return found


def current_extreme(bars: pd.DataFrame, htf: int, bucket_iso: str, direction: str, level: float) -> Optional[float]:
    if bars.empty:
        return None
    start = _ts(bucket_iso)
    cur = bars[bars.index >= start]
    end = start + pd.Timedelta(minutes=htf)
    cur = cur[cur.index < end]
    if cur.empty:
        return None
    if direction == "SHORT":
        return (float(cur["high"].max()) - level) / level * 100.0
    return (level - float(cur["low"].min())) / level * 100.0


def locked_margin() -> float:
    m = 0.0
    for p in STATE["pending"]:
        m += float(p["margin"])
    for p in STATE["positions"]:
        if p["status"] == "open":
            m += float(p["margin"])
    return m


def plan_size(key: str, price: float) -> Optional[dict]:
    equity = float(STATE["balance"])
    free = equity - locked_margin()
    if price <= 0 or equity <= 0 or free <= 0:
        return None
    full_notional = equity * (RISK_PCT / STOP_COST_PCT)
    full_margin = full_notional / LEVERAGE
    reduced = False
    if free + 1e-9 < full_margin:
        notional = free * LEVERAGE
        reduced = True
    else:
        notional = full_notional
    step = SYMBOLS[key]["step"]
    qty = floor_step(notional / price, step)
    if qty < step - 1e-12:
        return {"ok": False, "reason": "min", "need": step * price, "full": full_notional}
    actual = qty * price
    if actual < MIN_NOTIONAL:
        return {"ok": False, "reason": "min", "need": MIN_NOTIONAL, "full": full_notional}
    margin = actual / LEVERAGE
    if margin > free + 1e-6:
        return {"ok": False, "reason": "margin", "need": margin, "full": full_notional}
    return {
        "ok": True,
        "qty": qty,
        "notional": actual,
        "margin": margin,
        "reduced": reduced,
        "full": full_notional,
    }


def levels(direction: str, entry: float, key: str) -> tuple[float, float]:
    if direction == "LONG":
        tp = entry * (1 + TARGET_PCT / 100.0)
        sl = entry * (1 - STOP_PCT / 100.0)
    else:
        tp = entry * (1 - TARGET_PCT / 100.0)
        sl = entry * (1 + STOP_PCT / 100.0)
    return round_tick(tp, key), round_tick(sl, key)


def trade_pnl(direction: str, entry: float, exit_px: float, notional: float, reason: str) -> tuple[float, float, float]:
    sign = 1.0 if direction == "LONG" else -1.0
    gross = (exit_px - entry) / entry * notional * sign
    fee_out = MAKER if reason == "tp" else TAKER
    fees = notional * MAKER + notional * fee_out
    return gross, fees, gross - fees


def pair_busy(sym: str) -> bool:
    if any(p["sym"] == sym for p in STATE["pending"]):
        return True
    return any(p["sym"] == sym and p["status"] == "open" for p in STATE["positions"])


def _exchange_client() -> ccxt.bybit:
    global _exchange
    if _exchange is None:
        _exchange = ccxt.bybit({
            "apiKey": os.environ.get("BYBIT_API_KEY", "").strip(),
            "secret": os.environ.get("BYBIT_API_SECRET", "").strip(),
            "timeout": 30000,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
                "defaultSubType": "linear",
                "recvWindow": 10000,
                "adjustForTimeDifference": True,
            },
        })
    return _exchange


async def call_exchange(fn, what: str, attempts: int = 3):
    last = None
    for i in range(attempts):
        try:
            return await asyncio.get_event_loop().run_in_executor(None, fn)
        except Exception as e:
            last = e
            logger.warning(f"{what} попытка {i + 1}/{attempts}: {e}")
            if i < attempts - 1:
                await asyncio.sleep(2 ** (i + 1))
    logger.error(f"{what} не вышло: {last}")
    return None


def _ohlcv_frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close", "volume"]]


async def fetch_bars(key: str, limit: int, since_ms: Optional[int] = None) -> Optional[pd.DataFrame]:
    sym = SYMBOLS[key]["symbol"]
    client = _exchange_client()

    def _do():
        return client.fetch_ohlcv(sym, "1m", since=since_ms, limit=limit)

    rows = await call_exchange(_do, f"свечи {key}")
    if not rows:
        return None
    return _ohlcv_frame(rows)


def _merge_bars(key: str, fresh: pd.DataFrame) -> None:
    if key in BARS and not BARS[key].empty:
        merged = pd.concat([BARS[key], fresh])
    else:
        merged = fresh
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    BARS[key] = merged.iloc[-2500:]


async def refresh_symbol(key: str, full: bool) -> bool:
    if full or key not in BARS:
        fresh = await fetch_bars(key, 1000)
        if fresh is None or fresh.empty:
            return False
        _merge_bars(key, fresh)
        since_ms = int(fresh.index[0].timestamp() * 1000) - 1000 * 60_000
        older = await fetch_bars(key, 1000, since_ms)
        if older is not None and not older.empty:
            _merge_bars(key, older)
        return True
    fresh = await fetch_bars(key, 5)
    if fresh is None or fresh.empty:
        return False
    _merge_bars(key, fresh)
    return True


async def refresh_price(key: str) -> Optional[float]:
    sym = SYMBOLS[key]["symbol"]
    client = _exchange_client()

    def _do():
        return client.fetch_ticker(sym)

    ticker = await call_exchange(_do, f"цена {key}", attempts=2)
    if not ticker or ticker.get("last") is None:
        return None
    px = float(ticker["last"])
    PRICES[key] = (px, time.time())
    return px


def last_price(key: str, max_age: float = 30.0) -> Optional[float]:
    row = PRICES.get(key)
    if not row:
        return None
    px, ts = row
    if time.time() - ts > max_age:
        return None
    return px


async def send_telegram(text: str) -> None:
    preview = text.replace("\n", " ")[:160]
    if _notify is None:
        logger.info(f"[TG offline] {preview}")
        return
    try:
        await _notify(text)
    except Exception as e:
        logger.error(f"Telegram sweep: {e}")


def _pnl_lines(gross: float, fees: float, net: float, margin: float) -> str:
    g_pct = gross / margin * 100 if margin > 0 else 0.0
    n_pct = net / margin * 100 if margin > 0 else 0.0
    return (
        f"PnL:   {gross:+.2f} USDT  ({g_pct:+.1f}%)\n"
        f"Fees:  −{fees:.2f} USDT\n"
        f"Net:   {net:+.2f} USDT  ({n_pct:+.1f}%)"
    )


def _alloc_id() -> int:
    n = int(STATE["next_id"])
    STATE["next_id"] = n + 1
    return n


def _scanner_line() -> str:
    if not _tasks_on():
        return "🛑 остановлен"
    if _scanner_on():
        return "▶ работает"
    return "⏸ пауза"


def _status_text() -> str:
    today = day_num(utcnow())
    lines = [
        f"{mode_tag()} {_scanner_line()}",
        f"Баланс: {STATE['balance']:.2f} USDT",
        f"Занято маржи: {locked_margin():.2f} USDT",
        f"Риск на стоп: {RISK_PCT:.2f}%   плечо {LEVERAGE}×",
    ]
    for htf in HTFS:
        q, how = threshold(htf, today)
        lines.append(f"Порог {HTF_NAME[htf]}: {q:.3f}% ({how})")
    if not STATE["pending"] and not any(p["status"] == "open" for p in STATE["positions"]):
        lines.append("Сделок нет")
    for p in STATE["pending"]:
        lines.append(
            f"⏳ #{p['id']} {p['sym']} {HTF_NAME[p['htf']]} {p['direction']} "
            f"лимит {fmt_px(p['entry'], p['sym'])}"
        )
    for p in STATE["positions"]:
        if p["status"] != "open":
            continue
        lines.append(
            f"📌 #{p['id']} {p['sym']} {HTF_NAME[p['htf']]} {p['direction']} "
            f"вход {fmt_px(p['entry'], p['sym'])}"
        )
    lines.append("Команды: /sweep  /sweep stats  /sweep close")
    return "\n".join(lines)


def _stats_text() -> str:
    trades = list(STATE["trades"])
    bal = STATE["balance"]
    if not trades:
        return f"{mode_tag()} сделок ещё не было\nБаланс: {bal:.2f} USDT"
    nets = [float(t["net"]) for t in trades]
    wins = sum(1 for n in nets if n > 0)
    return (
        f"{mode_tag()} сделок {len(trades)}\n"
        f"В плюсе: {wins} ({wins / len(trades) * 100:.0f}%)\n"
        f"Net: {sum(nets):+.2f} USDT\n"
        f"Баланс: {bal:.2f} USDT"
    )


async def status_block() -> str:
    async with LOCK:
        return _status_text()


async def stats_block() -> str:
    async with LOCK:
        return _stats_text()


async def _too_small(key: str, need: float) -> None:
    now = time.time()
    last = float(STATE["small_note"].get(key) or 0)
    if now - last < 6 * 3600:
        return
    STATE["small_note"][key] = now
    await send_telegram(
        f"{mode_tag()} {SYMBOLS[key]['label']}: лот меньше минимума биржи\n"
        f"На риск {RISK_PCT:.2f}% нужно около {STATE['balance'] * RISK_PCT / STOP_COST_PCT:.1f} USDT, "
        f"минимальный лот около {need:.1f} USDT. Сигнал пропущен."
    )


async def place_limit(sym: str, sig: dict) -> None:
    if pair_busy(sym):
        return
    today = day_num(sig["rej"])
    short, q, how = is_short(sig["depth"], sig["htf"], today)
    sig_key = f"{sym}|{sig['htf']}|{sig['bucket']}|{sig['direction']}|{sig['wick']}"
    if remember(sig_key):
        return
    if not short:
        logger.info(
            f"{sym} {HTF_NAME[sig['htf']]} {sig['direction']} фитиль {sig['depth']:.3f}% "
            f"> порога {q:.3f}% — мимо"
        )
        return
    entry = round_tick(sig["entry"], sym)
    if entry <= 0:
        return
    size = plan_size(sym, entry)
    if size is None or not size["ok"]:
        need = float((size or {}).get("need") or MIN_NOTIONAL)
        await _too_small(sym, need)
        save_state(STATE)
        return
    tp, sl = levels(sig["direction"], entry, sym)
    born = _ts(sig["rej"]) + pd.Timedelta(minutes=1)
    deadline = born + pd.Timedelta(minutes=LIMIT_MIN)
    row = {
        "id": _alloc_id(),
        "sym": sym,
        "htf": sig["htf"],
        "direction": sig["direction"],
        "entry": entry,
        "stop": sl,
        "tp": tp,
        "qty": size["qty"],
        "notional": size["notional"],
        "margin": size["margin"],
        "reduced": bool(size["reduced"]),
        "depth": sig["depth"],
        "threshold": q,
        "threshold_how": how,
        "level": sig["level"],
        "extreme": sig["extreme"],
        "bucket": sig["bucket"],
        "rej": sig["rej"],
        "deadline": deadline.isoformat(),
        "wick": sig["wick"],
    }
    STATE["pending"].append(row)
    save_state(STATE)
    extra = ""
    if row["reduced"]:
        extra = (
            f"\nРазмер урезан: полный был {size['full']:.1f} USDT, "
            f"свободной маржи хватило на {size['notional']:.1f}"
        )
    await send_telegram(
        f"{mode_tag()} 📌 ЛИМИТКА #{row['id']} {row['direction']}\n"
        f"Инструмент: {SYMBOLS[sym]['label']}\n"
        f"ТФ: {HTF_NAME[sig['htf']]}\n"
        f"Вход: {fmt_px(entry, sym)}\n"
        f"Стоп: {fmt_px(sl, sym)}  |  Тейк: {fmt_px(tp, sym)}\n"
        f"Фитиль: {sig['depth']:.3f}%  |  порог: {q:.3f}% ({how})\n"
        f"Объём: {size['notional']:.2f} USDT  |  маржа: {size['margin']:.2f}\n"
        f"Снять, если не возьмёт за {LIMIT_MIN} мин"
        f"{extra}"
    )


async def cancel_pending(row: dict, reason: str) -> None:
    STATE["pending"] = [p for p in STATE["pending"] if p["id"] != row["id"]]
    save_state(STATE)
    await send_telegram(
        f"{mode_tag()} 🗑 ЛИМИТКА #{row['id']} снята\n"
        f"{SYMBOLS[row['sym']]['label']}  {HTF_NAME[row['htf']]}  {row['direction']}\n"
        f"Entry: {fmt_px(row['entry'], row['sym'])}\n"
        f"Причина: {reason}"
    )


async def fill_pending(row: dict, px: float) -> None:
    STATE["pending"] = [p for p in STATE["pending"] if p["id"] != row["id"]]
    pos = {
        "id": row["id"],
        "sym": row["sym"],
        "htf": row["htf"],
        "direction": row["direction"],
        "entry": row["entry"],
        "stop": row["stop"],
        "tp": row["tp"],
        "qty": row["qty"],
        "notional": row["notional"],
        "margin": row["margin"],
        "status": "open",
        "opened": utcnow().isoformat(),
        "deadline": (utcnow() + pd.Timedelta(minutes=POSITION_MIN)).isoformat(),
        "checked_until": utcnow().isoformat(),
    }
    STATE["positions"].append(pos)
    save_state(STATE)
    await send_telegram(
        f"{mode_tag()} ✅ #{pos['id']} вход {pos['direction']}\n"
        f"Инструмент: {SYMBOLS[pos['sym']]['label']}\n"
        f"ТФ: {HTF_NAME[pos['htf']]}\n"
        f"Цена: {fmt_px(pos['entry'], pos['sym'])}  (касание {fmt_px(px, pos['sym'])})\n"
        f"Стоп: {fmt_px(pos['stop'], pos['sym'])}  |  Тейк: {fmt_px(pos['tp'], pos['sym'])}\n"
        f"Объём: {pos['notional']:.2f} USDT\n"
        f"Выход по времени через {POSITION_MIN // 60} ч"
    )


async def _close_position(pos: dict, px: float, reason: str) -> None:
    if pos["status"] != "open":
        return
    gross, fees, net = trade_pnl(pos["direction"], pos["entry"], px, pos["notional"], reason)
    pos["status"] = reason
    pos["exit"] = px
    pos["closed"] = utcnow().isoformat()
    pos["gross"] = gross
    pos["fees"] = fees
    pos["net"] = net
    STATE["balance"] = float(STATE["balance"]) + net
    STATE["trades"].append({
        "id": pos["id"],
        "sym": pos["sym"],
        "htf": pos["htf"],
        "direction": pos["direction"],
        "net": net,
        "reason": reason,
        "closed": pos["closed"],
    })
    labels = {
        "tp": ("🟢", "ТЕЙК ПРОФИТ"),
        "sl": ("🔴", "СТОП ЛОСС"),
        "time": ("⏰", "ТАЙМАУТ — закрыт по рынку"),
        "manual": ("🔒", "ЗАКРЫТ ВРУЧНУЮ"),
    }
    ico, title = labels.get(reason, ("•", reason))
    arrow = "📈" if pos["direction"] == "LONG" else "📉"
    await send_telegram(
        f"{mode_tag()} {ico} #{pos['id']} {title} {arrow} {pos['direction']}\n"
        f"Инструмент: {SYMBOLS[pos['sym']]['label']}\n"
        f"ТФ: {HTF_NAME[pos['htf']]}\n"
        f"Вход: {fmt_px(pos['entry'], pos['sym'])}  |  Выход: {fmt_px(px, pos['sym'])}\n"
        f"{_pnl_lines(gross, fees, net, pos['margin'])}\n"
        f"💼 Баланс: {STATE['balance']:.2f} USDT"
    )


def _bar_hit(direction: str, bar, stop: float, tp: float) -> Optional[str]:
    if direction == "LONG":
        sl = float(bar["low"]) <= stop
        tp_hit = float(bar["high"]) >= tp
    else:
        sl = float(bar["high"]) >= stop
        tp_hit = float(bar["low"]) <= tp
    if sl:
        return "sl"
    if tp_hit:
        return "tp"
    return None


def _price_hit(direction: str, px: float, stop: float, tp: float) -> Optional[str]:
    if direction == "LONG":
        sl = px <= stop
        tp_hit = px >= tp
    else:
        sl = px >= stop
        tp_hit = px <= tp
    if sl and tp_hit:
        return "sl"
    if sl:
        return "sl"
    if tp_hit:
        return "tp"
    return None


def _limit_touched(direction: str, entry: float, px_high: float, px_low: float) -> bool:
    if direction == "SHORT":
        return px_high >= entry
    return px_low <= entry


def _as_utc(ts) -> datetime:
    d = _ts(ts).to_pydatetime()
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


async def watch_pending() -> None:
    now = utcnow()
    for row in list(STATE["pending"]):
        sym = row["sym"]
        bars = BARS.get(sym)
        deadline = _as_utc(row["deadline"])
        after_signal = _as_utc(_ts(row["rej"]) + pd.Timedelta(minutes=1))
        if bars is not None and not bars.empty:
            depth_now = current_extreme(bars, row["htf"], row["bucket"], row["direction"], row["level"])
            if depth_now is not None and depth_now > float(row["depth"]) + 1e-6:
                today = day_num(now)
                short, q, _how = is_short(depth_now, row["htf"], today)
                if not short:
                    await cancel_pending(row, f"фитиль ушёл до {depth_now:.3f}% при пороге {q:.3f}%")
                else:
                    await cancel_pending(
                        row,
                        f"кончик обновился до {depth_now:.3f}%, ждём новое закрытие обратно",
                    )
                continue
            rej = _ts(row["rej"])
            later = bars[bars.index > rej]
            hit_bar = None
            for ts, bar in later.iterrows():
                if _as_utc(ts) >= deadline:
                    break
                hi, lo = float(bar["high"]), float(bar["low"])
                if _limit_touched(row["direction"], row["entry"], hi, lo):
                    hit_bar = bar
                    break
            if hit_bar is not None:
                await fill_pending(row, float(hit_bar["high"] if row["direction"] == "SHORT" else hit_bar["low"]))
                if row["id"] and any(p["id"] == row["id"] and p["status"] == "open" for p in STATE["positions"]):
                    pos = next(p for p in STATE["positions"] if p["id"] == row["id"] and p["status"] == "open")
                    if _bar_hit(pos["direction"], hit_bar, pos["stop"], pos["tp"]) == "sl":
                        await _close_position(pos, pos["stop"], "sl")
                continue
        if now <= deadline:
            px = last_price(sym)
            if px is not None and now >= after_signal and _limit_touched(row["direction"], row["entry"], px, px):
                await fill_pending(row, px)
                continue
        elif now > deadline:
            await cancel_pending(row, f"{LIMIT_MIN} минут без исполнения")


async def watch_positions() -> None:
    for pos in list(STATE["positions"]):
        if pos["status"] != "open":
            continue
        sym = pos["sym"]
        bars = BARS.get(sym)
        opened = _ts(pos["opened"])
        checked = _ts(pos.get("checked_until") or pos["opened"])
        if bars is not None and not bars.empty:
            later = bars[bars.index > checked]
            for ts, bar in later.iterrows():
                if _ts(ts) + pd.Timedelta(minutes=1) <= opened:
                    continue
                reason = _bar_hit(pos["direction"], bar, pos["stop"], pos["tp"])
                pos["checked_until"] = _ts(ts).isoformat()
                if reason:
                    px = pos["stop"] if reason == "sl" else pos["tp"]
                    await _close_position(pos, px, reason)
                    break
            if pos["status"] != "open":
                continue
        px = last_price(sym)
        if px is not None:
            reason = _price_hit(pos["direction"], px, pos["stop"], pos["tp"])
            if reason:
                exit_px = pos["stop"] if reason == "sl" else pos["tp"]
                await _close_position(pos, exit_px, reason)
                continue
        end = _ts(pos["deadline"]).to_pydatetime()
        if utcnow() >= end:
            exit_px = px if px is not None else last_price(sym, max_age=600)
            if exit_px is None:
                continue
            await _close_position(pos, exit_px, "time")


def harvest(sym: str) -> None:
    bars = BARS.get(sym)
    if bars is None or bars.empty:
        return
    born = _ts(STATE["born"])
    for htf in HTFS:
        for row in closed_sweeps(bars, htf):
            closed_at = _ts(row["bucket"]) + pd.Timedelta(minutes=htf)
            if closed_at < born:
                continue
            record_sweep(sym, htf, row["bucket"], row["direction"], row["depth"], row["rej"])


async def scan_once() -> None:
    for sym in PAIRS:
        harvest(sym)
    if not _scanner_on():
        return
    found: list[tuple[str, dict]] = []
    for sym in PAIRS:
        bars = closed_frame(BARS.get(sym, pd.DataFrame()))
        if bars.empty:
            continue
        last = bars.index[-1]
        age_s = (utcnow() - _as_utc(last)).total_seconds()
        if age_s > 180:
            continue
        for htf in HTFS:
            for sig in fresh_signals(bars, htf):
                found.append((sym, sig))
    found.sort(key=lambda item: (item[1]["rej"], item[1]["htf"]))
    for sym, sig in found:
        await place_limit(sym, sig)


async def close_all() -> list[str]:
    """Снять лимитки и закрыть открытые теневые сделки по последней цене."""
    notes = []
    async with LOCK:
        for p in list(STATE["pending"]):
            notes.append(f"снята лимитка #{p['id']} {p['sym']}")
        STATE["pending"] = []
        for pos in STATE["positions"]:
            if pos["status"] != "open":
                continue
            px = last_price(pos["sym"], max_age=120) or pos["entry"]
            await _close_position(pos, px, "manual")
            notes.append(f"закрыта #{pos['id']} {pos['sym']} @ {fmt_px(px, pos['sym'])}")
        save_state(STATE)
    return notes


async def run() -> None:
    logger.info("SWEEP: гружу минутные свечи")
    for sym in PAIRS:
        ok = await refresh_symbol(sym, full=True)
        logger.info(f"SWEEP {sym}: {'ок' if ok else 'нет свечей'}")
    last_bar_fetch = time.time()
    last_stale_alert = 0.0
    announced = False
    while True:
        try:
            if not _tasks_on():
                await asyncio.sleep(5)
                continue
            now = time.time()
            if now - last_bar_fetch >= 20:
                for sym in PAIRS:
                    await refresh_symbol(sym, full=sym not in BARS)
                last_bar_fetch = time.time()
            for sym in PAIRS:
                await refresh_price(sym)
            ages = [time.time() - ts for _px, ts in PRICES.values()] or [999.0]
            if min(ages) > 30 and time.time() - last_stale_alert > 300:
                await send_telegram(f"⚠️ SWEEP: цены устарели {min(ages):.0f}с — нет связи с Bybit")
                last_stale_alert = time.time()
            async with LOCK:
                await watch_pending()
                await watch_positions()
                await scan_once()
                save_state(STATE)
            if not announced:
                announced = True
                await send_telegram(await status_block())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"sweep цикл: {e}")
            await send_telegram(f"⚠️ SWEEP: сбой цикла, повтор через 5с: {e}")
        await asyncio.sleep(5)


def run_self_test() -> None:
    global STATE
    saved = STATE
    STATE = _empty_state()
    STATE["balance"] = 100.0
    STATE["sweeps"] = []

    idx = pd.date_range("2026-06-01 00:00", periods=8, freq="1min", tz="UTC")
    rows = [
        (100, 100.0, 99.5, 99.8),
        (99.8, 100.0, 99.4, 99.7),
        (99.7, 99.9, 99.4, 99.6),
        (99.6, 99.9, 99.5, 99.7),
        (99.7, 100.10, 99.6, 99.90),
        (99.9, 99.95, 99.7, 99.8),
        (99.8, 99.9, 99.6, 99.7),
        (99.7, 99.85, 99.5, 99.6),
    ]
    bars = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    sigs = fresh_signals(bars.iloc[:5], 4)
    assert len(sigs) == 1 and sigs[0]["direction"] == "SHORT", sigs
    assert abs(sigs[0]["depth"] - 0.10) < 1e-6, sigs[0]["depth"]

    q, how = threshold(240, day_num("2026-06-02"))
    assert abs(q - SEED_Q[240]) < 1e-9 and "старт" in how
    today = 20_000
    STATE["sweeps"] = [
        {"htf": 240, "day": today - 1, "depth": float(i), "key": str(i)}
        for i in range(MIN_PAST)
    ]
    q2, how2 = threshold(240, today)
    expect = float(np.quantile(np.arange(MIN_PAST, dtype=float), 0.25))
    assert abs(q2 - expect) < 1e-9, (q2, expect, how2)
    STATE["sweeps"].append({"htf": 240, "day": today, "depth": 0.0, "key": "today"})
    q3, _ = threshold(240, today)
    assert abs(q3 - q2) < 1e-9

    assert plan_size("BTC", 60_000)["ok"] is False
    eth = plan_size("ETH", 3_000)
    assert eth and eth["ok"] and eth["qty"] >= 0.01, eth
    STATE["positions"] = [{
        "status": "open", "margin": 97.0, "sym": "ETH",
    }]
    small = plan_size("SOL", 150.0)
    assert small and small["ok"] and small["reduced"], small

    hit = _bar_hit("LONG", {"low": 99.0, "high": 101.0}, stop=99.5, tp=100.5)
    assert hit == "sl"
    assert _bar_hit("LONG", {"low": 99.8, "high": 101.0}, stop=99.5, tp=100.5) == "tp"
    assert _price_hit("SHORT", 101.0, stop=100.2, tp=99.5) == "sl"
    g, f, n = trade_pnl("LONG", 100.0, 100.5, 40.0, "tp")
    assert n > 0 and f > 0
    STATE = saved
    print("selftest ok")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        run_self_test()
