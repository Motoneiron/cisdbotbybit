"""trend_combo.py — анализ КОМБИНАЦИЙ: EMA13-slope гейт vs перепроверенные (linreg/DI/Aroon/ER).

Берёт фичи двух сканов (оба — книга tf7_abl, якорь=created, 9 пар):
- trend_scan_feats.pkl  : er10/er20, chop14, adx14, pdi/mdi, ar_up/ar_dn, lr13/lr21
- ema_anchor_feats.pkl  : slope EMA (5m) на якорях created/fl1h/...

Вопрос: добавляют ли забракованные фильтры что-то ПОВЕРХ EMA-гейта (или это дубли).
Порог EMA13 = 0.0002 (доля/бар) == linreg13 0.02 (%/бар).
"""
from __future__ import annotations

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"

t = pd.read_pickle(f"{BASE}/trend_scan_feats.pkl")
e = pd.read_pickle(f"{BASE}/ema_anchor_feats.pkl")

t = t.copy()
e = e.copy()
t["k"] = t.sym.astype(str) + "|" + pd.to_datetime(t.created_ts).astype(str)
e["k"] = e.sym.astype(str) + "|" + pd.to_datetime(e.created_ts).astype(str)
cols_e = [c for c in e.columns if c.startswith("5m_created")] + ["k"]
m = t.merge(e[cols_e], on="k", how="inner")
print(f"объединено: trend={len(t)} anchor={len(e)} → merged={len(m)}", flush=True)

m["r"] = m["r_net_mexc"].astype(float)
L = m.direction == "LONG"
S = m.direction == "SHORT"
base = m.r.mean()
print(f"база: n={len(m)} avg={base:+.4f}", flush=True)


def dir_ok(v: pd.Series, thr: float) -> pd.Series:
    return (L & (v > thr)) | (S & (v < -thr)) | v.isna()


ema13 = dir_ok(m["5m_created_13"], 0.0002)
lr13 = dir_ok(m["lr13"], 0.02)
di = ((L & (m.pdi > m.mdi)) | (S & (m.mdi > m.pdi))) | m.pdi.isna()
ar = ((L & (m.ar_up > m.ar_dn)) | (S & (m.ar_dn > m.ar_up))) | m.ar_up.isna()
er = (m.er10 > 0.3) | m.er10.isna()


def show(name: str, ok: pd.Series) -> None:
    sk = m[~ok]
    ps = m[ok]
    ys = [sk[sk.year == y].r.sum() for y in sorted(m.year.unique()) if len(sk[sk.year == y]) >= 5]
    print(
        f"{name:>30} skip={100*len(sk)/len(m):>5.1f}% skipavg={sk.r.mean() if len(sk) else float('nan'):+8.3f} "
        f"passavg={ps.r.mean() if len(ps) else float('nan'):+8.3f} yneg={sum(1 for x in ys if x < 0)}/{len(ys)}",
        flush=True,
    )


print("\n=== одиночки vs поверх EMA13 ===", flush=True)
show("EMA13 (эталон)", ema13)
show("DI alone", di)
show("EMA13 & DI", ema13 & di)
show("linreg13 alone", lr13)
show("EMA13 & linreg13", ema13 & lr13)
show("Aroon alone", ar)
show("EMA13 & Aroon", ema13 & ar)
show("ER10>0.3 alone", er)
show("EMA13 & ER10", ema13 & er)
show("EMA13 & DI & Aroon", ema13 & di & ar)
show("EMA13 & DI & ER", ema13 & di & er)

print("\n=== 4 группы EMA13 x DI ===", flush=True)
for e_ok in (True, False):
    for d_ok in (True, False):
        g = m[(ema13 == e_ok) & (di == d_ok)]
        if len(g):
            print(f"EMA13={'pass' if e_ok else 'SKIP'} DI={'pass' if d_ok else 'SKIP'} n={len(g):>5} "
                  f"avg={g.r.mean():+.3f} SR={g.r.sum():+.0f}", flush=True)

print("\n=== корреляции (spearman) ===", flush=True)
cc = m[["5m_created_13", "lr13", "er10", "adx14", "chop14"]].corr(method="spearman")
print(cc.round(3), flush=True)
print("\nDONE", flush=True)
