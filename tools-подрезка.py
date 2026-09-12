#!/usr/bin/env python3
"""Подрезка нарезанных файлов — только тишина ПЕРЕД словом.

Сначала я срезал и хвост тоже, и это оказалось ошибкой: конец слова у
русских слов тихий — «снеговиК», «солнцЕ», «дождиК», — глухой согласный
в разы слабее гласной и уходит под любой разумный порог. Проверка
распознаванием показала «снеговик» → «гайвик», «солнце» → «сон»,
«дождик» → «дождь». Лишняя тишина в конце не мешает никому, а съеденное
окончание ребёнок повторит за приложением неправильно.

Поэтому трогаем только начало, и только когда тишины действительно много.

Нарезка по паузам оставляет по краям куска запас тишины, а вместе с ним
случайный щелчок, вдох или стук — они попадают в файл и звучат в игре
как непонятный призвук. Плюс ребёнок ждёт: полсекунды тишины перед
словом для пятилетки это вечность, он успевает отвлечься.

Отдельно — паузы внутри. В слове их быть не должно: если слог прочитан
в два приёма («ыф … фы»), ребёнок слышит два разных звука вместо одного
и повторяет их порознь. Внутри фразы пауза законна, там не трогаем.

    python3 tools-подрезка.py --dir audio --list /tmp/_golos_man.json
"""
import argparse, json, os, subprocess, wave
import numpy as np

SR = 24000
_u = __import__("importlib").import_module("importlib.util")
_s = _u.spec_from_file_location("gen", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "tools-озвучка2.py"))
gen = _u.module_from_spec(_s); _s.loader.exec_module(gen)


def load(p):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p, "-ar", str(SR), "-ac", "1",
                    "/tmp/_tr.wav"], check=True)
    with wave.open("/tmp/_tr.wav", "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


def runs(e, thr):
    out, s0 = [], None
    for i, h in enumerate(e > thr):
        if h and s0 is None: s0 = i
        elif not h and s0 is not None: out.append((s0, i)); s0 = None
    if s0 is not None: out.append((s0, len(e)))
    return out


def polish(x, phrase):
    """Три осторожных правки, каждая — только там, где она заведомо безопасна.

    1. Тишина перед словом. Если в начале больше 0,4 с на уровне шума,
       срезаем, оставляя 0,12 с. У «СОК» и «СУП» так висело по шестьсот
       миллисекунд: ребёнок нажал картинку и ждёт, пока приложение молчит.
    2. Щелчок в хвосте. Короткий всплеск, оторванный от слова паузой
       больше 0,4 с, — это вдох, стук или шорох страницы, не речь.
    3. Пауза внутри слова. Слог, прочитанный в два приёма («ыф … фы»),
       ребёнок слышит как два разных звука и повторяет их порознь.
       Внутри фразы пауза законна — там не трогаем.

    Чего здесь нет намеренно: подрезки конца. Русское слово кончается тихо
    («снеговиК», «солнцЕ», «дождиК»), глухой согласный в разы слабее
    гласной и уходит под любой разумный порог. Я это попробовал, и
    проверка распознаванием показала «снеговик» → «гайвик», «солнце» →
    «сон». Лишняя тишина в конце не мешает никому."""
    win = int(SR * 0.02)
    e = np.array([np.sqrt((x[i:i+win]**2).mean()) for i in range(0, max(1, len(x)-win), win)])
    if len(e) < 4 or e.max() < 1e-5: return x
    thr = e.max() * 0.12                      # уверенно выше шума и ниже любого согласного
    rs = runs(e, thr)
    if not rs: return x

    # 2. хвостовой щелчок
    while len(rs) > 1 and (rs[-1][1]-rs[-1][0])*0.02 < 0.15 and (rs[-1][0]-rs[-2][1])*0.02 > 0.40:
        rs = rs[:-1]
    # 1. тишина в начале
    pad = int(0.12/0.02)
    a = max(0, rs[0][0]-pad) if rs[0][0]*0.02 > 0.40 else 0
    end = min(len(e), rs[-1][1] + int(0.25/0.02))
    if end >= len(e)-1: end = len(e)
    # 3. пауза внутри слова
    keep, cur = [], a
    if not phrase:
        for k in range(len(rs)-1):
            if (rs[k+1][0]-rs[k][1])*0.02 > 0.45:
                keep.append((cur, min(len(e), rs[k][1]+int(0.12/0.02))))
                cur = max(0, rs[k+1][0]-pad)
    keep.append((cur, end))
    parts = [x[s0*win:min(len(x), s1*win)] for s0, s1 in keep if s1 > s0]
    if not parts: return x
    if len(parts) == 1: return parts[0]
    sil = np.zeros(int(SR*0.18), dtype=np.float32)
    out = parts[0]
    for q in parts[1:]: out = np.concatenate([out, sil, q])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="audio")
    ap.add_argument("--list", default="/tmp/_golos_man.json")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    man = json.load(open(a.list))
    changed = []
    for t, n in sorted(man.items()):
        p = f"{a.dir}/{n}.mp3"
        if not os.path.exists(p): continue
        x = load(p)
        y = polish(x, phrase=(" " in t))
        d0, d1 = len(x)/SR, len(y)/SR
        if abs(d0-d1) > 0.04:
            changed.append((t, d0, d1))
            if not a.check: gen.save_mp3(p, np.ascontiguousarray(y), SR)
    print(f"подрезано {len(changed)} из {len(man)}")
    for t, d0, d1 in sorted(changed, key=lambda r: r[1]-r[2], reverse=True)[:25]:
        print(f"    {t[:30]:30s} {d0:.2f} → {d1:.2f}с  (−{d0-d1:.2f})")


if __name__ == "__main__":
    main()
