"""Годовые доходности портфеля: cur vs new гейт (риск 1%, по сделкам)."""
import numpy as np
import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/gate_trades_timed.pkl")
tk = df[df.taken].copy()
CUR = ((tk.dir == "LONG") & (tk.vd <= -3)) | ((tk.dir == "SHORT") & (tk.vd <= 0))
NEW = ((tk.dir == "LONG") & (tk.vd > 0)) | ((tk.dir == "SHORT") & (tk.vd <= 0))

print("Годовые доходности (риск 1%, по сделкам, без ограничений слотов):")
print(f"{'год':>5} | {'cur n':>5} {'cur SumR':>9} {'cur xгод':>9} | {'new n':>5} {'new SumR':>9} {'new xгод':>9}")
for year in sorted(tk.year.unique()):
    dc = tk[CUR & (tk.year == year)]
    dn = tk[NEW & (tk.year == year)]
    fc = np.exp(np.log1p(0.01 * dc.r).sum())
    fn = np.exp(np.log1p(0.01 * dn.r).sum())
    print(f"{year:>5} | {len(dc):>5} {dc.r.sum():>+9.1f} {fc:>8.2f}x | {len(dn):>5} {dn.r.sum():>+9.1f} {fn:>8.2f}x")

dc = tk[CUR]; dn = tk[NEW]
print(f"\nAvgR: cur {dc.r.mean():+.3f} | new {dn.r.mean():+.3f}")
print(f"Сделок/день: cur {len(dc)/2448:.2f} | new {len(dn)/2448:.2f}")
