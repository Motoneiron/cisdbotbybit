"""ЧЕСТНАЯ сетка vwap-гейта по зонам vd: LONG над VWAP vs под; SHORT под.

Модель: окно [ceil5(cbt+conf), +W минут] (tf7 W=20, tf8 W=30), min_stop 0.25%,
TP1R, комиссии, 1m. Все сделки (LIMIT) 10 пар 2020-2026. numpy-векторизация.
"""
import glob
import pickle
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14
from cryptofish.adapters.features import daily_session_vwap

MAKER = 0.00036
TAKER = 0.0010
MIN_STOP = 0.0025
NS_MIN = 60_000_000_000


def vd_at(df, i, vwap, atr):
    if i < 0 or i >= len(df):
        return None
    if pd.isna(atr.iloc[i]) or atr.iloc[i] <= 0:
        return None
    return (float(df.iloc[i]["close"]) - float(vwap.iloc[i])) / float(atr.iloc[i])


def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else \
        ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
    rows = []
    for sym in syms:
        # собираем кэши по годам
        all_files = sorted(glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_tf*_*.pkl"),
                           key=lambda p: p.replace("\\", "/"))
        best = {}
        for f in all_files:
            name = f.replace("\\", "/").split("/")[-1]
            m = re.match(rf"{sym}_(tf\d)_(\d{{4}})-\d{{2}}-\d{{2}}_.*\.pkl", name)
            if m:
                best[(m.group(1), m.group(2))] = f
        years = sorted({y for (_, y) in best.keys()})
        for year in years:
            df1 = None
            for prof in ("tf7", "tf8"):
                f = best.get((prof, year))
                if not f:
                    continue
                if prof == "tf8":
                    conf_min, pos_h, W, dft_tf = 5, 6, 30, "30m"
                else:
                    conf_min, pos_h, W, dft_tf = 1, 16, 20, "5m"
                try:
                    c = pickle.load(open(f, "rb"))
                except Exception:
                    continue
                sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
                trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
                if not trades:
                    continue
                dft, _ = load_ltf(tf=dft_tf, since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
                dft.index = pd.DatetimeIndex(dft.index)
                atr = compute_atr14(dft)
                vwap = daily_session_vwap(dft)
                if df1 is None:
                    df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
                    df1.index = pd.DatetimeIndex(df1.index)
                    # pandas 3 держит datetime в разных единицах (ms!) — приводим к нс явно
                    t1 = df1.index.to_numpy(dtype="datetime64[ns]").astype("int64") // NS_MIN
                    hi = df1["high"].to_numpy(dtype=float)
                    lo = df1["low"].to_numpy(dtype=float)
                    cl = df1["close"].to_numpy(dtype=float)
                for t in trades:
                    s = sigs.get(str(t.get("hash")))
                    if not s:
                        continue
                    sb = s.get("scan_bar")
                    i = int(sb) if sb is not None and 0 <= int(sb) < len(dft) else None
                    if i is None:
                        continue
                    vd = vd_at(dft, i, vwap, atr)
                    if vd is None:
                        continue
                    entry = float(t["entry_px"]); stop = float(t["stop"])
                    sp = abs(entry - stop) / entry
                    if sp < MIN_STOP:
                        continue
                    direction = t["direction"]
                    long = direction == "LONG"
                    cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
                    from_ts = (cbt + pd.Timedelta(minutes=conf_min)).ceil("5min")
                    m0 = from_ts.value // NS_MIN
                    i0 = int(np.searchsorted(t1, m0, "left"))
                    iN = int(np.searchsorted(t1, m0 + W, "left"))
                    taken = False
                    r = 0.0
                    out = "none"
                    if i0 < iN:
                        seg = lo[i0:iN] <= entry if long else hi[i0:iN] >= entry
                        if seg.any():
                            k = int(np.argmax(seg))
                            hit_i = i0 + k
                            taken = True
                            hit_m = int(t1[hit_i])
                            j1 = int(np.searchsorted(t1, hit_m + pos_h * 60, "right"))
                            s_lo = lo[hit_i:j1]; s_hi = hi[hit_i:j1]
                            tp1 = entry + (entry - stop) if long else entry - (stop - entry)
                            if long:
                                m_sl = s_lo <= stop
                                m_tp = s_hi >= tp1
                            else:
                                m_sl = s_hi >= stop
                                m_tp = s_lo <= tp1
                            i_sl = int(np.argmax(m_sl)) if m_sl.any() else 10**9
                            i_tp = int(np.argmax(m_tp)) if m_tp.any() else 10**9
                            if i_sl <= i_tp and i_sl != 10**9:
                                out, r = "sl", -1.0 - MAKER / sp - TAKER / sp
                            elif i_tp != 10**9:
                                out, r = "tp", 1.0 - 2 * MAKER / sp
                            else:
                                px = float(cl[j1 - 1] if j1 - 1 >= hit_i else cl[hit_i])
                                r = ((entry - px) / (entry - stop) if not long else (px - entry) / (entry - stop)) \
                                    - MAKER / sp - TAKER / sp
                                out = "time"
                    rows.append({"sym": sym, "prof": prof, "year": year, "dir": direction,
                                 "vd": float(vd), "sp": sp, "taken": taken, "out": out, "r": r})
        print(f"{sym}: done ({len(rows)} rows)", flush=True)

    df = pd.DataFrame(rows)
    df.to_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/gate_grid_trades.pkl")
    print("\n=== БАЗА ===", len(df), "сделок")

    tk = df[df.taken].copy()
    bins = [-100, -4, -3, -2, -1, 0, 1, 2, 3, 4, 100]
    lbls = ["≤-4", "-4..-3", "-3..-2", "-2..-1", "-1..0", "0..1", "1..2", "2..3", "3..4", ">4"]

    for dr in ("LONG", "SHORT"):
        d = tk[tk.dir == dr]
        d = d.assign(zone=pd.cut(d.vd, bins=bins, labels=lbls))
        g = d.groupby("zone", observed=True).agg(
            n=("r", "size"), wr=("out", lambda s: round(100 * (s == "tp").sum() / max(1, ((s == "tp").sum() + (s == "sl").sum())), 1)),
            sumr=("r", "sum"))
        print(f"\n=== {dr}: зоны vd (честные окна, min_stop, TP1R) ===")
        print(g.round(1).to_string())

    # варианты гейта
    print("\n=== ВАРИАНТЫ ГЕЙТА (сумма по всем годам) ===")
    variants = {
        "как сейчас: L vd≤-3 + S vd≤0": ((tk.dir == "LONG") & (tk.vd <= -3)) | ((tk.dir == "SHORT") & (tk.vd <= 0)),
        "L vd>0 + S vd≤0": ((tk.dir == "LONG") & (tk.vd > 0)) | ((tk.dir == "SHORT") & (tk.vd <= 0)),
        "L 0<vd≤2 + S vd≤0": ((tk.dir == "LONG") & (tk.vd > 0) & (tk.vd <= 2)) | ((tk.dir == "SHORT") & (tk.vd <= 0)),
        "L 0<vd≤4 + S vd≤0": ((tk.dir == "LONG") & (tk.vd > 0) & (tk.vd <= 4)) | ((tk.dir == "SHORT") & (tk.vd <= 0)),
        "L vd>4 + S vd≤0": ((tk.dir == "LONG") & (tk.vd > 4)) | ((tk.dir == "SHORT") & (tk.vd <= 0)),
        "L 0<vd≤4 + S vd≤1": ((tk.dir == "LONG") & (tk.vd > 0) & (tk.vd <= 4)) | ((tk.dir == "SHORT") & (tk.vd <= 1)),
        "L 0<vd≤4 + S vd≤-1": ((tk.dir == "LONG") & (tk.vd > 0) & (tk.vd <= 4)) | ((tk.dir == "SHORT") & (tk.vd <= -1)),
        "L все + S vd≤0": ((tk.dir == "LONG")) | ((tk.dir == "SHORT") & (tk.vd <= 0)),
    }
    for name, mask in variants.items():
        d = tk[mask]
        tp = int((d.out == "tp").sum()); sl = int((d.out == "sl").sum())
        wr = round(100 * tp / max(1, tp + sl), 1)
        print(f"  {name:34}: n={len(d):5d} WR={wr:5.1f}% SumR={d.r.sum():+8.1f}")

    # по годам для главного варианта и текущего
    print("\n=== ПО ГОДАМ: текущий vs L(vd>0..4)+S(vd≤0) ===")
    cur = ((tk.dir == "LONG") & (tk.vd <= -3)) | ((tk.dir == "SHORT") & (tk.vd <= 0))
    new = ((tk.dir == "LONG") & (tk.vd > 0) & (tk.vd <= 4)) | ((tk.dir == "SHORT") & (tk.vd <= 0))
    t = pd.DataFrame({
        "cur_n": tk[cur].groupby("year").size(), "cur_R": tk[cur].groupby("year").r.sum(),
        "new_n": tk[new].groupby("year").size(), "new_R": tk[new].groupby("year").r.sum(),
    }).fillna(0)
    print(t.round(1).to_string())


if __name__ == "__main__":
    main()
