"""Портфельная симуляция гейтов: cur (L≤-3+S≤0) vs new (L vd>0+S≤0).

Правила: 1 позиция/пара; лимит одновременных (по умолч. 7); риск 1% от баланса; $100.
События по минутам: в одну минуту сначала ВЫХОДЫ, потом ВХОДЫ. t_out <= t_in — мгновенные.
"""
import heapq

import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/gate_trades_timed.pkl")
tk = df[df.taken].copy()

CUR = ((tk.dir == "LONG") & (tk.vd <= -3)) | ((tk.dir == "SHORT") & (tk.vd <= 0))
NEW = ((tk.dir == "LONG") & (tk.vd > 0)) | ((tk.dir == "SHORT") & (tk.vd <= 0))


def portfolio(d, risk_pct=0.01, start=100.0, max_pos=None, one_per_pair=True):
    d = d.sort_values("t_in").reset_index(drop=True)
    # --- отбор (правила слотов) ---
    taken, skipped_pair, skipped_lim = [], 0, 0
    pair_end = {}
    open_heap = []
    max_conc = 0
    for _, row in d.iterrows():
        tin, tout, sym = int(row.t_in), int(row.t_out), row.sym
        while open_heap and open_heap[0] <= tin:
            heapq.heappop(open_heap)
        if one_per_pair:
            pe = pair_end.get(sym)
            if pe is not None and tin < pe:
                skipped_pair += 1
                continue
        if max_pos is not None and len(open_heap) >= max_pos:
            skipped_lim += 1
            continue
        taken.append(row)
        heapq.heappush(open_heap, tout)
        pair_end[sym] = tout
        max_conc = max(max_conc, len(open_heap))

    # --- баланс с реинвестом ---
    ev = []
    for idx, row in enumerate(taken):
        tin, tout = int(row.t_in), int(row.t_out)
        ev.append((tin, 1, idx))  # open
        if tout > tin:
            ev.append((tout, 0, idx))  # close
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    balance = start
    risks = {}
    curve = [(ev[0][0] if ev else 0, balance)]
    for t, kind, idx in ev:
        row = taken[idx]
        if kind == 0:
            if idx in risks:
                balance += risks.pop(idx) * float(row.r)
        else:
            rr = balance * risk_pct
            if int(row.t_out) <= int(row.t_in):
                balance += rr * float(row.r)
            else:
                risks[idx] = rr
        curve.append((t, balance))
    if risks:
        print("  ВНИМАНИЕ: незакрытые:", len(risks))
    s = pd.Series([c[1] for c in curve])
    cummax = s.cummax()
    mdd = float(((s - cummax) / cummax).min() * 100)
    stats = {"n": len(taken), "skip_pair": skipped_pair, "skip_lim": skipped_lim,
             "max_conc": max_conc, "left_open": len(risks)}
    return balance, mdd, stats


def report(name, d, **kw):
    final, mdd, st = portfolio(d, **kw)
    if len(d):
        yrs = (int(d.t_out.max()) - int(d.t_in.min())) / (60 * 24 * 365.25)
    else:
        yrs = 1
    cagr = (final / 100) ** (1 / yrs) - 1 if yrs > 0 else 0
    print(f"  {name:26} | n={st['n']:5d} | скип пара={st['skip_pair']:4d} лимит={st['skip_lim']:4d} "
          f"| макс~={st['max_conc']:2d} | финал ${final:>12,.0f} | x{final/100:>10,.0f} | CAGR {100*cagr:>5.1f}% | MaxDD {mdd:>6.1f}%")


print(f"=== сделок в базе: {len(tk)} | период: {tk.t_in.min()} .. {tk.t_out.max()} (минуты эпохи) ===")
print(f"cur гейт: {int(CUR.sum())} сд | new гейт: {int(NEW.sum())} сд")

print("\n--- БЕЗ ограничений (каждая сделка) ---")
report("cur: L≤-3+S≤0", tk[CUR], max_pos=None, one_per_pair=False)
report("new: L>0+S≤0", tk[NEW], max_pos=None, one_per_pair=False)

print("\n--- 1 позиция/пара ---")
report("cur", tk[CUR], one_per_pair=True)
report("new", tk[NEW], one_per_pair=True)

print("\n--- 1 поз/пара + лимит 7 (боевой) ---")
report("cur", tk[CUR], max_pos=7, one_per_pair=True)
report("new", tk[NEW], max_pos=7, one_per_pair=True)

print("\n--- new: чувствительность к лимиту ---")
for lim in (6, 8, 9, 10):
    report(f"new lim={lim}", tk[NEW], max_pos=lim, one_per_pair=True)

print("\n--- cur: лимит 7 vs без лимита (для сравнения) ---")
report("cur lim=8", tk[CUR], max_pos=8, one_per_pair=True)
