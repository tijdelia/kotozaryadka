#!/usr/bin/env python3
"""
Готовит лист для записи голоса: страницу для чтения вслух и список для нарезки.

Оба файла делаются из одного источника — самого index.html, поэтому разъехаться
не могут. Родитель открывает только страницу; список нужен скрипту нарезки.

    python3 tools-лист-записи.py            # звуки и слова: 27 фраз
    python3 tools-лист-записи.py --похвала  # похвала: 22 фразы
"""
import argparse, importlib.util, os, re

_s = importlib.util.spec_from_file_location(
    "gen", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools-озвучка2.py"))
gen = importlib.util.module_from_spec(_s); _s.loader.exec_module(gen)

# как произносить каждую группу — это единственное, что задаётся здесь руками
GROUPS = [
    ("Тянущиеся звуки", "Тяни долго, четыре секунды. Один непрерывный звук, "
                        "а не четыре коротких.", "долго"),
    ("Гласные",         "Коротко и чётко, один раз.", "коротко"),
    ("Слоги",           "Медленно, разделяя звуки.", "медленно"),
    ("Слова",           "Медленно и раздельно, как показываете сыну на занятии, "
                        "а не как в обычной речи.", "медленно"),
    ("Чистоговорка",    "Обычным темпом, как говорите всегда.", "обычно"),
]
NOTE = {
    "в-в-в-в": "нижняя губа к верхним зубам, с голосом — горло дрожит",
}


# похвалу читают обычным голосом — она звучит в приложении чаще всего
PRAISE_GROUPS = [("Похвала", "Обычным голосом, тепло, как говорите сыну на самом деле. "
                             "Не диктуйте — хвалите.", "обычно")]


def collect_praise():
    return [[t for t, r in gen.phrases_from_app() if r == "norm"]]


def collect():
    items = gen.phrases_from_app()
    slow = [t for t, r in items if r == "slow"]
    hold  = [t for t in slow if t.lower() in gen.HOLD] + ["в-в-в-в"]
    vow   = [t for t in slow if len(t) == 1]
    # «АВ-ВУ», «ФА-АФА» — это тоже слоги, хоть и длинные
    syl   = [t for t in slow if t.isupper() and (2 <= len(t) <= 3 or "-" in t)]
    words = [t for t in slow if t.isupper() and t not in syl and len(t) > 3]
    rest  = [t for t in slow if t not in hold + vow + syl + words]
    return [hold, vow, syl, words, rest]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--похвала", action="store_true", dest="praise")
    ap.add_argument("--часть", type=int, default=0, dest="part",
                    help="номер части: список режется по 35 фраз")
    a = ap.parse_args()

    if a.praise:
        groups, gdef = collect_praise(), PRAISE_GROUPS
        list_name, page_name, title = "похвала-для-записи.txt", "zapis2.html", "Запись похвалы"
    else:
        groups, gdef = collect(), GROUPS
        list_name, page_name, title = "звуки-для-записи.txt", "zapis.html", "Запись голоса"

    flat = [t for g in groups for t in g]

    # длинный список режем на части: 97 фраз за один присест — перебор
    CH = 35
    total_parts = -(-len(flat) // CH)
    if a.part:
        lo, hi = (a.part - 1) * CH, a.part * CH
        keep = set(flat[lo:hi])
        if not keep:
            raise SystemExit(f"части {a.part} нет: всего {-(-len(flat)//CH)}")
        groups = [[t for t in g if t in keep] for g in groups]
        flat = flat[lo:hi]
        list_name = list_name.replace(".txt", f"-{a.part}.txt")
        page_name = page_name.replace(".html", f"-{a.part}.html")
        title += f" — часть {a.part} из {total_parts}"


    with open(list_name, "w", encoding="utf-8") as f:
        f.write("# порядок строго как на странице записи, менять нельзя\n")
        f.write("\n".join(flat) + "\n")

    rows, n = [], 0
    for (gt, how, tag), g in zip(gdef, groups):
        rows.append(f'<h2>{gt}</h2><p class="how">{how}</p>')
        for t in g:
            n += 1
            note = NOTE.get(t.lower(), "")
            rows.append(
                f'<div class="i"><span class="n">{n}</span>'
                f'<span class="w {tag}">{t}</span>'
                + (f'<span class="note">{note}</span>' if note else "") + "</div>")

    html = (HTML.replace("{{ROWS}}", "\n".join(rows))
                .replace("{{N}}", str(n)).replace("{{TITLE}}", title))
    open(page_name, "w", encoding="utf-8").write(html)
    print(f"страница {page_name} и список {list_name} готовы: {n} фраз")


HTML = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Котозарядка — {{TITLE}}</title>
<style>
  :root{--paper:#F1EFEA;--card:#fff;--ink:#191713;--muted:#8C877D;--line:#E2DFD8;--accent:#FF4D6D}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--paper);color:var(--ink);
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       -webkit-font-smoothing:antialiased;padding:28px 20px 80px;font-weight:600}
  main{max-width:640px;margin:0 auto}
  h1{font-size:27px;font-weight:800;letter-spacing:-.02em}
  h2{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;
     color:var(--muted);margin:34px 0 4px}
  .lead{font-size:16px;line-height:1.6;font-weight:500;color:#3D3A34;margin-top:12px}
  .rules{background:var(--card);border-radius:18px;padding:16px 18px;margin:18px 0 6px}
  .rules li{font-size:15px;line-height:1.65;font-weight:500;color:#3D3A34;margin-left:18px}
  .rules b{font-weight:800;color:var(--ink)}
  .how{font-size:14px;font-weight:500;color:var(--muted);line-height:1.5;margin-bottom:10px}
  .i{background:var(--card);border-radius:16px;padding:14px 18px;margin-top:8px;
     display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  .n{font-size:13px;font-weight:800;color:var(--line);min-width:24px}
  .w{font-size:32px;font-weight:800;letter-spacing:-.01em;flex:1}
  .w.долго{color:var(--accent)}
  .w.обычно{font-size:24px}
  .note{font-size:13px;font-weight:600;color:var(--muted);flex-basis:100%;
        padding-left:38px;line-height:1.4}
  .end{margin-top:36px;background:var(--card);border-radius:18px;padding:18px}
  .end p{font-size:15px;line-height:1.6;font-weight:500;color:#3D3A34}
</style>
<main>
  <h1>{{TITLE}}</h1>
  <p class="lead">Всего {{N}} фраз, минуты три. Читайте сверху вниз одной записью,
     не останавливая её. <b>Крупным</b> — то, что говорить. Мелким серым — как.</p>

  <ul class="rules">
    <li>Между фразами — <b>пауза в секунду</b>. Молча, отчётливо. По ней я режу запись.</li>
    <li>Внутри фразы не молчать, иначе она разрежется пополам.</li>
    <li>Ошиблись — <b>не перезаписывайте</b>: помолчите две секунды и скажите фразу заново.
        Лишний кусок я уберу.</li>
    <li>Тихая комната, телефон в 20–30 см ото рта.</li>
    <li>Тот же голос и та же манера, что в первой записи.</li>
  </ul>

  {{ROWS}}

  <div class="end">
    <p><b>Готово.</b> Положите файл в папку проекта и скажите мне его имя.</p>
  </div>
</main>
</html>
"""

if __name__ == "__main__":
    main()
