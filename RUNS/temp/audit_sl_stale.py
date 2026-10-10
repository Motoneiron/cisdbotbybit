"""Аудит закрытых SHADOW-сделок: правда ли цена касалась стопа/тейка ПОСЛЕ входа.

Проверка по 1m OHLCV Bybit в окне [entry_time, факт_закрытия).
Ложный SL: закрыто по стопу, а 1m-данные не дают касания стопа после входа.
"""
import json
import datetime as dt
from pathlib import Path

import ccxt

ex = ccxt.bybit({"enableRateLimit": True})
TZ = dt.timezone.utc

pos = json.load(open("shadow_positions.json"))
closed = [p for p in pos if str(p.get("status", "")).startswith("closed")]

facts = {}
for f in sorted(Path("trade_logs").glob("trades_*.jsonl")):
    for line in f.open():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("event") == "closed" and r.get("id"):
            facts[r["id"]] = r.get("exit_time")


def ms(s):
    d = dt.datetime.fromisoformat(str(s))
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return int(d.timestamp() * 1000)


def klines(sym, t0, t1):
    out = []
    since = t0
    for _ in range(6):
        batch = ex.fetch_ohlcv(sym, "1m", since=since, limit=1000)
        if not batch:
            break
        out += [k for k in batch if k[0] < t1]
        if len(batch) < 1000:
            break
        since = batch[-1][0] + 60000
    return out


rows = []
for p in closed:
    sk = p.get("symbol_key") or "SOL"
    sym = f"{sk}/USDT:USDT"
    t0 = ms(p["entry_time"])
    ex_t = facts.get(p["id"]) or p.get("exit_time")
    t1 = ms(ex_t)
    st, tp, d = p["stop_price"], p["tp_price"], p["direction"]
    try:
        o = klines(sym, t0, t1)
    except Exception as e:
        rows.append((p["id"], sk, p["tf"], d, p["status"], "FETCH_ERR " + str(e)[:40]))
        continue
    if not o:
        rows.append((p["id"], sk, p["tf"], d, p["status"], "нет 1m баров"))
        continue
    low = min(k[3] for k in o)
    high = max(k[2] for k in o)
    if d == "LONG":
        touch_sl, touch_tp = low <= st, high >= tp
    else:
        touch_sl, touch_tp = high >= st, low <= tp

    if p["status"] == "closed_sl":
        verdict = "OK" if touch_sl else "!! ЛОЖНЫЙ SL"
    elif p["status"] == "closed_tp":
        verdict = "OK" if touch_tp else "!! ЛОЖНЫЙ TP"
    else:
        verdict = "TIME" + ("" if not touch_sl and not touch_tp else
                            f" (но было касание: sl={touch_sl} tp={touch_tp})")
    rows.append((
        p["id"], sk, p["tf"], d, p["status"], verdict,
        str(p["entry_time"])[:19], str(ex_t)[:19],
        f"entry={p['entry_price']}", f"low={low}", f"high={high}",
        f"stop={st}", f"tp={tp}",
    ))

print("=" * 40)
bad = 0
for r in rows:
    flag = "  <== " if str(r[5]).startswith("!!") else ""
    print(" | ".join(str(x) for x in r) + flag)
    if str(r[5]).startswith("!!"):
        bad += 1
print("=" * 40)
print(f"всего закрытых: {len(rows)}   подозрительных: {bad}")
