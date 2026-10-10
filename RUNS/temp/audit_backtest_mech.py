"""Разбор механики fill в бэктесте: сделка 0 из SOL tf7 2024."""
import pickle
import glob
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

f = sorted(glob.glob(r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf7_2024*.pkl"))[-1]
c = pickle.load(open(f, "rb"))
df, _ = load_ltf(tf="5m", since="2024-01-01", until="2024-12-31", symbol="SOL")
df.index = pd.DatetimeIndex(df.index)

sigs = {str(s.get("hash")): s for s in c.get("signals") or []}

print("df бары 240-247:")
for i in range(240, 248):
    r = df.iloc[i]
    print(f"  [{i}] {df.index[i]}: O={r.open:.2f} H={r.high:.2f} L={r.low:.2f} C={r.close:.2f}")

print()
print("первые 3 сделки:")
for t in c["trades"][:3]:
    s = sigs.get(str(t.get("hash")))
    print(f"trade {t.get('hash')[:8]}: created_bar={t['created_bar']} entry_bar={t['entry_bar']} "
          f"entry_px={t['entry_px']:.2f} dir={t['direction']} outcome={t['outcome']}")
    if s:
        print(f"   signal: confirm_bar_time={s.get('confirm_bar_time')} confirm_idx={s.get('confirm_idx')} "
              f"confirm_timeframe={s.get('confirm_timeframe')}")
        print(f"   sweep_close_bar_time={s.get('sweep_close_bar_time')} sweep_close_idx={s.get('sweep_close_idx')} "
              f"sweep_confirm_5m_time={s.get('sweep_confirm_5m_time')}")
        print(f"   trigger_bar_time={s.get('trigger_bar_time')} trigger_idx={s.get('trigger_idx')} "
              f"scan_bar={s.get('scan_bar')} cisd={s.get('cisd_level')} stop={s.get('stop')}")
    eb = t["entry_bar"]
    if 0 <= eb < len(df):
        b = df.iloc[eb]
        print(f"   entry bar [{eb}] {df.index[eb]}: H={b.high:.2f} L={b.low:.2f} | entry_px={t['entry_px']:.2f} "
              f"| хит: SHORT high>=entry? {b.high >= t['entry_px']} / LONG low<=entry? {b.low <= t['entry_px']}")
    print()
