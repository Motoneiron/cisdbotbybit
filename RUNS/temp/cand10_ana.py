# cand10_ana.py — сводка нового кандидата: 10 пар (8 + AVAX + TON).
import pandas as pd

df = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_10par.pkl")
new = pd.read_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_new4.pkl")
c8 = df[~df["sym"].isin(["ETH", "BNB"])]
add = new[new["sym"].isin(["AVAX", "TON"])]
c10 = pd.concat([c8, add])


def summ(s):
    n = len(s)
    tp = int((s["outcome"] == "tp").sum())
    sl = int((s["outcome"] == "sl").sum())
    tm = int((s["outcome"] == "time").sum())
    return f"n={n:4d} tp={tp:3d} sl={sl:3d} time={tm:3d} WR={tp / n * 100:5.1f}% SR={s['r'].sum():+7.1f} avgR={s['r'].mean():+.3f}"


print("10 ПАР (SOL DOGE KAS ADA LINK LTC XRP BTC AVAX TON):", summ(c10))
print("сделок/день: {:.2f}".format(len(c10) / 974))
print()
for y, g in c10.groupby("year"):
    print(f"  {y}:", summ(g))
print()
print("по парам:")
for sym, g in c10.groupby("sym"):
    print(f"  {sym:5s}:", summ(g))
print()
for d, g in c10.groupby("direction"):
    print(f"{d:5s}:", summ(g))
c10.to_pickle(r"D:\PYTHON\cisdbotbybit\RUNS\temp\stopt_v2_10pairs_final.pkl")
print("\nsaved: stopt_v2_10pairs_final.pkl")
