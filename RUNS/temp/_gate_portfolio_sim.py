"""Портфельный сим гейтов на ЧИСТОМ контуре (stream_ungated_v2.pkl).

Логика 1:1 с portfolio_gate_sim.py (13.09, на котором принимался деплой):
1 позиция/пара; лимит одновременных 7; риск 1% от баланса; $100; события по минутам,
в одну минуту сначала ВЫХОДЫ, потом ВХОДЫ. Реинвест.
Варианты: без гейта / гейт confirm-якорь (как в боте) / гейт scan-якорь (старая калибровка).
Плюс по годам: баланс на конец года.
"""
import heapq

import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_ungated_v2.pkl")


def to_min(col):
    # юнит-безопасно (pandas 3.x: datetime64[us/s/ns] бывают разными): секунды → минуты
    return ((pd.to_datetime(col) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")


df["t_in"] = to_min(df.ts_fill)
df["t_out"] = to_min(df.exit_ts)
df = df[df.t_out > df.t_in].copy()

M_ALL = pd.Series(True, index=df.index)
M_CONF = ((df["dir"] == "SHORT") & (df.vd_conf <= 0)) | ((df["dir"] == "LONG") & (df.vd_conf >= 0))
M_SCAN = ((df["dir"] == "SHORT") & (df.vd_scan <= 0)) | ((df["dir"] == "LONG") & (df.vd_scan >= 0))


def portfolio(d, risk_pct=0.01, start=100.0, max_pos=7, one_per_pair=True):
    d = d.sort_values("t_in").reset_index(drop=True)
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

    ev = []
    for idx, row in enumerate(taken):
        tin, tout = int(row.t_in), int(row.t_out)
        ev.append((tin, 1, idx))
        if tout > tin:
            ev.append((tout, 0, idx))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    balance = start
    risks = {}
    curve = [(ev[0][0] if ev else 0, balance)]
    for t, kind, idx in ev:
        row = taken[idx]
        if kind == 0:
            if idx in risks:
                balance += risks.pop(idx) * float(row.r_net)
        else:
            rr = balance * risk_pct
            if int(row.t_out) <= int(row.t_in):
                balance += rr * float(row.r_net)
            else:
                risks[idx] = rr
        curve.append((t, balance))
    if risks:
        print("  ВНИМАНИЕ: незакрытых:", len(risks))
    s = pd.Series([c[1] for c in curve])
    cummax = s.cummax()
    mdd = float(((s - cummax) / cummax).min() * 100)
    cur = pd.DataFrame(curve, columns=["t", "bal"])
    cur["year"] = pd.to_datetime(cur.t, unit="m").dt.year
    yearly = cur.groupby("year")["bal"].last()
    stats = {"n": len(taken), "skip_pair": skipped_pair, "skip_lim": skipped_lim,
             "max_conc": max_conc, "left_open": len(risks)}
    return balance, mdd, stats, yearly


def report(name, d, **kw):
    final, mdd, st, yearly = portfolio(d, **kw)
    yrs = (int(d.t_out.max()) - int(d.t_in.min())) / (60 * 24 * 365.25) if len(d) else 1
    cagr = (final / 100) ** (1 / yrs) - 1 if yrs > 0 else 0
    print(f"  {name:24} | взято={st['n']:5d} | скип пара={st['skip_pair']:6d} лимит={st['skip_lim']:6d} "
          f"| макс.одн={st['max_conc']:2d} | финал ${final:>14,.0f} | x{final/100:>11,.1f} | CAGR {100*cagr:>6.1f}% | MaxDD {mdd:>6.1f}%")
    ytxt = " | ".join(f"{int(y)}:${v:,.0f}" for y, v in yearly.items())
    print(f"      по годам: {ytxt}")
    return final, mdd, st


print(f"=== база: {len(df)} заполненных сделок | период: {pd.to_datetime(df.t_in.min(), unit='m')} .. {pd.to_datetime(df.t_out.max(), unit='m')} ===")
print(f"  масок: all={int(M_ALL.sum())}, conf={int(M_CONF.sum())}, scan={int(M_SCAN.sum())}")

print("\n--- 1 поз/пара + лимит 7 (боевой конфиг), риск 1%, $100 ---")
r_all = report("БЕЗ гейта", df[M_ALL], max_pos=7, one_per_pair=True)
r_conf = report("гейт CONFIRM (деплой)", df[M_CONF], max_pos=7, one_per_pair=True)
r_scan = report("гейт SCAN (старый)", df[M_SCAN], max_pos=7, one_per_pair=True)

print("\n--- без лимита слотов (изолированное качество, без слотов) ---")
r_all2 = report("БЕЗ гейта", df[M_ALL], max_pos=None, one_per_pair=False)
r_conf2 = report("гейт CONFIRM", df[M_CONF], max_pos=None, one_per_pair=False)
