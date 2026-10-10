"""trend_scan.py — перепроверка ЗАБРАКОВАННЫХ трендовых фильтров на честной книге tf7-канона.

Из SUMMARY_ALL_2026-09-21 (июльский NARRATIVE): ER, Chop, DI, linreg, Aroon были REJECT
(на старой базе/логике). Проверяем на книге tf7_abl с найденным лучшим якорем = created_ts.

Якорь: created_ts, только ЗАКРЫТЫЕ 5m-бары (close_time <= created_ts). NaN -> pass (fail-open).
Гейты (направленные — условие для LONG/SHORT; нейтральные — для обоих):
- ER(n)      : pass if ER > thr            (эффективность движения; n=10,20; thr 0.2/0.3/0.5)
- Chop(14)   : pass if CI < thr            (низкий CI = тренд; thr 38.2/50/61.8)
- ADX(14)    : pass if ADX > thr           (thr 20/25)
- DI(14)     : pass if +DI>-DI (LONG) или -DI>+DI (SHORT); вариант + ADX>20
- Aroon(14)  : pass if Up>Dn (LONG) / Dn>Up (SHORT); вариант + уровень 70
- linreg(n)  : pass if наклон/цена > +thr (LONG) или < -thr (SHORT); n=13,21; thr 0/0.02%/0.05%
Запуск: python trend_scan.py            # 9 пар (без BTC)
        python trend_scan.py ADA,DOGE   # смоук
"""
from __future__ import annotations

