p = r"D:\PYTHON\cisdbotbybit\RUNS\temp\STOP_TIMING_2026-10-02.md"
s = open(p, encoding="utf-8").read()
bad = "+" + chr(92) + "u200bBTC"
n = s.count(bad)
s = s.replace(bad, "+BTC")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("fixed occurrences:", n)
i = s.find("Убрано 144")
print(repr(s[i:i+120]))
