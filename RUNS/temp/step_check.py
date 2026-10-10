"""Проверка якоря канона: entry до created? сетка сканов? сетка филлов?"""
import pickle

import pandas as pd

for sym in ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]:
    try:
        rows = pickle.load(open(f"tf7_abl/ABL_MSS_MAIN_{sym}_2024.pkl", "rb"))
    except FileNotFoundError:
        print(sym, "нет файла")
        continue
    ct = pd.to_datetime([r["created_ts"] for r in rows])
    et = pd.to_datetime([r["entry_ts"] for r in rows])
    xt = pd.to_datetime([r["exit_ts"] for r in rows])
    n = len(rows)
    gap = (ct - et).total_seconds() / 60.0  # >0: entry раньше created
    print(f"{sym}: n={n}")
    print(f"   created минутные метки mod5: {sorted(set(ct.minute % 5))}  mod10: {sorted(set(ct.minute % 10))}")
    print(f"   entry   минутные метки mod5: {sorted(set(et.minute % 5))}  mod10: {sorted(set(et.minute % 10))}")
    print(f"   entry<created: {(gap > 0.5).mean():.1%} | entry==created(±0.5m): {(gap.abs() <= 0.5).mean():.1%} | entry>created: {(gap < -0.5).mean():.1%}")
    print(f"   gap (created-entry) медиана {gap.median():.0f} мин, среднее {gap.mean():.1f}")
    print(f"   gap>0 распределение: {pd.Series(gap[gap > 0.5].round(0)).value_counts().head(6).to_dict()}")
    # created - exit
    g2 = (xt - ct).total_seconds() / 60.0
    print(f"   exit>created: {(g2 > 0).mean():.1%} | exit<created: {(g2 < 0).mean():.1%}")
    print()
