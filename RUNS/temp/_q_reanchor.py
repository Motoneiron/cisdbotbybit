"""РЕАНКОРИНГ: пересчёт фич lv0-стрима на ЯКОРЬ ЛАЙВА (from_ts = закрытие confirm-бара).

Проблема (найдено 14.09 вечер): фичи стрима (vd, of_1h, r1, kc, zz, kNN) считались на
decision_at = момент accept движка (detect_step; tf7 ≈ +26 мин, tf8 ≈ +60 мин после конфирма),
а филлы — на from_ts (confirm+5м). 96% филлов — ДО decision_at → фичи видели пост-входное
движение. Считаем те же фичи на from_ts и сравниваем с прежними.

Выход: _q_reanchor.pkl + сравнительные таблицы:
  1) согласие знака vd(старый) vs vd(новый) — масштаб сдвига деплой-гейта;
  2) градиент потока of_1h на новом якоре vs старый;
  3) r1/kc/chase на новом якоре (bands/клетка/карман).
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14
from backtest.vwap_filter import daily_session_vwap

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def zigzag(htf, atr, theta):
    pivots = []
    idx = htf.index
    h = htf["high"].to_numpy(float)
    l = htf["low"].to_numpy(float)
    c = htf["close"].to_numpy(float)
    a = atr.to_numpy(float)
    n = len(htf)
    if n < 3:
        return pivots
    dirn = 1 if c[1] >= c[0] else -1
    ext = h[1] if dirn == 1 else l[1]
    ext_i = 1
    for i in range(2, n):
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        if dirn == 1:
            if h[i] > ext:
                ext, ext_i = h[i], i
            elif (ext - l[i]) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "up"))
                dirn, ext, ext_i = -1, l[i], i
        else:
            if l[i] < ext:
                ext, ext_i = l[i], i
            elif (h[i] - ext) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "down"))
                dirn, ext, ext_i = 1, h[i], i
    return pivots


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def main() -> None:
    df = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_pf.pkl")
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    df["decision_at"] = pd.to_datetime(df["decision_at"])
    for c in ["vd_new", "of1_new_s", "r1_new_s", "kc_new_s", "chase_new"]:
        df[c] = np.nan

    # --- поток на новом якоре из минутных баз (быстро) ---
    for sym, idx in df.groupby("sym").groups.items():
        m = pd.read_pickle(f"{BASE}/cvd/{sym}USDT_minute.pkl").sort_values("ts_ms")
        ts = m.ts_ms.to_numpy(np.int64)
        dlt = m.delta.to_numpy(float)
        vol = (m.buy + m.sell).to_numpy(float)
        cd = np.concatenate([[0.0], np.cumsum(dlt)])
        cv = np.concatenate([[0.0], np.cumsum(vol)])
        for r_i, row in df.loc[idx].iterrows():
            t1 = int(row.from_ts.timestamp() * 1000)
            i0 = np.searchsorted(ts, t1 - 3600_000, "left")
            i1 = np.searchsorted(ts, t1, "left")
            v = cv[i1] - cv[i0]
            if v > 0:
                of = (cd[i1] - cd[i0]) / v
                df.at[r_i, "of1_new_s"] = of * (1.0 if row["dir"] == "LONG" else -1.0)
        print(f"[flow {sym}] done", flush=True)

    # --- ценовые фичи на новом якоре ---
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        rule = "4h" if prof == "tf7" else "8h"
        try:
            dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
        except Exception as e:
            print(f"[{sym} {prof} {year}] load fail {e!r}", flush=True)
            continue
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        c = dft["close"]
        cl = c.to_numpy(float)
        e20 = ema(c, 20).to_numpy(float)
        atr = compute_atr14(dft)
        av = atr.to_numpy(float)
        vwap = daily_session_vwap(dft).to_numpy(float)
        htf = pd.DataFrame({
            "high": dft["high"].resample(rule, label="left", closed="left").max(),
            "low": dft["low"].resample(rule, label="left", closed="left").min(),
            "close": c.resample(rule, label="left", closed="left").last(),
        }).dropna()
        htf_atr = compute_atr14(htf)
        for r_i, row in df.loc[idx].iterrows():
            fts = row.from_ts
            i = int(np.searchsorted(ts, np.datetime64(fts - pd.Timedelta(minutes=tfm)), "right")) - 1
            if i < 30:
                continue
            sgn = 1.0 if row["dir"] == "LONG" else -1.0
            if av[i] > 0 and np.isfinite(vwap[i]):
                df.at[r_i, "vd_new"] = (cl[i] - vwap[i]) / av[i]
            step1 = int(60 / tfm)
            if i - step1 >= 1 and cl[i - step1] > 0:
                df.at[r_i, "r1_new_s"] = (cl[i] / cl[i - step1] - 1.0) * sgn
            if av[i] > 0:
                df.at[r_i, "kc_new_s"] = ((cl[i] - e20[i]) / (1.5 * av[i])) * sgn
            # zz: закрытые бакеты
            hc = htf.loc[htf.index + pd.Timedelta(rule) <= fts]
            if len(hc) >= 3:
                piv = zigzag(hc, htf_atr.loc[hc.index], 1.5)
                if len(piv) >= 2:
                    pB, pA = piv[-1], piv[-2]
                    leg = abs(pB[2] - pA[2])
                    if leg > 0:
                        sl = dft.loc[(dft.index >= pB[0] + pd.Timedelta(rule)) & (dft.index <= fts)]
                        if not sl.empty:
                            if pB[3] == "up":
                                frac = (pB[2] - float(sl["low"].min())) / leg
                            else:
                                frac = (float(sl["high"].max()) - pB[2]) / leg
                            same = (pB[3] == "up" and row["dir"] == "LONG") or (pB[3] == "down" and row["dir"] == "SHORT")
                            df.at[r_i, "chase_new"] = 1.0 if (same and frac < 0.236) else 0.0
        print(f"[{sym} {prof} {int(year)}] done", flush=True)

    df.to_pickle(f"{BASE}/_q_reanchor.pkl")
    print("saved _q_reanchor.pkl", flush=True)

    # ============ СРАВНЕНИЯ ============
    print("\n=== 1) СОГЛАСИЕ vd: старый якорь (decision) vs новый (from_ts) ===", flush=True)
    ok_vd = df.vd.notna() & df.vd_new.notna()
    d = df[ok_vd]
    old_ok = ((d["dir"] == "SHORT") & (d.vd <= 0)) | ((d["dir"] == "LONG") & (d.vd >= 0))
    new_ok = ((d["dir"] == "SHORT") & (d.vd_new <= 0)) | ((d["dir"] == "LONG") & (d.vd_new >= 0))
    print(f"  n={len(d)} | вердикт гейта совпал: {100*(old_ok==new_ok).mean():.1f}% | старый PASS {100*old_ok.mean():.1f}% новый PASS {100*new_ok.mean():.1f}%", flush=True)
    print(f"  корреляция vd: {np.corrcoef(d.vd.rank(), d.vd_new.rank())[0,1]:.3f}", flush=True)
    print(f"  знак vd совпал: {100*((d.vd>0)==(d.vd_new>0)).mean():.1f}%", flush=True)

    print("\n=== 2) ПОТОК of_1h: старый якорь vs новый ===", flush=True)
    c = np.corrcoef(df.of_1h_s.rank(), df.of1_new_s.rank())[0, 1]
    print(f"  corr = {c:.3f}", flush=True)
    for tag, col in [("СТАРЫЙ", "of_1h_s"), ("НОВЫЙ", "of1_new_s")]:
        for dr in ("SHORT", "LONG"):
            g = df[(df["dir"] == dr) & df[col].notna()].copy()
            if len(g) < 500:
                continue
            g["q"] = pd.qcut(g[col].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
            line = " ".join(f"Q{q}:{wr(s):.0f}%/{s.r_net.mean():+.3f}" for q, s in g.groupby("q", observed=True))
            print(f"  {tag} {dr}: {line}", flush=True)

    print("\n=== 3) r1 / kc / chase на новом якоре ===", flush=True)
    fit = df[df.year <= 2023]
    for col, dr in [("r1_new_s", "SHORT"), ("r1_new_s", "LONG")]:
        g = df[(df["dir"] == dr) & df[col].notna()].copy()
        g["q"] = pd.qcut(g[col].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        line = " ".join(f"Q{q}:{wr(s):.0f}%/{s.r_net.mean():+.3f}" for q, s in g.groupby("q", observed=True))
        print(f"  {dr} {col}: {line}", flush=True)
    q1 = fit.r1_new_s.quantile(1 / 3)
    kcn = df.kc_new_s < 0
    r1l = df.r1_new_s < q1
    cell = kcn & r1l
    cdf = df[cell.fillna(False)]
    print(f"  KC-клетка (нов.): n={len(cdf)} WR={wr(cdf):.1f}% ΣR={cdf.r_net.sum():+.1f} avg={cdf.r_net.mean():+.3f}", flush=True)
    for y, g in df.groupby("year"):
        cc = g[(g.kc_new_s < 0) & (g.r1_new_s < q1)]
        if len(cc) >= 20:
            print(f"    {int(y)}: n={len(cc):4d} ΣR={cc.r_net.sum():+7.1f} avg={cc.r_net.mean():+.3f}", flush=True)
    ch = df[df.chase_new == 1.0]
    print(f"  chase (нов.): n={len(ch)} WR={wr(ch):.1f}% ΣR={ch.r_net.sum():+.1f} avg={ch.r_net.mean():+.3f}", flush=True)
    for y, g in df.groupby("year"):
        cc = g[g.chase_new == 1.0]
        if len(cc) >= 20:
            print(f"    {int(y)}: n={len(cc):4d} ΣR={cc.r_net.sum():+7.1f} avg={cc.r_net.mean():+.3f}", flush=True)


if __name__ == "__main__":
    main()
