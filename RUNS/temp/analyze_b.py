"""analyze_b.py — задача B: признаки плохих сделок.

Живые сделки 2024 (live_feats, keep-фильтр) классифицируются по канонным событиям
(canon_events): paired / reject_market / reject_other / accept_nofill / notseen.
Затем — сравнение фич классов: что отличает notseen (плохой) от paired.

Классификация: сначала по hash (если совпадают), иначе по времени cbt ± 2 мин / entry ± 6 мин.
"""
import os
import pickle

import numpy as np
import pandas as pd

LIVE = "live_feats"
CANON = "canon_events"
PAIRS = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]


def keep(r):
    sw, vol, soft = r.get("sw"), r.get("vol"), r.get("soft")
    if sw is None or not np.isfinite(sw) or sw < 0.40:
        return False
    if soft:
        return True
    return vol is not None and np.isfinite(vol) and vol <= 2.5


def load(sym):
    lp = f"{LIVE}/{sym}_2024.pkl"
    cp = f"{CANON}/{sym}_2024.pkl"
    if not (os.path.exists(lp) and os.path.exists(cp)):
        return None, None
    lrows = [r for r in pickle.load(open(lp, "rb")) if keep(r)]
    cev = pickle.load(open(cp, "rb"))
    return lrows, cev


def classify(sym, lrows, cev):
    sig_by_hash = {}
    sig_by_cbt = {}
    for s in cev["signals"]:
        sig_by_hash[s["hash"]] = s
        sig_by_cbt.setdefault((s["cbt"], s["direction"]), []).append(s)
    acc_by_hash = {}
    rej_by_hash = {}
    for d in cev["decisions"]:
        (acc_by_hash if d["accepted"] else rej_by_hash)[d["hash"]] = d
    trades = cev["trades"]
    tr_hashes = {t["hash"] for t in trades}
    tr_by_time = {}
    for t in trades:
        tr_by_time.setdefault(t["direction"], []).append(t)

    out = []
    for r in lrows:
        cls = None
        # 1) прямой мэтч по хэшу (полный или по префиксу)
        h = r.get("hash") or ""
        s = sig_by_hash.get(h)
        if s is None and h:
            for ch, cs in sig_by_hash.items():
                if ch and (ch.startswith(h[:10]) or h.startswith(ch[:10])):
                    s = cs
                    break
        src = "hash"
        if s is None:
            # 2) по времени: канонный сигнал с тем же cbt (±2 мин) и направлением
            cbt = pd.Timestamp(r["cbt"]) if r.get("cbt") else None
            if cbt is not None:
                for (cc, dd), arr in sig_by_cbt.items():
                    if dd != r["direction"]:
                        continue
                    try:
                        dt = abs((pd.Timestamp(cc) - cbt).total_seconds())
                    except Exception:
                        continue
                    if dt <= 120:
                        s = arr[0]
                        break
            src = "time"
        # 3) пары по времени исполнения (entry ±6 мин) — если канонный трейд рядом
        paired_time = False
        t0 = pd.Timestamp(r["scan"])
        for t in tr_by_time.get(r["direction"], []):
            try:
                dt = abs((pd.Timestamp(t["entry_ts"]) - t0).total_seconds())
            except Exception:
                continue
            if dt <= 360:
                paired_time = True
                break
        # определяем класс
        if s is not None and s["hash"] in tr_hashes:
            cls = "paired"
        elif paired_time:
            cls = "paired"
        elif s is not None:
            if s["hash"] in acc_by_hash:
                cls = "accept_nofill"
            elif s["fib"]:
                cls = "reject_market"
            else:
                cls = "reject_other"
        else:
            cls = "notseen"
        out.append({**r, "cls": cls, "src": src})
    return out


def desc(o, col):
    x = pd.to_numeric(o[col], errors="coerce")
    return f"{x.median():.3g}/{x.mean():.3g}" if len(x.dropna()) else "—"


