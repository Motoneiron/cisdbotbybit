# dup_check.py — дублируют ли гейт lc и фильтр «≥2ч» друг друга (SOL/2025).
import pickle
import pandas as pd


def load(p):
    with open(p, "rb") as f:
        return pd.DataFrame(pickle.load(f))


def dt(df):
    return (pd.to_datetime(df["cbt"]) - pd.to_datetime(df["tbt"])).dt.total_seconds() / 60.0


BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt"

# 1) gated noatr (с гейтом, без dt-фильтра) — есть tbt
g = load(BASE + r"\stopt_tf1lc15_alloff_l1h\SOL_2025.pkl")
g["dt"] = dt(g)
print("GATED noatr (с гейтом):")
print(f"  всего n={len(g)} SR={g['r'].sum():+.1f}")
print(f"  dt<2ч : n={int((g['dt']<120).sum())} ({(g['dt']<120).mean()*100:.0f}%) SR={g[g['dt']<120]['r'].sum():+.1f}")
print(f"  dt>=2ч: n={int((g['dt']>=120).sum())} SR={g[g['dt']>=120]['r'].sum():+.1f}")

# 2) ng (без гейта, без dt) — новый прогон
try:
    m = load(BASE + r"\quick_tp_tf1ng_q\SOL_2025.pkl")
    m["dt"] = dt(m)
    print("\nNG (без гейта):")
    print(f"  всего n={len(m)} SR={m['r'].sum():+.1f}")
    print(f"  dt<2ч : n={int((m['dt']<120).sum())} ({(m['dt']<120).mean()*100:.0f}%) SR={m[m['dt']<120]['r'].sum():+.1f}")
    print(f"  dt>=2ч: n={int((m['dt']>=120).sum())} SR={m[m['dt']>=120]['r'].sum():+.1f}")
    print(f"  tp/sl/time всего: {int((m.outcome=='tp').sum())}/{int((m.outcome=='sl').sum())}/{int((m.outcome=='time').sum())}")
except Exception as e:
    print("NG MISSING:", e)

# 3) справка: v2 (с гейтом + dt)
v = load(BASE + r"\stopt_tf1v2\SOL_2025.pkl")
print(f"\nV2 (гейт+dt): n={len(v)} SR={v['r'].sum():+.1f}")
