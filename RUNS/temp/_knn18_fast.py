"""Быстрый эквивалент analog_votes (тот же алгоритм, без парсинга таймстампов в цикле).

Логика 1:1 с cryptofish/training/analog.py:
  prior(i) = {j: outcome_j in {tp,sl}, vec_j валиден, dec_j < as_of_i, exit_j <= as_of_i}
  если |prior| < min_n(20) -> SKIP(p=0.5); иначе стандартизация по prior, k=25 ближайших,
  prob = (wins+alpha)/(k+alpha+beta), SKIP если prob < 0.45.
Режимы:
  --validate  : прогнать официальный модуль и свой на ОДНОМ небольшом пуле, сравнить prob/verdict
  --run       : посчитать голоса по всему пулу и записать отчёт (как knn18_*_report.txt)
"""
import argparse
import importlib.util
import json
import sys

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
ANALOG = r"D:/PYTHON/cryptofish/training/analog.py"
POLICY = r"D:/PYTHON/cryptofish/training/code_policy_v1.json"
COL_MAP = {"sweep_size_atr": "sweep_atr", "volume_ratio": "vol_ratio_scan", "quality_score": "quality_score",
           "vwap_deviation_atr": "vd", "stoch_k": "stoch_k", "macd_hist": "macd_hist",
           "ema_distance_atr": "ema_distance_atr", "atr_percentile": "atr_percentile"}


