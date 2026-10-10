"""Край и комиссия в процентах ЦЕНЫ, а не в R.

Зачем: R = ширина стопа, а она у профилей разная (tf0 0,6% / tf8 1,5%).
Поэтому «край в R» между профилями напрямую не сравним: одно и то же движение
цены даёт разный R. Переводим обе величины в проценты цены:

    край_%  = gross_R * stop_%
    комис_% = fee_R   * stop_%   (должно выйти ~2*0,036% = 0,072%)

Тогда видно, край это свойство профиля или инварианта сетапа.
"""
import numpy as np
import pandas as pd

EARLY, LATE = [2020, 2021, 2022, 2023], [2024, 2025, 2026]


def stat(x) -> tuple:
    x = np.asarray(x, dtype=float)
    n = len(x)
    m = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n))
    return n, m, se, (m / se if se > 0 else float("nan"))


def main() -> None:
    d = pd.read_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/gross_by_year.pkl")
    d["edge_pct"] = d["gross"] * d["stop_pct"]      # % цены
    d["fee_pct"] = d["fee"] * d["stop_pct"]         # % цены
    d["asym_pct"] = d["asym"] * d["stop_pct"]

    print("=" * 92)
    print("КРАЙ В ПРОЦЕНТАХ ЦЕНЫ (не в R). Комиссия должна выйти ~0,072%")
    print("=" * 92)
    print(f"{'проф':5} {'период':9} {'n':>6} {'мед.стоп%':>9} "
          f"{'край%':>9} {'SE':>7} {'t':>6} {'комис%':>7} {'край/комис':>11}")
    for p in ("tf0", "tf1", "tf2", "tf8"):
        s = d[d["profile"] == p]
        for lbl, q in (("всё", s), ("2020-23", s[s["year"].isin(EARLY)]),
                       ("2024-26", s[s["year"].isin(LATE)])):
            n, m, se, t = stat(q["edge_pct"])
            fee = float(q["fee_pct"].mean())
            print(f"{p:5} {lbl:9} {n:6d} {q['stop_pct'].median():9.2f} "
                  f"{m:+9.4f} {se:7.4f} {t:+6.2f} {fee:7.4f} {m/fee:+11.2f}")
        print()

    print("=" * 92)
    print("ТО ЖЕ ПО ГОДАМ (край в % цены) — проверка, что это не режим")
    print("=" * 92)
    print(f"{'год':6} " + " ".join(f"{p:>16}" for p in ("tf0", "tf1", "tf2", "tf8")))
    for y in range(2020, 2027):
        cells = []
        for p in ("tf0", "tf1", "tf2", "tf8"):
            q = d[(d["profile"] == p) & (d["year"] == y)]
            if len(q) < 30:
                cells.append(f"{'—':>16}")
                continue
            _, m, se, t = stat(q["edge_pct"])
            cells.append(f"{m:+.4f} (t{t:+.1f})".rjust(16))
        print(f"{y}{'*' if y == 2026 else ' '} " + " ".join(cells))

    print()
    print("=" * 92)
    print("ИНВАРИАНТ: край в % цены, все профили вместе")
    print("=" * 92)
    for lbl, q in (("2020-2023", d[d["year"].isin(EARLY)]),
                   ("2024-2026", d[d["year"].isin(LATE)]),
                   ("всё", d)):
        n, m, se, t = stat(q["edge_pct"])
        fee = float(q["fee_pct"].mean())
        print(f"{lbl:10} n={n:6d} край={m:+.4f}% (SE {se:.4f}, t {t:+.2f}) "
              f"комиссия={fee:.4f}% доля={m/fee:.2f}")

    print()
    print("Во сколько раз нужно улучшить край (или подешевить исполнение), "
          "чтобы выйти в ноль:")
    for p in ("tf0", "tf1", "tf2", "tf8"):
        for lbl, q in (("2020-23", d[(d["profile"] == p) & d["year"].isin(EARLY)]),
                       ("2024-26", d[(d["profile"] == p) & d["year"].isin(LATE)])):
            m = float(q["edge_pct"].mean())
            fee = float(q["fee_pct"].mean())
            k = fee / m if m > 0 else float("inf")
            print(f"  {p} {lbl}: x{k:.2f}" if np.isfinite(k) else
                  f"  {p} {lbl}: край <= 0, множителя нет")


if __name__ == "__main__":
    main()
