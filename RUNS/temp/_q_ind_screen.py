"""Индикаторный скрин на lv0 (наследники «677-фазы»): MACD, KC, ADX, RSI, Stoch.

Считаем значения на LTF (5m/30m) в последнем ЗАКРЫТОМ баре до decision.
Фичи (в сторону сделки): macd_hist_s (sign×hist/close), kc_pos_s ((close-EMA20)/(1.5*ATR) × sign),
rsi_s (RSI-50 × sign), stoch_s ((%K-50)/50 × sign), adx (сырой), kc_mid_against (bool: LONG close>EMA20? и т.п.).
Таблицы фит/OOS + по годам для лучшего.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi_wilder(close, n=14):
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    au = up.ewm(alpha=1 / n, adjust=False).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr_wilder(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx_wilder(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm).ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    mdi = 100 * pd.Series(minus_dm).ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def main() -> None:
    df = pd.concat([pd.read_pickle(f"{BASE}/stream_{s}_cvd.pkl") for s in SYMS], ignore_index=True)
    for c in ["macd_hist_s", "kc_pos_s", "rsi_s", "stoch_s", "adx"]:
        df[c] = np.nan
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        try:
            dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
        except Exception as e:
            print(f"[{sym} {prof} {year}] load fail {e!r}", flush=True)
            continue
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        c = dft["close"]
        h = dft["high"]
        l = dft["low"]
        macd = ema(c, 12) - ema(c, 26)
        hist = macd - ema(macd, 9)
        e20 = ema(c, 20)
        atr = atr_wilder(h, l, c)
        rsi = rsi_wilder(c)
        ll = l.rolling(14).min()
        hh = h.rolling(14).max()
        kk = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
        stoch = kk.rolling(3).mean()
        adx = adx_wilder(h, l, c)
        arrs = {k: v.to_numpy(float) for k, v in {
            "hist": hist, "e20": e20, "atr": atr, "rsi": rsi, "stoch": stoch, "adx": adx, "close": c,
        }.items()}
        for r_i, row in df.loc[idx].iterrows():
            dec = pd.Timestamp(str(row["decision_at"]))
            i = int(np.searchsorted(ts, np.datetime64(dec - pd.Timedelta(minutes=tfm)), "right")) - 1
            if i < 30:
                continue
            sgn = 1.0 if row["dir"] == "LONG" else -1.0
            cl = arrs["close"][i]
            if np.isfinite(arrs["hist"][i]):
                df.at[r_i, "macd_hist_s"] = sgn * arrs["hist"][i] / max(cl, 1e-12)
            a = arrs["atr"][i]
            if np.isfinite(a) and a > 0:
                df.at[r_i, "kc_pos_s"] = sgn * (cl - arrs["e20"][i]) / (1.5 * a)
            if np.isfinite(arrs["rsi"][i]):
                df.at[r_i, "rsi_s"] = sgn * (arrs["rsi"][i] - 50.0)
            if np.isfinite(arrs["stoch"][i]):
                df.at[r_i, "stoch_s"] = sgn * (arrs["stoch"][i] - 50.0) / 50.0
            if np.isfinite(arrs["adx"][i]):
                df.at[r_i, "adx"] = arrs["adx"][i]
        print(f"[{sym} {prof} {int(year)}] done", flush=True)

    df.to_pickle(f"{BASE}/stream_off_v1_lv0_v2_ind.pkl")
    print("saved stream_off_v1_lv0_v2_ind.pkl", flush=True)

    def qtab(g, col, tag):
        gg = g[g[col].notna()]
        if len(gg) < 100:
            print(f"  {tag}: мало ({len(gg)})", flush=True)
            return
        gg = gg.copy()
        gg["q"] = pd.qcut(gg[col].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        out = " ".join(f"Q{q}:{wr(s):.0f}%/{s.r_net.mean():+.3f}" for q, s in gg.groupby("q", observed=True))
        print(f"  {tag} n={len(gg)} | {out}", flush=True)

    fit = df[df.year <= 2023]
    oos = df[df.year >= 2024]
    print("\n=== Индикаторный скрин (значения подписаны в сторону сделки) ===", flush=True)
    for name, g in [("FIT", fit), ("OOS", oos)]:
        print(f" -- {name}", flush=True)
        for col in ("macd_hist_s", "kc_pos_s", "rsi_s", "stoch_s", "adx"):
            qtab(g, col, col)
    print("\n=== Ключевые пороги-кандидаты (MACD>0, RSI в сторону, ADX>20, KC-позиция) ===", flush=True)
    for name, g in [("FIT", fit), ("OOS", oos)]:
        for lbl, m in [
            ("macd_hist_s>0", g.macd_hist_s > 0),
            ("rsi_s>0", g.rsi_s > 0),
            ("adx>20", g.adx > 20),
            ("kc_pos_s>0", g.kc_pos_s > 0),
            ("kc_pos_s<0", g.kc_pos_s < 0),
        ]:
            s = g[m.fillna(False)]
            ns = g[~m.fillna(False) & g.rsi_s.notna()]
            if len(s):
                print(f"  {name} {lbl}: n={len(s)} ({100*len(s)/max(1,len(g)):.0f}%) WR={wr(s):.1f}% avg={s.r_net.mean():+.3f}", flush=True)
    print("\n=== по годам: MACD>0 vs <0 ===", flush=True)
    for y, g in df[df.macd_hist_s.notna()].groupby("year"):
        a = g[g.macd_hist_s > 0]
        b = g[g.macd_hist_s <= 0]
        print(f"  {int(y)}: >0 n={len(a)} WR={wr(a):.1f}%/{a.r_net.mean():+.3f} | <=0 n={len(b)} WR={wr(b):.1f}%/{b.r_net.mean():+.3f}", flush=True)


if __name__ == "__main__":
    main()
