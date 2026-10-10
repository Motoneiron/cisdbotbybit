"""Примеры: cbt → created_bar → entry_bar → expire (tf8, SOL 2024)."""
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf

f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-12/bot_aligned/SOL_tf8_2024-01-01_2024-12-31.pkl"
ck = pickle.load(open(f, "rb"))
sigs = {str(s.get("hash")): s for s in ck.get("signals") or []}
trades = [t for t in ck.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
df, _ = load_ltf(tf="30m", since="2024-01-01", until="2024-12-31", symbol="SOL")
df.index = pd.DatetimeIndex(df.index)

print(" # | cbt     | created | entry   | expire  | cbt→cre | cre→ent | ent→exp")
for t in trades[:12]:
    s = sigs.get(str(t.get("hash")))
    if not s:
        continue
    cb = int(t["created_bar"]); eb = int(t["entry_bar"])
    exp_i = min(cb + 1, len(df) - 1)
    t_created = pd.Timestamp(df.index[cb])
    t_entry = pd.Timestamp(df.index[eb])
    t_expire = pd.Timestamp(df.index[exp_i]) + pd.Timedelta(minutes=30)
    cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
    print(f"   | {cbt:%d %H:%M} | {t_created:%d %H:%M} | {t_entry:%d %H:%M} | {t_expire:%d %H:%M} | "
          f"{(t_created-cbt).total_seconds()/60:6.0f} | {(t_entry-t_created).total_seconds()/60:6.0f} | "
          f"{(t_expire-t_entry).total_seconds()/60:6.0f}")

# и проверим: как далеко created от ближайшего вызова сетки (detect_step=2)
print("\nПроверка сетки: created_bar % 2 ==", [int(t['created_bar']) % 2 for t in trades[:12]])
