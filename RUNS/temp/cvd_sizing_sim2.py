"""CVD-сайзинг v2: устойчивость. k-сетка, по годам, направления, frozen-границы."""
import heapq

import numpy as np
import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_multi_cvd.pkl")
d = df.copy()
d["t_in"] = pd.to_datetime(d["ts_fill"]).astype("int64") // 60_000_000_000
d["t_out"] = pd.to_datetime(d["exit_ts"]).astype("int64") // 60_000_000_000

# winsorize of_1h_s по 1/99 (для frozen-границ)
lo, hi = d.of_1h_s.quantile(0.01), d.of_1h_s.quantile(0.99)
d["ofw"] = d.of_1h_s.clip(lo, hi)

r = d["of_1h_s"].rank(pct=True)
for k in (0.4, 0.6, 0.8, 1.0, 1.25, 1.5):
    d[f"k{k}"] = 1 + k * (r - 0.5)

# frozen-терцили из диск-периода (2020-23)
disc = d[d.year <= 2023]
c1, c2 = disc.ofw.quantile(1 / 3), disc.ofw.quantile(2 / 3)
print(f"frozen границы (из 2020-23): c1={c1:+.4f} c2={c2:+.4f}")
print("медиана ofw диск:", disc.ofw.median().round(4), "| оос:", d[d.year >= 2024].ofw.median().round(4))
d["w_frozen"] = np.select([d.ofw < c1, d.ofw > c2], [0.7, 1.3], default=1.0)
d["w_base"] = 1.0


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
    return bal, dd


oos = d[d.year >= 2024]
full = d
print("\n=== k-сетка (×-фактор) ===")
print(f"{'k':>5} | {'ВСЁ 2020-26':>14} {'MaxDD':>7} | {'OOS 2024-26':>14} {'MaxDD':>7}")
b = simulate(full, "w_base")
bo = simulate(oos, "w_base")
print(f"{'base':>5} | {b[0]/100:>14,.0f} {b[1]:>6.1f}% | {bo[0]/100:>14,.0f} {bo[1]:>6.1f}%")
for k in (0.4, 0.6, 0.8, 1.0, 1.25, 1.5):
    f = simulate(full, f"k{k}")
    o = simulate(oos, f"k{k}")
    print(f"{k:>5} | {f[0]/100:>14,.0f} {f[1]:>6.1f}% | {o[0]/100:>14,.0f} {o[1]:>6.1f}%")

fo = simulate(oos, "w_frozen")
print(f"\nfrozen терцили (границы 2020-23, применены к OOS): ×{fo[0]/100:,.0f} MaxDD {fo[1]:.1f}% "
      f"| vs base ×{bo[0]/100:,.0f} {bo[1]:.1f}%")

print("\n=== по годам (k=1.0) ===")
print(f"{'год':>5} | {'base ×':>12} {'MaxDD':>7} | {'k1.0 ×':>12} {'MaxDD':>7} | ratio")
for y in sorted(d.year.unique()):
    yy = d[d.year == y]
    bb = simulate(yy, "w_base")
    kk = simulate(yy, "k1.0")
    print(f"{y:>5} | {bb[0]/100:>12,.1f} {bb[1]:>6.1f}% | {kk[0]/100:>12,.1f} {kk[1]:>6.1f}% | "
          f"×{kk[0]/max(bb[0],1e-9):.2f}")

print("\n=== направления (OOS, k=1.0) ===")
for dr in ("LONG", "SHORT"):
    dd_ = oos[oos["dir"] == dr]
    bb = simulate(dd_, "w_base")
    kk = simulate(dd_, "k1.0")
    print(f"{dr}: base ×{bb[0]/100:,.0f} ({bb[1]:.1f}%) | k1.0 ×{kk[0]/100:,.0f} ({kk[1]:.1f}%) "
          f"| ratio ×{kk[0]/max(bb[0],1e-9):.2f}")
