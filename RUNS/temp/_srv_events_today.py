import collections
import json

import pandas as pd

pd.set_option("display.width", 250)
ev = [json.loads(l) for l in open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/trades_2026-09.jsonl", encoding="utf-8") if l.strip()]
d = pd.DataFrame(ev)
d["t"] = pd.to_datetime(d.logged_at)
d["day"] = d.t.dt.strftime("%m-%d")
print("период событий:", d.t.min(), "..", d.t.max())
print()
for day in ("09-14", "09-15"):
    g = d[d.day == day]
    print(f"=== {day}: {len(g)} событий ===")
    print(g.groupby(["event", "direction"]).size().to_string())
    print()
print("=== signal_skipped за 09-15: причины × направление ===")
s = d[(d.day == "09-15") & (d.event == "signal_skipped")]
print(s.groupby(["skip_reason", "direction"]).size().sort_values(ascending=False).to_string())
print()
print("=== created/filled/closed за 09-15 по ТФ и направлению ===")
for e in ("pending_created", "entry_filled", "closed"):
    g = d[(d.day == "09-15") & (d.event == e)]
    print(f"  {e}: " + str(dict(g.groupby(["tf", "direction"]).size())))
print()
print("=== все signal_skipped 09-15 (первые 25) ===")
print(s[["t", "symbol", "tf", "direction", "skip_reason", "vwap_dev", "signal_entry"]].head(25).to_string(index=False))
print()
print("=== closed 09-14/09-15: факт закрытия ===")
c = d[d.event == "closed"]
print(c[["t", "symbol", "tf", "direction", "id"]].to_string(index=False))
