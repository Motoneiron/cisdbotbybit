"""Условный выход по прибыли на 6ч (tf8 + min_stop 0.5%).

Правило применяется к сделкам, которые на 6ч ЕЩЁ ОТКРЫТЫ (TIME-группа); TP/SL-сделки уже закрыты.
 g6  — нереализованный P&L в R на 6ч (gross: r_6 + комиссия выхода, чтобы порог был «честный»)
 B   — «плюс тянем»: если g6 > thr → держим до касания TP/SL в пределах 24ч, иначе крышка на 6ч
 C   — «минус тянем» (инверсия): если g6 < -thr → держим до 24ч, иначе крышка на 6ч
Сетка thr + walk-forward (thr выбираем на 1-й половине, проверяем на 2-й).
"""
import heapq

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
MAKER, TAKER = 0.00036, 0.0010
d = pd.read_pickle(f"{BASE}/stream_tf8_timeout.pkl")
d = d[d["r_6"].notna() & (d.sp >= 0.005)].copy()
d["ts_fill"] = pd.to_datetime(d.ts_fill)
d["t_in"] = ((d.ts_fill - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
d["fee"] = (MAKER + TAKER) / d.sp
d["g6"] = d["r_6"] + d["fee"]           # нереализованный P&L на 6ч (до комиссии выхода)
op = d["res_6"] == "time"               # открыты на 6ч
print(f"всего {len(d)} | открыты на 6ч: {int(op.sum())} ({100*op.mean():.0f}%) | закрыты TP/SL раньше: {int((~op).sum())}")
print(f"у открытых на 6ч: g6 медиана {d.loc[op,'g6'].median():+.3f}R | в плюсе {100*(d.loc[op,'g6']>0).mean():.0f}% | в минусе {100*(d.loc[op,'g6']<0).mean():.0f}%")

THRS = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
print("\n=== сетка (весь период): ΣR ===")
print(f"  {'thr':>5} | {'B «плюс тянем»: держим n / ΣR':>34} | {'C «минус тянем»: держим n / ΣR':>34}")
base6 = d["r_6"].sum(); hold24 = d["r_24"].sum()
print(f"  статика: крышка на 6ч ΣR={base6:+.1f} | держать всех до 24ч ΣR={hold24:+.1f}")
for t in THRS:
    mb = op & (d.g6 > t); rb = np.where(mb, d.r_24, d.r_6)
    mc = op & (d.g6 < -t); rc = np.where(mc, d.r_24, d.r_6)
    print(f"  {t:5.1f} | держим {int(mb.sum()):5d} ΣR={np.sum(rb):+8.1f} | держим {int(mc.sum()):5d} ΣR={np.sum(rc):+8.1f}")

mid = d.ts_fill.quantile(0.5)
tr, te = d[d.ts_fill < mid], d[d.ts_fill >= mid]
print(f"\n=== WALK-FORWARD (thr по 1-й половине → тест на 2-й) ===")
print(f"  {'правило':>16} | {'лучший thr (1-я)':>16} | {'2-я половина: сетка ΣR':>38}")
for nm in ("B", "C"):
    best_t, best_r = None, -1e18
    for t in THRS:
        sgn = 1 if nm == "B" else -1
        m = (tr["res_6"] == "time") & (tr.g6 > sgn * t if nm == "B" else tr.g6 < -t)
        r = np.where(m, tr.r_24, tr.r_6).sum()
        if r > best_r:
            best_r, best_t = r, t
    r6 = te["r_6"].sum(); r24 = te["r_24"].sum()
    sgn = 1 if nm == "B" else -1
    m = (te["res_6"] == "time") & (te.g6 > best_t if nm == "B" else te.g6 < -best_t)
    rr = np.where(m, te.r_24, te.r_6).sum()
    print(f"  {nm:>16} | thr={best_t:>4} ({best_r:+7.1f}) | 6ч {r6:+7.1f} / 24ч {r24:+7.1f} / правило {rr:+7.1f}")

print("\n=== по годам: B(thr=0.3) и C(thr=0.3) против статики ===")
mb = op & (d.g6 > 0.3); mc = op & (d.g6 < -0.3)
d["rB"] = np.where(mb, d.r_24, d.r_6); d["rC"] = np.where(mc, d.r_24, d.r_6)
for y, g in d.groupby("year"):
    print(f"  {int(y)}: 6ч {g['r_6'].sum():+7.1f} | 24ч все {g['r_24'].sum():+7.1f} | B {g['rB'].sum():+7.1f} | C {g['rC'].sum():+7.1f}")


def pf(x, rcol, hout):
    g = x.copy()
    tmin = np.minimum(g.t_tp_min.fillna(1e9), g.t_sl_min.fillna(1e9))
    # закрытые на 6ч → выход на 360 мин; удержанные → до касания/24ч
    tmin = np.minimum(tmin, hout * 60)
    g["t_out"] = g.t_in + tmin.fillna(hout * 60).astype("int64")
    it = list(zip(g.t_in, g.t_out, g.sym, g[rcol].astype(float)))
    pe, hp, tk = {}, [], []
    for tin, tout, sym, r in it:
        while hp and hp[0] <= tin:
            heapq.heappop(hp)
        p = pe.get(sym)
        if p is not None and tin < p:
            continue
        if len(hp) >= 7:
            continue
        tk.append((tin, tout, r)); heapq.heappush(hp, tout); pe[sym] = tout
    ev = []
    for i, (tin, tout, r) in enumerate(tk):
        ev.append((tin, 1, i)); ev.append((tout, 0, i))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    bal = 100.0; rm = {}; cur = [(ev[0][0] if ev else 0, bal)]
    for t, k, i in ev:
        tin, tout, r = tk[i]
        if k == 0:
            if i in rm:
                bal += rm.pop(i) * r
        else:
            if tout <= tin:
                bal += bal * 0.01 * r
            else:
                rm[i] = bal * 0.01
        cur.append((t, bal))
    s = pd.Series([c[1] for c in cur])
    return bal, float(((s - s.cummax()) / s.cummax()).min() * 100), len(tk)


print("\n=== Портфель ($100, 7 слотов, риск 1%) ===")
dd = d.copy()
# для удержанных правило B/C: горизонт 24ч, иначе 6ч
dd["r_ruleB"] = dd["rB"]; dd["r_ruleC"] = dd["rC"]
for lab, col, hout in (("статика 6ч", "r_6", 6), ("все до 24ч", "r_24", 24),
                       ("B «плюс тянем» 0.3R", "r_ruleB", 24), ("C «минус тянем» 0.3R", "r_ruleC", 24)):
    g = dd[dd["r_6"].notna()].copy()
    f, mdd, n = pf(g, col, hout)
    g24 = g[g.year >= 2024]
    f2, m2, n2 = pf(g24, col, hout)
    print(f"  {lab:22} | все: n={n:6d} ${f:>12,.0f} ({mdd:>6.1f}%) | 2024-26: n={n2:5d} ${f2:>9,.0f} ({m2:>6.1f}%)")
print("\nDONE")
