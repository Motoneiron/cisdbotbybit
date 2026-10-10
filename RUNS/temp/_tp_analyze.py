"""Анализ TP-сетки (данные уже в stream_tp_grid.pkl): TP=1R / 1.25 / 1.5 / 2R и адаптив для узких стопов."""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
XS = ("1.0", "1.25", "1.5", "2.0")


def wr(g, res):
    d = g[g[res].isin(["tp", "sl"])]
    return 100.0 * (d[res] == "tp").mean() if len(d) else float("nan")


ok = df["r_1.0"].notna()
print(f"симуляция покрыла {int(ok.sum())} из {len(df)}")
d = df[ok & df.r_net.notna()]
print("\n=== SANITY: TP=1R против исходного потока ===")
print(f"  corr={np.corrcoef(d['r_1.0'], d.r_net)[0,1]:.4f} | медиана |Δ|={(d['r_1.0']-d.r_net).abs().median():.5f} | "
      f"Σ simul={d['r_1.0'].sum():+.1f} vs поток={d.r_net.sum():+.1f} | совпало до 1e-6: {100*((d['r_1.0']-d.r_net).abs()<1e-6).mean():.1f}%")

print("\n=== TP-варианты на ВСЁМ потоке ===")
for x in XS:
    g = df[df[f"r_{x}"].notna()]
    tp = int((g[f"res_{x}"] == "tp").sum()); sl = int((g[f"res_{x}"] == "sl").sum()); tm = int((g[f"res_{x}"] == "time").sum())
    print(f"  TP={x}R: n={len(g)} TP/SL/TIME={tp}/{sl}/{tm} WR={100*tp/max(1,tp+sl):.1f}% ΣR={g[f'r_{x}'].sum():+8.1f} avg={g[f'r_{x}'].mean():+.3f}")

print("\n=== децили по ширине стопа sp: что даёт каждый TP ===")
g = df[ok].copy()
g["dec"] = pd.qcut(g.sp.rank(method="first"), 10, labels=range(1, 11))
hdr = "  " + f"{'дециль':8}" + f"{'sp med':>9}" + "".join(f"{'TP'+x+'R':>11}" for x in XS) + f"{'fee_SL R':>10}"
print(hdr)
for q, gg in g.groupby("dec", observed=True):
    fee = (0.00036 + 0.0010) / gg.sp.median()
    print(f"  D{int(q):<7}{100*gg.sp.median():>8.3f}%" + "".join(f"{gg[f'r_{x}'].sum():>+11.1f}" for x in XS) + f"{fee:>10.2f}")

print("\n=== УЗКИЕ стопы (sp<0.5%): подробно ===")
n = df[ok & (df.sp < 0.005)]
for x in XS:
    tp = int((n[f"res_{x}"] == "tp").sum()); sl = int((n[f"res_{x}"] == "sl").sum()); tm = int((n[f"res_{x}"] == "time").sum())
    print(f"  TP={x}R: n={len(n)} TP/SL/TIME={tp}/{sl}/{tm} WR={100*tp/max(1,tp+sl):.1f}% ΣR={n[f'r_{x}'].sum():+8.1f} avg={n[f'r_{x}'].mean():+.3f}")
print(f"  (у таких сделок fee_SL = {(0.00036+0.0010)/n.sp.median():.2f}R, fee_TP(1R) = {2*0.00036/n.sp.median():.2f}R)")

print("\n=== АДАПТИВ: узким (sp<порога) ставим TP=1.5R, остальным 1R ===")
for thr in (0.003, 0.004, 0.005, 0.006, 0.008, 0.010):
    g = df[ok].copy()
    nar = g.sp < thr
    g["r_ad"] = np.where(nar, g["r_1.5"], g["r_1.0"])
    g["rs_ad"] = np.where(nar, g["res_1.5"], g["res_1.0"])
    tp = int((g.rs_ad == "tp").sum()); sl = int((g.rs_ad == "sl").sum())
    print(f"  sp<{100*thr:.1f}% (узких {int(nar.sum()):5d}): WR={100*tp/max(1,tp+sl):5.1f}% ΣR={g.r_ad.sum():+8.1f} "
          f"(база TP1R {g['r_1.0'].sum():+8.1f}, Δ {g.r_ad.sum()-g['r_1.0'].sum():+7.1f})")

print("\n=== то же по годам (адаптив sp<0.5%, TP1.5R) ===")
g = df[ok].copy()
nar = g.sp < 0.005
g["r_ad"] = np.where(nar, g["r_1.5"], g["r_1.0"])
for y, gg in g.groupby("year"):
    print(f"  {int(y)}: база {gg['r_1.0'].sum():+7.1f} | адаптив {gg.r_ad.sum():+7.1f} | Δ {gg.r_ad.sum()-gg['r_1.0'].sum():+7.1f}")

print("\n=== альтернатива: просто ВЫКИНУТЬ узкие (min_stop) ===")
for thr in (0.003, 0.004, 0.005, 0.006, 0.008):
    g = df[ok & (df.sp >= thr)]
    print(f"  min_stop {100*thr:.1f}%: n={len(g)} ΣR={g['r_1.0'].sum():+8.1f} avg={g['r_1.0'].mean():+.3f} "
          f"(выкинуто {len(df[ok])-len(g)} сд, их ΣR={df[ok & (df.sp < thr)]['r_1.0'].sum():+.1f})")
print("\nDONE")
