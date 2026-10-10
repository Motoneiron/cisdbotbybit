"""CVD-сайзинг: веса по of_1h_s (ранк) в портфеле. Диск 2020-23 / ООС 2024-26.
Портфель: 1 поз/пара, лимит 7, риск 1% x вес, реинвест $100.
"""
import heapq

import numpy as np
import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_multi_cvd.pkl")
d = df.copy()
d["t_in"] = pd.to_datetime(d["ts_fill"]).astype("int64") // 60_000_000_000
d["t_out"] = pd.to_datetime(d["exit_ts"]).astype("int64") // 60_000_000_000
r = d["of_1h_s"].rank(pct=True)
d["w_lin15"] = 1 + 1.0 * (r - 0.5)          # 0.5 .. 1.5
d["w_lin13"] = 1 + 0.6 * (r - 0.5)          # 0.7 .. 1.3
qq = pd.qcut(r, 3, labels=[0, 1, 2], duplicates="drop")
d["w_tern"] = qq.map({0: 0.7, 1: 1.0, 2: 1.3}).astype(float)
q4 = pd.qcut(r, 4, labels=[0, 1, 2, 3], duplicates="drop")
d["w_quart"] = q4.map({0: 0.75, 1: 0.9, 2: 1.1, 3: 1.25}).astype(float)
print("spearman of_1h_s vs vd:", d[["of_1h_s", "vd"]].corr(method="spearman").iloc[0, 1].round(3))


def simulate(part, wcol, max_pos=7, risk=0.01):
    p = part.sort_values("t_in").reset_index(drop=True)
    pair_end, heap, taken = {}, [], []
    skips = 0
    for idx, row in p.iterrows():
        tin, tout, sym = int(row.t_in), int(row.t_out), row.sym
        while heap and heap[0] <= tin:
            heapq.heappop(heap)
        if sym in pair_end and tin < pair_end[sym]:
            continue
        if len(heap) >= max_pos:
            skips += 1
            continue
        taken.append(idx)
        heapq.heappush(heap, tout)
        pair_end[sym] = tout
    events = []
    for idx in taken:
        tin, tout = int(p.at[idx, "t_in"]), int(p.at[idx, "t_out"])
        events.append((tin, 1, idx))
        if tout > tin:
            events.append((tout, 0, idx))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    bal, risks, eqs = 100.0, {}, [100.0]
    for t, kind, idx in events:
        row = p.loc[idx]
        if kind == 0:
            if idx in risks:
                bal += risks.pop(idx) * float(row.r_net)
                eqs.append(bal)
        else:
            w = float(row[wcol]) if pd.notna(row.get(wcol)) else 1.0
            rr = bal * risk * w
            if row.t_out <= row.t_in:
                bal += rr * float(row.r_net)
                eqs.append(bal)
            else:
                risks[idx] = rr
    eq = np.array(eqs)
    peak = np.maximum.accumulate(eq)
    dd = float(((eq - peak) / peak).min()) * 100
    return bal, dd, len(taken), skips


for label, part in (("ВСЁ 2020-26", d),
                    ("DISC 2020-23", d[d.year <= 2023]),
                    ("OOS 2024-26", d[d.year >= 2024])):
    print(f"\n=== {label} (n={len(part)}) ===")
    for wcol in ("w_lin15", "w_lin13", "w_tern", "w_quart"):
        d2 = part.copy()
        d2["w_base"] = 1.0
        base = simulate(d2, "w_base")
        wt = simulate(d2, wcol)
        print(f"  {wcol:9}: ×{wt[0]/100:>12,.0f} | MaxDD {wt[1]:.1f}% | {wt[2]} взято | {wt[3]} скипов | "
              f"vs base ×{base[0]/100:,.0f} (MaxDD {base[1]:.1f}%)")
