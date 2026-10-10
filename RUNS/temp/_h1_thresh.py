import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")
import h1_4h_levers as L
import pandas as pd

raw = L.load_all()
df = L._attach(raw)
base = df[df.delay_min.notna() & (df.delay_min <= 60) & (df.delay_min >= -0.05)].copy()
base["sw"] = pd.to_numeric(base.sw, errors="coerce")
base["vol"] = pd.to_numeric(base.vol, errors="coerce")
col = "r_1.0_12"


def line(g, label):
    x = g.loc[g.year >= 2024, col].dropna()
    x3 = g.loc[g.year == 2023, col].dropna()
    a24 = x.mean() if len(x) else float("nan")
    a23 = x3.mean() if len(x3) else float("nan")
    print(
        f"{label:22} n24={len(x):5} avg24={a24:+.3f} sum24={x.sum():+.0f} "
        f"t={L._tstat(x):+.2f} n23={len(x3):4} avg23={a23:+.3f}"
    )


print("BASE")
line(base, "no filters")
print("GRID")
for a in (0.0, 0.15, 0.20, 0.25, 0.30, 0.40):
    for v in (99, 2.5, 2.0, 1.5, 1.2, 1.0):
        g = base[(base.sw >= a) & base.vol.notna() & (base.vol <= v)]
        x = g.loc[g.year >= 2024, col].dropna()
        if len(x) < 200:
            continue
        line(g, f"A>={a:.2f} V<={v:.1f}")
