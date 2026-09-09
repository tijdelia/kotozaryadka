#!/usr/bin/env python3
"""Страница для прослушивания Б и П — парами.

Б и П отличаются одним признаком: у Б связки включаются до взрыва, у П
нет. Проверить это машиной я не смог: детектор взрыва цепляется то за
начало файла, то за середину слова, и его выводам верить нельзя. Зато
ухо ловит разницу мгновенно, если поставить БА и ПА подряд. Поэтому
страница построена парами, а не списком.
"""
import json, os, re, sys

SP = "/tmp/claude-1000/-home-amolod-dev-logoped/d83516c8-76b5-4294-896e-00556d39b00c/scratchpad"
man = json.load(open(os.path.join(SP, "_manifest.json")))
new = set(json.load(open(os.path.join(SP, "_novye.json"))))

PAIRS_BP = [("БА","ПА"),("БО","ПО"),("БУ","ПУ"),("БЫ","ПЫ"),("БЭ","ПЭ"),
         ("АБА","АПА"),("ОБО","ОПО"),("УБУ","УПУ"),("ЫБЫ","ЫПЫ"),
         ("АБ","АП"),("ОБ","ОП"),("УБ","УП"),("ЫБ","ЫП"),
         ("БА-БО","ПА-ПО"),("БУ-БЫ","ПУ-ПЫ"),
         ("БОЧКА","ПОЧКА"),("БАЛКА","ПАЛКА"),("БУХ","ПУХ")]

PAIRS_SZ = [("СА","ЗА"),("СО","ЗО"),("СУ","ЗУ"),("СЫ","ЗЫ"),("СЭ","ЗЭ"),
            ("АСА","АЗА"),("ОСО","ОЗО"),("УСУ","УЗУ"),("ЫСЫ","ЫЗЫ"),
            ("СА-СО","ЗА-ЗО"),("СУ-СЫ","ЗУ-ЗЫ"),
            ("СОК","ЗОНТ"),("САНКИ","ЗАЯЦ"),("СУМКА","ЗУБЫ"),("СОВА","ЗВОНОК")]

SETS = [("Б и П", "Слева Б, справа П.", PAIRS_BP),
        ("С и З", "Слева С — горло молчит. Справа З — горло гудит.", PAIRS_SZ)]

def au(t):
    n = man.get(t.lower())
    return f'<audio controls preload="none" src="audio/{n}.mp3"></audio>' if n else "<i>нет</i>"

def main():
    used = {w.lower() for _, _, ps in SETS for p in ps for w in p}
    rows = []
    for title, how, ps in SETS:
        rows.append(f'<h2>{title} — слушайте подряд</h2>'
                    f'<p class="how">{how} Включите оба подряд: если разница слышна сразу, '
                    f'слог годится. Если звучат одинаково — скажите, перезапишем.</p>')
        for a, b in ps:
            rows.append(f'<div class="pr"><div class="c b"><span class="w">{a}</span>{au(a)}</div>'
                        f'<div class="c p"><span class="w">{b}</span>{au(b)}</div></div>')

    rest = sorted(t for t in new if t not in used)
    words = [t for t in rest if " " not in t]
    say   = [t for t in rest if " " in t]
    if words:
        rows.append(f'<h2>Слова — {len(words)}</h2>')
        rows += [f'<div class="i"><span class="w">{t.upper()}</span>{au(t)}</div>' for t in words]
    if say:
        rows.append(f'<h2>Чистоговорки — {len(say)}</h2>')
        rows += [f'<div class="i"><span class="w sm">{t}</span>{au(t)}</div>' for t in say]

    open("poslushat-pary.html", "w", encoding="utf-8").write(
        HTML.replace("{{ROWS}}", "\n".join(rows)).replace("{{N}}", str(len(new))))
    print(f"poslushat-pary.html готов: {len(new)} новых фраз, "
          f"{sum(len(p) for _,_,p in SETS)} пар")


HTML = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Котозарядка — пары звуков</title>
<style>
  :root{--paper:#F1EFEA;--card:#fff;--ink:#191713;--muted:#8C877D;--line:#E2DFD8;--accent:#FF4D6D}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--paper);color:var(--ink);font-weight:600;
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       -webkit-font-smoothing:antialiased;padding:26px 18px 70px}
  main{max-width:680px;margin:0 auto}
  h1{font-size:26px;font-weight:800;letter-spacing:-.02em}
  h2{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;
     color:var(--muted);margin:32px 0 6px}
  .lead{font-size:15px;line-height:1.6;font-weight:500;color:#3D3A34;margin-top:10px}
  .how{font-size:14px;font-weight:500;color:var(--muted);line-height:1.5;margin-bottom:10px}
  .pr{display:flex;gap:10px;margin-top:8px}
  .c{flex:1;background:var(--card);border-radius:16px;padding:12px 14px;min-width:0}
  .c.b{box-shadow:inset 0 0 0 2px #8FBEE8}
  .c.p{box-shadow:inset 0 0 0 2px #FFC46B}
  .i{background:var(--card);border-radius:16px;padding:12px 16px;margin-top:8px;
     display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  .w{font-size:21px;font-weight:800;display:block;margin-bottom:6px}
  .i .w{margin:0;flex:1;min-width:110px}
  .w.sm{font-size:16px}
  audio{width:100%;height:34px}
</style>
<main>
  <h1>Пары звуков — послушайте подряд</h1>
  <p class="lead">Б/П и С/З устроены одинаково: слева глухой, справа звонкий.
     Проверить это машиной надёжно не вышло — у Б и П согласный длится
     миллисекунды, у С и З разрыв есть, но замер цепляет гласную. Ухо надёжнее.
     Скажите, что перезаписать, или продиктуйте сами.</p>
  {{ROWS}}
</main>
</html>
"""

if __name__ == "__main__":
    main()
