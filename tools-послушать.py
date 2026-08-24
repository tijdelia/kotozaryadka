#!/usr/bin/env python3
"""Страница для прослушивания свежей озвучки.

Машина проверяет озвучку распознавателем, но на слогах вроде «ыф-фы»
распознаватель бесполезен: таких слов в русском нет, и он придумывает
что угодно. Последнее слово за мамой — поэтому всё, что вызывает
сомнение, выносится наверх отдельным списком.
"""
import json, os, re, sys, importlib.util

_s = importlib.util.spec_from_file_location("g", "tools-озвучка2.py")
g = importlib.util.module_from_spec(_s); _s.loader.exec_module(g)

OUT = "audio_new3"
rows = json.load(open("/tmp/_proverka.json"))
by = {r["t"]: r for r in rows}

# распознаватель не судья бессмысленным слогам — только словам
def real_word(t):
    return bool(re.fullmatch(r"[а-яё]+", t)) and t not in NONSENSE
NONSENSE = set()
for r in rows:
    t = r["t"]
    if re.fullmatch(r"[авфсоуыэи-]{1,7}", t) and not re.search(r"[бгджзклмнпртхцчшщ]", t):
        NONSENSE.add(t)

SYLL = lambda t: bool(re.fullmatch(r"[аоуыэивфс-]{1,7}", t))
GROUPS = [
    ("Слоги на В", lambda t: SYLL(t) and "в" in t),
    ("Слоги на Ф", lambda t: SYLL(t) and "ф" in t),
    ("Слоги на С", lambda t: SYLL(t) and "с" in t),
    ("Чистоговорки", lambda t: " " in t),
    ("Слова на Ф", lambda t: "ф" in t),
    ("Слова на С", lambda t: "с" in t),
    ("Слова на В", lambda t: "в" in t),
    ("Названия наклеек", lambda t: True),
]

def main():
    new = set(json.load(open("/tmp/_novye.json")))
    man = json.load(open("/tmp/_manifest.json"))
    items, seen = [], set()
    for title, test in GROUPS:
        g_items = []
        for t in sorted(new):
            if t in seen: continue
            if test(t): g_items.append(t); seen.add(t)
        if g_items: items.append((title, g_items))

    doubt = [t for t in sorted(new) if by.get(t, {}).get("v") != "ok"]

    def card(t):
        r = by.get(t, {})
        f = man.get(t, g.slug(t))
        q = r.get("v") != "ok"
        note = f'<span class="q">под вопросом</span>' if q else ""
        return (f'<div class="i{" q" if q else ""}"><span class="w">{t.upper()}</span>{note}'
                f'<audio controls preload="none" src="{OUT}/{f}.mp3"></audio></div>')

    body = []
    if doubt:
        body.append(f'<h2>Сначала эти — {len(doubt)}</h2>'
                    f'<p class="how">Машина в них не уверена. Послушайте и скажите номер или слово — '
                    f'переделаю или запишу с вашего голоса.</p>')
        body += [card(t) for t in doubt]
    for title, g_items in items:
        body.append(f'<h2>{title} — {len(g_items)}</h2>')
        body += [card(t) for t in g_items]

    html = HTML.replace("{{ROWS}}", "\n".join(body)).replace("{{N}}", str(len(new)))
    open("poslushat.html", "w", encoding="utf-8").write(html)
    print(f"poslushat.html готов: {len(new)} фраз, под вопросом {len(doubt)}")


HTML = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Котозарядка — послушать новую озвучку</title>
<style>
  :root{--paper:#F1EFEA;--card:#fff;--ink:#191713;--muted:#8C877D;--line:#E2DFD8;--accent:#FF4D6D}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--paper);color:var(--ink);font-weight:600;
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       -webkit-font-smoothing:antialiased;padding:26px 18px 70px}
  main{max-width:640px;margin:0 auto}
  h1{font-size:26px;font-weight:800;letter-spacing:-.02em}
  h2{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;
     color:var(--muted);margin:32px 0 6px}
  .lead{font-size:15px;line-height:1.6;font-weight:500;color:#3D3A34;margin-top:10px}
  .how{font-size:14px;font-weight:500;color:var(--muted);line-height:1.5;margin-bottom:10px}
  .i{background:var(--card);border-radius:16px;padding:12px 16px;margin-top:8px;
     display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  .i.q{box-shadow:inset 0 0 0 2px var(--accent)}
  .w{font-size:22px;font-weight:800;flex:1;min-width:110px}
  .q{font-size:11px;font-weight:800;color:#fff;background:var(--accent);
     border-radius:99px;padding:3px 9px;text-transform:uppercase;letter-spacing:.06em}
  audio{width:100%;height:36px}
</style>
<main>
  <h1>Новая озвучка — {{N}} фраз</h1>
  <p class="lead">Всё это раньше читал синтезатор планшета. Теперь — ваш голос,
     склонированный моделью с вашей записи. Послушайте и скажите, что переделать.</p>
  {{ROWS}}
</main>
</html>
"""

if __name__ == "__main__":
    main()
