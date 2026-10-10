"""Живой якорь: часы (freeze-списки из _q_time_freeze) + KC-позиция + KC-клетка (с r1).

Зачем: в архиве 14.09 это были кандидаты №1 (KC-клетка) и весовой слой (часы). Оба мерились
на заражённом якоре. Проверяем на from_ts: часы от from_ts (почти инвариантны к якорю),
kc_pos_s = ((close-EMA20)/(1.5*ATR14)) * sgn на последнем закрытом баре к from_ts.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
WEAK = [0, 3, 4, 5, 8, 23]
STRONG = [10, 13, 15, 19, 20, 21]


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def line(g, lbl, total=None):
    sh = f" ({100*len(g)/total:4.1f}%)" if total else ""
    return f"  {lbl:30}: n={len(g):6d} WR={wr(g):5.1f}% ΣR={g.r_net.sum():+8.1f} avg={g.r_net.mean():+.3f}{sh}"


def main():
    df = pd.read_pickle(f"{BASE}/stream_r1_live.pkl").copy()
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    df["hour"] = df.from_ts.dt.hour
    df["kc"] = np.nan
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        cl = dft["close"].to_numpy(float)
        e20 = dft["close"].ewm(span=20, adjust=False, min_periods=20).mean().to_numpy(float)
        atr = compute_atr14(dft).to_numpy(float)
        ii = np.searchsorted(ts, (df.loc[idx, "from_ts"] - pd.Timedelta(minutes=tfm)).to_numpy(), "right") - 1
        sgn = np.where(df.loc[idx, "dir"].to_numpy() == "LONG", 1.0, -1.0)
        good = (ii >= 30) & (ii < len(dft)) & np.isfinite(atr[np.clip(ii, 0, len(dft)-1)]) & (atr[np.clip(ii, 0, len(dft)-1)] > 0)
        pos = np.clip(np.where(good, ii, 0), 0, len(dft) - 1)
        df.loc[idx, "kc"] = np.where(good, ((cl[pos] - e20[pos]) / (1.5 * atr[pos])) * sgn, np.nan)
        print(f"  [{sym} {prof} {int(year)}] ok", flush=True)
    df.to_pickle(f"{BASE}/stream_hours_kc_live.pkl")

    t = len(df)
    print("\n=== ЧАСЫ (от from_ts, UTC) на живом якоре ===", flush=True)
    print(line(df[df.hour.isin(WEAK)], "слабые часы (freeze 2020-23)", t), flush=True)
    print(line(df[df.hour.isin(STRONG)], "сильные часы (freeze 2020-23)", t), flush=True)
    print("  по годам (сильные vs слабые):", flush=True)
    for y, g in df.groupby("year"):
        a = g[g.hour.isin(STRONG)]; b = g[g.hour.isin(WEAK)]
        print(f"    {int(y)}: сильные n={len(a):5d} WR={wr(a):5.1f}% avg={a.r_net.mean():+.3f} | "
              f"слабые n={len(b):5d} WR={wr(b):5.1f}% avg={b.r_net.mean():+.3f}", flush=True)
    print("  OOS 2024-26:", flush=True)
    g = df[df.year >= 2024]
    a = g[g.hour.isin(STRONG)]; b = g[g.hour.isin(WEAK)]
    print(f"    сильные: n={len(a)} WR={wr(a):.1f}% avg={a.r_net.mean():+.3f} | слабые: n={len(b)} WR={wr(b):.1f}% avg={b.r_net.mean():+.3f}", flush=True)
    print("  часы детально (avg):", flush=True)
    h = df.groupby("hour").agg(n=("r_net", "size"), wr=("outcome", lambda s: 100 * (s == "tp").sum() / max(1, (s.isin(["tp", "sl"])).sum())), avg=("r_net", "mean"))
    print("   " + " ".join(f"{int(i):02d}:{r.avg:+.3f}" for i, r in h.iterrows()), flush=True)

    print("\n=== KC-позиция (живой якорь) ===", flush=True)
    s = df[df.kc.notna()].copy()
    s["q"] = pd.qcut(s.kc.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    print("  квинтили: " + "  ".join(f"Q{q}:{wr(x):4.0f}%/{x.r_net.mean():+.3f}" for q, x in s.groupby("q", observed=True)), flush=True)
    for dr in ("LONG", "SHORT"):
        ss = s[s["dir"] == dr]
        print(f"  {dr}: " + "  ".join(f"Q{q}:{wr(x):4.0f}%/{x.r_net.mean():+.3f}" for q, x in ss.groupby("q", observed=True)), flush=True)

    print("\n=== KC-клетка (KC<0 & r1 ниже терцили фита) — архивный SKIP №1 ===", flush=True)
    fit = df[df.year <= 2023]
    q1 = fit.r1.quantile(1 / 3)
    print(f"  порог r1 (терциль 2020-23): {q1:+.4f}", flush=True)
    cell = (df.kc < 0) & (df.r1 < q1)
    print(line(df[cell], "KC<0 & r1-низ", t), flush=True)
    for y, g in df.groupby("year"):
        c = g[(g.kc < 0) & (g.r1 < q1)]
        if len(c) >= 20:
            print(f"    {int(y)}: n={len(c):4d} WR={wr(c):5.1f}% ΣR={c.r_net.sum():+8.1f} avg={c.r_net.mean():+.3f}", flush=True)
    print(line(df[(df.kc < 0) & ~(df.r1 < q1)], "KC<0, r1 норма", t), flush=True)
    print(line(df[(df.kc >= 0) & (df.r1 < q1)], "KC>=0, r1-низ", t), flush=True)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
