"""Аудит закрытых SHADOW-сделок v2.

Классификация:
  INSTANT — факт закрытия позже входа менее чем на 2 мин (подозрение на закрытие
            по УЖЕ ЗАКРЫТОМУ бару: state.ohlcv_closed хранит последний закрытый бар ТФ,
            который в момент входа мог содержать экстремум ДО входа);
  NORMAL  — проверяем касание стопа/тейка по 1m в окне [entry, факт_закрытия).
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
    d = d.replace(tzinfo=TZ) if d.tzinfo is None else d
    return int(d.timestamp() * 1000)


def klines(sym, t0, t1):
    out, since = [], t0
    for _ in range(8):
        batch = ex.fetch_ohlcv(sym, "1m", since=since, limit=1000)
        if not batch:
            break
        out += [k for k in batch if k[0] < t1]
        if len(batch) < 1000:
            break
        since = batch[-1][0] + 60000
    return out


def touched(direction, o, st, tp):
    if not o:
        return None, None
    low = min(k[3] for k in o)
    high = max(k[2] for k in o)
    if direction == "LONG":
        return low <= st, high >= tp
    return high >= st, low <= tp


rows = []
for p in closed:
    sk = p.get("symbol_key") or "SOL"
    sym = f"{sk}/USDT:USDT"
    t0 = ms(p["entry_time"])
    ex_t = facts.get(p["id"]) or p.get("exit_time")
    t1 = ms(ex_t)
    st, tp, d = p["stop_price"], p["tp_price"], p["direction"]
    dt_min = round((t1 - t0) / 60000, 2)
    try:
        o = klines(sym, t0, max(t1, t0 + 180000))   # минимум 3 минуты окна
    except Exception as e:
        rows.append((p["id"], sk, p["tf"], d, p["status"], "FETCH_ERR " + str(e)[:40], dt_min))
        continue
    if not o:
        rows.append((p["id"], sk, p["tf"], d, p["status"], "НЕТ 1m ДАННЫХ", dt_min))
        continue
    t_sl, t_tp = touched(d, o, st, tp)

    if dt_min < 2:
        # окно после входа: 1m бар входа + следующие 2 бара
        win = [k for k in o if k[0] < t0 + 180000]
        w_sl, w_tp = touched(d, win, st, tp)
        verdict = f"INSTANT ({p['status']}) касание в первые 3 мин: sl={w_sl} tp={w_tp}"
    elif p["status"] == "closed_sl":
        verdict = "OK" if t_sl else "!! ЛОЖНЫЙ SL (стоп не тронут)"
    elif p["status"] == "closed_tp":
        verdict = "OK" if t_tp else "!! ЛОЖНЫЙ TP (тейк не тронут)"
    else:
        verdict = "TIME" + (f" (касание: sl={t_sl} tp={t_tp})" if (t_sl or t_tp) else "")

    rows.append((p["id"], sk, p["tf"], d, p["status"], verdict, dt_min, t_sl, t_tp))

print("=" * 30)
for r in rows:
    mark = "  <== " if ("!!" in str(r[5]) or "INSTANT" in str(r[5]) or "НЕТ" in str(r[5])) else ""
    print(" | ".join(str(x) for x in r) + mark)
print("=" * 30)
print("всего закрытых:", len(rows))
print("INSTANT (<2 мин):", sum(1 for r in rows if "INSTANT" in str(r[5])))
print("ложных SL:", sum(1 for r in rows if "ЛОЖНЫЙ SL" in str(r[5])))
print("ложных TP:", sum(1 for r in rows if "ЛОЖНЫЙ TP" in str(r[5])))
