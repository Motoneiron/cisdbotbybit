"""Ценовые фичи к сделкам lv0 (один проход по LTF): дивергенция r vs flow, волатильность (24ч), Хёрст, EMA-HTФ.

Вход: stream_<SYM>_cvd.pkl (10 пар, есть of_1h_s, r_net, decision_at, dir, prof, sym, year)
Выход: stream_off_v1_lv0_v2_pf.pkl — колонки: r1_s, r4_s, vol24, vol_pct, hurst, ema10_ok, ema20_ok, ema_slope_s
Печать: таблицы по фичам (фит/OOS), симуляции сайзинга (волатильность), кроссы дивергенции, по годам.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]


def hurst_rs(x, lags=(8, 16, 32, 64, 128)):
    x = np.asarray(x, float)
    if len(x) < lags[-1] * 2:
        return np.nan
    lr = np.diff(np.log(x))
    pts = []
    for lag in lags:
        n = len(lr) // lag
        if n < 2:
            continue
        rs = []
        for k in range(n):
            seg = lr[k * lag:(k + 1) * lag]
            z = seg - seg.mean()
            s = z.std(ddof=0)
            if s <= 0:
                continue
            r = z.cumsum()
            rs.append((r.max() - r.min()) / s)
        if rs:
            pts.append((lag, float(np.mean(rs))))
    if len(pts) < 3:
        return np.nan
    lg = np.log([p[0] for p in pts])
    ls = np.log([p[1] for p in pts])
    return float(np.polyfit(lg, ls, 1)[0])


def main() -> None:
    df = pd.concat([pd.read_pickle(f"{BASE}/stream_{s}_cvd.pkl") for s in SYMS], ignore_index=True)
    for c in ["r1_s", "r4_s", "vol24", "vol_pct", "hurst", "ema10_ok", "ema20_ok", "ema_slope_s"]:
        df[c] = np.nan
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        rule = "4h" if prof == "tf7" else "8h"
        tfm = 5 if prof == "tf7" else 30
        try:
            dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
        except Exception as e:
            print(f"[{sym} {prof} {year}] load fail {e!r}", flush=True)
            continue
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        cl = dft["close"].to_numpy(float)
        # EMA на HTF (по закрытым бакетам)
        htf_close = dft["close"].resample(rule, label="left", closed="left").last().dropna()
        ema10 = htf_close.ewm(span=10, adjust=False).mean()
        ema20 = htf_close.ewm(span=20, adjust=False).mean()
        htf_idx_ms = (htf_close.index + pd.Timedelta(rule)).to_numpy()  # время ЗАКРЫТИЯ бакета
        # vol24: rolling std логредоходности
        lr = np.diff(np.log(cl), prepend=np.log(cl[0]))
        s_lr = pd.Series(lr, index=dft.index)
        win = 288 if tfm == 5 else 48
        vol24 = s_lr.rolling(win, min_periods=win // 2).std().to_numpy()
        win30 = win * 30
        for r_i, row in df.loc[idx].iterrows():
            dec = pd.Timestamp(str(row["decision_at"]))
            dec_np = np.datetime64(dec)
            i = int(np.searchsorted(ts, np.datetime64(dec - pd.Timedelta(minutes=tfm)), "right")) - 1  # последний ПОЛНОСТЬЮ закрытый бар
            if i < 0:
                continue
            i = min(i, len(cl) - 2)
            if i < 60:
                continue
            step1 = int(60 / tfm)
            step4 = int(240 / tfm)
            if i - step4 < 1:
                continue
            r1 = cl[i] / cl[i - step1] - 1.0
            r4 = cl[i] / cl[i - step4] - 1.0
            sgn = 1.0 if row["dir"] == "LONG" else -1.0
            df.at[r_i, "r1_s"] = r1 * sgn
            df.at[r_i, "r4_s"] = r4 * sgn
            v = vol24[i]
            if np.isfinite(v):
                df.at[r_i, "vol24"] = float(v)
                lo = max(0, i - win30)
                tra = vol24[lo:i]
                tra = tra[np.isfinite(tra)]
                if len(tra) > win30 // 4:
                    df.at[r_i, "vol_pct"] = float(100.0 * (tra < v).mean())
            if i >= 700:
                try:
                    df.at[r_i, "hurst"] = hurst_rs(cl[i - 719:i + 1])
                except Exception:
                    pass
            j = int(np.searchsorted(htf_idx_ms, dec_np, "right")) - 1  # последний ЗАКРЫТЫЙ htf-бакет
            if j >= 21:
                c_h = float(htf_close.iloc[j])
                e10 = float(ema10.iloc[j])
                e20 = float(ema20.iloc[j])
                if row["dir"] == "LONG":
                    df.at[r_i, "ema10_ok"] = 1.0 if c_h > e10 else 0.0
                    df.at[r_i, "ema20_ok"] = 1.0 if c_h > e20 else 0.0
                else:
                    df.at[r_i, "ema10_ok"] = 1.0 if c_h < e10 else 0.0
                    df.at[r_i, "ema20_ok"] = 1.0 if c_h < e20 else 0.0
                sl = (e10 - float(ema10.iloc[j - 1])) / max(c_h, 1e-12)
                df.at[r_i, "ema_slope_s"] = sl * (1.0 if row["dir"] == "LONG" else -1.0)
        print(f"[{sym} {prof} {int(year)}] done", flush=True)

    df.to_pickle(f"{BASE}/stream_off_v1_lv0_v2_pf.pkl")
    print("saved stream_off_v1_lv0_v2_pf.pkl", flush=True)

    def wr(g):
        d = g[g.outcome.isin(["tp", "sl"])]
        return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")

    fit = df[df.year <= 2023]
    oos = df[df.year >= 2024]

    def qtab(g, col, tag):
        gg = g[g[col].notna()]
        if len(gg) < 100:
            print(f"  {tag}: мало данных ({len(gg)})", flush=True)
            return
        gg = gg.copy()
        gg["q"] = pd.qcut(gg[col].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        out = " ".join(f"Q{q}:{wr(s):.0f}%/{s.r_net.mean():+.3f}" for q, s in gg.groupby("q", observed=True))
        print(f"  {tag} n={len(gg)} | {out}", flush=True)

    print("\n=== Дивергенция (r1_s / r4_s: цена за час/4ч в сторону сделки) ===", flush=True)
    for name, g in [("FIT", fit), ("OOS", oos)]:
        print(f" -- {name}", flush=True)
        qtab(g[g["dir"] == "LONG"], "r1_s", "LONG r1_s")
        qtab(g[g["dir"] == "SHORT"], "r1_s", "SHORT r1_s")
        qtab(g, "r4_s", "ALL r4_s")
    print("\n=== Кросс поток x цена (дивергенция): клетки ===", flush=True)
    for name, g in [("FIT", fit), ("OOS", oos)]:
        gg = g[g.of_1h_s.notna() & g.r1_s.notna()]
        print(f" -- {name} n={len(gg)}", flush=True)
        for fl_lbl, fl in [("flow<0", gg.of_1h_s < 0), ("flow>=0", gg.of_1h_s >= 0)]:
            for pr_lbl, pr in [("цена в сторону>0.2%", gg.r1_s > 0.002), ("цена против<-0.2%", gg.r1_s < -0.002), ("флэт", gg.r1_s.abs() <= 0.002)]:
                s = gg[fl & pr]
                if len(s):
                    print(f"    {fl_lbl:8s} x {pr_lbl:20s}: n={len(s):4d} WR={wr(s):4.1f}% avg={s.r_net.mean():+.3f}", flush=True)
    print("\n=== Волатильность (vol_pct) ===", flush=True)
    for name, g in [("FIT", fit), ("OOS", oos)]:
        print(f" -- {name}", flush=True)
        qtab(g, "vol_pct", "vol_pct")
    print(" -- симуляция (терцили фита: <33% → 0.7 | 33-67% → 1.0 | >67% → 1.3)", flush=True)
    vfit = fit[fit.vol_pct.notna()]
    t1, t2 = vfit.vol_pct.quantile(0.33), vfit.vol_pct.quantile(0.67)
    print(f"    терцили фита: {t1:.1f} / {t2:.1f}", flush=True)

    def w_vol(v):
        if not np.isfinite(v):
            return 1.0
        return 0.7 if v < t1 else (1.3 if v > t2 else 1.0)

    df["w_vol"] = df.vol_pct.map(w_vol)
    for name, mask in [("FIT", df.year <= 2023), ("OOS", df.year >= 2024), ("ALL", slice(None))]:
        g = df[mask]
        base = float((1 + 0.01 * g.r_net).prod())
        s = float((1 + 0.01 * g.w_vol * g.r_net).prod())
        print(f"    {name}: base={base:,.0f}x sized={s:,.0f}x → ×{s/base:.2f}", flush=True)
    print("\n=== Хёрст ===", flush=True)
    qtab(fit, "hurst", "FIT hurst")
    qtab(oos, "hurst", "OOS hurst")
    print("\n=== EMA10 / EMA20 / slope ===", flush=True)
    for name, g in [("FIT", fit), ("OOS", oos)]:
        for col in ("ema10_ok", "ema20_ok"):
            gg = g[g[col].notna()]
            if len(gg):
                ok = gg[gg[col] == 1]
                no = gg[gg[col] == 0]
                print(f"  {name} {col}: ok n={len(ok)} WR={wr(ok):.1f}% avg={ok.r_net.mean():+.3f} | no n={len(no)} WR={wr(no):.1f}% avg={no.r_net.mean():+.3f}", flush=True)
        qtab(g, "ema_slope_s", f"{name} slope_s")


if __name__ == "__main__":
    main()
