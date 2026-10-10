"""CVD v2: дивергенция, ускорение/наклон потока, поток на свипе и после свипа.

Первое поколение (`feat_cvd_elliott.py`) считало только дельту/объём за фиксированное
окно. Разделение значимое (t = 5,6 на 12ч), но размах асимметрии ≈0,21 R против
комиссии 0,116 R ⇒ ровно ноль. Здесь конструкции, у которых размах может быть больше.

Якорь решения — момент постановки лимитки: ceil_5m(cbt + 30м).
Причинность: минутный CVD-бар доступен с ts_ms + 60с, 30m-бар — с open + 30м,
поэтому всё режется по cut = якорь − 1 минута.

Важно про кэш CVD: он покрывает ~65% календарных дней (качались дни вокруг
сигналов). Поэтому нормировка «против распределения за 30 дней» невозможна —
все фичи считаются только по своему окну и остаются безразмерными. Пустое окно
даёт нулевую разность кумсумм, а не пропуск, поэтому везде проверяется объём.

Фичи (sgn = +1 LONG, −1 SHORT; «of» >0 = поток в сторону сделки):

  of_30m/1h/4h/12h   дельта/объём за окно до якоря, со знаком сделки
  push_1h/4h/12h     ход цены ПРОТИВ сделки за окно, в ATR (30m) — «на сколько
                     цену задрали перед нашим шортом»
  accel_4h/12h       of(вторая половина окна) − of(первая половина)
  slope_4h/12h       наклон CVD по минутам, нормированный на объём в минуту

  sw_of              поток на баре свипа (<0 = агрессия шла против нас и застряла)
  sw_of_last10       поток в последние 10 минут бара свипа (разворот внутри бара)
  sw_vol_z           объём бара свипа / медиана 48 предыдущих (по клайнам, не CVD)
  sw_range_atr       размах бара свипа в ATR
  sw_absorb          max(0, −sw_of) × sw_vol_z — «сила ловушки»

  post_of            поток от close бара свипа до якоря (фаза CISD/подтверждения)
  post_min           длительность этой фазы в минутах

Выход: RUNS/temp/feat_cvd_v2/<SYM>.pkl
Запуск: python feat_cvd_v2.py [workers=3]
"""
from __future__ import annotations

import glob
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
SRC = "D:/PYTHON/CISDBOT/RUNS/filters_off_full_aligned"
OUTDIR = f"{BASE}/feat_cvd_v2"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
OF_WINDOWS = {"30m": 30, "1h": 60, "4h": 240, "12h": 720}
PUSH_WINDOWS = {"1h": 60, "4h": 240, "12h": 720}
HALF_WINDOWS = {"4h": 240, "12h": 720}
MIN_MS = 60_000
BAR_MS = 30 * 60_000


