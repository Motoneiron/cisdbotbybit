"""Статистика SHADOW-сделок: направления, TP/SL/TIME, инструменты."""
import json
from collections import Counter, defaultdict

d = json.load(open("/opt/cisdbotbybit/shadow_positions.json"))
positions = d["positions"] if isinstance(d, dict) else d

op = [p for p in positions if p.get("status") == "open"]
cl = [p for p in positions if str(p.get("status", "")).startswith("closed")]
print(f"всего записей: {len(positions)} | открытых: {len(op)} | закрытых: {len(cl)}")
print("статусы:", dict(Counter(p["status"] for p in cl)))

def brk(items, title):
    print(f"\n=== {title} ({len(items)} сд) ===")
    for dr in ("LONG", "SHORT"):
        cc = [p for p in items if p["direction"] == dr]
        st = Counter("TP" if "tp" in p["status"] else "SL" if "sl" in p["status"] else "TIME" if "time" in p["status"] else p["status"] for p in cc)
        pnl = sum(float(p.get("pnl_net") or 0) for p in cc)
        print(f"  {dr}: {len(cc)} сд | {dict(st)} | pnl_net={pnl:+.2f}")

brk(cl, "ВСЕ закрытые")
cl2 = [p for p in cl if str(p.get("entry_time") or "") >= "2026-09-12"]
brk(cl2, "ЧЕСТНЫЕ (с 12.09)")

print(f"\n=== ПО ИНСТРУМЕНТАМ (все закрытые) ===")
agg = defaultdict(lambda: {"n": 0, "L": 0, "S": 0, "TP": 0, "SL": 0, "TIME": 0, "pnl": 0.0})
for p in cl:
    a = agg[f"{p.get('symbol_key')} {p.get('tf')}"]
    a["n"] += 1
    a[p["direction"][0]] += 1
    s = p["status"]
    if "tp" in s: a["TP"] += 1
    elif "sl" in s: a["SL"] += 1
    elif "time" in s: a["TIME"] += 1
    a["pnl"] += float(p.get("pnl_net") or 0)
print(f"{'инстр':12} | n | L | S | TP | SL | TIME | pnl_net")
for k, a in sorted(agg.items(), key=lambda x: -x[1]["n"]):
    print(f"{k:12} | {a['n']} | {a['L']} | {a['S']} | {a['TP']} | {a['SL']} | {a['TIME']} | {a['pnl']:+.2f}")

byday = defaultdict(float)
for p in cl:
    byday[str(p.get("entry_time"))[:10]] += float(p.get("pnl_net") or 0)
print("\nпо дням входа:", {k: round(v, 2) for k, v in sorted(byday.items())})

print("\n=== ОТКРЫТЫЕ ===")
for p in op:
    print(f"  {p.get('symbol_key')} {p.get('tf')} {p['direction']} entry={p['entry_price']} "
          f"@{str(p.get('entry_time'))[:16]} | план.выход={str(p.get('exit_time'))[:16]}")

tot = sum(float(p.get("pnl_net") or 0) for p in cl)
print(f"\nИТОГО pnl_net закрытых: {tot:+.2f}")
# журнал
import os
tl = "/opt/cisdbotbybit/trade_logs"
cancels = Counter()
for f in sorted(os.listdir(tl)):
    path = os.path.join(tl, f)
    lines = open(path, encoding="utf-8").readlines()
    print(f"\n{tl}/{f}: строк {len(lines)}")
    if lines:
        print("  последняя:", lines[-1][:220])
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") == "pending_cancelled":
            cancels[str(rec.get("cancel_reason") or rec.get("status") or "?")] += 1
if cancels:
    print("\n=== ОТМЕНЫ ЛИМИТОК (журнал) ===")
    for k, n in cancels.most_common():
        print(f"  {k}: {n}")
