#!/usr/bin/env python3
"""Переозвучка коротких слов и слогов.

Короткое слово модель отдельно произносить не умеет — ей не за что
зацепиться. Поэтому оно говорится в конце длинной знакомой фразы-зачина,
а потом вырезается. Всё дело в том, где резать.

Раньше граница искалась по паузе внутри звука: берём самую близкую к
ожидаемому месту. Ожидаемое место считалось по длине текста в буквах, и
на коротких словах промахивалось на целый слог — «фонтан» превращался в
«дан», а «конфета» в «а». По громкости это не видно: кусок звонкий,
нужной длины, просто не то слово.

Теперь границу говорит распознаватель. Зачин — обычная русская фраза,
её он разбирает уверенно и с метками слов. Конец последнего слова зачина
и есть граница; дальше ищем, где снова начался звук, — это и есть начало
нашего слова. Само слово распознавать не нужно: слогов вроде «ыф-фы» в
русском языке нет, и на них любой распознаватель фантазирует.
"""
import json, os, re, subprocess, sys
import numpy as np

sys.argv = [sys.argv[0]]
import importlib.util
_s = importlib.util.spec_from_file_location("g", "tools-озвучка2.py")
g = importlib.util.module_from_spec(_s); _s.loader.exec_module(g)

OUT   = "audio_new3"
REF   = "ref_mama.wav"
RTEXT = "Привет! Сегодня мы будем заниматься вместе. Слушай внимательно и повторяй за мной."
TRIES = 4

# зачины: обычные фразы, которые распознаватель разбирает без ошибок
CARRIERS = [
    "Мы сегодня очень хорошо позанимались вместе.",
    "Я очень рада что мы с тобой сегодня позанимались.",
    "Смотри как здорово мы с тобой поработали сегодня.",
    "Сегодня мы с тобой хорошо потрудились вместе.",
]


def onset(x, sr, after, thr_rel=0.06, back=0.035):
    """Первый звук после метки: идём по огибающей и берём начало всплеска."""
    win = int(sr * 0.01)
    env = np.array([np.sqrt((x[i:i+win]**2).mean()) for i in range(0, len(x)-win, win)])
    if env.max() < 1e-6: return None
    thr = env.max() * thr_rel
    i0 = int(after * sr / win)
    for i in range(max(0, i0), len(env)):
        if env[i] > thr:
            return max(0.0, i * win / sr - back)
    return None


def main():
    todo = json.load(open("/tmp/_perezvuchka.json"))
    print(f"переозвучиваем {len(todo)}")

    import torch
    from ruaccent import RUAccent
    from huggingface_hub import hf_hub_download
    from f5_tts.infer.utils_infer import (infer_process, load_model, load_vocoder,
                                          preprocess_ref_audio_text)
    from f5_tts.model import DiT
    from faster_whisper import WhisperModel

    cfg = g.MODELS["f5ru"]
    ckpt  = hf_hub_download(cfg["repo"], cfg["file"])
    vocab = hf_hub_download(cfg["vocab"][0], cfg["vocab"][1])
    g.patch_torchaudio(); g.patch_ruaccent()
    acc = RUAccent(); acc.load(omograph_model_size='turbo3.1', use_dictionary=True, tiny_mode=False)
    stress = lambda t: t if '+' in t else g.clean_stress(acc.process_all(t))
    vocoder = load_vocoder()
    model = load_model(DiT, cfg["arch"], ckpt, vocab_file=vocab)
    ref_audio, ref_text = preprocess_ref_audio_text(REF, stress(RTEXT))
    asr = WhisperModel("medium", device="cuda", compute_type="float16")
    print("→ готово, поехали")

    def cut(text, speed, car):
        w, sr, _ = infer_process(ref_audio, ref_text, stress(car + " " + text), model,
                                 vocoder, speed=speed, nfe_step=32, cross_fade_duration=0.15)
        w = np.asarray(w, dtype=np.float32)
        p = "/tmp/_cut.wav"
        import soundfile as sf; sf.write(p, w, sr)
        segs, _ = asr.transcribe(p, language="ru", word_timestamps=True, beam_size=5)
        words = [x for s in segs for x in s.words]
        if not words: return None, sr
        # последнее слово зачина: ищем по его хвосту, а не по номеру —
        # распознаватель мог склеить или разбить слова
        last = re.sub(r"[^а-яё]", "", car.lower().split()[-1])
        end = None
        for x in words:
            if re.sub(r"[^а-яё]", "", x.word.lower()).endswith(last[-5:]): end = x.end
        if end is None: return None, sr
        st = onset(w, sr, end + 0.02)
        if st is None or st * sr >= len(w) - int(sr * 0.15): return None, sr
        return g.trim(w[int(st*sr):], 0.012), sr

    def need(t):
        """Слоги на медленном темпе идут примерно два с половиной в секунду.
        Нижнюю границу держим строго: обрезанный слог всегда короткий, и
        именно по длине его и видно."""
        n = max(1, sum(c in g.SYL for c in t.lower()))
        return n / 3.2, n / 1.2

    man, bad = {}, []
    for i, (text, reg) in enumerate(todo):
        sp = g.SPEED[reg]
        lo, hi = need(text)
        best, bsr, bd = None, None, 0
        for k in range(TRIES):
            w, sr = cut(text, sp, CARRIERS[(i + k) % len(CARRIERS)])
            if w is None or len(w) == 0: continue
            d = len(w) / sr
            if lo <= d <= hi and float(np.abs(w).max()) > 0.05:
                best, bsr, bd = w, sr, d; break
            if best is None or abs(d - lo) < abs(bd - lo):
                best, bsr, bd = w, sr, d
        if best is None:
            bad.append(text); print(f"  {i+1}/{len(todo)}  ПРОВАЛ  {text}"); continue
        n = g.slug(text.strip().lower())
        g.save_mp3(f"{OUT}/{n}.mp3", best, bsr)
        man[text.strip().lower()] = n
        flag = "" if lo <= bd <= hi else "  ← длина странная"
        print(f"  {i+1}/{len(todo)}  {text[:28]:28s} {bd:.2f}с (ждали {lo:.2f}–{hi:.2f}){flag}", flush=True)

    json.dump(man, open("/tmp/_perezvuchka_man.json", "w"), ensure_ascii=False)
    if bad: print("\nне вышло:", ", ".join(bad))


if __name__ == "__main__":
    main()