def one(sym: str) -> str:
    dst = f"{OUTDIR}/{sym}.pkl"
    if os.path.exists(dst):
        return f"skip {sym}"
    t0 = time.time()
    from _cvd_load import load_cvd_minute
    from backtest.data import load_ltf
    from backtest.sweep_atr_filter import compute_atr14

    trades = []
    for f in glob.glob(f"{BASE}/tp_grid/{sym}_*.pkl"):
        for r in pickle.load(open(f, "rb")):
            if r.get("hold") == 6:
                trades.append(r)
    if not trades:
        return f"empty {sym}"
    sig_by_hash: dict[str, dict] = {}
    for f in glob.glob(f"{SRC}/{sym}_tf8_*.pkl"):
        for s in pickle.load(open(f, "rb")).get("signals") or []:
            sig_by_hash[str(s.get("hash"))] = s

    try:
        m = load_cvd_minute(sym)
    except Exception as e:
        return f"CVD FAIL {sym}: {e!r}"
    mt = m.ts_ms.to_numpy(np.int64)
    c_dlt = np.concatenate([[0.0], np.cumsum(m.delta.to_numpy(float))])
    c_vol = np.concatenate([[0.0], np.cumsum((m.buy + m.sell).to_numpy(float))])

    def of(a_ms: int, b_ms: int) -> float:
        """Дельта/объём в окне [a, b). NaN, если в кэше нет данных."""
        i0 = int(np.searchsorted(mt, a_ms, "left"))
        i1 = int(np.searchsorted(mt, b_ms, "left"))
        v = float(c_vol[i1] - c_vol[i0])
        if v <= 0:
            return np.nan
        return float(c_dlt[i1] - c_dlt[i0]) / v

    rows = []
    years = sorted({int(t["year"]) for t in trades})
    for year in years:
        yt = [t for t in trades if int(t["year"]) == year]
        try:
            d30, _ = load_ltf(
                tf="30m", since=f"{year - 1}-12-01", until=f"{year}-12-31", symbol=sym,
            )
        except Exception:
            continue
        d30.index = pd.DatetimeIndex(d30.index)
        atr_arr = compute_atr14(d30).to_numpy(float)
        open_ms = d30.index.astype("int64").to_numpy() // 1_000_000
        close_ms = open_ms + BAR_MS               # момент доступности бара
        cl = d30["close"].to_numpy(float)
        hi = d30["high"].to_numpy(float)
        lo = d30["low"].to_numpy(float)
        vol = (
            d30["volume"].to_numpy(float) if "volume" in d30.columns
            else np.full(len(d30), np.nan)
        )

        def last_closed(ts_ms: int) -> int:
            """Индекс последнего 30m-бара, закрытого к моменту ts_ms."""
            return int(np.searchsorted(close_ms, ts_ms, "right")) - 1

        for t in yt:
            h = str(t["hash"])
            s = sig_by_hash.get(h)
            cbt = pd.Timestamp(t["cbt"])
            anchor = (cbt + pd.Timedelta(minutes=30)).ceil("5min")
            a_ms = int(anchor.value // 1_000_000)
            cut = a_ms - MIN_MS
            sgn = -1.0 if t["dir"] == "SHORT" else 1.0
            row = {"hash": h, "sym": sym, "year": year}

            for lbl, mins in OF_WINDOWS.items():
                v = of(cut - mins * 60_000, cut)
                row[f"of_{lbl}"] = sgn * v if np.isfinite(v) else np.nan

            j = last_closed(cut)
            atr_j = atr_arr[j] if 0 <= j < len(atr_arr) else np.nan
            for lbl, mins in PUSH_WINDOWS.items():
                j0 = last_closed(cut - mins * 60_000)
                if j0 >= 0 and j > j0 and np.isfinite(atr_j) and atr_j > 0:
                    # >0 = за окно цену увели против нашей сделки
                    row[f"push_{lbl}"] = -sgn * float(cl[j] - cl[j0]) / atr_j
                else:
                    row[f"push_{lbl}"] = np.nan

            for lbl, mins in HALF_WINDOWS.items():
                w_ms = mins * 60_000
                half = w_ms // 2
                v2, v1 = of(cut - half, cut), of(cut - w_ms, cut - half)
                row[f"accel_{lbl}"] = (
                    sgn * (v2 - v1) if np.isfinite(v2) and np.isfinite(v1) else np.nan
                )
                i0 = int(np.searchsorted(mt, cut - w_ms, "left"))
                i1 = int(np.searchsorted(mt, cut, "left"))
                vv = float(c_vol[i1] - c_vol[i0])
                if i1 - i0 >= 10 and vv > 0:
                    seg = c_dlt[i0:i1 + 1] - c_dlt[i0]
                    sl = float(np.polyfit(np.arange(len(seg), dtype=float), seg, 1)[0])
                    row[f"slope_{lbl}"] = sgn * sl / (vv / (i1 - i0))
                else:
                    row[f"slope_{lbl}"] = np.nan

            tb = str((s or {}).get("trigger_bar_time") or "")
            if tb:
                sw0 = int(pd.Timestamp(tb).value // 1_000_000)
                sw1 = sw0 + BAR_MS
                if sw1 <= a_ms:                   # бар свипа закрыт до якоря
                    v = of(sw0, sw1)
                    row["sw_of"] = sgn * v if np.isfinite(v) else np.nan
                    v10 = of(sw1 - 10 * 60_000, sw1)
                    row["sw_of_last10"] = sgn * v10 if np.isfinite(v10) else np.nan
                    k = int(np.searchsorted(close_ms, sw1, "right")) - 1
                    if 48 <= k < len(vol):
                        med = float(np.nanmedian(vol[k - 48:k]))
                        row["sw_vol_z"] = vol[k] / med if med > 0 else np.nan
                        a_k = atr_arr[k]
                        if np.isfinite(a_k) and a_k > 0:
                            row["sw_range_atr"] = float((hi[k] - lo[k]) / a_k)
                        if np.isfinite(row["sw_of"]) and np.isfinite(row.get("sw_vol_z", np.nan)):
                            row["sw_absorb"] = max(0.0, -row["sw_of"]) * row["sw_vol_z"]
                    if cut > sw1:
                        pv = of(sw1, cut)
                        row["post_of"] = sgn * pv if np.isfinite(pv) else np.nan
                        row["post_min"] = (cut - sw1) / 60_000.0
            rows.append(row)
    pickle.dump(rows, open(dst + ".tmp", "wb"))
    os.replace(dst + ".tmp", dst)
    return f"OK {sym}: {len(rows)} строк sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    nworkers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    os.makedirs(OUTDIR, exist_ok=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nworkers) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, PAIRS), 1):
            print(f"[{i}/{len(PAIRS)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)
