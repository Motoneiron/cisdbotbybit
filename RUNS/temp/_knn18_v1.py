"""Прогон 18-го (kNN analog) по снапшоту потока — точно по cryptofish/training/analog.py.

Использование: python _knn18_v1.py <stream_v2_pkl> [--tag my]
Требует колонки: hash, dir, decision_at, exit_ts, outcome, r_net + вектор (см. COL_MAP).
Выход: knn18_<tag>.pkl + knn18_<tag>_report.txt"""
import argparse
import importlib.util
import json
import sys

import numpy as np
import pandas as pd

ANALOG_PATH = r"D:/PYTHON/cryptofish/training/analog.py"
POLICY_PATH = r"D:/PYTHON/cryptofish/training/code_policy_v1.json"

COL_MAP = {
    "sweep_size_atr": "sweep_atr",
    "volume_ratio": "vol_ratio_scan",
    "quality_score": "quality_score",
    "vwap_deviation_atr": "vd",
    "stoch_k": "stoch_k",
    "macd_hist": "macd_hist",
    "ema_distance_atr": "ema_distance_atr",
    "atr_percentile": "atr_percentile",
}


def load_analog():
    spec = importlib.util.spec_from_file_location("cf_analog", ANALOG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wr(part: pd.DataFrame) -> float:
    dec = part[part["outcome"].isin(["tp", "sl"])]
    if not len(dec):
        return 0.0
    return 100.0 * (dec["outcome"] == "tp").mean()


def block(name, part, fh):
    line = f"{name:28s} n={len(part):5d} WR={wr(part):5.1f}% ΣR={part['r_net'].sum():8.1f} AvgR={part['r_net'].mean() if len(part) else 0:6.3f}"
    print(line, flush=True)
    fh.write(line + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stream")
    ap.add_argument("--tag", default="v1")
    args = ap.parse_args()
    df = pd.read_pickle(args.stream).reset_index(drop=True)
    analog = load_analog()
    policy = json.load(open(POLICY_PATH, encoding="utf-8"))
    names = policy["agent_18_statistical"]["vector"]
    scored = []
    for r in df.itertuples():
        vals = {}
        for nm in names:
            col = COL_MAP[nm]
            v = getattr(r, col, None)
            vals[nm] = None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)
        scored.append(
            {
                "hash": str(r.hash),
                "direction": str(r.dir),
                "decision_at": str(r.decision_at),
                "exit_at": str(r.exit_ts),
                "outcome": r.outcome,
                "snapshot": {"values": vals},
            }
        )
    print(f"n rows: {len(scored)} | вектор: {names}", flush=True)
    votes = analog.analog_votes(scored, policy=policy)
    vdf = pd.DataFrame(
        {
            "hash": list(votes.keys()),
            "prob": [v["probability"] for v in votes.values()],
            "keep": [v["direction"] != "SKIP" for v in votes.values()],
            "ncount": [v["neighbor_count"] for v in votes.values()],
            "codes": [",".join(v["reason_codes"]) for v in votes.values()],
        }
    )
    m = df.merge(vdf, on="hash", how="left")
    codes = m["codes"].fillna("")
    # настоящий «недостаточно матёрых соседей»: INSUFFICIENT_SUPPORT без STAT_BETA (p<0.45 SKIP тоже содержит EFFECTIVE_SUPPORT)
    insuff = m[codes.str.contains("INSUFFICIENT_SUPPORT", na=False) & ~codes.str.contains("STAT_BETA", na=False)]
    out_pkl = rf"D:/PYTHON/cisdbotbybit/RUNS/temp/knn18_{args.tag}.pkl"
    m.to_pickle(out_pkl)
    rep = rf"D:/PYTHON/cisdbotbybit/RUNS/temp/knn18_{args.tag}_report.txt"
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write(f"stream: {args.stream} | n={len(m)}\n")
        fh.write(f"supported: {len(m) - len(insuff)} | insufficient: {len(insuff)}\n\n")
        block("ALL", m, fh)
        block("KEEP (p>=0.45)", m[m["keep"]], fh)
        block("SKIP (p<0.45)", m[m["keep"] == False], fh)
        block("INSUFFICIENT ONLY", insuff, fh)
        block("KEEP без insufficient", m[(m["keep"]) & (~m.index.isin(insuff.index))], fh)
        fh.write("\n-- по годам (KEEP vs SKIP) --\n")
        for yr, g in m.groupby("year"):
            block(f"{yr} KEEP", g[g["keep"]], fh)
            block(f"{yr} SKIP", g[g["keep"] == False], fh)
        fh.write("\n-- по tf --\n")
        for tf, g in m.groupby("prof"):
            block(f"{tf} KEEP", g[g["keep"]], fh)
            block(f"{tf} SKIP", g[g["keep"] == False], fh)
        fh.write("\n-- по направлениям --\n")
        for d, g in m.groupby("dir"):
            block(f"{d} KEEP", g[g["keep"]], fh)
            block(f"{d} SKIP", g[g["keep"] == False], fh)
        fh.write("\n-- кривая порогов (по prob; insufficient исключены) --\n")
        sup = m[~m.index.isin(insuff.index)]
        for th in [0.40, 0.425, 0.45, 0.475, 0.50, 0.55]:
            k = sup[sup["prob"] >= th]
            line = f"th={th:.3f} keep_n={len(k):5d} ({100*len(k)/max(1,len(sup)):4.1f}%) WR={wr(k):5.1f}% ΣR={k['r_net'].sum():8.1f}"
            print(line, flush=True)
            fh.write(line + "\n")
    print("saved:", out_pkl, "|", rep)


if __name__ == "__main__":
    main()
