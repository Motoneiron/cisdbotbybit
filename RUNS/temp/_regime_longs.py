"""Почему лонги плохи: проверка режимной гипотезы + разбор сделок бота.

1) На research-потоке (54 368 сд, живой якорь) считаем РЕЖИМ рынка на from_ts:
   - trend_ema50_d: (close_d - EMA50_d)/EMA50_d по ДНЕВНЫМ закрытым свечам
   - ret7 / ret30: доходность пары за 7 / 30 дней до from_ts
   и раскладываем лонги/шорты по режиму: WR, ΣR, avg.
2) Отдельно — сделки tf7 по режиму (там основная боль).
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def main():
    df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl").copy()
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    df["trend"] = np.nan
    df["ret7"] = np.nan
    df["ret30"] = np.nan
    for (sym, year), _ in df.groupby(["sym", "year"]).groups.items():
        try:
            d30, _ = load_ltf(tf="30m", since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
        except Exception as e:
            print(f"  load fail {sym} {year}: {e!r}", flush=True); continue
        d30.index = pd.DatetimeIndex(d30.index)
        dd = pd.DataFrame({"close": d30["close"].resample("1D").last()}).dropna()
        e50 = dd["close"].ewm(span=50, adjust=False, min_periods=50).mean()
        idx = df.index[(df.sym == sym) & (df.year == year)]
        fts = df.loc[idx, "from_ts"]
        # последний ЗАКРЫТЫЙ день к from_ts
        di = np.searchsorted(dd.index.to_numpy(), fts.to_numpy(), "right") - 1
        good = (di >= 50) & (di < len(dd))
        pos = np.clip(np.where(good, di, 0), 0, len(dd) - 1)
        cl = dd["close"].to_numpy(float); e50a = e50.to_numpy(float)
        df.loc[idx, "trend"] = np.where(good & (e50a[pos] > 0), cl[pos] / e50a[pos] - 1.0, np.nan)
        c30 = d30["close"].to_numpy(float)
        i30 = np.searchsorted(d30.index.to_numpy(), fts.to_numpy(), "right") - 1
        for lag, col in ((7 * 48, "ret7"), (30 * 48, "ret30")):
            j = i30 - lag
            ok = (i30 > lag) & (j >= 0)
            pp = np.clip(np.where(ok, j, 0), 0, len(c30) - 1)
            qq = np.clip(np.where(ok, i30, 0), 0, len(c30) - 1)
            df.loc[idx, col] = np.where(ok & (c30[pp] > 0), c30[qq] / c30[pp] - 1.0, np.nan)
        print(f"  [{sym} {year}] ok", flush=True)
    df.to_pickle(f"{BASE}/stream_regime_live.pkl")

    t = len(df)
    print(f"\nрежим посчитан: trend {int(df.trend.notna().sum())}, ret30 {int(df.ret30.notna().sum())} из {t}", flush=True)
    print("\n=== ЛОНГИ по режиму (дневная свеча к EMA50) ===", flush=True)
    bins = [-1, -0.10, -0.03, 0.0, 0.03, 0.10, 10]
    lbl = ["<-10%", "-10..-3%", "-3..0%", "0..+3%", "3..10%", ">10%"]
    L = df[df["dir"] == "LONG"].copy()
    L["z"] = pd.cut(L.trend, bins=bins, labels=lbl)
    print(L.groupby("z", observed=True).apply(lambda g: pd.Series({"n": len(g), "WR": round(wr(g), 1), "ΣR": round(g.r_net.sum(), 1), "avg": round(g.r_net.mean(), 3)}), include_groups=False).to_string(), flush=True)
    print("\n=== ШОРТЫ по тому же режиму ===", flush=True)
    S = df[df["dir"] == "SHORT"].copy()
    S["z"] = pd.cut(S.trend, bins=bins, labels=lbl)
    print(S.groupby("z", observed=True).apply(lambda g: pd.Series({"n": len(g), "WR": round(wr(g), 1), "ΣR": round(g.r_net.sum(), 1), "avg": round(g.r_net.mean(), 3)}), include_groups=False).to_string(), flush=True)
    print("\n=== по годам: средний trend при входе в лонг и результат ===", flush=True)
    for y, g in L.groupby("year"):
        print(f"  {int(y)}: лонги n={len(g)} trend_med={g.trend.median()*100:+.1f}% WR={wr(g):.1f}% ΣR={g.r_net.sum():+7.1f}", flush=True)
    print("\n=== лонги: ret30 (30-дневная динамика) ===", flush=True)
    L["z30"] = pd.cut(L.ret30, bins=[-1, -0.15, -0.05, 0.0, 0.05, 0.15, 10], labels=["<-15%", "-15..-5%", "-5..0%", "0..+5%", "5..15%", ">15%"])
    print(L.groupby("z30", observed=True).apply(lambda g: pd.Series({"n": len(g), "WR": round(wr(g), 1), "ΣR": round(g.r_net.sum(), 1), "avg": round(g.r_net.mean(), 3)}), include_groups=False).to_string(), flush=True)
    print("\n=== tf7-лонги по режиму t50 ===", flush=True)
    L7 = L[L.prof == "tf7"]
    print(L7.groupby("z", observed=True).apply(lambda g: pd.Series({"n": len(g), "WR": round(wr(g), 1), "ΣR": round(g.r_net.sum(), 1), "avg": round(g.r_net.mean(), 3)}), include_groups=False).to_string(), flush=True)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
