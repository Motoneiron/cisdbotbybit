"""Сводка фильтров tf2: vwap / slope / D / W + комбо + поверх SHORT>=2.5%."""
import glob
import pickle

import numpy as np
import pandas as pd

D = "D:/PYTHON/cisdbotbybit/RUNS/temp"

rows = []
for f in sorted(glob.glob(f"{D}/tf2_filters/*.pkl")):
    rows.extend(pickle.load(open(f, "rb")))
df = pd.DataFrame(rows)
df["net"] = df["r_1.0"] - np.where(df["out_1.0"] == "tp", df["fee_maker2"], df["fee_mix"])
df["d_side"] = np.where(df["dir"] == "LONG", df["d_bull"] == True, df["d_bull"] == False)
df["w_side"] = np.where(df["dir"] == "LONG", df["w_bull"] == True, df["w_bull"] == False)
print(f"всего сделок: {len(df)}")
print(f"база: avg={df['net'].mean():+.4f} Σ={df['net'].sum():+.0f}")


def show(name, m_keep, base=None):
    g_all = base if base is not None else df
    keep = g_all[m_keep]
    drop = g_all[~m_keep]
    def stats(g):
        if len(g) == 0:
            return "n=0"
        w = g[g["out_1.0"].isin(["tp", "sl"])]
        wr = 100 * (w["out_1.0"] == "tp").mean() if len(w) else float("nan")
        yrs = sum(1 for y in sorted(g["year"].unique()) if g[g["year"] == y]["net"].mean() > 0)
        return f"n={len(g):>5} WR={wr:4.1f}% avg={g['net'].mean():+.4f} Σ={g['net'].sum():+.0f} плюс-лет {yrs}/{g['year'].nunique()}"
    print(f"  {name:<14} ОСТАВЛЕНО: {stats(keep)}")
    print(f"  {'':<14} ОТСЕЯНО:   {stats(drop)}")


print("\n=== ПО ОДИНОЧКЕ ===")
show("vwap ok", df["vwap_ok"])
show("slope ok", df["slope_ok"])
show("D за", df["d_side"] == True)
show("W за", df["w_side"] == True)

print("\n=== КОМБО ===")
show("vwap&slope", df["vwap_ok"] & df["slope_ok"])
show("vwap&slope&Dза", df["vwap_ok"] & df["slope_ok"] & (df["d_side"] == True))
show("vwap&Dза", df["vwap_ok"] & (df["d_side"] == True))

print("\n=== ПОВЕРХ SHORT>=2.5% (база ячейки: +0.0239) ===")
sh = df[(df["dir"] == "SHORT") & (df["stop_pct"] >= 2.5)]
print(f"  ячейка чистая: n={len(sh)} avg={sh['net'].mean():+.4f}")
for name, m in (("+vwap ok", sh["vwap_ok"]), ("+slope ok", sh["slope_ok"]),
                ("+D за", sh["d_side"] == True), ("+W за", sh["w_side"] == True),
                ("+vwap&slope", sh["vwap_ok"] & sh["slope_ok"])):
    g = sh[m]
    if len(g) < 30:
        print(f"  {name:<12}: n={len(g)} — мало")
        continue
    yrs = sum(1 for y in sorted(g["year"].unique()) if g[g["year"] == y]["net"].mean() > 0)
    print(f"  {name:<12}: n={len(g):>5} avg={g['net'].mean():+.4f} Σ={g['net'].sum():+.0f} плюс-лет {yrs}/{g['year'].nunique()}")

print("\n=== SHORT>=2.5%: по годам с фильтрами ===")
for name, m in (("чистая", pd.Series(True, index=sh.index)), ("vwap&slope&D/за", sh["vwap_ok"] & sh["slope_ok"] & (sh["d_side"] == True))):
    g = sh[m]
    line = f"  {name:<14}: "
    for y in sorted(g["year"].unique()):
        gy = g[g["year"] == y]
        line += f"{y}:{gy['net'].mean():+.3f}({len(gy)}) "
    print(line)
