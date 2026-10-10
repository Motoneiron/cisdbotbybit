"""Разбор 14 живых сделок 16-18.09: класс «30m закрылся за уровнем» против «только фитиль».

Для каждой сделки берём 30m-данные Bybit вокруг входа и смотрим:
  entry_bar_close  — close той 30m-свечи, ВНУТРИ которой произошёл вход (для SHORT: за уровнем = close < entry);
  next_bar_close   — close следующей 30m-свечи.
Класс wick_only = свеча входа НЕ закрылась за уровнем.
"""
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
    ("LINK", "SHORT", "2026-09-17 18:27:00", +0.7050), ("LTC", "SHORT", "2026-09-17 19:25:00", -1.1580),
]
LEVELS = {"ADA": None, "KAS": None, "BTC": None, "SOL": None, "DOGE": None, "ETH": None,
          "LTC": None, "BNB": None, "LINK": None, "XRP": None}
# уровни CISD = цена входа сделки (лимитка стояла на уровне)
ENTRY = {"2026-09-16 02:43:53": 0.1946, "2026-09-16 07:09:13": 0.03253, "2026-09-16 11:37:49": 75999.9,
         "2026-09-16 13:14:59": 97.24, "2026-09-16 18:30:11": 0.07924, "2026-09-16 18:38:32": 75681.0,
         "2026-09-16 19:32:13x": 0, "2026-09-16 20:01:04": 0.1942, "2026-09-17 02:37:30": 724.0,
         "2026-09-17 04:38:47": 11.084, "2026-09-17 14:32:41": 1.3121, "2026-09-17 18:27:00": 11.368,
         "2026-09-17 19:25:00": 53.56}
ENTRY2 = {"2026-09-16 19:32:13": {"LTC": 50.58, "ETH": 2387.67}}
rows = []
for sym, d, ts, net in TRADES:
    t = pd.Timestamp(ts)
    lvl = ENTRY.get(ts) or (ENTRY2.get(ts, {}) or {}).get(sym, 0)
    if ts == "2026-09-16 19:32:13":
        lvl = ENTRY2[ts][sym]
    o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "30m", since=int((t - pd.Timedelta(hours=20)).timestamp() * 1000), limit=60)
    df = pd.DataFrame(o, columns=["ts", "o", "h", "l", "c", "v"])
    df["dt"] = pd.to_datetime(df.ts, unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt")
    pos = df.index.searchsorted(t, side="right") - 1
    ec = float(df["c"].iloc[pos]); nc = float(df["c"].iloc[min(pos + 1, len(df) - 1)])
    beyond = (ec < lvl) if d == "SHORT" else (ec > lvl)
    cls = "close_beyond" if beyond else "wick_only"
    rows.append({"ts": ts, "sym": sym, "dir": d, "lvl": lvl, "entry_bar_close": ec, "next": nc,
                 "cls": cls, "net": net})
    print(f"{ts} {sym:5s} {d:5s} lvl={lvl:<10g} close={ec:<10g} next={nc:<10g} {cls:13s} net={net:+.3f}")
r = pd.DataFrame(rows)
print()
for c in ("close_beyond", "wick_only"):
    d = r[r.cls == c]
    if len(d):
        print(f"  {c:13s}: n={len(d):2d}  net={d.net.sum():+.3f}  убыточных={int((d.net<0).sum())}")
