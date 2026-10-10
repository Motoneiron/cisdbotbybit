"""CVD-проверка РЕАЛЬНЫХ сделок бота (13-14.09.2026) — поток на момент решения. v2

Binance spot aggTrades точечно (ADA/BNB/DOGE/ETH/LINK/LTC/SOL/XRP) + Bybit CSV для KAS (спот KASUSDT умер).
Кэш лент в _cvd_live_tape.pkl. of_1h_s/of_4h_s подписаны в сторону сделки.
Пороги freeze-check (disc 2020-23): A: of_1h_s>=0; B10: S<-0.0397/L<-0.0882; B20: S<-0.0038/L<-0.0511.
"""
import csv
import gzip
import io
import json
import os
import time
import urllib.request

import pandas as pd

API = "https://api.binance.com/api/v3/aggTrades"
BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
H = 3600_000
H4 = 4 * H

TRADES = [
    ("LTC", "SHORT", "tf7", "closed_sl", -1.4687, "2026-09-13 01:05:15", 53.65),
    ("KAS", "SHORT", "tf8", "closed_sl", -1.1376, "2026-09-13 04:00:13", 0.03501),
    ("KAS", "SHORT", "tf7", "closed_tp", 0.9065, "2026-09-13 06:58:51", 0.03499),
    ("LTC", "SHORT", "tf8", "closed_time", -0.7434, "2026-09-13 09:30:08", 53.51),
    ("BNB", "LONG", "tf7", "closed_tp", 0.6173, "2026-09-13 13:40:04", 715.3),
    ("KAS", "SHORT", "tf8", "closed_tp", 0.8858, "2026-09-13 20:29:29", 0.03438),
    ("DOGE", "SHORT", "tf8", "closed_tp", 0.9021, "2026-09-13 22:05:11", 0.08344),
    ("LINK", "SHORT", "tf8", "closed_time", -0.5552, "2026-09-13 22:20:07", 11.251),
    ("DOGE", "LONG", "tf7", "closed_tp", 0.8539, "2026-09-14 00:35:03", 0.08257),
    ("SOL", "LONG", "tf7", "closed_tp", 0.8108, "2026-09-14 00:45:05", 99.66),
    ("XRP", "LONG", "tf7", "closed_tp", 0.9462, "2026-09-14 02:15:07", 1.3576),
    ("ADA", "LONG", "tf8", "closed_time", -0.2006, "2026-09-14 07:05:05", 0.2091),
    ("BNB", "LONG", "tf7", "closed_tp", 0.6840, "2026-09-14 09:50:07", 724.4),
    ("BNB", "SHORT", "tf7", "closed_tp", 0.8501, "2026-09-14 10:55:07", 722.8),
    ("ETH", "LONG", "tf7", "closed_sl", -1.5090, "2026-09-14 12:20:05", 2511.84),
    ("LINK", "SHORT", "tf7", "open", None, "2026-09-14 12:40:08", 11.353),
]


def ms(s: str) -> int:
    return int(pd.Timestamp(s).timestamp() * 1000)


def fetch_binance(symbol: str, t0: int, t1: int):
    out = []
    fid = None
    while True:
        url = f"{API}?symbol={symbol}&limit=1000" + (f"&startTime={t0}" if fid is None else f"&fromId={fid}")
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode())
        if not isinstance(data, list) or not data:
            break
        for d in data:
            q = float(d["q"])
            out.append((int(d["T"]), -q if d["m"] else q, q))
        if len(data) < 1000 or out[-1][0] >= t1:
            break
        fid = int(data[-1]["a"]) + 1
        time.sleep(0.12)
    return out


def fetch_kas_bybit(day: str = "2026-09-13"):
    url = f"https://public.bybit.com/trading/KASUSDT/KASUSDT{day}.csv.gz"
    raw = urllib.request.urlopen(url, timeout=60).read()
    out = []
    with gzip.open(io.BytesIO(raw), "rt", errors="replace") as fh:
        for row in csv.DictReader(fh):
            t = int(float(row["timestamp"]) * 1000)
            q = float(row["size"])
            side = (row.get("side") or "").strip()
            out.append((t, q if side == "Buy" else -q, q))
    out.sort(key=lambda x: x[0])
    print(f"[KAS/bybit] rows={len(out)} sample={out[:2]}", flush=True)
    return out


def sums(tape, t0, t1):
    d = v = 0.0
    for T, qs, q in tape:
        if t0 <= T < t1:
            d += qs
            v += q
    return d, v


