"""Gross-край по годам и по половинам выборки, все четыре профиля.

Вопрос: заявленный +0,021 R/сделку (без комиссий, TP1R) — ровный по годам
или это свойство 2020-2023, как все клетки tf2?

Считаем две независимые меры:
  * gross = mean(r_1.0) — исход при тейке 1R БЕЗ комиссий;
  * asym  = mean(mfe_r - mae_r) — асимметрия хода, не зависит от выбора тейка.

Данные: честные кэши (якорь = филл после закрытия конфирм-бара, пересчёт по 1m).
Ничего не фильтруем: ни направления, ни ширины стопа, ни фильтров бота.
"""
import glob
import pickle

import numpy as np
import pandas as pd

TF8 = "D:/PYTHON/cisdbotbybit/RUNS/temp/tp_grid"
OTHER = "D:/PYTHON/cisdbotbybit/RUNS/temp/tp_grid_other"
HOLD = {"tf0": 6, "tf1": 16, "tf2": 24, "tf8": 6}   # канонический hold профиля
EARLY, LATE = [2020, 2021, 2022, 2023], [2024, 2025, 2026]


def load() -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(f"{TF8}/*.pkl")):
        for r in pickle.load(open(f, "rb")):
            r["profile"] = "tf8"
            rows.append(r)
    for f in sorted(glob.glob(f"{OTHER}/*.pkl")):
        rows.extend(pickle.load(open(f, "rb")))
    d = pd.DataFrame(rows)
    d["hold"] = d["hold"].astype(int)
    d["year"] = d["year"].astype(int)
    keep = d["hold"] == d["profile"].map(HOLD)
    d = d.loc[keep].copy()
    d["gross"] = d["r_1.0"].astype(float)
    d["asym"] = d["mfe_r"].astype(float) - d["mae_r"].astype(float)
    d["fee"] = d["fee_maker2"].astype(float)
    d["net"] = d["gross"] - d["fee"]
    return d


def stat(x: np.ndarray) -> tuple:
    """n, mean, SE, t."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2:
        return n, float("nan"), float("nan"), float("nan")
    m = float(x.mean())
    se = float(x.std(ddof=1) / np.sqrt(n))
    return n, m, se, (m / se if se > 0 else float("nan"))


def welch(a: np.ndarray, b: np.ndarray) -> tuple:
    """Разница средних b-a, её SE и t."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b.mean() - a.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float(d), float(se), float(d / se) if se > 0 else float("nan")


def main() -> None:
    d = load()
    print("=" * 78)
    print("ВСЯ ВЫБОРКА (gross = TP1R без комиссий, канонический hold)")
    print("=" * 78)
    print(f"{'проф':5} {'n':>7} {'gross':>8} {'SE':>7} {'t':>6} "
          f"{'asym':>8} {'t_asym':>7} {'комис':>7} {'net':>8}")
    for p in ("tf0", "tf1", "tf2", "tf8"):
        s = d[d["profile"] == p]
        n, m, se, t = stat(s["gross"])
        _, ma, sea, ta = stat(s["asym"])
        print(f"{p:5} {n:7d} {m:+8.4f} {se:7.4f} {t:+6.2f} "
              f"{ma:+8.4f} {ta:+7.2f} {s['fee'].mean():7.4f} {s['net'].mean():+8.4f}")

    for p in ("tf0", "tf1", "tf2", "tf8"):
        s = d[d["profile"] == p]
        print()
        print("=" * 78)
        print(f"{p}: ПО ГОДАМ")
        print("=" * 78)
        print(f"{'год':6} {'n':>6} {'gross':>8} {'SE':>7} {'t':>6} "
              f"{'asym':>8} {'t_asym':>7} {'комис':>7} {'net':>8}")
        for y in sorted(s["year"].unique()):
            q = s[s["year"] == y]
            n, m, se, t = stat(q["gross"])
            _, ma, sea, ta = stat(q["asym"])
            mark = "*" if y == 2026 else " "
            print(f"{y}{mark} {n:6d} {m:+8.4f} {se:7.4f} {t:+6.2f} "
                  f"{ma:+8.4f} {ta:+7.2f} {q['fee'].mean():7.4f} {q['net'].mean():+8.4f}")
        e = s[s["year"].isin(EARLY)]
        l = s[s["year"].isin(LATE)]
        ne, me, see, te = stat(e["gross"])
        nl, ml, sel, tl = stat(l["gross"])
        _, mae_, _, tae = stat(e["asym"])
        _, mal, _, tal = stat(l["asym"])
        dd, dse, dt = welch(e["gross"], l["gross"])
        print(f"{'20-23':6} {ne:6d} {me:+8.4f} {see:7.4f} {te:+6.2f} "
              f"{mae_:+8.4f} {tae:+7.2f} {e['fee'].mean():7.4f} {e['net'].mean():+8.4f}")
        print(f"{'24-26':6} {nl:6d} {ml:+8.4f} {sel:7.4f} {tl:+6.2f} "
              f"{mal:+8.4f} {tal:+7.2f} {l['fee'].mean():7.4f} {l['net'].mean():+8.4f}")
        print(f"       разница поздние-ранние: {dd:+.4f} (SE {dse:.4f}, t {dt:+.2f})")

    print()
    print("=" * 78)
    print("СВОДКА: gross на половинах")
    print("=" * 78)
    print(f"{'проф':5} {'n 20-23':>8} {'gross':>8} {'t':>6} | "
          f"{'n 24-26':>8} {'gross':>8} {'t':>6} | {'разница':>8} {'t':>6}")
    for p in ("tf0", "tf1", "tf2", "tf8"):
        s = d[d["profile"] == p]
        e, l = s[s["year"].isin(EARLY)], s[s["year"].isin(LATE)]
        ne, me, _, te = stat(e["gross"])
        nl, ml, _, tl = stat(l["gross"])
        dd, _, dt = welch(e["gross"], l["gross"])
        print(f"{p:5} {ne:8d} {me:+8.4f} {te:+6.2f} | "
              f"{nl:8d} {ml:+8.4f} {tl:+6.2f} | {dd:+8.4f} {dt:+6.2f}")

    print()
    print("=" * 78)
    print("ПУЛ ЧЕТЫРЁХ ПРОФИЛЕЙ (исходы коррелируют, t завышен — только знак)")
    print("=" * 78)
    for lbl, q in (("2020-2023", d[d["year"].isin(EARLY)]),
                   ("2024-2026", d[d["year"].isin(LATE)])):
        n, m, se, t = stat(q["gross"])
        _, ma, _, ta = stat(q["asym"])
        print(f"{lbl}: n={n:6d} gross={m:+.4f} (t {t:+.2f}) "
              f"asym={ma:+.4f} (t {ta:+.2f}) net={q['net'].mean():+.4f}")

    d.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/gross_by_year.pkl")
    print("\nсохранено: RUNS/temp/gross_by_year.pkl")


if __name__ == "__main__":
    main()
