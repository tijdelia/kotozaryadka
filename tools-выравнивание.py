#!/usr/bin/env python3
"""Нарезка длинной записи с выравниванием по списку.

Прежний скрипт резал по паузам и подбирал порог так, чтобы кусков вышло
ровно столько, сколько фраз в списке. Это работает, пока читают без
запинок. Но если фразу переписали — кусков стало больше, счёт сошёлся
случайно, и дальше весь список поехал на единицу: каждое слово получило
чужой файл, и заметить это можно было только на слух.

Здесь иначе. Куски режутся щедро, каждый распознаётся, и дальше список и
куски выравниваются как две последовательности — тем же способом, каким
сравнивают тексты. Порядок чтения известен, поэтому выравнивание почти
полностью определяется им, а распознавание нужно только чтобы понять,
где переписанный дубль, а где настоящая фраза. Лишние куски отбрасываются
сами, пропущенные фразы видны в отчёте.

    python3 tools-выравнивание.py --in запись.m4a --list звуки-для-записи.txt --check
    python3 tools-выравнивание.py --in запись.m4a --list звуки-для-записи.txt --out audio_golos
"""
import argparse, json, os, re, subprocess, sys, wave
from difflib import SequenceMatcher
import numpy as np

_u = __import__("importlib").import_module("importlib.util")
_s = _u.spec_from_file_location("gen", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "tools-озвучка2.py"))
gen = _u.module_from_spec(_s); _s.loader.exec_module(gen)

SR = 24000


