"""Анализ ИСПРАВЛЕННОЙ TP-сетки: TP 1R/1.25/1.5/2R + адаптив для узких стопов.

SANITY с учётом известного бага потока: TP/SL и LONG-TIME должны совпасть с r_net;
SHORT-TIME у потока с перевёрнутым знаком, поэтому сверяем их с исправленной формулой.
"""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
MAKER, TAKER = 0.00036, 0.0010
df = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
XS = ("1_0", "1_25", "1_5", "2_0")
LAB = {"1_0": "1.0R", "1_25": "1.25R", "1_5": "1.5R", "2_0": "2.0R"}


def wr(g, res):
    d = g[g[res].isin(["tp", "sl"])]
    return 100.0 * (d[res] == "tp").mean() if len(d) else float("nan")


ok = df["r_1_0"].notna()
print(f"покрытие: {int(ok.sum())}/{len(df)}")
d = df[ok].copy()
d["fee"] = (MAKER + TAKER) / d.sp
# sanity
seg = d[d.outcome.isin(["tp", "sl"]) | ((d.outcome == "time") & (d["dir"] == "LONG"))]
print("\n=== SANITY (TP/SL + LONG-TIME): мой r_1.0R против потока ===")
print(f"  corr={np.corrcoef(seg['r_1_0'], seg.r_net)[0,1]:.5f} | медиана |Δ|={(seg['r_1_0']-seg.r_net).abs().median():.6f} | "
      f"совпало до 1e-6: {100*((seg['r_1_0']-seg.r_net).abs()<1e-6).mean():.1f}%")
st = d[(d.outcome == "time") & (d["dir"] == "SHORT")]
exp = -st.r_net - 2 * st.fee
print(f"  SHORT-TIME (поток с перевёрнутым знаком): моя формула совпала с ИСПРАВЛЕННОЙ на {100*((st['r_1_0']-exp).abs()<1e-6).mean():.1f}%")

print("\n=== TP-варианты на всём потоке (исправленный TIME) ===")
for x in XS:
    g = df[df[f"r_{x}"].notna()]
    tp = int((g[f"res_{x}"] == "tp").sum()); sl = int((g[f"res_{x}"] == "sl").sum()); tm = int((g[f"res_{x}"] == "time").sum())
    print(f"  TP={LAB[x]:6}: TP/SL/TIME={tp:6d}/{sl:6d}/{tm:6d} WR={100*tp/max(1,tp+sl):5.1f}% "
          f"ΣR={g[f'r_{x}'].sum():+9.1f} avg={g[f'r_{x}'].mean():+.4f}")

print("\n=== по децилям ширины стопа (fee_SL = (maker+taker)/sp) ===")
g = df[ok].copy()
g["dec"] = pd.qcut(g.sp.rank(method="first"), 10, labels=range(1, 11))
print("  " + f"{'дец':<5}{'sp med':>8}{'fee_SL':>8}" + "".join(f"{LAB[x]:>12}" for x in XS))
for q, gg in g.groupby("dec", observed=True):
    print(f"  D{int(q):<4}{100*gg.sp.median():>7.3f}%{(MAKER+TAKER)/gg.sp.median():>8.2f}" + "".join(f"{gg[f'r_{x}'].sum():>+12.1f}" for x in XS))

print("\n=== АДАПТИВ: узким (sp<порога) TP=1.5R, остальным 1R ===")
for thr in (0.003, 0.004, 0.005, 0.006, 0.008, 0.010):
    g = df[ok].copy()
    nar = g.sp < thr
    g["r_ad"] = np.where(nar, g.r_1_5, g.r_1_0)
    g["rs_ad"] = np.where(nar, g.res_1_5, g.res_1_0)
    tp = int((g.rs_ad == "tp").sum()); sl = int((g.rs_ad == "sl").sum())
    print(f"  sp<{100*thr:.1f}% (узких {int(nar.sum()):5d}): WR={100*tp/max(1,tp+sl):5.1f}% ΣR={g.r_ad.sum():+9.1f} "
          f"(база {g['r_1_0'].sum():+9.1f}, Δ {g.r_ad.sum()-g['r_1_0'].sum():+8.1f})")

print("\n=== то же по годам (адаптив sp<0.5%) ===")
g = df[ok].copy()
nar = g.sp < 0.005
g["r_ad"] = np.where(nar, g.r_1_5, g.r_1_0)
for y, gg in g.groupby("year"):
    print(f"  {int(y)}: база {gg['r_1_0'].sum():+8.1f} | адаптив {gg.r_ad.sum():+8.1f} | Δ {gg.r_ad.sum()-gg['r_1_0'].sum():+7.1f}")

print("\n=== все TP=1.5R (без адаптива) по годам ===")
for y, gg in df[ok].groupby("year"):
    print(f"  {int(y)}: TP1R {gg['r_1_0'].sum():+8.1f} | TP1.5R {gg['r_1_5'].sum():+8.1f} | TP2R {gg['r_2_0'].sum():+8.1f}")

print("\n=== узкие (sp<0.5%) отдельно ===")
n = df[ok & (df.sp < 0.005)]
for x in XS:
    tp = int((n[f"res_{x}"] == "tp").sum()); sl = int((n[f"res_{x}"] == "sl").sum())
    print(f"  TP={LAB[x]:6}: n={len(n)} TP/SL={tp}/{sl} WR={100*tp/max(1,tp+sl):5.1f}% ΣR={n[f'r_{x}'].sum():+8.1f}")

print("\n=== альтернатива: выкинуть узкие (min_stop) — на исправленном TIME ===")
for thr in (0.003, 0.004, 0.005, 0.006, 0.008):
    g = df[ok & (df.sp >= thr)]
    print(f"  min_stop {100*thr:.1f}%: n={len(g)} ΣR={g['r_1_0'].sum():+9.1f} avg={g['r_1_0'].mean():+.4f} "
          f"(выкинуто {len(df[ok])-len(g)}, их ΣR={df[ok & (df.sp < thr)]['r_1_0'].sum():+.1f})")
print("\nDONE")
