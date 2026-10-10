# progress_check.py — быстрый срез сетки выходов по готовым точкам.
import os
import pickle
import pandas as pd

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt"


def load_dir(root):
    rows = []
    for f in sorted(os.listdir(root)):
        if f.endswith(".pkl"):
            with open(os.path.join(root, f), "rb") as fh:
                rows += pickle.load(fh)
    return pd.DataFrame(rows)


for h in (2, 4, 6, 8, 10, 12, 14, 16):
    d = BASE + f"\\stopt_tf1v2_h{h}"
    if not os.path.isdir(d):
        continue
    df = load_dir(d)
    n = len(df)
    tp = int((df["outcome"] == "tp").sum())
    sl = int((df["outcome"] == "sl").sum())
    tm = int((df["outcome"] == "time").sum())
    print(f"h{h:>2}: n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} WR={tp/n*100:5.1f}% SR={df['r'].sum():+7.1f} avgR={df['r'].mean():+.3f}")
