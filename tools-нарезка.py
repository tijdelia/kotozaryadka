#!/usr/bin/env python3
"""
Нарезка одной длинной записи на отдельные файлы озвучки.

Родитель читает список вслух одним заходом, делая паузу между словами.
Скрипт режет запись по паузам и раскладывает куски по именам файлов.

    python3 tools-нарезка.py --in звуки.m4a --list звуки.txt --check
    python3 tools-нарезка.py --in звуки.m4a --list звуки.txt --out audio --write-app

--check  — только показать, что нашлось, ничего не записывая.

Живой голос всегда лучше синтеза, а для тянущихся звуков и отдельных букв
он вообще единственный рабочий вариант: синтез их не умеет.
"""
import argparse, json, os, re, subprocess, sys, wave
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_t = __import__("importlib").import_module("importlib.util")
_spec = _t.spec_from_file_location("gen", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                       "tools-озвучка2.py"))
gen = _t.module_from_spec(_spec); _spec.loader.exec_module(gen)


def read_wav(path):
    if not path.lower().endswith(".wav"):
        tmp = "/tmp/_cut_in.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path,
                        "-ar", "24000", "-ac", "1", tmp], check=True)
        path = tmp
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    return x, sr


def split(x, sr, gap, thr):
    """Режем по паузам. gap — сколько тишины считать границей, секунд."""
    win = int(sr * 0.02)
    env = np.array([np.sqrt((x[i:i + win] ** 2).mean()) for i in range(0, len(x) - win, win)])
    if env.max() < 1e-4: return []
    hot = env > env.max() * thr
    out, st, g = [], None, 0
    for i, h in enumerate(hot):
        if h:
            if st is None: st = i
            g = 0
        elif st is not None:
            g += 1
            if g * 0.02 > gap:
                out.append((max(0, st - 3) * win, (i - g + 3) * win)); st = None; g = 0
    if st is not None: out.append((max(0, st - 3) * win, len(x)))
    return [(a, b) for a, b in out if b - a > sr * 0.12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="запись целиком")
    ap.add_argument("--list", required=True, help="файл со списком фраз, по одной в строке")
    ap.add_argument("--out", default="audio")
    ap.add_argument("--gap", type=float, default=0.35, help="длина паузы между словами, секунд")
    ap.add_argument("--thr", type=float, default=0.035, help="порог тишины от пика")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write-app", action="store_true")
    a = ap.parse_args()

    items = [l.strip() for l in open(a.list, encoding="utf-8") if l.strip()
             and not l.strip().startswith("#")]
    x, sr = read_wav(a.src)
    print(f"запись: {len(x)/sr:.1f} с, в списке {len(items)} фраз")

    # подбираем паузу так, чтобы кусков вышло ровно столько же, сколько фраз
    best = None
    for gap in (a.gap, 0.30, 0.25, 0.40, 0.45, 0.50, 0.20, 0.60):
        for thr in (a.thr, 0.02, 0.05, 0.08):
            cs = split(x, sr, gap, thr)
            if best is None or abs(len(cs) - len(items)) < abs(best[0] - len(items)):
                best = (len(cs), gap, thr, cs)
            if len(cs) == len(items):
                print(f"совпало при паузе {gap} с и пороге {thr}")
                best = (len(cs), gap, thr, cs); break
        if best[0] == len(items): break

    n, gap, thr, cs = best
    if n != len(items):
        print(f"\nНЕ СОВПАЛО: кусков {n}, фраз {len(items)} (лучшее при паузе {gap}, пороге {thr})")
        for i, (s, e) in enumerate(cs):
            print("  %2d  %5.2f–%5.2f с  (%.2f с)" % (i + 1, s / sr, e / sr, (e - s) / sr))
        print("\nЕсли кусков больше — вы сделали паузу внутри слова; если меньше —"
              " паузы между словами слишком короткие. Перезапишите с паузой в секунду,"
              " либо задайте --gap вручную.")
        return

    print()
    for (s, e), t in zip(cs, items):
        print("  %-32s %5.2f с" % (t, (e - s) / sr))
    if a.check:
        print("\nпроверка, ничего не записано")
        return

    os.makedirs(a.out, exist_ok=True)
    man = {}
    for (s, e), t in zip(cs, items):
        seg = x[s:e].copy()
        r = min(len(seg) // 8, int(sr * 0.03))
        if r > 1:                                  # мягкие края, чтобы не щёлкало
            seg[:r] *= np.linspace(0, 1, r); seg[-r:] *= np.linspace(1, 0, r)
        fn = gen.slug(t.strip().lower())
        gen.save_mp3(f"{a.out}/{fn}.mp3", seg, sr)
        man[t.strip().lower()] = fn
    print(f"\nзаписано файлов: {len(man)} в {a.out}/")

    if a.write_app:
        old = json.load(open("/tmp/_manifest.json")) if os.path.exists("/tmp/_manifest.json") else {}
        old.update(man)
        json.dump(old, open("/tmp/_manifest.json", "w"), ensure_ascii=False, indent=0)
        gen.write_app(old)


if __name__ == "__main__":
    main()
