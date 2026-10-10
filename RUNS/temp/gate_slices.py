"""Срезы классов гейта свипа: что будет, если торговать ТОЛЬКО провалившие проверку окном."""
import numpy as np
import pandas as pd

d = pd.read_pickle("gate_emul_rows.pkl")
d["htf"] = pd.to_datetime(d.htf)
print("диапазон данных:", d.htf.min(), "->", d.htf.max())
for y in [2023, 2024, 2025, 2026]:
    q = d[d.year == y]
    if len(q) == 0:
        continue
    days = (q.htf.max().normalize() - q.htf.min().normalize()).days + 1
    print(f"  {y}: сделок {len(q)}, дней {days}")

YEARD = {2023: 365, 2024: 366, 2025: 365, 2026: 174}
ALL = 365 + 366 + 365 + 174


def stat(name, q, days):
    n = len(q)
    if n == 0:
        print(name, "n=0")
        return
    tp = 100 * (q.outcome == "tp").mean()
    sl = 100 * (q.outcome == "sl").mean()
    tm = 100 * (q.outcome == "time").mean()
    sd = q.r_byb.std(ddof=1)
    t = q.r_byb.mean() / (sd / np.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    print(f"{name}: n={n:4d} | {n/days:5.3f} сд/день | tp {tp:2.0f}% sl {sl:2.0f}% time {tm:2.0f}% | avg {q.r_byb.mean():+.4f} t={t:+.2f} | Sum {q.r_byb.sum():+7.1f}")


print()
print("=== СРЕЗ A: только провалившие проверку окном (APPL & ok2F) = то, что бот скипает ===")
a = d[(d.appl == True) & (d.ok2 == False)]
stat("  всего 2023-26", a, ALL)
for y in [2023, 2024, 2025, 2026]:
    stat(f"  {y}", a[a.year == y], YEARD[y])

print()
print("=== СРЕЗ B: весь класс 'свип не пережил окно' (ok2F, включая PRE где проверка не дошла) ===")
b = d[d.ok2 == False]
stat("  всего 2023-26", b, ALL)
for y in [2023, 2024, 2025, 2026]:
    stat(f"  {y}", b[b.year == y], YEARD[y])

print()
print("=== справочно: полный поток канона ===")
stat("  всего 2023-26", d, ALL)
stat("  2024-26", d[d.year >= 2024], 366 + 365 + 174)

print()
print("=== СРЕЗ A, разбивка по парам (2023-26) ===")
for s in ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]:
    stat(f"  {s:5s}", a[a.sym == s], ALL)
