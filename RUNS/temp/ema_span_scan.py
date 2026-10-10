"""ema_span_scan.py — скрин трендовых EMA-гейтов (slope и pos) по span×ТФ на tf7-каноне.

Якорь: created_ts (момент постановки лимитки). Только ЗАКРЫТЫЕ бары:
- tag=incl: последний бар с close_time <= created_ts (конвенция NIGHT "исполнимая");
- tag=str : строгий вариант close_time < created_ts (контроль, "не попади в ловушку").

Книга: tf7_abl/ABL_MSS_MAIN_*.pkl (10 пар, 2020-26, LIMIT-филлы, r_net_mexc).
Фичи: slope=(EMA_s/EMA_s[-1]-1), pos=close/EMA_s-1 на 5m/15m/1h/4h, span in {2,3,5,8,13,21}.
Правило: LONG при slope>+thr; SHORT при slope<-thr; |slope|<=thr dead -> pass; NaN -> pass (fail-open),
как в TASK_slope_gate.md.

Запуск: python ema_span_scan.py            # все пары
        python ema_span_scan.py ADA,DOGE   # смоук на подмножестве
"""
from __future__ import annotations

import glob
import pickle
import sys
import time

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
ALL_PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]


def _src1m(s: str) -> str:
    import os
    p1 = rf"D:/databtcusdt/{s}USDT-1m/{s}USDT_1m_full_hdr.csv"
    p2 = rf"D:/databtcusdt/{s}USDT-1m-merged.csv"
    return p1 if os.path.exists(p1) else p2


C5 = {s: _src1m(s) for s in ALL_PAIRS}
TFS = {"5m": ("5min", 5), "15m": ("15min", 15), "1h": ("1h", 60), "4h": ("4h", 240)}
SPANS = [2, 3, 5, 8, 13, 21]
THRS = [0.0, 0.0002, 0.0005, 0.001]


