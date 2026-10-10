# dup_match.py — точный матч по ключам: что именно отсеивает гейт vs dt-фильтр (SOL/2025).
import pickle
import pandas as pd


def load(p):
    with open(p, "rb") as f:
        return pd.DataFrame(pickle.load(f))


def dt(df):
    return (pd.to_datetime(df["cbt"]) - pd.to_datetime(df["tbt"])).dt.total_seconds() / 60.0


BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt"
g = load(BASE + r"\stopt_tf1lc15_alloff_l1h\SOL_2025.pkl")
m = load(BASE + r"\quick_tp_tf1ng_q\SOL_2025.pkl")


def key(df):
    return list(zip(df["direction"], df["scan"].astype(str), df["cbt"].astype(str)))


g["k"] = key(g)
m["k"] = key(m)
kg, km = set(g["k"]), set(m["k"])
common = kg & km
print(f"gated n={len(g)} | ng n={len(m)} | общие={len(common)} | только-gated={len(kg-km)} | только-ng={len(km-kg)}")

only_ng = m[m["k"].isin(km - kg)]
only_g = g[g["k"].isin(kg - km)]
inter_g = g[g["k"].isin(common)]
inter_m = m[m["k"].isin(common)]

for name, df in [
    ("гейт отсеял (только-ng)  ", only_ng),
    ("только-gated (dt бы отсек/пустил)", only_g),
    ("общие                   ", inter_g),
]:
    d = dt(df)
    print(f"{name}: n={len(df):3d} | <2ч: {int((d<120).sum()):3d} ({(d<120).mean()*100:3.0f}%) | SR={df['r'].sum():+6.1f}")

# для общих проверим совпадение r (same trade)
mm = inter_m.set_index("k"); gg = inter_g.set_index("k")
diff = sum(1 for k in common if abs(mm.loc[k, "r"] - gg.loc[k, "r"]) > 1e-9)
print("общие с отличающимся r:", diff)

# Сводка-пересечение: сколько из "быстрых" (<2ч) в ng-потоке отсеял гейт
ng_fast = m[dt(m) < 120]
print(f"\nng-быстрые: {len(ng_fast)}; из них 'прошли гейт' (есть в gated): {ng_fast['k'].isin(kg).sum()}; отсеяно гейтом: {(~ng_fast['k'].isin(kg)).sum()}")
