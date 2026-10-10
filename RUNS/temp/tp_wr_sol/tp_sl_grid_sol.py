"""tp_sl_grid_sol.py — 2D-сетка (стоп × тейк) на nofilter-потоке SOL (вопрос юзера 10.10):
«если стоп также сужать — будет ли паритет/плюс?»

Два среза:
 (1) фикс-сетка: стоп и тейк в % от entry (одинаковая настройка для всех сделок);
 (2) пропорционально: стоп = родной sp × a (a<=1 — сужение), тейк = x × новый стоп (в R нового стопа).
Механика 1:1 с прогonом: филл лимитки 1ч (1m), позиция 16ч, комиссии Bybit maker 0.036% / taker 0.10%.
Стоп и тейк — вместо родных; SL имеет приоритет в баре (как в движке). Все R — net (с комиссиями),
в единицах СВОЕГО стопа (для фикс-сетки R' = s% от entry).
"""
import pickle, os, math
import numpy as np
import pandas as pd

MAKER, TAKER = 0.00036, 0.0010
LIMIT_MIN = 60
POS_H = 16

S_GRID = [0.003, 0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02, 0.03, 0.04]
T_GRID = [0.0015, 0.003, 0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02, 0.03]
A_GRID = [1.0, 0.75, 0.5, 0.33]
X_GRID = [0.5, 0.75, 1.0, 1.5, 2.0]

CACHE = r"C:\Users\Motoneiron\.hermes\cache\scratch\sol1m_cache.npz"
PKL = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\rows_tf1v2_nofilter\SOL_{}.pkl"
OUT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\tp_wr_sol"
os.makedirs(OUT, exist_ok=True)

z = np.load(CACHE)
ts = z["ts"]; high = z["high"]; low = z["low"]; close = z["close"]

trades = []
for y in (2024, 2025, 2026):
    for r in pickle.load(open(PKL.format(y), "rb")):
        if r.get("taken"):
            trades.append(r)
print(f"taken trades: {len(trades)}")

NS_MIN = 60 * 1_000_000_000
NS_LIM = LIMIT_MIN * NS_MIN
NS_POS = int(POS_H * 60) * NS_MIN

acc = {(si, ti): ([], []) for si in range(len(S_GRID)) for ti in range(len(T_GRID))}
acc2 = {(ai, xi): ([], []) for ai in range(len(A_GRID)) for xi in range(len(X_GRID))}
years = []
nofill = 0

for tr in trades:
    d = tr["direction"]; entry = float(tr["entry"])
    sp = abs(entry - float(tr["stop"])) / entry
    scan_v = pd.Timestamp(tr["scan"]).value
    i0 = int(np.searchsorted(ts, scan_v, "left"))
    i1 = int(np.searchsorted(ts, scan_v + NS_LIM, "left"))
    fill = -1
    if d == "LONG":
        for j in range(i0, min(i1, len(ts))):
            if low[j] <= entry: fill = j; break
    else:
        for j in range(i0, min(i1, len(ts))):
            if high[j] >= entry: fill = j; break
    if fill < 0:
        nofill += 1
        continue
    k1 = int(np.searchsorted(ts, ts[fill] + NS_POS, "right")) - 1
    if k1 < fill: k1 = fill
    hi = high[fill:k1 + 1]; lo = low[fill:k1 + 1]
    last_close = close[k1]
    years.append(int(tr["scan"][:4]))

    # (1) фикс-сетка
    sl_ids, tp_ids = [], []
    for s in S_GRID:
        p = entry * (1 - s) if d == "LONG" else entry * (1 + s)
        m = (lo <= p) if d == "LONG" else (hi >= p)
        sl_ids.append(int(m.argmax()) if m.any() else -1)
    for t in T_GRID:
        p = entry * (1 + t) if d == "LONG" else entry * (1 - t)
        m = (hi >= p) if d == "LONG" else (lo <= p)
        tp_ids.append(int(m.argmax()) if m.any() else -1)
    gt = ((last_close - entry) / entry) if d == "LONG" else ((entry - last_close) / entry)  # в долях цены
    for si in range(len(S_GRID)):
        s = S_GRID[si]; s_i = sl_ids[si]
        for ti in range(len(T_GRID)):
            t = T_GRID[ti]; t_i = tp_ids[ti]
            if t_i >= 0 and (s_i < 0 or t_i < s_i):
                kind, gross = "tp", t / s
            elif s_i >= 0:
                kind, gross = "sl", -1.0
            else:
                kind, gross = "time", gt / s
            r = gross - MAKER / s - (MAKER if kind == "tp" else TAKER) / s
            acc[(si, ti)][0].append(r); acc[(si, ti)][1].append(kind)

    # (2) пропорционально (стоп = родной sp × a)
    for ai in range(len(A_GRID)):
        a = A_GRID[ai]; s_p = sp * a
        p = entry * (1 - s_p) if d == "LONG" else entry * (1 + s_p)
        m = (lo <= p) if d == "LONG" else (hi >= p)
        s_i = int(m.argmax()) if m.any() else -1
        for xi in range(len(X_GRID)):
            x = X_GRID[xi]
            tp_p = entry * (1 + x * s_p) if d == "LONG" else entry * (1 - x * s_p)
            m2 = (hi >= tp_p) if d == "LONG" else (lo <= tp_p)
            t_i = int(m2.argmax()) if m2.any() else -1
            if t_i >= 0 and (s_i < 0 or t_i < s_i):
                kind, gross = "tp", x
            elif s_i >= 0:
                kind, gross = "sl", -1.0
            else:
                kind, gross = "time", gt / s_p
            r = gross - MAKER / s_p - (MAKER if kind == "tp" else TAKER) / s_p
            acc2[(ai, xi)][0].append(r); acc2[(ai, xi)][1].append(kind)