import glob
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
DEFAULT_PAIRS = ["ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]


def _src1m(s: str) -> str:
    p1 = rf"D:/databtcusdt/{s}USDT-1m/{s}USDT_1m_full_hdr.csv"
    p2 = rf"D:/databtcusdt/{s}USDT-1m-merged.csv"
    return p1 if os.path.exists(p1) else p2


def _rolling_dot(vals: np.ndarray, n: int) -> np.ndarray:
    """Σ i*v[t-n+1+i] для каждого окна (len = N-n+1)."""
    w = sliding_window_view(vals, n)
    return w @ np.arange(n, dtype=float)


def main() -> None:
    pairs = DEFAULT_PAIRS
    if len(sys.argv) > 1 and sys.argv[1].strip():
        pairs = [p.strip().upper() for p in sys.argv[1].split(",") if p.strip()]

    rows = []
    for f in glob.glob(f"{BASE}/tf7_abl/ABL_MSS_MAIN_*.pkl"):
        rows += pickle.load(open(f, "rb"))
    D = pd.DataFrame(rows)
    D = D[D["entry_kind"] == "LIMIT"].copy()
    D = D[D.sym.isin(pairs)].copy()
    D["created_ts"] = pd.to_datetime(D["created_ts"])
    D["r"] = D["r_net_mexc"].astype(float)
    print(f"канон-книга: n={len(D)} avg={D.r.mean():+.4f}", flush=True)

    feat: dict[str, dict[str, pd.Series]] = {}
    for sym in pairs:
        t0 = time.time()
        df = pd.read_csv(_src1m(sym), usecols=["open_time", "high", "low", "close"])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df = df.set_index("open_time").sort_index()
        agg = {"high": "max", "low": "min", "close": "last"}
        d5 = df.resample("5min", label="left", closed="left").agg(agg).dropna()
        idx = d5.index
        ct = (idx + pd.Timedelta(minutes=5)).to_numpy()
        sub_idx = D[D.sym == sym].index
        anchors = D.loc[sub_idx, "created_ts"].to_numpy(dtype="datetime64[ns]")
        pos = np.searchsorted(ct, anchors, side="right") - 1
        n_rows = len(d5)
        good = (pos >= 0) & (pos < n_rows)
        posc = np.clip(pos, 0, max(0, n_rows - 1))

        c = d5["close"].astype(float)
        h = d5["high"].astype(float)
        l = d5["low"].astype(float)
        tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / 14, adjust=False).mean()

        feats: dict[str, np.ndarray] = {}

        # ER(n)
        chg = c.diff().abs()
        for n in (10, 20):
            er = (c - c.shift(n)).abs() / chg.rolling(n).sum()
            feats[f"er{n}"] = er.to_numpy(dtype=float)

        # Chop(14)
        ci = 100 * np.log10(tr.rolling(14).sum() / (h.rolling(14).max() - l.rolling(14).min())) / np.log10(14)
        feats["chop14"] = ci.to_numpy(dtype=float)

        # ADX / DI (Wilder 14)
        up = h.diff()
        dn = -l.diff()
        pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=idx)
        mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=idx)
        pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
        mdi = 100 * mdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
        dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
        adx = dx.ewm(alpha=1 / 14, adjust=False).mean()
        feats["adx14"] = adx.to_numpy(dtype=float)
        feats["pdi"] = pdi.to_numpy(dtype=float)
        feats["mdi"] = mdi.to_numpy(dtype=float)

        # Aroon(14) — окно 15
        hv = h.to_numpy(dtype=float)
        lv = l.to_numpy(dtype=float)
        w_h = sliding_window_view(hv, 15)
        w_l = sliding_window_view(lv, 15)
        ar_up = np.full(n_rows, np.nan)
        ar_dn = np.full(n_rows, np.nan)
        ar_up[14:] = 100.0 * w_h.argmax(axis=1) / 14
        ar_dn[14:] = 100.0 * w_l.argmin(axis=1) / 14
        feats["ar_up"] = ar_up
        feats["ar_dn"] = ar_dn

        # linreg slope (нормированный, % на бар)
        cv = c.to_numpy(dtype=float)
        for n in (13, 21):
            x = np.arange(n, dtype=float)
            denom = n * (x ** 2).sum() - x.sum() ** 2
            sty = np.full(n_rows, np.nan)
            sty[n - 1:] = _rolling_dot(cv, n)
            sy = pd.Series(cv).rolling(n).sum().to_numpy()
            slope = (n * sty - x.sum() * sy) / denom
            feats[f"lr{n}"] = slope / cv * 100.0  # % на бар

        for k, v in feats.items():
            feat.setdefault(k, {})[sym] = pd.Series(v[posc] if True else v, index=sub_idx)
            if not good.all():
                s = feat[k][sym]
                s[~good] = np.nan
                feat[k][sym] = s
        print(f"  [{sym}] фичи готовы ({time.time()-t0:.0f}s)", flush=True)

    for col, dct in feat.items():
        D[col] = np.nan
        for sym, ser in dct.items():
            D.loc[ser.index, col] = ser.values
    print("фичи сшиты", flush=True)
    D.to_pickle(f"{BASE}/trend_scan_feats.pkl")

    out: list[str] = []

    def p(line: str = "") -> None:
        print(line, flush=True)
        out.append(str(line))

    base = D.r.mean()
    L = D.direction == "LONG"
    S = D.direction == "SHORT"
    p(f"\n=== БАЗА: n={len(D)} avg={base:+.4f} SR={D.r.sum():+.0f} ===")
    p("Якорь: created_ts (закрытые 5m-бары). Забракованные трендовые: ER / Chop / ADX / DI / Aroon / linreg.")

    def show(name: str, ok: pd.Series) -> None:
        sk = D[~ok]
        ps = D[ok]
        ys = [sk[sk.year == y].r.sum() for y in sorted(D.year.unique()) if len(sk[sk.year == y]) >= 5]
        p(f"{name:>22} skip={100*len(sk)/len(D):>5.1f}% skipavg={sk.r.mean() if len(sk) else np.nan:>+8.3f} "
          f"passavg={ps.r.mean() if len(ps) else np.nan:>+8.3f} d={ps.r.mean()-base:>+8.4f} yneg={sum(1 for x in ys if x < 0)}/{len(ys)}")

    def gate(name: str, col: str, mode: str, thr: float) -> None:
        v = D[col]
        if mode == "gt":      # нейтральный: pass if v > thr
            ok = (v > thr) | v.isna()
        elif mode == "lt":    # нейтральный: pass if v < thr
            ok = (v < thr) | v.isna()
        elif mode == "dir":   # направленный: L: v>thr / S: v<-thr
            ok = (L & (v > thr)) | (S & (v < -thr)) | v.isna()
        elif mode == "di":    # DI по направлению
            ok = (L & (D["pdi"] > D["mdi"])) | (S & (D["mdi"] > D["pdi"])) | D["pdi"].isna()
        elif mode == "di20":  # DI по направлению + ADX>20
            ok = ((L & (D["pdi"] > D["mdi"])) | (S & (D["mdi"] > D["pdi"]))) & (D["adx14"] > 20) | D["pdi"].isna()
        elif mode == "aroon":  # Up vs Down по направлению
            ok = (L & (D["ar_up"] > D["ar_dn"])) | (S & (D["ar_dn"] > D["ar_up"])) | D["ar_up"].isna()
        elif mode == "aroon70":  # направление + уровень 70
            ok = (L & (D["ar_up"] > D["ar_dn"]) & (D["ar_up"] > 70)) | \
                 (S & (D["ar_dn"] > D["ar_up"]) & (D["ar_dn"] > 70)) | D["ar_up"].isna()
        else:
            raise ValueError(mode)
        show(name, ok)

    p("\n=== КЛЕТКИ (sort по passavg) ===")
    results = []
    for n in (10, 20):
        for thr in (0.2, 0.3, 0.5):
            results.append((f"ER{n} > {thr}", f"er{n}", "gt", thr))
    for thr in (38.2, 50.0, 61.8):
        results.append((f"Chop14 < {thr}", "chop14", "lt", thr))
    for thr in (20.0, 25.0):
        results.append((f"ADX14 > {thr}", "adx14", "gt", thr))
    results.append(("DI направление", "pdi", "di", 0.0))
    results.append(("DI напр. + ADX>20", "pdi", "di20", 0.0))
    results.append(("Aroon Up/Dn", "ar_up", "aroon", 0.0))
    results.append(("Aroon + уровень 70", "ar_up", "aroon70", 0.0))
    for n in (13, 21):
        for thr in (0.0, 0.02, 0.05):
            results.append((f"linreg{n} |slope|>{thr}%", f"lr{n}", "dir", thr))

    # таблица
    for name, col, mode, thr in results:
        v = D[col]
        if mode == "gt":
            ok = (v > thr) | v.isna()
        elif mode == "lt":
            ok = (v < thr) | v.isna()
        elif mode == "dir":
            ok = (L & (v > thr)) | (S & (v < -thr)) | v.isna()
        elif mode == "di":
            ok = (L & (D["pdi"] > D["mdi"])) | (S & (D["mdi"] > D["pdi"])) | D["pdi"].isna()
        elif mode == "di20":
            ok = (((L & (D["pdi"] > D["mdi"])) | (S & (D["mdi"] > D["pdi"]))) & (D["adx14"] > 20)) | D["pdi"].isna()
        elif mode == "aroon":
            ok = (L & (D["ar_up"] > D["ar_dn"])) | (S & (D["ar_dn"] > D["ar_up"])) | D["ar_up"].isna()
        else:
            ok = (L & (D["ar_up"] > D["ar_dn"]) & (D["ar_up"] > 70)) | \
                 (S & (D["ar_dn"] > D["ar_up"]) & (D["ar_dn"] > 70)) | D["ar_up"].isna()
        show(name, ok)

    p("\n=== ТОП по чистоте отсечения (skipavg, только skip>=10%) ===")
    scored = []
    for name, col, mode, thr in results:
        v = D[col]
        if mode == "gt":
            ok = (v > thr) | v.isna()
        elif mode == "lt":
            ok = (v < thr) | v.isna()
        elif mode == "dir":
            ok = (L & (v > thr)) | (S & (v < -thr)) | v.isna()
        elif mode == "di":
            ok = (L & (D["pdi"] > D["mdi"])) | (S & (D["mdi"] > D["pdi"])) | D["pdi"].isna()
        elif mode == "di20":
            ok = (((L & (D["pdi"] > D["mdi"])) | (S & (D["mdi"] > D["pdi"]))) & (D["adx14"] > 20)) | D["pdi"].isna()
        elif mode == "aroon":
            ok = (L & (D["ar_up"] > D["ar_dn"])) | (S & (D["ar_dn"] > D["ar_up"])) | D["ar_up"].isna()
        else:
            ok = (L & (D["ar_up"] > D["ar_dn"]) & (D["ar_up"] > 70)) | \
                 (S & (D["ar_dn"] > D["ar_up"]) & (D["ar_dn"] > 70)) | D["ar_up"].isna()
        sk = D[~ok]
        if len(sk) >= 0.10 * len(D):
            ys = [sk[sk.year == y].r.sum() for y in sorted(D.year.unique()) if len(sk[sk.year == y]) >= 5]
            scored.append((sk.r.mean(), name, 100 * len(sk) / len(D), sk.r.mean(), D[ok].r.mean(), sum(1 for x in ys if x < 0), len(ys)))
    for s in sorted(scored):
        p(f"{s[1]:>22} skip={s[2]:>5.1f}% skipavg={s[3]:>+8.3f} passavg={s[4]:>+8.3f} yneg={s[5]}/{s[6]}")

    open(f"{BASE}/trend_scan_out.txt", "w", encoding="utf-8").write("\n".join(out))
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
