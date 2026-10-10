"""Аудит 9 shadow-сделок: был ли реальный ретест к entry ПОСЛЕ создания лимитки.

Для каждой сделки: качаем 1m данные (Bybit), проверяем окно [created, created+limit_h]:
- SHORT: был ли 1m бар с high >= entry
- LONG:  был ли 1m бар с low <= entry
Если нет — фантомный вход (fill по бару ДО создания).
"""
import json
import time

import ccxt
import pandas as pd

TRADES_FILE = r"D:/PYTHON/cisdbotbybit/RUNS/temp/shadow_trades_audit.json"
CACHE_FILE = r"D:/PYTHON/cisdbotbybit/RUNS/temp/audit_1m_cache.pkl"

PAIR_MAP = {
    "DOGE": "DOGE/USDT:USDT", "ETH": "ETH/USDT:USDT", "BTC": "BTC/USDT:USDT",
    "LTC": "LTC/USDT:USDT", "KAS": "KAS/USDT:USDT", "ADA": "ADA/USDT:USDT",
    "BNB": "BNB/USDT:USDT",
}
LIMIT_H = {"tf7": 20 / 60, "tf8": 30 / 60}  # часов

ex = ccxt.bybit({"defaultType": "swap"})

trades = json.load(open(TRADES_FILE, encoding="utf-8"))

# скачать 1m по каждой паре за период 09.09 - 13.09
start = pd.Timestamp("2026-09-09 00:00:00").tz_localize("UTC")
end = pd.Timestamp("2026-09-13 00:00:00").tz_localize("UTC")
start_ms = int(start.timestamp() * 1000)
end_ms = int(end.timestamp() * 1000)

cache = {}
import os
if os.path.exists(CACHE_FILE):
    cache = pd.read_pickle(CACHE_FILE)

for sym_key in sorted({t["symbol_key"] for t in trades}):
    if sym_key in cache:
        continue
    pair = PAIR_MAP[sym_key]
    all_rows = []
    since = start_ms
    while since < end_ms:
        rows = ex.fetch_ohlcv(pair, "1m", since=since, limit=1000)
        if not rows:
            break
        all_rows.extend(rows)
        last_ts = rows[-1][0]
        if last_ts <= since:
            break
        since = last_ts + 60_000
        time.sleep(0.3)
    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["dt"] = pd.to_datetime(df.ts, unit="ms", utc=True)
    df = df.set_index("dt").drop(columns=["ts"])
    cache[sym_key] = df
    print(f"{sym_key}: {len(df)} баров 1m", flush=True)

pd.to_pickle(cache, CACHE_FILE)

print()
print("=" * 100)
for t in trades:
    sym = t["symbol_key"]
    df = cache[sym]
    created = pd.Timestamp(t["pending_created_at"]).tz_localize("UTC")
    win_end = created + pd.Timedelta(hours=LIMIT_H[t["tf"]])
    seg = df.loc[(df.index >= created) & (df.index <= win_end)]
    seg_pre = df.loc[(df.index >= created - pd.Timedelta(minutes=35)) & (df.index < created)]
    entry = float(t["entry_price"])
    d = t["direction"]
    if d == "SHORT":
        hit = seg[seg.high >= entry]
        hit_pre = seg_pre[seg_pre.high >= entry] if len(seg_pre) else seg_pre
    else:
        hit = seg[seg.low <= entry]
        hit_pre = seg_pre[seg_pre.low <= entry] if len(seg_pre) else seg_pre
    n = len(seg)
    hs = len(hit)
    pre = len(hit_pre) if len(hit_pre) else 0
    if hs > 0:
        verdict = "✅ ЧЕСТНЫЙ (ретест был)"
        first_t = hit.index[0]
    else:
        verdict = "❌ ФАНТОМ (ретеста НЕ было)"
        first_t = "-"
    print(f"{sym:5} {d:5} {t['tf']} entry={entry} | окно {created.strftime('%d.%m %H:%M')}-{win_end.strftime('%H:%M')} UTC | "
          f"баров: {n}, касаний: {hs} | касаний ДО создания (35м): {pre} | {verdict} | {first_t if hs else ''}")
