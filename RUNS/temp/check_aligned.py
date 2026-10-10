"""Сверка: сделки движка (aligned-кэши) против моего пересчёта на якоре cbt+30."""
import glob
import pickle

import pandas as pd

mine = {}
for f in sorted(glob.glob("RUNS/temp/night_core_aligned/*.pkl")):
    name = f.replace("\\", "/").split("/")[-1].replace(".pkl", "")
    r = pd.DataFrame(pickle.load(open(f, "rb")))
    mine[name] = int(((r.anchor == 30) & (r.win == 30) & (r.filled)).sum())
eng = {}
for f in sorted(glob.glob("D:/PYTHON/CISDBOT/RUNS/filters_off_full_aligned/*_tf8_*.pkl")):
    p = pickle.load(open(f, "rb"))
    sym = str(p.get("symbol") or "").replace("USDT", "")
    eng[f"{sym}_{str(p.get('since'))[:4]}"] = len([t for t in (p.get("trades") or []) if t.get("entry_kind") == "LIMIT"])
keys = sorted(set(eng) & set(mine))
print(f"сопоставлено пары-год: {len(keys)} из {len(eng)} (движок) / {len(mine)} (мои)")
print(f"{'пара-год':12s} {'движок':>7s} {'мой cbt+30':>11s} {'Δ':>6s}")
tm = te = 0
for k in keys:
    tm += mine[k]; te += eng[k]
    print(f"  {k:10s} {eng[k]:7d} {mine[k]:11d} {mine[k] - eng[k]:6d}")
print(f"  ВСЕГО: движок {te} | мой {tm} | Δ {tm - te}")
if keys:
    rel = 100.0 * (tm - te) / max(1, te)
    print(f"  расхождение: {rel:+.1f}%")
