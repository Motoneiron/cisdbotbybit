"""Проверка смоуков абляций: таймстампы + сверка BASE с tf7_pairs C5."""
import pickle

b = pickle.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_abl/BASE_rerun_SOL_2026.pkl", "rb"))
m = pickle.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_abl/ABL_MSS_MAIN_SOL_2026.pkl", "rb"))
c = pickle.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_pairs/C5_limit_1r_SOL_2026.pkl", "rb"))
for nm, d in (("BASE       ", b), ("ABL_MSS_MAIN", m), ("C5_tf7pairs ", c)):
    s = sum(float(x["r_net_mexc"]) for x in d)
    print(nm, "n=", len(d), "SumR=%+.1f" % s)
print("\nBASE sample:", {k: b[0].get(k) for k in ("outcome", "direction", "entry_ts", "exit_ts", "created_ts", "entry_bar", "htf_time", "sp")})
hb = {str(x["hash"]) for x in b}
hc = {str(x["hash"]) for x in c}
hm = {str(x["hash"]) for x in m}
print("\nBASE vs C5_tf7pairs: общих хешей", len(hb & hc), "из C5", len(hc))
print("BASE vs MSS_MAIN : общих хешей", len(hb & hm), "из MAIN", len(hm))

# sanity: exit >= entry, окно удержания
from datetime import datetime
def dt(s): return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
ok = [x for x in b if x.get("entry_ts") and x.get("exit_ts")]
bad = [x for x in ok if dt(x["entry_ts"]) > dt(x["exit_ts"])]
durs = [(dt(x["exit_ts"]) - dt(x["entry_ts"])).total_seconds() / 3600 for x in ok]
print("exit<entry:", len(bad), "из", len(ok), "| удержание ч: макс %.1f, сред %.1f" % (max(durs), sum(durs) / len(durs)))
print("sample2:", {k: b[5].get(k) for k in ("outcome", "created_ts", "entry_ts", "exit_ts")})
