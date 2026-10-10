"""Time-of-day САЙЗИНГ: freeze-check (фит 2020-23 → OOS 2024-26) + компаундинг + комбо с CVD-весами.

Правило (стиль CVD): часы-группы выбираются ТОЛЬКО на фите (2020-23):
  weak = 6 часов с худшим avgR (вес 0.7), strong = 6 лучших (1.3), остальные 1.0.
Проверка: OOS-статистика групп + отношение итогового капитала (sized/base) на OOS и по годам.
Комбо: вес = вес_времени × вес_CVD (пороги CVD: <0.0063 → 0.7; >0.0712 → 1.3).
"""
import numpy as np
import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def main() -> None:
    p = pd.concat([pd.read_pickle(f"{BASE}/stream_{s}_cvd.pkl") for s in SYMS], ignore_index=True)
    p = p[p.of_1h_s.notna()].copy()
    p["dec"] = pd.to_datetime(p["decision_at"])
    p["hour"] = p.dec.dt.hour
    fit = p[p.year <= 2023]
    oos = p[p.year >= 2024]

    hs = fit.groupby("hour").agg(n=("r_net", "size"), avg=("r_net", "mean"))
    hs = hs.sort_values("avg")
    weak_h = [int(h) for h in hs.index[:6]]
    strong_h = [int(h) for h in hs.index[-6:]]
    print("ФИТ 2020-23:", flush=True)
    print("  weak hours   (0.7):", weak_h, [f"{hs.loc[h,'avg']:+.3f}" for h in weak_h], flush=True)
    print("  strong hours (1.3):", strong_h, [f"{hs.loc[h,'avg']:+.3f}" for h in strong_h], flush=True)

    def w_time(h):
        if h in weak_h:
            return 0.7
        if h in strong_h:
            return 1.3
        return 1.0

    p["w_t"] = p.hour.map(w_time)
    p["w_c"] = np.where(p.of_1h_s < 0.0063, 0.7, np.where(p.of_1h_s > 0.0712, 1.3, 1.0))
    p["w_combo"] = p.w_t * p.w_c

    for name, mask in [("FIT 2020-23", p.year <= 2023), ("OOS 2024-26", p.year >= 2024)]:
        g = p[mask]
        print(f"\n=== {name} ===", flush=True)
        for lbl, sub in [
            ("weak  0.7", g[g.w_t == 0.7]),
            ("mid   1.0", g[g.w_t == 1.0]),
            ("strong 1.3", g[g.w_t == 1.3]),
        ]:
            print(f"  {lbl}: n={len(sub)} WR={wr(sub):.1f}% avg={sub.r_net.mean():+.3f} ΣR={sub.r_net.sum():+.0f}", flush=True)

    print("\n=== Компаундинг (риск 1%×вес, единица R = r_net) ===", flush=True)
    for name, mask in [("FIT", p.year <= 2023), ("OOS", p.year >= 2024), ("ALL", slice(None))]:
        g = p[mask]
        base = float((1 + 0.01 * g.r_net).prod())
        t = float((1 + 0.01 * g.w_t * g.r_net).prod())
        c = float((1 + 0.01 * g.w_c * g.r_net).prod())
        cmb = float((1 + 0.01 * g.w_combo * g.r_net).prod())
        print(f"  {name}: base={base:,.0f}x | time={t:,.0f}x (×{t/base:.2f}) | cvd={c:,.0f}x (×{c/base:.2f}) | combo={cmb:,.0f}x (×{cmb/base:.2f})", flush=True)

    print("\n=== По годам: time-ratio / combo-ratio ===", flush=True)
    for y, g in p.groupby("year"):
        base = float((1 + 0.01 * g.r_net).prod())
        t = float((1 + 0.01 * g.w_t * g.r_net).prod())
        cmb = float((1 + 0.01 * g.w_combo * g.r_net).prod())
        print(f"  {int(y)}: time ×{t/base:.2f} | combo ×{cmb/base:.2f}", flush=True)

    # недельная проверка дней (мелко, без весов — просто тилт)
    p["dow"] = p.dec.dt.day_name().str[:3]
    print("\n=== Дни недели (весь период, справочно) ===", flush=True)
    for d, g in p.groupby("dow"):
        print(f"  {d}: n={len(g)} WR={wr(g):.1f}% avg={g.r_net.mean():+.3f}", flush=True)


if __name__ == "__main__":
    main()
