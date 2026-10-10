"""Цвет недельной/дневной свечи на момент сделки vs исходы (честная база tp_grid, hold 6).

Каузально: для каждой сделки берём цвет дневной (и недельной) свечи НА МОМЕНТ входа:
open периода vs close последнего 5м-бара <= момента (ts = cbt+30, момент решения).
Плюс: цвет предыдущей ЗАКРЫТОЙ свечи.
"""
import glob
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf  # noqa: E402

MAKER, TAKER = 0.00036, 0.0010

rows = []
for f in sorted(glob.glob("tp_grid/*.pkl")):
    rows.extend([r for r in pickle.load(open(f, "rb")) if r.get("hold") == 6])
df = pd.DataFrame(rows)
print("сделок (hold 6):", len(df), flush=True)
sp = df.stop_pct / 100
df["net"] = df["r_1.0"] - np.where(df["out_1.0"] == "tp", 2 * MAKER / sp, (MAKER + TAKER) / sp)
df["ts"] = pd.to_datetime(df.cbt) + pd.Timedelta(minutes=30)

res = []
for sym, g in df.groupby("sym"):
    try:
        d, _ = load_ltf(tf="5m", since="2020-01-01", until="2026-12-31", symbol=sym)
    except Exception as e:
        print(sym, "FAIL:", repr(e), flush=True)
        continue
    d = d.sort_index()
    d = d[~d.index.duplicated(keep="last")]
    cl = d["close"].to_numpy(dtype=float)
    cli = d.index
    g = g.copy()
    tsi = pd.Index(g.ts)
    j = cli.searchsorted(tsi, side="right") - 1
    jc = np.clip(j, 0, len(d) - 1)
    close_now = cl[jc]
    for rule, pref in (("W-MON", "w"), ("D", "dd")):
        o = d["open"].resample(rule, label="left", closed="left").first()
        cfull = d["close"].resample(rule, label="left", closed="left").last()
        up_full = (cfull > o).to_numpy()
        pos = o.index.searchsorted(tsi, side="right") - 1
        p = np.clip(pos, 0, len(o) - 1)
        g[pref + "_cur"] = close_now > o.to_numpy()[p]
        pp = np.clip(pos - 1, 0, len(o) - 1)
        g[pref + "_prev"] = np.where(pos >= 1, up_full[pp], np.nan)
    res.append(g)
    print(sym, "ok:", len(g), flush=True)

r = pd.concat(res, ignore_index=True)
r.to_pickle("wd_split.pkl")
print("сохранено:", len(r), flush=True)


def wr_avg(g):
    w = g[g["out_1.0"].isin(["tp", "sl"])]
    wr = 100 * (w["out_1.0"] == "tp").mean() if len(w) else np.nan
    return wr, g.net.mean(), g.net.sum()


print("\n=== ТЕКУЩАЯ дневная свеча на момент входа ===")
for dr in ("LONG", "SHORT"):
    for lbl, cond in (("D bullish", r.dd_cur == True), ("D bearish", r.dd_cur == False)):
        g = r[(r["dir"] == dr) & cond]
        wr, avg, s = wr_avg(g)
        print(f"  {dr} | {lbl}: n={len(g):>5} WR={wr:5.1f}% avg={avg:+.3f} S={s:+.0f}")

print("\n=== ТЕКУЩАЯ недельная свеча ===")
for dr in ("LONG", "SHORT"):
    for lbl, cond in (("W bullish", r.w_cur == True), ("W bearish", r.w_cur == False)):
        g = r[(r["dir"] == dr) & cond]
        wr, avg, s = wr_avg(g)
        print(f"  {dr} | {lbl}: n={len(g):>5} WR={wr:5.1f}% avg={avg:+.3f} S={s:+.0f}")

print("\n=== Согласованность (текущие D и W в сторону сделки) ===")
side_d = ((r["dir"] == "LONG") & (r.dd_cur == True)) | ((r["dir"] == "SHORT") & (r.dd_cur == False))
side_w = ((r["dir"] == "LONG") & (r.w_cur == True)) | ((r["dir"] == "SHORT") & (r.w_cur == False))
for name, mask in (
    ("D+W ЗА сделку", side_d & side_w),
    ("D за, W против", side_d & ~side_w),
    ("W за, D против", ~side_d & side_w),
    ("D+W ПРОТИВ", ~side_d & ~side_w),
):
    g = r[mask]
    wr, avg, s = wr_avg(g)
    print(f"  {name:>14}: n={len(g):>5} WR={wr:5.1f}% avg={avg:+.3f} S={s:+.0f}")

print("\n=== Последняя ЗАКРЫТАЯ дневная свеча ===")
for dr in ("LONG", "SHORT"):
    for lbl, cond in (("prevD bull", r.dd_prev == True), ("prevD bear", r.dd_prev == False)):
        g = r[(r["dir"] == dr) & cond]
        wr, avg, s = wr_avg(g)
        print(f"  {dr} | {lbl}: n={len(g):>5} WR={wr:5.1f}% avg={avg:+.3f} S={s:+.0f}")

print("\n=== Согласованность по годам (D+W за vs не за) ===")
ok = side_d & side_w
for y in sorted(r.year.unique()):
    gy = r[r.year == y]
    o = ok.reindex(gy.index)
    print(f"  {y}: D+W за: {gy[o].net.mean():+.3f} (n={int(o.sum())}) | "
          f"иначе: {gy[~o].net.mean():+.3f} (n={int((~o).sum())})")
