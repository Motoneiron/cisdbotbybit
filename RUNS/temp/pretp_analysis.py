"""Анализ pre-TP: сделки, где цена касалась TP-уровня ДО заполнения: исходы."""
import heapq
import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/gate_trades_timed3.pkl")
tk = df[df.taken].copy()
print(f"взятых: {len(tk)} | pre_tp: {int(tk.pre_tp.sum())} ({100*tk.pre_tp.mean():.1f}%)")

def stats(d, name):
    if not len(d):
        print(f"  {name}: пусто")
        return
    tp = int((d.out == "tp").sum()); sl = int((d.out == "sl").sum()); tm = int((d.out == "time").sum())
    wr = 100 * tp / max(1, tp + sl)
    print(f"  {name:22}: n={len(d):5d} | TP={tp:4d} SL={sl:4d} TIME={tm:3d} | WR={wr:5.1f}% | "
          f"ΣR={d.r.sum():+8.1f} | AvgR={d.r.mean():+.3f}")

print("\n=== ВСЕ (по всей истории) ===")
stats(tk[tk.pre_tp], "pre-TP БЫЛ")
stats(tk[~tk.pre_tp], "pre-TP НЕ был")

CUR = ((tk.dir == "LONG") & (tk.vd <= -3)) | ((tk.dir == "SHORT") & (tk.vd <= 0))
NEW = ((tk.dir == "LONG") & (tk.vd > 0)) | ((tk.dir == "SHORT") & (tk.vd <= 0))

for gname, mask in (("cur гейт", CUR), ("new гейт", NEW)):
    g = tk[mask]
    print(f"\n=== {gname} ===")
    stats(g[g.pre_tp], "pre-TP БЫЛ")
    stats(g[~g.pre_tp], "pre-TP НЕ был")
    for dr in ("LONG", "SHORT"):
        gd = g[g.dir == dr]
        print(f"  -- {dr}: pre-TP был:")
        stats(gd[gd.pre_tp], f"   {dr} pre-TP")
        stats(gd[~gd.pre_tp], f"   {dr} БЕЗ pre-TP")

# насколько «повторно» доходят до TP в pre-TP группе
g = tk[NEW]
p = g[g.pre_tp]
print(f"\n=== new: pre-TP группа: повторно дошли до TP: {int((p.out=='tp').sum())}/{len(p)} "
      f"({100*(p.out=='tp').mean():.1f}%), стоп: {int((p.out=='sl').sum())} "
      f"({100*(p.out=='sl').mean():.1f}%)")

# распределение «за сколько до заполнения» цепляли TP
if len(p):
    dt = (p.t_in - p.pre_tp_at) / 60  # в минутах
    print("за сколько минут до входа касались TP-уровня (p25/медиана/p75):",
          f"{dt.quantile(.25):.0f}/{dt.median():.0f}/{dt.quantile(.75):.0f} мин")

# портфель: эффект отмены pre-TP сделок (new)
def portfolio(d, max_pos=7):
    d = d.sort_values("t_in").reset_index(drop=True)
    taken, pair_end, heap = [], {}, []
    for row in d.itertuples():
        tin, tout, sym = int(row.t_in), int(row.t_out), row.sym
        while heap and heap[0] <= tin:
            heapq.heappop(heap)
        if sym in pair_end and tin < pair_end[sym]:
            continue
        if max_pos and len(heap) >= max_pos:
            continue
        taken.append(row)
        heapq.heappush(heap, tout)
        pair_end[sym] = tout
    ev = []
    for idx, row in enumerate(taken):
        tin, tout = int(row.t_in), int(row.t_out)
        ev.append((tin, 1, idx))
        if tout > tin:
            ev.append((tout, 0, idx))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    balance = 100.0
    risks = {}
    for t, kind, idx in ev:
        row = taken[idx]
        if kind == 0:
            if idx in risks:
                balance += risks.pop(idx) * float(row.r)
        else:
            rr = balance * 0.01
            if int(row.t_out) <= int(row.t_in):
                balance += rr * float(row.r)
            else:
                risks[idx] = rr
    return balance

f0 = portfolio(tk[NEW])
f1 = portfolio(tk[NEW & ~tk.pre_tp])
print(f"\nпортфель new: все ×{f0/100:,.0f} | без pre-TP ×{f1/100:,.0f}")
