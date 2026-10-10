# time_slices.py — срезы time-сделок кандидата (10 пар, TP=1R).
import pandas as pd

df = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_10p_tp1.pkl")
t = df[df["outcome"] == "time"]
print("time всего:", len(t), "| сумма:", round(t["r"].sum(), 1), "| avg:", round(t["r"].mean(), 3))
print("\nраспределение r (time):")
bins = [-1.1, -0.5, -0.2, 0.0, 0.2, 0.5, 0.9]
labels = ["< -0.5", "-0.5..-0.2", "-0.2..0", "0..+0.2", "+0.2..+0.5", "+0.5..+0.85"]
t2 = t.copy()
t2["bin"] = pd.cut(t2["r"], bins=bins, labels=labels)
g = t2.groupby("bin", observed=True).agg(n=("r", "size"), sumR=("r", "sum")).round(1)
print(g.to_string())
print("\nпо парам:")
rows = []
for sym, g_ in df.groupby("sym"):
    tt = g_[g_["outcome"] == "time"]
    rows.append({
        "sym": sym,
        "n_all": len(g_),
        "n_time": len(tt),
        "pct_time": round(len(tt) / len(g_) * 100, 1),
        "sum_time": round(tt["r"].sum(), 1),
        "avg_time": round(tt["r"].mean(), 3) if len(tt) else 0,
    })
print(pd.DataFrame(rows).to_string(index=False))
print("\nпо годам:")
for y, g_ in df.groupby("year"):
    tt = g_[g_["outcome"] == "time"]
    print(f"  {y}: n_time={len(tt)} ({len(tt)/len(g_)*100:.0f}%) sum={tt['r'].sum():+.1f} avg={tt['r'].mean():+.3f}")
