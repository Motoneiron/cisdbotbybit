"""Тайминг pre_tp (в минутах) + разбор BNB #9 по живому API."""
import json
import urllib.request
from datetime import datetime, timezone

import pandas as pd

tk = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/gate_trades_timed3.pkl")
NEW = ((tk.dir == "LONG") & (tk.vd > 0)) | ((tk.dir == "SHORT") & (tk.vd <= 0))
p = tk[tk.taken & tk.pre_tp & NEW]
dt = (p.t_in - p.pre_tp_at)  # уже в минутах
print("pre-TP new: за сколько минут до входа (describe, мин):")
print(dt.describe().round(1).to_string())
print("доля <=5 мин:", f"{(dt<=5).mean():.0%}", "| <=15 мин:", f"{(dt<=15).mean():.0%}",
      "| >30 мин:", f"{(dt>30).mean():.0%}")

print("\n=== BNB #9 (live, Bybit 1m) ===")
start = int(datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc).timestamp() * 1000)
url = ("https://api.bybit.com/v5/market/kline?category=linear&symbol=BNBUSDT"
       f"&interval=1&start={start}&limit=500")
with urllib.request.urlopen(url, timeout=30) as r:
    js = json.load(r)
bars = list(reversed([[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])]
                      for x in js["result"]["list"]]))  # ts, open, high, low, close
t0 = datetime(2026, 9, 14, 9, 45, tzinfo=timezone.utc).timestamp() * 1000
entry, tp, stop = 724.4, 727.4, 721.4
fill = None
for b in bars:
    if b[0] >= t0 and b[3] <= entry:
        fill = b
        break
print(f"баров с 09:30 UTC: {len(bars)} | первый таймстamp: {datetime.fromtimestamp(bars[0][0]/1000, timezone.utc):%H:%M} UTC")
if fill:
    fi = bars.index(fill)
    pre = bars[:fi]
    hi_pre = max(x[2] for x in pre) if pre else None
    pre_tp = hi_pre is not None and hi_pre >= tp
    print(f"заполнение: {datetime.fromtimestamp(fill[0]/1000, timezone.utc):%H:%M} UTC "
          f"(low={fill[3]}) | до заполнения max(high)={hi_pre}")
    print(f"pre-TP (>= {tp}): {pre_tp}")
    after = bars[fi:]
    hi_after = max(x[2] for x in after)
    print(f"после заполнения max(high)={hi_after} | TP достигнут повторно: {hi_after >= tp} | "
          f"текущая close={after[-1][4]}")
else:
    print("заполнения (low<=724.4) не было; min(low) с 09:45:", min(b[3] for b in bars if b[0] >= t0))
    print("max(high):", max(b[2] for b in bars if b[0] >= t0), "| текущая:", bars[-1][4])
