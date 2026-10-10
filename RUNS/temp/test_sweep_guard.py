"""Проверка _sweep_valid_for_setup (коммит 42c985e) на реальных данных Bybit.

Кейсы:
  1) LTC 16.09 (окно 08:00 закрыто, свеча закрылась НИЖЕ уровня свипа) -> ожидаем False;
  2) то же окно, когда оно ещё формируется (16:00)                       -> ожидаем True (мягкий режим);
  3) все tf8-лимитки из журнала (файл tf8_pendings.json)                  -> таблица вердиктов.
"""
import json
import sys
import datetime as dt

import ccxt
import pandas as pd

sys.path.insert(0, "D:/PYTHON/cisdbotbybit")
import cisdbot as B   # noqa: E402

ex = ccxt.bybit({"enableRateLimit": True})
CACHE = {}
TF_MIN = 30


def df30(sym):
    if sym in CACHE:
        return CACHE[sym]
    o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "30m", limit=1000)
    d = pd.DataFrame(o, columns=["t", "open", "high", "low", "close", "volume"])
    d["ts"] = pd.to_datetime(d["t"], unit="ms", utc=True).dt.tz_localize(None)
    d = d.set_index("ts")[["open", "high", "low", "close", "volume"]]
    CACHE[sym] = d
    return d


def check(sym, htf, trig, lvl, direction):
    d = df30(sym)
    return B._sweep_valid_for_setup(d, 480, htf, trig, float(lvl), direction)


print("=" * 90)
print("1) LTC (кейс #12, окно 08:00 закрыто):")
d = df30("LTC")
print("   ", B._sweep_valid_for_setup(d, 480, "2026-09-16 08:00:00", "2026-09-16T14:00:00", 50.48, "LONG"))

print("2) то же окно, но ещё формируется (htf=16:00 -> True) и LTC-окно при обрезанном df (до 15:30):")
print("   htf=16:00:", B._sweep_valid_for_setup(d, 480, "2026-09-16 16:00:00", "2026-09-16T16:30:00", 50.35, "LONG"))
d_cut = d[d.index <= pd.Timestamp("2026-09-16 15:30:00")]
print("   df до 15:30, окно 08:00:", B._sweep_valid_for_setup(d_cut, 480, "2026-09-16 08:00:00", "2026-09-16T14:00:00", 50.48, "LONG"))

print()
print("3) все tf8-лимитки из журнала (28 шт), проверка на текущих данных:")
print(f"{'created(UTC)':17s} {'sym':5s} {'dir':5s} {'htf_time':17s} {'trig':17s} ok   reason")
pends = json.load(open("D:/PYTHON/cisdbotbybit/RUNS/temp/tf8_pendings.json"))
n_false = 0
for p in pends:
    sym = p["symbol"]
    ok, why = check(sym, p.get("htf_time") or "", p.get("trigger_bar_at") or "",
                    p.get("htf_sweep_level") or p.get("sweep_level") or 0, p["direction"])
    if not ok:
        n_false += 1
    print(f"{str(p['pending_created_at'])[:16]:17s} {sym:5s} {p['direction']:5s} "
          f"{str(p.get('htf_time'))[:16]:17s} {str(p.get('trigger_bar_at'))[:16]:17s} "
          f"{str(ok):5s} {why}")
print()
print("итого лимиток:", len(pends), "| скипнуто проверкой свипа:", n_false)