def load_analog():
    spec = importlib.util.spec_from_file_location("cf_analog", ANALOG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Fast:
    def __init__(self, df, names, time_col="decision_at", k=25, min_n=20, alpha=1.0, beta=1.0, pmin=0.45):
        self.k, self.min_n, self.alpha, self.beta, self.pmin = k, min_n, alpha, beta, pmin
        self.names = names
        self.d = len(names)
        V = np.full((len(df), self.d), np.nan)
        for i, nm in enumerate(names):
            V[:, i] = pd.to_numeric(df[COL_MAP[nm]], errors="coerce").to_numpy(float)
        self.valid = np.isfinite(V).all(axis=1)
        self.V = np.where(self.valid[:, None], V, 0.0)
        self.dec = pd.to_datetime(df[time_col]).to_numpy("datetime64[ns]")
        self.exit = pd.to_datetime(df["exit_ts"]).to_numpy("datetime64[ns]")
        self.is_tp = (df["outcome"].to_numpy() == "tp")
        self.is_decided = df["outcome"].isin(["tp", "sl"]).to_numpy()
        cand = self.is_decided & self.valid & ~pd.isna(self.exit) & ~pd.isna(self.dec)
        order = np.argsort(np.where(pd.isna(self.exit), np.datetime64("2262-01-01"), self.exit))
        self.cand = order[cand[order]]
        self.c_exit = self.exit[self.cand]
        self.c_dec = self.dec[self.cand]
        self.c_tp = self.is_tp[self.cand]
        self.c_V = self.V[self.cand]

    def vote(self, i):
        as_of = self.dec[i]
        m = int(np.searchsorted(self.c_exit, as_of, "right"))
        sel = np.flatnonzero(self.c_dec[:m] < as_of)
        if (not self.valid[i]) or len(sel) < self.min_n:
            return None, 0.5, len(sel)
        mat = self.c_V[sel]
        mu = mat.mean(axis=0)
        sd = mat.std(axis=0)
        sd = np.where(sd < 1e-9, 1.0, sd)
        z = (mat - mu) / sd
        tgt = (self.V[i] - mu) / sd
        dist = np.sqrt(((z - tgt) ** 2).sum(axis=1))
        take = min(self.k, len(sel))
        idx = np.argpartition(dist, take - 1)[:take]
        wins = int(self.c_tp[sel][idx].sum())
        prob = (wins + self.alpha) / (take + self.alpha + self.beta)
        return prob, prob, take

    def all_votes(self):
        out = np.zeros(len(self.V), bool)
        prob = np.full(len(self.V), np.nan)
        ncnt = np.zeros(len(self.V), int)
        for i in range(len(self.V)):
            p, p2, n = self.vote(i)
            if p is None:
                prob[i] = 0.5
                out[i] = False
            else:
                prob[i] = p
                out[i] = p >= self.pmin
            ncnt[i] = n
        return out, prob, ncnt


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def report(m, fh, tag):
    def block(name, part):
        s = f"{name:30s} n={len(part):5d} WR={wr(part):5.1f}% ΣR={part['r_net'].sum():8.1f} AvgR={part['r_net'].mean() if len(part) else 0:6.3f}"
        print(s, flush=True); fh.write(s + "\n")
    fh.write(f"### {tag}\n")
    block("ALL", m)
    block("KEEP (p>=0.45)", m[m.keep])
    block("SKIP (p<0.45)", m[~m.keep])
    for y, g in m.groupby("year"):
        block(f"{int(y)} KEEP", g[g.keep]); block(f"{int(y)} SKIP", g[~g.keep])
    for tf, g in m.groupby("prof"):
        block(f"{tf} KEEP", g[g.keep]); block(f"{tf} SKIP", g[~g.keep])
    for d, g in m.groupby("dir"):
        block(f"{d} KEEP", g[g.keep]); block(f"{d} SKIP", g[~g.keep])
    fh.write("\n")
    for th in (0.40, 0.45, 0.50, 0.55):
        kk = m[m.prob >= th]
        s = f"th={th:.2f} keep_n={len(kk):5d} ({100*len(kk)/len(m):4.1f}%) WR={wr(kk):5.1f}% ΣR={kk['r_net'].sum():8.1f}"
        print(s, flush=True); fh.write(s + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["validate", "run"], default="run")
    ap.add_argument("--stream", default=f"{BASE}/knn18_live_input.pkl")
    ap.add_argument("--tag", default="live_fast")
    ap.add_argument("--time-col", default="decision_at")
    ap.add_argument("--n", type=int, default=3000)
    args = ap.parse_args()
    policy = json.load(open(POLICY, encoding="utf-8"))
    names = policy["agent_18_statistical"]["vector"]
    df = pd.read_pickle(args.stream).reset_index(drop=True)

    if args.mode == "validate":
        sub = df.iloc[: args.n].reset_index(drop=True)
        F = Fast(sub, names)
        v_fast = [F.vote(i) for i in range(len(sub))]
        analog = load_analog()
        scored = []
        for r in sub.itertuples():
            vals = {nm: float(getattr(r, COL_MAP[nm])) for nm in names}
            scored.append({"hash": str(r.hash), "direction": str(r.dir), "decision_at": str(r.decision_at),
                           "exit_at": str(r.exit_ts), "outcome": r.outcome, "snapshot": {"values": vals}})
        votes = analog.analog_votes(scored, policy=policy)
        dif = 0
        sup = 0
        for i, r in enumerate(sub.itertuples()):
            v = votes[str(r.hash)]
            p_fast, _, n_fast = v_fast[i]
            p_off = round(v["probability"], 4)
            if n_fast != v["neighbor_count"]:
                dif += 1
                print(f"  NDIFF {r.hash}: n_fast={n_fast} n_off={v['neighbor_count']}", flush=True)
                continue
            if p_fast is None:
                if v["direction"] != "SKIP" or n_fast >= 20:
                    dif += 1
                    print(f"  UDIFF {r.hash}: fast=None off={p_off} n={n_fast}", flush=True)
                continue
            sup += 1
            if round(p_fast, 4) != p_off:
                dif += 1
                if dif <= 100:
                    print(f"  DIFF {r.hash}: fast={round(p_fast,4)} off={p_off} n_fast={n_fast}", flush=True)
        print(f"ВАЛИДАЦИЯ: строк {len(sub)}, со сильной поддержкой {sup}, расхождений {dif}", flush=True)
        return

    F = Fast(df, names, time_col=args.time_col)
    keep, prob, ncnt = F.all_votes()
    m = df.copy()
    m["keep"] = keep
    m["prob"] = prob
    m["ncount"] = ncnt
    m.to_pickle(f"{BASE}/knn18_{args.tag}.pkl")
    fh = open(f"{BASE}/knn18_{args.tag}_report.txt", "w", encoding="utf-8")
    fh.write(f"stream: {args.stream} | time_col={args.time_col} | n={len(m)}\n\n")
    report(m, fh, args.tag)
    fh.close()
    print("saved", f"{BASE}/knn18_{args.tag}.pkl", flush=True)


if __name__ == "__main__":
    main()
