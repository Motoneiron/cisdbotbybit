"""fib_class.py — оценка класса fib_stretch_market (отброшен каноном, взят живым).

По trace-логу канона (trace_canon_out2.txt) берём все REJECT=kind:MARKET сигналы
за январь SOL, находим первый бар их выдачи живым детектом (как в live_filt_big:
скан каждого бара, ATR/VOL off, D on), затем гоняем живую модель исполнения
lf._outcome → смотрим, что этот класс дал бы живому прогону.
"""
import re
import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")

import pandas as pd

import live_filt_big as lf
import cisdbot as bot
import pickle

bot.CONFIG["tf7"]["detect_filters"] = {
    "atr_enabled": False,
    "vol_enabled": False,
    "d_enabled": True,
}
HTF = int(bot.CONFIG["tf7"]["htf_ratio"])

cases = []
pat = re.compile(
    r"scan=(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w{12}) (LONG|SHORT) "
    r"cbt=(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) swc=(\S+ \S+) e=([\d.]+) -> REJECT"
)
for line in open("trace_canon_out2.txt", encoding="utf-8"):
    m = pat.search(line)
    if m:
        cases.append(
            dict(scan=m.group(1), hash=m.group(2), dir=m.group(3), cbt=m.group(4), entry=float(m.group(6)))
        )
print(f"cases: {len(cases)}", flush=True)

df1 = lf.load_1m(lf.PATHS["SOL"], "2024-01-01", "2024-02-01")
df5 = bot._resample_ohlcv(df1, "5m")
print(f"df5 {len(df5)} bars {df5.index[0]} .. {df5.index[-1]}", flush=True)

rows = []
for k, c in enumerate(cases):
    scan0 = pd.Timestamp(c["scan"])
    cbt = pd.Timestamp(c["cbt"])
    j0 = int(df5.index.searchsorted(cbt + pd.Timedelta(minutes=5)))
    j1 = int(df5.index.searchsorted(scan0)) + 7
    j1 = min(j1, len(df5) - 1)
    found = None
    for j in range(j0, j1 + 1):
        if j < 300:
            continue
        sl = df5.iloc[j - 299 : j + 1]
        sigs = bot.detect_signals(
            sl, set(), htf_ratio=HTF, tf_name="tf7", df_confirm=None, min_sweep_atr=0.0
        ) or []
        for s in sigs:
            if str(s.get("direction")) != c["dir"]:
                continue
            if str(s.get("confirm_bar_time"))[:19] != c["cbt"]:
                continue
            ent = float(s.get("entry") or 0)
            if ent <= 0 or abs(ent - c["entry"]) / c["entry"] > 0.01:
                continue
            found = (pd.Timestamp(df5.index[j]), s)
            break
        if found:
            break
    if not found:
        print(f"{c['scan']} {c['hash']} {c['dir']} e={c['entry']} -> NO-SIGNAL-FOUND (jan)", flush=True)
        continue
    bar_ts, s = found
    direction = c["dir"]
    entry = float(s.get("entry") or 0)
    stop = float(s.get("stop") or 0)
    tp = float(s.get("tp") or 0)
    if entry <= 0 or stop <= 0 or entry == stop or tp <= 0:
        print(f"{c['scan']} {c['hash']} -> BAD-FIELDS e={entry} s={stop} tp={tp}", flush=True)
        continue
    got = lf._outcome(df1, str(bar_ts), direction, entry, stop, tp)
    if got is None:
        print(f"{c['scan']} {c['hash']} {direction} first={bar_ts} e={entry} -> NO-FILL", flush=True)
        rows.append(dict(scan=c["scan"], h=c["hash"], dir=direction, first=str(bar_ts), kind="nofill", r=0.0))
        continue
    kind, r, exit_ts = got
    rows.append(dict(scan=c["scan"], h=c["hash"], dir=direction, first=str(bar_ts), kind=kind, r=float(r)))
    print(f"{c['scan']} {c['hash']} {direction} first={bar_ts} e={entry} s={stop} tp={tp} -> {kind} r={r:+.2f}", flush=True)

print("\n==== SUMMARY (class fib_stretch_market, jan SOL, live model) ====")
n = len(rows)
tp = sum(1 for r_ in rows if r_["kind"] == "tp")
sl = sum(1 for r_ in rows if r_["kind"] == "sl")
tm = sum(1 for r_ in rows if r_["kind"] == "time")
nf = sum(1 for r_ in rows if r_["kind"] == "nofill")
s = sum(r_["r"] for r_ in rows)
print(f"n={n} tp={tp} sl={sl} time={tm} nofill={nf} SumR={s:+.1f} AvgR={(s/n if n else 0):+.3f}")
with open("fib_class_rows.pkl", "wb") as f:
    pickle.dump(rows, f)