def main() -> None:
    pairs = ALL_PAIRS
    suffix = "ALL"
    if len(sys.argv) > 1 and sys.argv[1].strip():
        pairs = [p.strip().upper() for p in sys.argv[1].split(",") if p.strip()]
        suffix = "_".join(pairs)

    rows = []
    for f in glob.glob(f"{BASE}/tf7_abl/ABL_MSS_MAIN_*.pkl"):
        rows += pickle.load(open(f, "rb"))
    D = pd.DataFrame(rows)
    D = D[D["entry_kind"] == "LIMIT"].copy()
    if suffix != "ALL":
        D = D[D.sym.isin(pairs)].copy()
    D["created_ts"] = pd.to_datetime(D["created_ts"])
    D["r"] = D["r_net_mexc"].astype(float)
    D["year"] = D["year"].astype(int)
    print(f"канон-книга: n={len(D)} avg={D.r.mean():+.4f} SR={D.r.sum():+.0f}", flush=True)

    feat_cols: dict[str, dict[str, pd.Series]] = {}
    for sym in pairs:
        if sym not in C5:
            print(f"  [{sym}] нет в списке пар", flush=True)
            continue
        t0 = time.time()
        df = pd.read_csv(C5[sym], usecols=["open_time", "close"])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df = df.set_index("open_time").sort_index()
        df = pd.DataFrame({"close": df["close"].resample("5min", label="left", closed="left").last().dropna()})
        sub = D[D.sym == sym]
        if not len(sub):
            continue
        idx = sub.index
        fts = sub["created_ts"].to_numpy(dtype="datetime64[ns]")
        for tfname, (rule, mins) in TFS.items():
            if mins == 5:
                c = df["close"]
            else:
                c = df["close"].resample(rule, label="left", closed="left").last().dropna()
            ct_arr = (c.index + pd.Timedelta(minutes=mins)).to_numpy()
            i_incl = np.searchsorted(ct_arr, fts, side="right") - 1
            i_str = np.searchsorted(ct_arr, fts, side="left") - 1
            n = len(c)
            for s in SPANS:
                e = c.ewm(span=s, adjust=False, min_periods=s).mean()
                sl = (e / e.shift(1) - 1.0).to_numpy(dtype=float)
                pos = (c / e - 1.0).to_numpy(dtype=float)
                for tag, ii in (("incl", i_incl), ("str", i_str)):
                    if n == 0:
                        v_s = np.full(len(idx), np.nan)
                        v_p = np.full(len(idx), np.nan)
                    else:
                        good = (ii >= 0) & (ii < n)
                        ip = np.clip(ii, 0, n - 1)
                        v_s = np.where(good, sl[ip], np.nan)
                        v_p = np.where(good, pos[ip], np.nan)
                    feat_cols.setdefault(f"s_{tfname}_{s}_{tag}", {})[sym] = pd.Series(v_s, index=idx)
                    feat_cols.setdefault(f"p_{tfname}_{s}_{tag}", {})[sym] = pd.Series(v_p, index=idx)
        print(f"  [{sym}] фичи готовы ({time.time()-t0:.0f}s, сделок {len(sub)})", flush=True)

    for col, dct in feat_cols.items():
        D[col] = np.nan
        for sym, ser in dct.items():
            D.loc[ser.index, col] = ser.values
    print("фичи сшиты", flush=True)
    D.to_pickle(f"{BASE}/ema_span_scan_feats_{suffix}.pkl")

    out: list[str] = []

    def p(line: str = "") -> None:
        print(line, flush=True)
        out.append(str(line))

    base_avg = D.r.mean()
    L = D.direction == "LONG"
    S = D.direction == "SHORT"
    p(f"\n=== БАЗА: n={len(D)} avg={base_avg:+.4f} SR={D.r.sum():+.0f} ===")

    def scan(prefix: str, thr_list: list[float]) -> pd.DataFrame:
        res = []
        for tfname in TFS:
            for s in SPANS:
                for tag in ("incl", "str"):
                    if tag == "str" and tfname not in ("5m", "4h"):
                        continue  # строгий контроль только для 5m/4h
                    col = f"{prefix}_{tfname}_{s}_{tag}"
                    v = D[col]
                    for thr in thr_list:
                        if prefix == "s":
                            ok = (L & (v > thr)) | (S & (v < -thr)) | v.isna()
                        else:
                            ok = (L & (v > thr)) | (S & (v < -thr)) | v.isna()
                        skip = ~ok
                        sk = D[skip]
                        ps = D[ok]
                        ys = []
                        for y in sorted(D.year.unique()):
                            ysk = sk[sk.year == y]
                            if len(ysk) >= 5:
                                ys.append(ysk.r.sum())
                        res.append(
                            dict(tf=tfname, span=s, tag=tag, thr=thr, skip_n=len(sk),
                                 skip_sh=100 * len(sk) / len(D),
                                 skip_avg=sk.r.mean() if len(sk) else np.nan,
                                 pass_avg=ps.r.mean() if len(ps) else np.nan,
                                 yneg=sum(1 for x in ys if x < 0), ytot=len(ys))
                        )
        return pd.DataFrame(res)

    R = scan("s", THRS)
    p("\n=== SLOPE-гейт: LONG slope>+thr / SHORT slope<-thr; dead(|s|<=thr) и NaN — pass ===")
    sub = R[(R.tag == "incl") & (R.skip_sh >= 10)].sort_values("pass_avg", ascending=False)
    p("\n--- топ-20 клеток по avg остатка (skip>=10%, tag=incl) ---")
    p(f"{'tf':4}{'span':>5}{'thr%':>7}{'skip%':>7}{'skipavg':>9}{'passavg':>9}{'dPass':>9}{'yneg':>7}")
    for _, r in sub.head(20).iterrows():
        p(f"{r.tf:4}{int(r.span):>5}{100*r.thr:>7.2f}{r.skip_sh:>7.1f}{r.skip_avg:>+9.3f}{r.pass_avg:>+9.3f}{r.pass_avg-base_avg:>+9.4f}{int(r.yneg)}/{int(r.ytot):>2}")
    p("\n--- худшие-5 (skip>=10%) ---")
    for _, r in sub.tail(5).iterrows():
        p(f"{r.tf:4}{int(r.span):>5}{100*r.thr:>7.2f}{r.skip_sh:>7.1f}{r.skip_avg:>+9.3f}{r.pass_avg:>+9.3f}{r.pass_avg-base_avg:>+9.4f}{int(r.yneg)}/{int(r.ytot):>2}")

    p("\n--- 5m: полные строки по thr ---")
    for s in SPANS:
        for thr in THRS:
            r = R[(R.tf == "5m") & (R.span == s) & (R.tag == "incl") & (R.thr == thr)]
            if len(r):
                r = r.iloc[0]
                p(f"  5m s={s:<3}{100*thr:>6.2f}% skip={r.skip_sh:>5.1f}% skipavg={r.skip_avg:>+8.3f} passavg={r.pass_avg:>+8.3f} d={r.pass_avg-base_avg:>+8.4f} yneg={int(r.yneg)}/{int(r.ytot)}")
    p("\n--- 4h: полные строки по thr ---")
    for s in SPANS:
        for thr in THRS:
            r = R[(R.tf == "4h") & (R.span == s) & (R.tag == "incl") & (R.thr == thr)]
            if len(r):
                r = r.iloc[0]
                p(f"  4h s={s:<3}{100*thr:>6.2f}% skip={r.skip_sh:>5.1f}% skipavg={r.skip_avg:>+8.3f} passavg={r.pass_avg:>+8.3f} d={r.pass_avg-base_avg:>+8.4f} yneg={int(r.yneg)}/{int(r.ytot)}")

    p("\n--- контроль якоря str vs incl (span=8, thr=0.02%) ---")
    for tfname in ("5m", "4h"):
        for tag in ("incl", "str"):
            r = R[(R.tf == tfname) & (R.span == 8) & (R.tag == tag) & (R.thr == 0.0002)]
            if len(r):
                r = r.iloc[0]
                p(f"  {tfname:4}{tag:>5}: skip%={r.skip_sh:.1f} skipavg={r.skip_avg:+.3f} passavg={r.pass_avg:+.3f}")

    Rp = scan("p", THRS)
    p("\n=== POS-гейт: LONG close>EMA / SHORT close<EMA (порог thr=0 для pos) ===")
    subp = Rp[(Rp.tag == "incl") & (Rp.skip_sh >= 10) & (Rp.thr == 0.0)].sort_values("pass_avg", ascending=False)
    for _, r in subp.head(12).iterrows():
        p(f"  {r.tf:4}{int(r.span):>5} skip={r.skip_sh:>5.1f}% skipavg={r.skip_avg:>+8.3f} passavg={r.pass_avg:>+8.3f} d={r.pass_avg-base_avg:>+8.4f} yneg={int(r.yneg)}/{int(r.ytot)}")

    open(f"{BASE}/ema_span_scan_out_{suffix}.txt", "w", encoding="utf-8").write("\n".join(out))
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
