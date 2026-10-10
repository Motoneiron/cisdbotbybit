"""KAS 5m окно 16:00-20:00 UTC: где low/high по времени."""
import json
import urllib.request
import datetime as dt

url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=KASUSDT&interval=5&limit=500"
with urllib.request.urlopen(url, timeout=30) as r:
    d = json.loads(r.read())
rows = d["result"]["list"][::-1]
bars = []
for x in rows:
    t = dt.datetime.fromtimestamp(int(x[0]) / 1000, dt.UTC).replace(tzinfo=None)
    bars.append((t, float(x[1]), float(x[2]), float(x[3]), float(x[4])))
win = [b for b in bars if dt.datetime(2026, 9, 13, 16, 0) <= b[0] < dt.datetime(2026, 9, 13, 20, 0)]
print(f"баров в окне 16:00-20:00: {len(win)}")
lo = min(win, key=lambda b: b[3])
hi = max(win, key=lambda b: b[2])
print(f"low  = {lo[3]} в {lo[0]} (бар 5m)")
print(f"high = {hi[2]} в {hi[0]}")
print("\nпервые/последние бары окна:")
for b in win[:3] + win[-4:]:
    print(f"  {b[0].strftime('%H:%M')} o={b[1]} h={b[2]} l={b[3]} c={b[4]}")
