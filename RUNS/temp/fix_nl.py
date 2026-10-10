p = r"D:\PYTHON\cisdbotbybit\RUNS\SUMMARY_ALL_2026-10-01.md"
s = open(p, encoding="utf-8").read()
bad = "+89.7." + chr(92) + "nДублирование"
n = s.count(bad)
s = s.replace(bad, "+89.7.\nДублирование")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("fixed:", n)
i = s.find("Новые пары (03.10)")
print(s[i:i+280])