def main() -> None:
    cache = BASE + "/_cvd_live_tape.pkl"
    if os.path.exists(cache):
        tape = pd.read_pickle(cache)
        print("tape из кэша:", {k: len(v) for k, v in tape.items()}, flush=True)
        if tape.get("KAS") and tape["KAS"][0][0] < 10**12:
            print("KAS ts были в секундах — перекачиваю Bybit", flush=True)
            tape["KAS"] = fetch_kas_bybit()
            pd.to_pickle(tape, cache)
    else:
        tape = {}
        for s in sorted({t[0] for t in TRADES}):
            need = []
            for (sym, _d, _tf, _st, _p, c, _e) in TRADES:
                if sym != s:
                    continue
                ms0 = ms(c)
                need.append((ms0 - H4 - 600_000, ms0 + 300_000))
            need.sort()
            merged = []
            for a, b in need:
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], b))
                else:
                    merged.append((a, b))
            if s == "KAS":
                tape[s] = fetch_kas_bybit()
                continue
            try:
                rows = []
                for a, b in merged:
                    rows += fetch_binance(s + "USDT", a, b)
                tape[s] = rows
                print(f"[{s}] aggTrades={len(rows)}", flush=True)
            except urllib.error.HTTPError as e:
                body = e.read().decode()[:120]
                print(f"[{s}] HTTP {e.code}: {body} — пропуск", flush=True)
                tape[s] = []
        pd.to_pickle(tape, cache)

    print()
    hdr = f"{'sym':4}{'dir':6}{'tf':4}{'status':12}{'pnl':>7} | {'of_1h_s':>9} {'of_4h_s':>9} | A(>=0) B10  B20"
    print(hdr, flush=True)
    res = []
    for (sym, d, tf, st, pnl, c, entry) in TRADES:
        ms0 = ms(c)
        d1, v1 = sums(tape[sym], ms0 - H, ms0)
        d4, v4 = sums(tape[sym], ms0 - H4, ms0)
        of1 = (d1 / v1) if v1 > 0 else float("nan")
        of4 = (d4 / v4) if v4 > 0 else float("nan")
        if d == "SHORT":
            of1 = -of1 if v1 > 0 else of1
            of4 = -of4 if v4 > 0 else of4
        a_keep = not (v1 > 0 and of1 < 0)
        b10 = not ((d == "SHORT" and of1 < -0.0397) or (d == "LONG" and of1 < -0.0882))
        b20 = not ((d == "SHORT" and of1 < -0.0038) or (d == "LONG" and of1 < -0.0511))
        pnl_s = f"{pnl:+.2f}" if pnl is not None else "open"
        print(f"{sym:4}{d:6}{tf:4}{st:12}{pnl_s:>7} | {of1:+9.4f} {of4:+9.4f} | {str(a_keep):6} {str(b10):5} {str(b20)}", flush=True)
        res.append(dict(sym=sym, dir=d, tf=tf, status=st, pnl=pnl, of1=of1, of4=of4, a=a_keep, b10=b10, b20=b20))

    df = pd.DataFrame(res)
    print("\n=== агрегаты (закрытые сделки; pnl в $ при риске ~$1) ===", flush=True)
    for rule, name in (("a", "A of_1h_s>=0"), ("b10", "B10 (нижние ~10%)"), ("b20", "B20 (нижние ~20%)")):
        cl = df[df.status.str.startswith("closed")].copy()
        kept = cl[cl[rule]]
        cut = cl[~cl[rule]]
        print(f"{name}: KEEP n={len(kept)} Σpnl={kept.pnl.sum():+.2f} WR={100*(kept.pnl > 0).mean():.0f}% | CUT n={len(cut)} Σpnl={cut.pnl.sum():+.2f} WR={100*(cut.pnl > 0).mean():.0f}%", flush=True)
        print("   CUT:", [(r['sym'], r['dir'], r['status'], round(r['pnl'], 2), round(r['of1'], 3)) for r in cut.to_dict('records')], flush=True)
        print("   KEEP-минусы:", [(r['sym'], r['dir'], r['status'], round(r['pnl'], 2), round(r['of1'], 3)) for r in kept[kept.pnl < 0].to_dict('records')], flush=True)

    df.to_pickle(BASE + "/_cvd_live_check.pkl")
    print("saved _cvd_live_check.pkl", flush=True)


if __name__ == "__main__":
    main()
