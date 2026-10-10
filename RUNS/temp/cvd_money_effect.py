"""CVD-сайзинг: денежный эффект в понятных терминах (без компаунд-фантазий)."""
import numpy as np
import pandas as pd

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_multi_cvd.pkl")
d = df.copy()
lo, hi = d.of_1h_s.quantile(0.01), d.of_1h_s.quantile(0.99)
d["ofw"] = d.of_1h_s.clip(lo, hi)
disc = d[d.year <= 2023]
c1, c2 = disc.ofw.quantile(1 / 3), disc.ofw.quantile(2 / 3)
d["w"] = np.select([d.ofw < c1, d.ofw > c2], [0.7, 1.3], default=1.0)

oos = d[d.year >= 2024].copy()
print("=== OOS 2024-26 ===")
print("средний вес:", round(oos.w.mean(), 3), "| доля весов:",
      {float(k): round(v, 2) for k, v in oos.w.value_counts(normalize=True).items()})
print(f"ΣR: {oos.r_net.sum():+,.0f} → с сайзингом: {(oos.w * oos.r_net).sum():+,.0f} "
      f"({((oos.w * oos.r_net).sum() / oos.r_net.sum() - 1) * 100:+.1f}% к сумме R, без реинвеста)")

print("\n=== по годам (линейный ΣR, без реинвеста) ===")
for y in sorted(oos.year.unique()):
    yy = oos[oos.year == y]
    r0, r1 = yy.r_net.sum(), (yy.w * yy.r_net).sum()
    print(f"  {y}: {r0:+8.0f}R → {r1:+8.0f}R ({100*(r1/r0-1):+.0f}%)")

print("\n=== по направлениям (OOS) ===")
for dr in ("LONG", "SHORT"):
    g = oos[oos["dir"] == dr]
    r0, r1 = g.r_net.sum(), (g.w * g.r_net).sum()
    print(f"  {dr}: {r0:+.0f}R → {r1:+.0f}R ({100*(r1/r0-1):+.0f}%)")

tp = oos[oos.outcome == "tp"]; sl = oos[oos.outcome == "sl"]
print(f"\nсредний TP: {tp.r_net.mean():+.3f}R | средний SL: {sl.r_net.mean():+.3f}R")
print("\n=== пример: одна сделка при балансе $300 (риск 1% = $3) ===")
base_risk = 3.0
for w in (0.7, 1.0, 1.3):
    r_amt = base_risk * w
    print(f"  вес {w}: ставка ${r_amt:.2f} | TP даёт ${r_amt * tp.r_net.mean():+.2f} | "
          f"SL даёт ${r_amt * sl.r_net.mean():+.2f}")

# сколько «лишних» денег даёт год при $300 (модельно, компаунд)
n_oos = len(oos)
print(f"\nза OOS-период сделок: {n_oos}, средний R на сделку: {oos.r_net.mean():+.3f} "
      f"→ с весом: {(oos.w * oos.r_net).mean():+.3f} (усреднённо по весам)")
