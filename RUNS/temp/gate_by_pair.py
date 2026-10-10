"""По парам и ТФ: current (L≤-3+S≤0) vs new (L>0+S≤0). 9 пар из pkl."""
import pickle

import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/gate_grid_trades.pkl")
tk = df[df.taken].copy()
print("пар:", tk.sym.nunique(), "| сделок:", len(tk))

cur = ((tk.dir == "LONG") & (tk.vd <= -3)) | ((tk.dir == "SHORT") & (tk.vd <= 0))
new = ((tk.dir == "LONG") & (tk.vd > 0)) | ((tk.dir == "SHORT") & (tk.vd <= 0))

print("\n=== ПО ПАРАМ: current vs new ===")
tab = pd.DataFrame({
    "cur_n": tk[cur].groupby("sym").size(), "cur_R": tk[cur].groupby("sym").r.sum().round(0),
    "new_n": tk[new].groupby("sym").size(), "new_R": tk[new].groupby("sym").r.sum().round(0),
    "dWR_cur": tk[cur].groupby("sym").out.apply(lambda s: 100 * (s == "tp").sum() / max(1, (s.isin(["tp", "sl"])).sum())).round(1),
    "dWR_new": tk[new].groupby("sym").out.apply(lambda s: 100 * (s == "tp").sum() / max(1, (s.isin(["tp", "sl"])).sum())).round(1),
}).fillna(0)
print(tab.to_string())

print("\n=== ПО ТФ ===")
tab2 = pd.DataFrame({
    "cur_n": tk[cur].groupby("prof").size(), "cur_R": tk[cur].groupby("prof").r.sum().round(0),
    "new_n": tk[new].groupby("prof").size(), "new_R": tk[new].groupby("prof").r.sum().round(0),
})
print(tab2.to_string())

print("\n=== НЕВЗЯТЫЕ (нет тача в окне): доли ===")
for name, mask in (("cur", cur), ("new", new)):
    sub = tk[mask]
    d = df[(df.taken == False)]
    print(f"{name}: взято {len(sub)}; доля от базы {100*len(sub)/len(df):.1f}%")
# сколько добавленных сделок в new: их исходы
add_mask = new & ~cur
add = tk[add_mask & new]
added = tk[new & ~cur]
print(f"\nДобавленные new (не в cur): n={len(added)}, SumR={added.r.sum():+.1f}, "
      f"WR={100*(added.out=='tp').sum()/max(1,(added.out.isin(['tp','sl'])).sum()):.1f}%")
lost = tk[cur & ~new]
print(f"Потерянные из cur (не в new): n={len(lost)}, SumR={lost.r.sum():+.1f}, "
      f"WR={100*(lost.out=='tp').sum()/max(1,(lost.out.isin(['tp','sl'])).sum()):.1f}%")
