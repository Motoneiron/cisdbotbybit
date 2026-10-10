"""Проверка одной позиции (по id) по тём же гейтам, что и cleanup_stats.py."""
import json
import sys
import glob

import ccxt
import pandas as pd

sys.path.insert(0, "/opt/cisdbotbybit")
import cisdbot as B   # noqa: E402

PID = sys.argv[1]
HTF_RATIO = 480
BASE = "/opt/cisdbotbybit"
ex = ccxt.bybit({"enableRateLimit": True})

trig = {}
for f in sorted(glob.glob(BASE + "/trade_logs/trades_*.jsonl")):
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("id") == PID and r.get("trigger_bar_at"):
            trig[PID] = str(r["trigger_bar_at"])

p = [x for x in json.load(open(BASE + "/shadow_positions.json", encoding="utf-8")) if x["id"] == PID][0]
sym = p.get("symbol_key") or "SOL"
d = p["direction"]
long = d == "LONG"
cisd = float(p.get("cisd_level") or p["entry_price"])
sweep = float(p.get("sweep_level") or 0)
htf = str(p.get("htf_time") or "")
trig_s = trig.get(PID, "")

o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "30m", limit=1000)
df = pd.DataFrame(o, columns=["t", "open", "high", "low", "close", "volume"])
df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_localize(None)
df = df.set_index("ts")[["open", "high", "low", "close", "volume"]]

a_ok = B._is_retrace_at_creation(d, cisd, float(p.get("price_at_creation") or 0))
b_ok, b_why = B._sweep_valid_for_setup(df, HTF_RATIO, htf, trig_s, sweep, d)
created = pd.Timestamp(str(p.get("pending_created_at") or p["entry_time"]))
win0 = max(pd.Timestamp(htf), pd.Timestamp(trig_s)) if trig_s else pd.Timestamp(htf)
win1 = pd.Timestamp(htf) + pd.Timedelta(minutes=HTF_RATIO)
c_ok = c_win = False
c_bars = []
for tsx, row in df.iterrows():
    if tsx < win0 or tsx >= win1:
        continue
    beyond = (float(row["close"]) > cisd) if long else (float(row["close"]) < cisd)
    if not beyond:
        continue
    c_win = True
    c_bars.append((str(tsx), float(row["close"]), str(tsx + pd.Timedelta(minutes=30))))
    if tsx + pd.Timedelta(minutes=30) <= created:
        c_ok = True

print(f"{PID} {sym} {d} cisd={cisd} sweep={sweep} htf={htf} trig={trig_s} created={created}")
print(f"A(неявный MARKET)={a_ok}  B(свип)={b_ok}  {b_why}")
print(f"C до создания={c_ok}  C в окне={c_win}  бары за уровнем: {c_bars}")
print("ВЕРДИКТ:", "УДАЛИТЬ" if (not a_ok or not b_ok or not c_win) else "оставить")