def read_audio(path):
    tmp = "/tmp/_alg_in.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path,
                    "-ar", str(SR), "-ac", "1", tmp], check=True)
    with wave.open(tmp, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


def segments(x, gap=0.34, thr_rel=0.045, minlen=0.10):
    """Режем щедро: лучше лишний кусок, который отбросит выравнивание,
    чем две фразы, слипшиеся в одну.

    Порог считаем от тишины в комнате, а не от самого громкого места
    записи. От громкого — ловушка: одно эмоциональное «Молодец!» задирает
    планку, и короткие тихие слоги вроде «ап» перестают до неё дотягивать.
    Ровно так потерялись четыре слога подряд: звук в записи есть, слышно
    его отлично, а нарезка его не видела."""
    win = int(SR * 0.02)
    env = np.array([np.sqrt((x[i:i + win] ** 2).mean()) for i in range(0, len(x) - win, win)])
    floor = np.percentile(env, 20)
    thr = max(floor * 6, env.max() * thr_rel * 0.28, 1e-4)
    need = int(gap / 0.02)
    out, s0, run = [], None, 0
    for i, h in enumerate(env > thr):
        if h:
            if s0 is None: s0 = i
            run = 0
        elif s0 is not None:
            run += 1
            if run >= need:
                if (i - run - s0) * 0.02 >= minlen: out.append((s0, i - run))
                s0, run = None, 0
    if s0 is not None: out.append((s0, len(env)))
    pad = int(0.06 / 0.02)
    return [(max(0, a - pad) * win, min(len(x), (b + pad) * win)) for a, b in out]


norm = lambda t: re.sub(r"[^а-яё]", "", t.lower().replace("ё", "е"))


def score(want, heard):
    a, b = norm(want), norm(heard)
    if not a or not b: return 0.0
    return SequenceMatcher(None, a, b).ratio()


def align(want, heard):
    """Выравнивание Нидлмана—Вунша: можно пропустить лишний кусок (дубль)
    и можно пропустить фразу (не прочитали). Пропуск куска дешевле —
    дублей заведомо больше, чем пропусков."""
    n, m = len(want), len(heard)
    NEG = -1e9
    D = np.full((n + 1, m + 1), NEG)
    P = np.zeros((n + 1, m + 1), dtype=np.int8)
    D[0, 0] = 0
    for j in range(1, m + 1):
        D[0, j] = D[0, j - 1] - 0.25; P[0, j] = 2          # лишний кусок в начале
    for i in range(1, n + 1):
        D[i, 0] = D[i - 1, 0] - 1.0; P[i, 0] = 3
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best, arg = D[i - 1, j - 1] + (score(want[i - 1], heard[j - 1]) - 0.25), 1
            if D[i, j - 1] - 0.25 > best: best, arg = D[i, j - 1] - 0.25, 2
            if D[i - 1, j] - 1.0 > best:  best, arg = D[i - 1, j] - 1.0, 3
            D[i, j], P[i, j] = best, arg
    i, j, pairs = n, m, {}
    while i > 0 or j > 0:
        p = P[i, j]
        if p == 1: pairs[i - 1] = j - 1; i -= 1; j -= 1
        elif p == 2: j -= 1
        else: i -= 1
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--list", dest="lst", required=True)
    ap.add_argument("--out", default="audio_golos")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--around", default="")
    ap.add_argument("--gap", type=float, default=0.34)
    ap.add_argument("--thr", type=float, default=0.045)
    a = ap.parse_args()

    want = [l.strip() for l in open(a.lst, encoding="utf-8")
            if l.strip() and not l.startswith("#")]
    x = read_audio(a.src)
    segs = segments(x, gap=a.gap, thr_rel=a.thr)
    print(f"запись {len(x)/SR:.0f} с · кусков {len(segs)} · фраз в списке {len(want)}")

    from faster_whisper import WhisperModel
    mdl = WhisperModel(a.model, device="cuda", compute_type="float16")
    heard = []
    for k, (s, e) in enumerate(segs):
        p = "/tmp/_alg_seg.wav"
        with wave.open(p, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.clip(x[s:e], -1, 1) * 32767).astype("<i2").tobytes())
        txt = " ".join(t.text for t in mdl.transcribe(p, language="ru", beam_size=5)[0]).strip()
        heard.append(txt)
        if (k + 1) % 40 == 0: print(f"  распознано {k+1}/{len(segs)}", flush=True)

    pairs = align(want, heard)
    miss = [i for i in range(len(want)) if i not in pairs]
    used = set(pairs.values())
    extra = [j for j in range(len(segs)) if j not in used]
    weak = [(i, j) for i, j in sorted(pairs.items()) if score(want[i], heard[j]) < 0.34]

    print(f"\nсовпало {len(pairs)} из {len(want)} · лишних кусков {len(extra)} · не найдено {len(miss)}")
    if miss:
        print("\nНЕ НАЙДЕНО:"); [print("   ", want[i]) for i in miss]
    if weak:
        print(f"\nПОД ВОПРОСОМ ({len(weak)}) — распознано не так, но по порядку встало сюда:")
        for i, j in weak[:40]:
            print(f"    {want[i]:28s} услышано: {heard[j][:40]:40s} {(segs[j][1]-segs[j][0])/SR:.2f}с")

    SYL = "аеёиоуыэюя"
    short = []
    for i, j in sorted(pairs.items()):
        n_syl = max(1, sum(c in SYL for c in want[i].lower()))
        d = (segs[j][1] - segs[j][0]) / SR
        if d < n_syl * 0.18: short.append((want[i], d, n_syl))
    if short:
        print(f"\nСЛИШКОМ КОРОТКИЕ ({len(short)}) — похоже, кусок разорван:")
        for t, d, n in short: print(f"    {t:28s} {d:.2f}с (звуков {n})")

    if extra:
        print(f"\nЛИШНИЕ КУСКИ ({len(extra)}) — переписанные дубли или помехи:")
        for j in extra:
            d=(segs[j][1]-segs[j][0])/SR
            near=[want[i] for i,k in sorted(pairs.items()) if abs(k-j)<=1]
            print(f"    #{j} {d:.2f}с  услышано: {heard[j][:38]:38s} рядом: {', '.join(near)}")
    if a.around:
        lo,hi=[int(v) for v in a.around.split("-")]
        print(f"\nЛЕНТА {lo}–{hi}:")
        for i in range(max(0,lo),min(len(want),hi)):
            j=pairs.get(i)
            if j is None: print(f"    {i:3d} {want[i]:14s}  — не найдено")
            else:
                s0,e0=segs[j]
                print(f"    {i:3d} {want[i]:14s}  кусок #{j} {s0/SR:7.2f}с {(e0-s0)/SR:.2f}с  «{heard[j][:34]}»")
    if a.check: return
    os.makedirs(a.out, exist_ok=True)
    man = {}
    for i, j in pairs.items():
        s, e = segs[j]
        name = gen.slug(want[i].strip().lower())
        gen.save_mp3(f"{a.out}/{name}.mp3", np.ascontiguousarray(x[s:e]), SR)
        man[want[i].strip().lower()] = name
    json.dump(man, open("/tmp/_golos_man.json", "w"), ensure_ascii=False)
    print(f"\nзаписано {len(man)} файлов в {a.out}/")


if __name__ == "__main__":
    main()
