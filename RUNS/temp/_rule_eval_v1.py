"""Rule-eval v1: переоценка кандидатов на снапшоте потока (WR-first, retention-кривые).

Использование: python _rule_eval_v1.py [stream_pkl]
Печатает по каждому правилу: retention, kept/cut (n, WR, ΣR, AvgR) + по-годовая ΣR kept.
"""
import os
import sys

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def metrics(g):
    n = len(g)
    tp = int((g.outcome == "tp").sum())
    sl = int((g.outcome == "sl").sum())
    return {
        "n": n,
        "WR": round(100 * tp / max(1, tp + sl), 1),
        "SumR": round(float(g.r_net.sum()), 1),
        "AvgR": round(float(g.r_net.mean()), 3) if n else None,
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "stream_off_v1.pkl")
    df = pd.read_pickle(path)
    df = df[df["r_net"].notna()].copy()
    print(f"stream: {path} | n={len(df)} | ΣR={df.r_net.sum():.1f}")
    base = metrics(df)

    rules = []
    for k in (2, 3, 4, 5, 6, 8):
        rules.append((f"touches>={k}", df["prior_touches"] >= k))
        rules.append((f"touches<={k}", df["prior_touches"] <= k))
    qs = df["quality_score"].quantile([0.5, 0.6, 0.7, 0.8])
    for q, v in qs.items():
        rules.append((f"score>={v:.2f}(q{int(q*100)})", df["quality_score"] >= v))
    rules.append(("score<=q50", df["quality_score"] <= qs[0.5]))
    rules.append(("psl_q<=2", df["psl_quartile"] <= 2))
    rules.append(("psl_q>=3", df["psl_quartile"] >= 3))
    rules.append(("psl_q==4", df["psl_quartile"] == 4))
    rules.append(("soft_dow", df["soft_dow"] == True))  # noqa: E712
    rules.append(("not_soft_dow", df["soft_dow"] == False))  # noqa: E712
    rules.append(("late_retest", df["late_retest"] == True))  # noqa: E712
    rules.append(("one_bar_sweep_cisd", df["one_bar_sweep_cisd"] == True))  # noqa: E712
    rules.append(("confirm_on_sweep", df["confirm_on_sweep"] == True))  # noqa: E712
    rules.append(("fib_stretch_market", df["fib_stretch_market"] == True))  # noqa: E712
    for t in (1.5, 2.0, 2.5):
        rules.append((f"rr>={t}", df["rr_planned"] >= t))
    for t in (0.004, 0.006, 0.008):
        rules.append((f"sp>={t}", df["sp"] >= t))
    rules.append(("vol_ratio<=1", df["vol_ratio"] <= 1.0))
    rules.append(("vol_ratio<=1.5", df["vol_ratio"] <= 1.5))
    rules.append(("vol_ratio>=2", df["vol_ratio"] >= 2.0))
    rules.append(("sweep_atr>=0.5", df["sweep_atr"] >= 0.5))
    rules.append(("sweep_atr>=1.0", df["sweep_atr"] >= 1.0))
    rules.append(("SHORT", df["dir"] == "SHORT"))
    rules.append(("LONG", df["dir"] == "LONG"))
    rules.append(("tf7", df["prof"] == "tf7"))
    rules.append(("tf8", df["prof"] == "tf8"))

    rows = []
    years = sorted(df["year"].unique())
    for name, mask in rules:
        m = mask.fillna(False).astype(bool)
        kept, cut = df[m], df[~m]
        if len(kept) < 30 or len(cut) < 30:
            continue
        km, cm = metrics(kept), metrics(cut)
        row = {
            "rule": name,
            "ret%": round(100 * len(kept) / len(df), 1),
            "kept_n": km["n"], "kept_WR": km["WR"], "kept_SumR": km["SumR"], "kept_AvgR": km["AvgR"],
            "cut_WR": cm["WR"], "cut_SumR": cm["SumR"],
            "dWR": round(km["WR"] - cm["WR"], 1),
            "dSumR": round(km["SumR"] - cm["SumR"], 1),
        }
        for y in years:
            ky = kept[kept.year == y]
            row[f"k{y}"] = round(float(ky.r_net.sum()), 1) if len(ky) else None
        rows.append(row)
    out = pd.DataFrame(rows)
    out = out.sort_values("kept_SumR", ascending=False)
    pd.set_option("display.width", 250)
    cols = ["rule", "ret%", "kept_n", "kept_WR", "kept_SumR", "kept_AvgR", "cut_WR", "cut_SumR", "dWR", "dSumR"]
    print("\n=== ОБЩАЯ ТАБЛИЦА (sorted by kept_SumR) ===")
    print(out[cols].to_string(index=False))
    ycols = ["rule"] + [c for c in out.columns if c.startswith("k20")]
    print("\n=== ПО ГОДАМ (ΣR kept) ===")
    print(out[ycols].to_string(index=False))
    dst = path.replace(".pkl", "_eval.txt")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(f"stream: {path}\nbase: {base}\n\n")
        f.write(out[cols].to_string(index=False))
        f.write("\n\n")
        f.write(out[ycols].to_string(index=False))
    print("saved:", dst)


if __name__ == "__main__":
    main()
