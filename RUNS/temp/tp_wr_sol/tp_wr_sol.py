"""tp_wr_sol.py — зависимость WR и экономики от TP (в R) на nofilter-потоке SOL.

Берём taken-строки прогона tf1v2_nofilter (все сделки без пользовательских фильтров
и гейта, busy-механика), профиль tf1: лимитка входа 1ч, позиция 16ч, комиссии Bybit
maker 0.036% / taker 0.10%. Для каждой сделки заново прорезаем 1m-путь и считаем
исход при TP = x*R для сетки x. Сверка: TP=1.0R обязан совпасть с полем r из прогона.
"""
import pickle, os, math
import numpy as np
import pandas as pd

MAKER, TAKER = 0.00036, 0.0010
LIMIT_MIN = 60          # таймаут кандидата: ожидание входа
POS_H = 16              # таймаут кандидата: позиция
TP_GRID = [0.1, 0.15, 0.2, 0.25, 0.33, 0.4, 0.5, 0.6, 0.66, 0.75, 0.8, 0.9, 1.0, 1.25, 1.5, 2.0]

CACHE = r"C:\Users\Motoneiron\.hermes\cache\scratch\sol1m_cache.npz"
PKL = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\rows_tf1v2_nofilter\SOL_{}.pkl"
OUT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\tp_wr_sol"
os.makedirs(OUT, exist_ok=True)

# ---------- 1m данные (кэш, ts в нс) ----------
z = np.load(CACHE)
ts = z["ts"]; high = z["high"]; low = z["low"]; close = z["close"]
print(f"1m bars: {len(ts)}  {pd.Timestamp(int(ts[0]))} .. {pd.Timestamp(int(ts[-1]))}")

# ---------- сделки ----------
trades = []
for y in (2024, 2025, 2026):
    rows = pickle.load(open(PKL.format(y), "rb"))
    for r in rows:
        if r.get("taken"):
            trades.append(r)
print(f"taken trades: {len(trades)}")

NS_MIN = 60 * 1_000_000_000
NS_LIM = LIMIT_MIN * NS_MIN
NS_POS = int(POS_H * 60) * NS_MIN

PRICES = np.array(TP_GRID)
n_tp = len(TP_GRID)
r_all = [[] for _ in TP_GRID]        # r net по сетке
kind_all = [[] for _ in TP_GRID]     # tp/sl/time
year_tot = []                        # год по сделке
sp_list = []
matched = mism = nofill = bad = 0
mm_examples = []
trade_records = []

for tr in trades:
    d = tr["direction"]; entry = float(tr["entry"]); stop = float(tr["stop"])
    risk = abs(entry - stop); sp = risk / entry
    scan = pd.Timestamp(tr["scan"]); scan_v = scan.value
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
    if d == "LONG":
        sl_mask = lo <= stop
    else:
        sl_mask = hi >= stop
    sl_i = int(sl_mask.argmax()) if sl_mask.any() else -1
    if d == "LONG":
        lv = entry + risk * PRICES
        mask = hi[:, None] >= lv[None, :]
    else:
        lv = entry - risk * PRICES
        mask = lo[:, None] <= lv[None, :]
    tp_first = np.where(mask.any(axis=0), mask.argmax(axis=0), -1)
    last_close = close[k1]
    gross_time = ((last_close - entry) / risk) if d == "LONG" else ((entry - last_close) / risk)

    rr, kk = [], []
    for xi in range(n_tp):
        x = TP_GRID[xi]
        ti = int(tp_first[xi])
        if ti >= 0 and (sl_i < 0 or ti < sl_i):
            kind, gross = "tp", x
        elif sl_i >= 0:
            kind, gross = "sl", -1.0
        else:
            kind, gross = "time", float(gross_time)
        fee_out = MAKER if kind == "tp" else TAKER
        r = gross - MAKER / sp - fee_out / sp
        rr.append(r); kk.append(kind)
    # --- сверка с pkl при TP=1.0 ---
    xi1 = TP_GRID.index(1.0)
    r_calc = rr[xi1]; kind_calc = kk[xi1]
    r_ref = tr.get("r"); kind_ref = tr.get("outcome")
    if r_ref is not None and abs(r_calc - r_ref) < 1e-6 and kind_calc == kind_ref:
        matched += 1
    else:
        mism += 1
        if len(mm_examples) < 10:
            mm_examples.append((tr["scan"], d, entry, stop, sp, kind_calc, round(r_calc, 4),
                                kind_ref, None if r_ref is None else round(r_ref, 4)))
    for xi in range(n_tp):
        r_all[xi].append(rr[xi]); kind_all[xi].append(kk[xi])
    year_tot.append(int(tr["scan"][:4])); sp_list.append(sp)
    trade_records.append((tr["scan"], d, entry, sp, *rr, *kk))