def main():
    all_rows = []
    for sym in PAIRS:
        lrows, cev = load(sym)
        if lrows is None:
            print(f"{sym}: нет данных (feats={os.path.exists(f'{LIVE}/{sym}_2024.pkl')}, canon={os.path.exists(f'{CANON}/{sym}_2024.pkl')})")
            continue
        rows = classify(sym, lrows, cev)
        for r in rows:
            r["sym"] = sym
        all_rows.extend(rows)
        df = pd.DataFrame(rows)
        df["r"] = df["r"].astype(float)
        g = df.groupby("cls")["r"].agg(["count", "sum", "mean"])
        print(f"\n== {sym} ==")
        print(g.round(3).to_string())
    if not all_rows:
        return
    A = pd.DataFrame(all_rows)
    A["r"] = A["r"].astype(float)
    print("\n\n===== ВСЕ ПАРЫ 2024 =====")
    g = A.groupby("cls")["r"].agg(["count", "sum", "mean"])
    g["tp"] = A[A.outcome == "tp"].groupby("cls")["r"].count()
    print(g.round(3).to_string())

    print("\n----- фичи по классам (median/mean) -----")
    for col in ["sw", "vol", "touches", "sp", "lag_min", "trig_lag_min", "htf_lag_min",
                "qual", "entry", "stop"]:
        line = f"{col:14}"
        for cls in ["paired", "notseen", "reject_market"]:
            o = A[A.cls == cls]
            line += f" | {cls[:9]:>9}: {desc(o, col):>13}"
        print(line)

    print("\n----- булевы/категориальные -----")
    for col in ["soft", "late", "obc", "cos", "fib_mkt"]:
        line = f"{col:14}"
        for cls in ["paired", "notseen", "reject_market"]:
            o = A[A.cls == cls]
            if len(o) == 0:
                line += f" | {cls[:9]:>9}: {'—':>13}"
            else:
                line += f" | {cls[:9]:>9}: {o[col].mean():.2f}/{len(o):4}"
        print(line)
    for col in ["direction"]:
        line = f"{col:14}"
        for cls in ["paired", "notseen", "reject_market"]:
            o = A[A.cls == cls]
            if len(o) == 0:
                line += f" | {cls[:9]:>9}: {'—':>13}"
            else:
                line += f" | {cls[:9]:>9}: {dict(o[col].value_counts())}"
        print(line)

    print("\n----- lag_min по классам (гистограмма по 15 мин) -----")
    A["lag_bin"] = (pd.to_numeric(A["lag_min"], errors="coerce") // 15 * 15)
    for cls in ["paired", "notseen", "reject_market"]:
        o = A[A.cls == cls]
        vc = o["lag_bin"].value_counts().sort_index()
        print(f"  {cls:14}: " + ", ".join(f"{int(k)}:{v}" for k, v in vc.items()))

    print("\n----- час скана -----")
    A["hour"] = pd.to_datetime(A["scan"]).dt.hour
    for cls in ["paired", "notseen", "reject_market"]:
        o = A[A.cls == cls]
        vc = o["hour"].value_counts().sort_index()
        print(f"  {cls:14}: " + ", ".join(f"{int(k):02d}:{v}" for k, v in vc.items()))

    print("\n----- минута cbt (гипотеза: notseen = cbt не попал в окно :20-сканов) -----")
    A["cbt_minute"] = pd.to_datetime(A["cbt"]).dt.minute
    for cls in ["paired", "notseen", "reject_market"]:
        o = A[A.cls == cls]
        vc = o["cbt_minute"].value_counts().sort_index()
        print(f"  {cls:14}: " + ", ".join(f"{int(k):02d}:{v}" for k, v in vc.items()))

    print("\n----- scan−cbt (лаг бара скана от конф-бара), по 5 мин -----")
    A["lag5"] = (pd.to_numeric(A["lag_min"], errors="coerce") // 5 * 5)
    for cls in ["paired", "notseen", "reject_market"]:
        o = A[A.cls == cls]
        vc = o["lag5"].value_counts().sort_index()
        print(f"  {cls:14}: " + ", ".join(f"{int(k)}:{v}" for k, v in vc.items()))

    A.to_csv("analyze_b_rows.csv", index=False)
    print("\nsaved analyze_b_rows.csv")


if __name__ == "__main__":
    main()
