"""Проверка маппинга trigger_idx -> глобальный индекс (окно 200 баров)."""
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf

CASES = [
    ("SOL", "SOL tf7 2024 (09-11)", r"D:/PYTHON/CISDBOT/RUNS/2026-09-11/bot_aligned/SOL_tf7_2024-01-01_2024-12-31.pkl", "5m", 5),
    ("SOL", "SOL tf8 2024 (09-11)", r"D:/PYTHON/CISDBOT/RUNS/2026-09-11/bot_aligned/SOL_tf8_2024-01-01_2024-12-31.pkl", "30m", 30),
    ("ADA", "ADA tf7 2023 (backup)", r"D:/PYTHON/CISDBOT/RUNS/backup_bot_aligned_before_filteroff/bot_aligned/ADA_tf7_2023-01-01_2023-12-31.pkl", "5m", 5),
]
for sym, label, path, tfc, mins in CASES:
    try:
        c = pickle.load(open(path, "rb"))
    except FileNotFoundError:
        print(label, ": нет файла")
        continue
    df, _ = load_ltf(tf=tfc, since="2023-01-01" if "2023" in path else "2024-01-01",
                     until="2023-12-31" if "2023" in path else "2024-12-31", symbol=sym)
    df.index = pd.DatetimeIndex(df.index)
    sigs = c.get("signals") or []
    n_ok = n_bad = n_na = n_shift = 0
    ex = []
    for s in sigs[:400]:
        sb, ti, tbt = s.get("scan_bar"), s.get("trigger_idx"), s.get("trigger_bar_time")
        if sb is None or ti is None or tbt is None:
            n_na += 1
            continue
        start = max(0, int(sb) - 199)
        gi = start + int(ti)
        t = pd.Timestamp(str(tbt)).floor(f"{mins}min")
        if 0 <= gi < len(df) and df.index[gi] == t:
            n_ok += 1
        else:
            # попробуем без -199 (ti как глобальный)
            g2 = int(ti)
            if 0 <= g2 < len(df) and df.index[g2] == t:
                n_shift += 1
            else:
                n_bad += 1
                if len(ex) < 5:
                    got = str(df.index[gi]) if 0 <= gi < len(df) else "OOR"
                    got2 = str(df.index[g2]) if 0 <= g2 < len(df) else "OOR"
                    ex.append(f"    t={t} (scan={sb} ti={ti}) window->{got} raw->{got2}")
    print(f"{label}: ok={n_ok} raw_ok={n_shift} bad={n_bad} na={n_na} / {len(sigs[:400])}")
    for e in ex:
        print(e)