print(f"сверка TP=1R: matched={matched} mismatch={mism} nofill={nofill}")
for e in mm_examples:
    print("  MM:", e)

sp_arr = np.array(sp_list)
print(f"sp: медиана={np.median(sp_arr):.4f}  среднее={sp_arr.mean():.4f}  min={sp_arr.min():.4f} max={sp_arr.max():.4f}")
year_arr = np.array(year_tot)

# ---------- агрегаты ----------
def agg(rs, ks):
    rs = np.array(rs); n = len(rs)
    if n == 0: return None
    tp = sum(1 for k in ks if k == "tp"); sl = sum(1 for k in ks if k == "sl"); tm = n - tp - sl
    wr_tp = tp / n; wr_net = float((rs > 0).mean())
    ci = 1.96 * rs.std(ddof=1) / math.sqrt(n) if n > 1 else 0.0
    return dict(n=n, tp=tp, sl=sl, tm=tm, wr=wr_tp, wr_net=wr_net,
                sr=rs.sum(), avg=rs.mean(), ci=ci)

lines = []
lines.append("## TP-сетка на nofilter-потоке SOL (tf1: лимитка 1ч, позиция 16ч, Bybit maker/taker)")
lines.append("")
lines.append("| TP (R) | n | tp/sl/time | WR(tp) | WR(net>0) | ΣR | avgR | CI95 | BE-WR(нужен) |")
lines.append("|---|---|---|---|---|---|---|---|---|")
agg_rows = []
for xi, x in enumerate(TP_GRID):
    a = agg(r_all[xi], kind_all[xi])
    rs = np.asarray(r_all[xi]); ks = kind_all[xi]
    tp_mask = np.array([k == "tp" for k in ks])
    if tp_mask.any() and (~tp_mask).any():
        x_net = float(rs[tp_mask].mean()); L = float(rs[~tp_mask].mean())
        be = L / (L - x_net) if (L - x_net) != 0 else float("nan")
    else:
        be = float("nan")
    a["be"] = be
    agg_rows.append((x, a))
    lines.append(f"| {x} | {a['n']} | {a['tp']}/{a['sl']}/{a['tm']} | {a['wr']*100:.1f}% | "
                 f"{a['wr_net']*100:.1f}% | {a['sr']:.1f} | {a['avg']:+.3f} | ±{a['ci']:.3f} | {be*100:.1f}% |")
    print(lines[-1])

# по годам
lines.append("")
lines.append("### avgR по годам")
lines.append("")
years = (2024, 2025, 2026)
hdr = "| TP (R) | " + " | ".join(f"{y} avgR (n)" for y in years) + " |"
lines.append(hdr); lines.append("|---|" + "---|" * len(years))
for xi, x in enumerate(TP_GRID):
    cells = []
    for y in years:
        idx = np.where(year_arr == y)[0]
        rs = np.array(r_all[xi])[idx]; ks = [kind_all[xi][i] for i in idx]
        a = agg(rs, ks)
        cells.append(f"{a['avg']:+.3f} ({a['n']}) / WR {a['wr']*100:.0f}%")
    lines.append("| " + " | ".join([str(x)] + cells) + " |")
    print(lines[-1])

# где WR растёт / экономика
best_avg = max(agg_rows, key=lambda t: t[1]["avg"])
best_wr = max(agg_rows, key=lambda t: t[1]["wr"])
print(f"\nmax avgR: TP={best_avg[0]} avg={best_avg[1]['avg']:+.3f}")
print(f"max WR: TP={best_wr[0]} WR={best_wr[1]['wr']*100:.1f}%")

# CSV: агрегаты
with open(os.path.join(OUT, "agg_by_tp.csv"), "w", encoding="utf-8") as f:
    f.write("tp_r,n,tp,sl,time,wr_tp,wr_net,sr,avg,ci,be_wr\n")
    for x, a in agg_rows:
        f.write(f"{x},{a['n']},{a['tp']},{a['sl']},{a['tm']},{a['wr']:.4f},{a['wr_net']:.4f},"
                f"{a['sr']:.3f},{a['avg']:.4f},{a['ci']:.4f},{a['be']:.4f}\n")

# CSV: по сделкам
with open(os.path.join(OUT, "trades_tp.csv"), "w", encoding="utf-8") as f:
    f.write("scan,direction,entry,sp," + ",".join(f"r_{x}" for x in TP_GRID) + ","
            + ",".join(f"k_{x}" for x in TP_GRID) + "\n")
    for rec in trade_records:
        f.write(",".join(str(v) for v in rec) + "\n")

with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\nsaved:", OUT)
