"""Кластеры: сколько ОДНОнаправленных сделок (по всем парам) идёт рядом по времени.

conc_same — число других сделок того же направления в ±win_h вокруг decision_at.
Таблицы: WR/ΣR по бакетам, отдельно по направлениям и годам.
Использование: python _cluster_probe.py <stream_pkl> [--win_h 2.0]"""
import argparse
import bisect

import pandas as pd


def line(name, part):
    dec = part[part["outcome"].isin(["tp", "sl"])]
    w = 100.0 * (dec["outcome"] == "tp").mean() if len(dec) else 0.0
    print(f"{name:28s} n={len(part):5d} WR={w:5.1f}% ΣR={part['r_net'].sum():8.1f} AvgR={part['r_net'].mean() if len(part) else 0:6.3f}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stream")
    ap.add_argument("--win_h", type=float, default=2.0)
    args = ap.parse_args()
    df = pd.read_pickle(args.stream).reset_index(drop=True)
    t = pd.to_datetime(df["decision_at"])
    df["dec_ms"] = t.map(lambda x: int(x.timestamp() * 1000))
    df = df.sort_values("dec_ms").reset_index(drop=True)
    W = int(args.win_h * 3600 * 1000)
    times = df["dec_ms"].to_list()
    dirs = df["dir"].to_list()
    same = []
    anyc = []
    for i in range(len(df)):
        l = bisect.bisect_left(times, times[i] - W)
        r = bisect.bisect_right(times, times[i] + W)
        same.append(sum(1 for k in range(l, r) if k != i and dirs[k] == dirs[i]))
        anyc.append(max(0, r - l - 1))
    df["conc_same"] = same
    df["conc_any"] = anyc
    df.to_pickle(args.stream.replace(".pkl", "_clu.pkl"))
    print(f"win=±{args.win_h}h | saved: {args.stream.replace('.pkl', '_clu.pkl')}", flush=True)
    line("ALL", df)
    for b0, b1, nm in [(0, 0, "0"), (1, 1, "1"), (2, 3, "2-3"), (4, 9, "4-9"), (10, 10**9, "10+")]:
        g = df[(df["conc_same"] >= b0) & (df["conc_same"] <= b1)]
        if len(g):
            line(f"conc_same {nm}", g)
    for d in ("SHORT", "LONG"):
        g0 = df[df["dir"] == d]
        line(f"{d} ALL", g0)
        for b0, b1, nm in [(0, 0, "0"), (1, 1, "1"), (2, 10**9, "2+")]:
            g = g0[(g0["conc_same"] >= b0) & (g0["conc_same"] <= b1)]
            if len(g):
                line(f"  {d} conc {nm}", g)
    print("-- по годам: conc_same>=1 vs 0 --", flush=True)
    for yr, g in df.groupby("year"):
        line(f"{yr} conc>=1", g[g["conc_same"] >= 1])
        line(f"{yr} conc=0", g[g["conc_same"] == 0])


if __name__ == "__main__":
    main()