print(f"nofill={nofill}")
year_arr = np.array(years)

def summarize(rs, ks):
    rs = np.asarray(rs); n = len(rs)
    tp = sum(1 for k in ks if k == "tp"); sl = sum(1 for k in ks if k == "sl")
    ci = 1.96 * rs.std(ddof=1) / math.sqrt(n) if n > 1 else 0.0
    return dict(n=n, tp=tp, sl=sl, tm=n - tp - sl, wr=tp / n, avg=rs.mean(), sr=rs.sum(), ci=ci)

# --- (1) матрица avgR ---
lines = []
lines.append("## (1) Фикс-сетка: стоп × тейк, % от entry — avgR (net), SOL nofilter, n=1694")
lines.append("")
hdr = "| SL↓ TP→ | " + " | ".join(f"{t*100:g}%" for t in T_GRID) + " |"
lines.append(hdr)
lines.append("|---|" + "---|" * len(T_GRID))
print(hdr)
mat = {}
for si, s in enumerate(S_GRID):
    row = []
    for ti, t in enumerate(T_GRID):
        a = summarize(*acc[(si, ti)])
        mat[(si, ti)] = a
        cell = f"{a['avg']:+.3f}"
        if a["avg"] > 0: cell = "**" + cell + "**"
        row.append(cell)
    ln = f"| {s*100:g}% | " + " | ".join(row) + " |"
    lines.append(ln); print(ln)

lines.append("")
lines.append("## WR(tp) для той же матрицы")
lines.append("")
lines.append(hdr); lines.append("|---|" + "---|" * len(T_GRID))
print(lines[-3]); print(lines[-2])
for si, s in enumerate(S_GRID):
    row = [f"{mat[(si, ti)]['wr']*100:.0f}%" for ti in range(len(T_GRID))]
    ln = f"| {s*100:g}% | " + " | ".join(row) + " |"
    lines.append(ln); print(ln)

# топ по avgR
top = sorted(mat.items(), key=lambda kv: kv[1]["avg"], reverse=True)[:10]
print("\n=== TOP-10 ячеек по avgR ===")
lines.append("")
lines.append("### TOP-10 ячеек по avgR")
lines.append("")
lines.append("| SL% | TP% | WR | sl% | avgR | CI95 | ΣR |")
lines.append("|---|---|---|---|---|---|---|")
for (si, ti), a in top:
    ln = (f"| {S_GRID[si]*100:g} | {T_GRID[ti]*100:g} | {a['wr']*100:.1f}% | "
          f"{a['sl']/a['n']*100:.1f}% | {a['avg']:+.3f} | ±{a['ci']:.3f} | {a['sr']:.0f} |")
    lines.append(ln); print(ln)

# где avgR > -0.02 (близко к паритету)
near = [(k, v) for k, v in mat.items() if v["avg"] > -0.02]
print(f"\nячеек с avgR > -0.02: {len(near)}")

