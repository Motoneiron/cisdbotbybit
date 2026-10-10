"""Живые сделки 16-18.09 против тренда EMA3 1H (правило: LONG при slope>+0.02%, SHORT при slope<-0.02%).
1h-данные берём с Bybit (локальные кэши кончаются в мае).
"""
import time
import urllib.request

import ccxt
import pandas as pd

ex = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
TRADES = [
    ("ADA", "LONG", "2026-09-16 02:43:53", -0.9051), ("KAS", "LONG", "2026-09-16 07:09:13", -1.0932),
    ("BTC", "LONG", "2026-09-16 11:37:49", -0.6466), ("SOL", "SHORT", "2026-09-16 13:14:59", +0.8269),
    ("DOGE", "LONG", "2026-09-16 18:30:11", +0.8395), ("BTC", "SHORT", "2026-09-16 18:38:32", -0.8639),
    ("ETH", "SHORT", "2026-09-16 19:32:13", -0.9120), ("LTC", "SHORT", "2026-09-16 19:32:13", -1.0524),
    ("ADA", "LONG", "2026-09-16 20:01:04", +0.3954), ("BNB", "SHORT", "2026-09-17 02:37:30", -0.3749),
    ("LINK", "SHORT", "2026-09-17 04:38:47", -1.1244), ("XRP", "LONG", "2026-09-17 14:32:41", -0.5950),
    ("LINK", "SHORT", "2026-09-17 18:30:00", +0.7050), ("LTC", "SHORT", "2026-09-17 19:30:00", -1.1580),
]
slope = {}
for sym in {t[0] for t in TRADES}:
    try:
        o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "1h", since=int(pd.Timestamp("2026-09-10").timestamp() * 1000), limit=250)
    except Exception as e:
        print(f"{sym}: fetch FAIL {e!r}")
        continue
    df = pd.DataFrame(o, columns=["ts", "o", "h", "l", "c", "v"])
    df["t"] = pd.to_datetime(df.ts, unit="ms", utc=True).dt.tz_localize(None)
    e3 = df["c"].ewm(span=3, adjust=False).mean()
    slope[sym] = pd.Series((e3 / e3.shift(1) - 1).values, index=df["t"])

print("правило: LONG нужен slope > +0.02%, SHORT нужен slope < -0.02%\n")
print(f"{'вход (UTC)':17s} {'пара':5s} {'напр':5s} {'slope 1h':>10s} {'вердикт':>9s} {'net':>8s}")
n_ag = 0
ag_net = 0.0
for sym, d, ts, net in sorted(TRADES, key=lambda z: z[2]):
    s = slope.get(sym)
    if s is None:
        continue
    t = pd.Timestamp(ts)
    k = s.index.searchsorted(t, side="right") - 1
    if k < 2:
        continue
    sl = float(s.iloc[k])
    with_tr = (d == "LONG" and sl > 0.0002) or (d == "SHORT" and sl < -0.0002)
    if not with_tr:
        n_ag += 1
        ag_net += net
    print(f"{ts:17s} {sym:5s} {d:5s} {sl*100:+9.3f}% {'WITH' if with_tr else 'AGAINST':>9s} {net:+8.3f}")
print()
tot = sum(t[3] for t in TRADES)
print(f"всего сделок: {len(TRADES)} | net {tot:+.3f}")
print(f"AGAINST (против тренда): {n_ag} сделок, их net {ag_net:+.3f}")
print(f"WITH: {len(TRADES)-n_ag} сделок, их net {tot-ag_net:+.3f}")
