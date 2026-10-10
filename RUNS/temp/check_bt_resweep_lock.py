"""Сверка с бэктестом: есть ли в tf8-потоке повторные сетапы в одном HTF-окне,
у которых триггер НЕ обновил предыдущий (равный или более мелкий экстремум).

Именно такие сетапы живой лок свипа (htf_sweep_lock → «ждём пересвип») блокирует.
Считаем: сколько сигналов и сделок попали бы под лок и сколько ΣR это стоит.

Источник: filters_off_full (полная история 2020-2026, 10 пар, фильтры off).
"""
import glob
import pickle
from collections import defaultdict

import pandas as pd

PAT = "D:/PYTHON/CISDBOT/RUNS/filters_off_full/*tf8*.pkl"
files = sorted(glob.glob(PAT))
print("кэшей:", len(files))

sigs = []
trades = []
for f in files:
    c = pickle.load(open(f, "rb"))
    sym = c.get("symbol")
    for s in c.get("signals") or []:
        sigs.append({
            "symbol": sym if sym else s.get("symbol_key"),
            "direction": s.get("direction"),
            "htf_time": str(s.get("htf_time")),
            "sweep_level": float(s.get("htf_sweep_level") or s.get("sweep_level") or 0),
            "trig_ext": float(s.get("trigger_extreme") or 0),
            "trig_time": str(s.get("trigger_bar_time") or ""),
            "hash": str(s.get("hash")),
        })
    for t in c.get("trades") or []:
        trades.append({
            "hash": str(t.get("hash")),
            "r_net": float(t.get("r_net") or 0),
            "outcome": t.get("outcome"),
        })

df = pd.DataFrame(sigs)
tr = pd.DataFrame(trades).drop_duplicates("hash")
print("сигналов:", len(df), "| сделок:", len(tr))
if df.empty:
    raise SystemExit

df["trig_ts"] = pd.to_datetime(df["trig_time"], errors="coerce")
df = df.sort_values(["symbol", "direction", "htf_time", "trig_ts"])

blocked = defaultdict(list)
kept = defaultdict(int)
for (sym, d, htf), g in df.groupby(["symbol", "direction", "htf_time"], sort=False):
    long = d == "LONG"
    run = None
    for _, r in g.iterrows():
        ext = float(r["trig_ext"])
        if run is None:
            run = ext
            kept[(sym, d, htf)] += 1
            continue
        deeper = (ext < run - 1e-9) if long else (ext > run + 1e-9)
        if deeper:
            run = ext
            kept[(sym, d, htf)] += 1
        else:
            blocked[(sym, d, htf)].append(r)

bl = [r for rows in blocked.values() for r in rows]
print()
print("--- итог по правилу «триггер должен обновить предыдущий в том же окне» ---")
print("окон (symbol+direction+htf):", len(kept) + len(blocked), "| из них с дублями:", len(blocked))
print("сигналов всего:", len(df), "| остались бы:", len(df) - len(bl), "| заблокировано локом:", len(bl),
      f"({100.0 * len(bl) / max(len(df), 1):.1f}%)")

bdf = pd.DataFrame(bl)
if not bdf.empty:
    m = bdf.merge(tr, on="hash", how="inner")
    print("из заблокированных сетапов сделок:", len(m), "| их ΣR (net):", round(float(m["r_net"].sum()), 2),
          "| средний R:", round(float(m["r_net"].mean()), 3) if len(m) else 0)
    print("плюсовых среди них:", int((m["r_net"] > 0).sum()), "| минусовых:", int((m["r_net"] < 0).sum()))
    print()
    print("--- по парам (сигналов / сделок / ΣR) ---")
    for sym, g in m.groupby("symbol"):
        s_cnt = int((bdf["symbol"] == sym).sum())
        print(f"  {sym:5s} сигналов {s_cnt:4d} | сделок {len(g):4d} | ΣR {float(g['r_net'].sum()):+8.1f}")
    print()
    print("--- по годам (сделок / ΣR) ---")
    m["year"] = pd.to_datetime(m.merge(bdf[["hash", "trig_time"]], on="hash")["trig_time"], errors="coerce").dt.year
    for y, g in m.groupby("year"):
        print(f"  {int(y)}: сделок {len(g):4d} | ΣR {float(g['r_net'].sum()):+8.1f}")
    print()
    print("--- примеры (первые 8) ---")
    for rows in list(blocked.values())[:8]:
        for r in rows[:1]:
            print(f"  {r['symbol']:5s} {r['direction']:5s} окно {r['htf_time']} trig {r['trig_time']} "
                  f"ext={r['trig_ext']} sweep={r['sweep_level']}")
