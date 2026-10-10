"""Только 2024-2026: держится ли gross-край на широких стопах?

Смысл: комиссия в R = 0,072% / стоп%. Если край в R не падает при росте
минимального стопа, то разрыв закрывается порогом, а не новым признаком.
Если край падает вместе с комиссией — закрывать нечем.
"""
import numpy as np
import pandas as pd

LATE = [2024, 2025, 2026]
CUTS = [0.0, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]


def stat(x) -> tuple:
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 30:
        return n, float("nan"), float("nan"), float("nan")
    m = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n))
    return n, m, se, (m / se if se > 0 else float("nan"))


def main() -> None:
    d = pd.read_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/gross_by_year.pkl")
    late = d[d["year"].isin(LATE)]

    for p in ("tf0", "tf1", "tf2", "tf8"):
        s = late[late["profile"] == p]
        print("=" * 84)
        print(f"{p}, только 2024-2026 (n={len(s)})")
        print("=" * 84)
        print(f"{'стоп >=':>8} {'n':>6} {'мед.стоп%':>9} {'gross R':>9} "
              f"{'SE':>7} {'t':>6} {'комис R':>8} {'net R':>9} {'WR':>6}")
        for c in CUTS:
            q = s[s["stop_pct"] >= c]
            n, m, se, t = stat(q["gross"])
            if n < 30:
                continue
            tp = int((q["out_1.0"] == "tp").sum())
            sl = int((q["out_1.0"] == "sl").sum())
            wr = tp / (tp + sl) * 100 if tp + sl else float("nan")
            print(f"{c:8.2f} {n:6d} {q['stop_pct'].median():9.2f} {m:+9.4f} "
                  f"{se:7.4f} {t:+6.2f} {q['fee'].mean():8.4f} "
                  f"{q['net'].mean():+9.4f} {wr:6.1f}")
        print()

    print("=" * 84)
    print("Лучшая клетка по net R на 2024-2026 и её проверка по годам")
    print("=" * 84)
    best = []
    for p in ("tf0", "tf1", "tf2", "tf8"):
        s = late[late["profile"] == p]
        for c in CUTS:
            q = s[s["stop_pct"] >= c]
            if len(q) < 300:
                continue
            best.append((float(q["net"].mean()), p, c, len(q)))
    best.sort(reverse=True)
    for net, p, c, n in best[:5]:
        s = late[(late["profile"] == p) & (late["stop_pct"] >= c)]
        yrs = []
        for y in LATE:
            q = s[s["year"] == y]
            yrs.append(f"{y}:{q['net'].mean():+.3f}" if len(q) >= 30 else f"{y}:—")
        _, m, se, t = stat(s["gross"])
        print(f"{p} стоп>={c:.2f}%: n={n:5d} net={net:+.4f} "
              f"gross={m:+.4f} (t{t:+.2f}) | {' '.join(yrs)}")


if __name__ == "__main__":
    main()
