"""Политика инвалидации на РЕАЛЬНЫХ 7 wick-сделках живого (16–18.09).

Данные — из вывода live_class_split.py (уровень входа, close 30m-свечи входа) и
shadow_trades.json (стоп). Считаем R при выходе на close 30m-свечи (инвалидация)
против фактического R сделки.
"""
MAKER, TAKER = 0.00036, 0.0010
# sym, dir, level(вход), stop, close_30m_свечи_входа, факт_net
WICK = [
    ("ADA", "LONG", 0.1946, 0.1921, 0.1943, -0.9051),
    ("KAS", "LONG", 0.03253, 0.03207, 0.03247, -1.0932),
    ("ETH", "SHORT", 2387.67, 2429.98, 2407.28, -0.9120),
    ("LTC", "SHORT", 50.58, 51.32, 50.85, -1.0524),
    ("LINK", "SHORT", 11.084, 11.178, 11.139, -1.1244),
    ("XRP", "LONG", 1.3121, 1.2883, 1.2997, -0.5950),
    ("LTC", "SHORT", 53.56, 53.95, 53.61, -1.1580),
]
CONF = [
    ("BTC", "LONG", 75999.9, 75306.5, 76206.7, -0.6466),
    ("SOL", "SHORT", 97.24, 98.29, 97.23, +0.8269),
    ("DOGE", "LONG", 0.07924, 0.07824, 0.07952, +0.8395),
    ("BTC", "SHORT", 75681.0, 76529.1, 75604.8, -0.8639),
    ("ADA", "LONG", 0.1942, 0.1901, 0.1953, +0.3954),
    ("BNB", "SHORT", 724.0, 728.7, 723.4, -0.3749),
    ("LINK", "SHORT", 11.368, 11.428, 11.363, +0.7050),
]


def inv_r(row):
    sym, d, lvl, stop, c30, _ = row
    risk = abs(lvl - stop)
    sp = risk / lvl
    gross = (c30 - lvl) / risk if d == "LONG" else (lvl - c30) / risk
    return gross - (MAKER + TAKER) / sp


print(f"{'сделка':22s} {'класс':13s} {'факт R*':>9s} {'инвалидация R':>14s}")
tot_f = tot_i = 0.0
for grp, rows in (("wick_only", WICK), ("close_beyond", CONF)):
    for r in rows:
        ri = inv_r(r) if grp == "wick_only" else None
        tot_f += r[5]
        if ri is not None:
            tot_i += ri
        print(f"  {r[0]+' '+r[1]:20s} {grp:13s} {r[5]:+9.3f} " + (f"{ri:+14.3f}" if ri is not None else f"{'—':>14s}"))
print()
w_f = sum(r[5] for r in WICK)
w_i = sum(inv_r(r) for r in WICK)
c_f = sum(r[5] for r in CONF)
print(f"wick_only   (7 сделок): фактически {w_f:+.3f} R | с инвалидацией {w_i:+.3f} R")
print(f"close_beyond(7 сделок): фактически {c_f:+.3f} R")
print(f"ИТОГО: фактически {w_f+c_f:+.3f} R | с инвалидацией в wick-классе {w_i+c_f:+.3f} R")
