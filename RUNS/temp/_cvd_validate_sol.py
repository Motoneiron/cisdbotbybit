"""Валидация CVD-сигнала SOL: годовая стабильность, алиасы, ортогональность к 18-му."""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def wr(p):
    d = p[p.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else 0.0


def qtab(g, col):
    gg = g[g[col].notna()].copy()
    if len(gg) < 40:
        return
    gg["q"] = pd.qcut(gg[col].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    out = []
    for q, s in gg.groupby("q", observed=True):
        out.append(f"Q{q}:{wr(s):4.0f}/{s.r_net.mean():+.3f}")
    print("   " + "  ".join(out), flush=True)


sol = pd.read_pickle(BASE + "/stream_sol_cvd.pkl")
el = pd.read_pickle(BASE + "/stream_off_v1_v2_el.pkl")[["hash", "zz_frac", "zz_last_dir"]]
knn = pd.read_pickle(BASE + "/knn18_full.pkl")
mp = knn.drop_duplicates("hash").set_index("hash")["keep"]
sol["keep18"] = sol["hash"].map(mp)
sol = sol.merge(el, on="hash", how="left", suffixes=("", "_el"))

print("=== алиасы (corr с of_1h_s):")
s = sol[sol.of_1h_s.notna()]
for c in ("vd", "sweep_atr", "quality_score", "of_trig_s", "act"):
    print(f"  corr(of_1h_s, {c}) = {s[['of_1h_s', c]].corr().iloc[0, 1]:.3f}")
print("  средний of_1h_s по zz:", s.groupby("zz_last_dir")["of_1h_s"].mean().round(4).to_dict())

print("\n=== SHORT of_1h_s по годам:")
for yr, g in sol[(sol['dir'] == "SHORT")].groupby("year"):
    print(f" {int(yr)} (n={len(g)}):", flush=True)
    qtab(g, "of_1h_s")

print("\n=== SHORT of_4h_s по годам:")
for yr, g in sol[(sol['dir'] == "SHORT")].groupby("year"):
    print(f" {int(yr)} (n={len(g)}):", flush=True)
    qtab(g, "of_4h_s")

print("\n=== внутри 18-KEEP: SHORT of_1h_s квартили:")
keep = sol[(sol.keep18 == True) & (sol['dir'] == "SHORT")]
qtab(keep, "of_1h_s")
print("=== внутри 18-KEEP: LONG of_1h_s квартили (n=%d):" % len(keep))
kt = sol[(sol.keep18 == True) & (sol['dir'] == "LONG")]
qtab(kt, "of_1h_s")

print("\n=== каскад: keep18 & of_1h_s>=медианы (SHORT):")
short = sol[sol['dir'] == "SHORT"]
med = short.of_1h_s.median()
casc = short[(short.keep18 == True) & (short.of_1h_s >= med)]
rest = short[~((short.keep18 == True) & (short.of_1h_s >= med))]
print(f"  каскад n={len(casc)} WR={wr(casc):.1f} ΣR={casc.r_net.sum():.1f}")
print(f"  остальное n={len(rest)} WR={wr(rest):.1f} ΣR={rest.r_net.sum():.1f}")
