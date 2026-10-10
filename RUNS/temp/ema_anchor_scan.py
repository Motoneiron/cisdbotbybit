"""ema_anchor_scan.py — EMA slope-гейт с РАЗНЫМИ ЯКОРЯМИ на книге tf7-канона.

Якорь = момент, на который берётся последний ЗАКРЫТЫЙ 5m-бар (правило fail-open):
- created : created_ts (постановка лимитки) — контроль (как ema_span_scan)
- fl1h    : floor(created_ts, 1h)  — «первый бар часа»: состояние на входе в час
- fl4h    : floor(created_ts, 4h)  — «первый бар 4ч»: состояние на входе в 4ч-блок
- htf     : htf_time (граница HTF-блока tf7 ≈ 40 мин) — промежуточный
- entry   : entry_ts (вход; в боте НЕДОСТУПЕН заранее — контроль чувствительности)

Сетка: 5m-TF × span {5,8,13,21} × thr {0, 0.02%, 0.05%}; контроль 4h-TF на created/fl4h.
Запуск: python ema_anchor_scan.py            # 9 пар (без BTC)
        python ema_anchor_scan.py ADA,DOGE   # смоук-подмножество
"""
from __future__ import annotations

import glob
import pickle
import sys
import time

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
DEFAULT_PAIRS = ["ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]


def _src1m(s: str) -> str:
    import os
    p1 = rf"D:/databtcusdt/{s}USDT-1m/{s}USDT_1m_full_hdr.csv"
    p2 = rf"D:/databtcusdt/{s}USDT-1m-merged.csv"
    return p1 if os.path.exists(p1) else p2


SPANS = [5, 8, 13, 21]
THRS = [0.0, 0.0002, 0.0005]
TF_RULES = {"5m": ("5min", 5), "4h": ("4h", 240)}
TFS_ANCH = {"5m": ["created", "fl1h", "fl4h", "htf", "entry"],
            "4h": ["created", "fl4h"]}


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
    for c in ("created_ts", "entry_ts", "htf_time"):
        D[c] = pd.to_datetime(D[c])
    D["r"] = D["r_net_mexc"].astype(float)
    print(f"канон-книга: n={len(D)} avg={D.r.mean():+.4f} SR={D.r.sum():+.0f}", flush=True)

    anchors_full = {
        "created": D["created_ts"],
        "fl1h": D["created_ts"].dt.floor("1h"),
        "fl4h": D["created_ts"].dt.floor("4h"),
        "htf": D["htf_time"],
        "entry": D["entry_ts"],
    }

    feat_cols: dict[str, dict[str, pd.Series]] = {}
    for sym in pairs:
        t0 = time.time()
        df = pd.read_csv(_src1m(sym), usecols=["open_time", "close"])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df = df.set_index("open_time").sort_index()
        df = pd.DataFrame({"close": df["close"].resample("5min", label="left", closed="left").last().dropna()})
        sub_idx = D[D.sym == sym].index
        for tfname, (rule, mins) in TF_RULES.items():
            if mins == 5:
                c = df["close"]
            else:
                c = df["close"].resample(rule, label="left", closed="left").last().dropna()
            ct_arr = (c.index + pd.Timedelta(minutes=mins)).to_numpy()
            n = len(c)
            for aname in TFS_ANCH[tfname]:
                ft = anchors_full[aname].loc[sub_idx].to_numpy(dtype="datetime64[ns]")
                ii = np.searchsorted(ct_arr, ft, side="right") - 1
                good = (ii >= 0) & (ii < n)
                ip = np.clip(ii, 0, max(0, n - 1))
                for s in SPANS:
                    e = c.ewm(span=s, adjust=False, min_periods=s).mean()
                    sl = (e / e.shift(1) - 1.0).to_numpy(dtype=float)
                    v = np.where(good & (n > 0), sl[ip], np.nan)
                    feat_cols.setdefault(f"{tfname}_{aname}_{s}", {})[sym] = pd.Series(v, index=sub_idx)
        print(f"  [{sym}] фичи готовы ({time.time()-t0:.0f}s)", flush=True)

    for col, dct in feat_cols.items():
        D[col] = np.nan
        for sym, ser in dct.items():
            D.loc[ser.index, col] = ser.values
    print("фичи сшиты", flush=True)
    D.to_pickle(f"{BASE}/ema_anchor_feats.pkl")

    out: list[str] = []

    def p(line: str = "") -> None:
        print(line, flush=True)
        out.append(str(line))

    base_avg = D.r.mean()
    L = D.direction == "LONG"
    S = D.direction == "SHORT"
    p(f"\n=== БАЗА: n={len(D)} avg={base_avg:+.4f} SR={D.r.sum():+.0f} ===")
    p("Якоря: created=лимитка, fl1h/fl4h=начало часа/4ч, htf=граница HTF, entry=вход (в боте недоступен)")

    def cell(tfname: str, aname: str, s: int, thr: float):
        col = f"{tfname}_{aname}_{s}"
        v = D[col]
        ok = (L & (v > thr)) | (S & (v < -thr)) | v.isna()
        sk = D[~ok]
        ps = D[ok]
        ys = [sk[sk.year == y].r.sum() for y in sorted(D.year.unique()) if len(sk[sk.year == y]) >= 5]
        return dict(skip_n=len(sk), skip_sh=100 * len(sk) / len(D),
                    skip_avg=sk.r.mean() if len(sk) else np.nan,
                    pass_avg=ps.r.mean() if len(ps) else np.nan,
                    yneg=sum(1 for x in ys if x < 0), ytot=len(ys))

    p("\n=== ПОЛНАЯ ТАБЛИЦА (5m-TF): якорь × span × thr ===")
    p(f"{'якорь':>8}{'span':>5}{'thr%':>7}{'skip%':>7}{'skipavg':>9}{'passavg':>9}{'dPass':>9}{'yneg':>7}")
    for aname in TFS_ANCH["5m"]:
        for s in SPANS:
            for thr in THRS:
                c = cell("5m", aname, s, thr)
                p(f"{aname:>8}{s:>5}{100*thr:>7.2f}{c['skip_sh']:>7.1f}{c['skip_avg']:>+9.3f}"
                  f"{c['pass_avg']:>+9.3f}{c['pass_avg']-base_avg:>+9.4f}{int(c['yneg'])}/{int(c['ytot']):>2}")

    p("\n=== СРАВНЕНИЕ ЯКОРЕЙ (фикс span=8, thr=0.02%) ===")
    p(f"{'якорь':>8}{'skip%':>7}{'skipavg':>9}{'passavg':>9}{'yneg':>7}")
    for aname in TFS_ANCH["5m"]:
        c = cell("5m", aname, 8, 0.0002)
        p(f"{aname:>8}{c['skip_sh']:>7.1f}{c['skip_avg']:>+9.3f}{c['pass_avg']:>+9.3f}{int(c['yneg'])}/{int(c['ytot']):>2}")
    p("\n--- то же для span=13, thr=0.02% ---")
    for aname in TFS_ANCH["5m"]:
        c = cell("5m", aname, 13, 0.0002)
        p(f"{aname:>8}{c['skip_sh']:>7.1f}{c['skip_avg']:>+9.3f}{c['pass_avg']:>+9.3f}{int(c['yneg'])}/{int(c['ytot']):>2}")

    p("\n=== 4h-TF: создание vs fl4h (span=8, thr=0.02%) ===")
    for aname in TFS_ANCH["4h"]:
        c = cell("4h", aname, 8, 0.0002)
        p(f"{aname:>8}{c['skip_sh']:>7.1f}{c['skip_avg']:>+9.3f}{c['pass_avg']:>+9.3f}")

    p("\n=== ПО ГОДАМ: топ-3 клетки по passavg (skip>=15%) ===")
    cells = []
    for aname in TFS_ANCH["5m"]:
        for s in SPANS:
            for thr in THRS:
                c = cell("5m", aname, s, thr)
                if c["skip_sh"] >= 15:
                    cells.append((aname, s, thr, c))
    cells.sort(key=lambda x: -x[3]["pass_avg"])
    for aname, s, thr, c in cells[:3]:
        p(f"\n-- {aname} span={s} thr={100*thr:.2f}% (skip {c['skip_sh']:.1f}%, skipavg {c['skip_avg']:+.3f}, passavg {c['pass_avg']:+.3f})")
        for y in sorted(D.year.unique()):
            col = f"5m_{aname}_{s}"
            v = D[col]
            ok = (L & (v > thr)) | (S & (v < -thr)) | v.isna()
            sk = D[(~ok) & (D.year == y)]
            ps = D[ok & (D.year == y)]
            if len(sk) or len(ps):
                p(f"   {y}: skip n={len(sk):>4} avg={sk.r.mean() if len(sk) else np.nan:+.3f} | pass n={len(ps):>4} avg={ps.r.mean() if len(ps) else np.nan:+.3f}")

    open(f"{BASE}/ema_anchor_scan_out.txt", "w", encoding="utf-8").write("\n".join(out))
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