# --- (2) пропорциональная ---
lines.append("")
lines.append("## (2) Пропорционально: стоп = родной × a (сужение), тейк = x × новый стоп — avgR (n=1694)")
lines.append("")
hdr2 = "| a \\ x | " + " | ".join(f"{x:g}R" for x in X_GRID) + " |"
lines.append(hdr2); lines.append("|---|" + "---|" * len(X_GRID))
print("\n" + hdr2)
mat2 = {}
for ai, a in enumerate(A_GRID):
    row = []
    for xi, x in enumerate(X_GRID):
        ag = summarize(*acc2[(ai, xi)])
        mat2[(ai, xi)] = ag
        cell = f"{ag['avg']:+.3f}"
        if ag["avg"] > 0: cell = "**" + cell + "**"
        row.append(cell)
    ln = f"| стоп×{a:g} | " + " | ".join(row) + " |"
    lines.append(ln); print(ln)
lines.append("")
lines.append("WR:")
lines.append("")
lines.append(hdr2); lines.append("|---|" + "---|" * len(X_GRID))
for ai, a in enumerate(A_GRID):
    row = [f"{mat2[(ai, xi)]['wr']*100:.0f}%" for xi in range(len(X_GRID))]
    ln = f"| стоп×{a:g} | " + " | ".join(row) + " |"
    lines.append(ln); print(ln)

# --- сводка: лучшая строка каждого среза ---
print("\n=== Лучшее по каждому SL (фикс) ===")
lines.append("")
lines.append("### Лучший тейк для каждого стопа (фикс-сетка)")
lines.append("")
lines.append("| SL% | лучший TP% | WR | avgR |")
lines.append("|---|---|---|---|")
for si, s in enumerate(S_GRID):
    bi = max(range(len(T_GRID)), key=lambda ti: mat[(si, ti)]["avg"])
    a = mat[(si, bi)]
    ln = f"| {s*100:g} | {T_GRID[bi]*100:g} | {a['wr']*100:.1f}% | {a['avg']:+.3f} |"
    lines.append(ln); print(ln)

# --- по годам для лучшей ячейки фикс-сетки и лучшей пропорциональной ---
(si_b, ti_b), a_b = top[0]
best2 = max(mat2.items(), key=lambda kv: kv[1]["avg"])
print(f"\nbest фикс: SL={S_GRID[si_b]*100:g}% TP={T_GRID[ti_b]*100:g}%")
print(f"best пропорц: a={A_GRID[best2[0][0]]} x={X_GRID[best2[0][1]]} "
      f"(средний стоп {np.mean([abs(float(t['entry'])-float(t['stop']))/float(t['entry']) for t in trades])*A_GRID[best2[0][0]]*100:.3f}%)")
lines.append("")
lines.append(f"### По годам: лучшая фикс-ячейка (SL {S_GRID[si_b]*100:g}% / TP {T_GRID[ti_b]*100:g}%)")
lines.append("")
lines.append("| год | n | WR | avgR |")
lines.append("|---|---|---|---|")
rs_b = np.array(acc[(si_b, ti_b)][0]); ks_b = acc[(si_b, ti_b)][1]
for y in (2024, 2025, 2026):
    idx = np.where(year_arr == y)[0]
    r_y = rs_b[idx]; k_y = [ks_b[i] for i in idx]
    tp = sum(1 for k in k_y if k == "tp")
    ln = f"| {y} | {len(r_y)} | {tp/len(r_y)*100:.1f}% | {r_y.mean():+.3f} |"
    lines.append(ln); print(ln)

# CSV
with open(os.path.join(OUT, "grid_sl_tp_fixed.csv"), "w", encoding="utf-8") as f:
    f.write("sl_pct,tp_pct,n,tp,sl,time,wr,avg,sr,ci\n")
    for si, s in enumerate(S_GRID):
        for ti, t in enumerate(T_GRID):
            a = mat[(si, ti)]
            f.write(f"{s},{t},{a['n']},{a['tp']},{a['sl']},{a['tm']},{a['wr']:.4f},"
                    f"{a['avg']:.4f},{a['sr']:.2f},{a['ci']:.4f}\n")
with open(os.path.join(OUT, "grid_sl_tp_prop.csv"), "w", encoding="utf-8") as f:
    f.write("a,x,n,tp,sl,time,wr,avg,sr,ci\n")
    for ai, a in enumerate(A_GRID):
        for xi, x in enumerate(X_GRID):
            ag = mat2[(ai, xi)]
            f.write(f"{a},{x},{ag['n']},{ag['tp']},{ag['sl']},{ag['tm']},{ag['wr']:.4f},"
                    f"{ag['avg']:.4f},{ag['sr']:.2f},{ag['ci']:.4f}\n")

with open(os.path.join(OUT, "report_grid.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\nsaved:", OUT)
