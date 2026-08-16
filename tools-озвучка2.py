#!/usr/bin/env python3
"""
Озвучка «Котозарядки» русскими нейросетевыми моделями на базе F5-TTS.

Модели клонируют голос из короткого образца, поэтому главный аргумент —
--ref: wav или mp3 на 6–12 секунд. Лучший вариант образца — голос мамы:
ребёнку он ближе любого стороннего диктора.

    python3 tools-озвучка2.py --model espeech --ref мама.wav --probe
    python3 tools-озвучка2.py --model espeech --ref мама.wav --all

--probe  — четыре пробные фразы, чтобы послушать и решить.
--all    — все 118 фраз приложения в audio/ плюс карта для объекта AUD.
"""
import argparse, json, os, re, subprocess, sys, wave
import numpy as np

MODELS = {
    "espeech": dict(repo="ESpeech/ESpeech-TTS-1_RL-V2", file="espeech_tts_rlv2.pt",
                    vocab=("ESpeech/ESpeech-TTS-1_RL-V2", "vocab.txt"),
                    arch=dict(dim=1024, depth=22, heads=16, ff_mult=2,
                              text_dim=512, conv_layers=4)),
    "f5ru":    dict(repo="Misha24-10/F5-TTS_RUSSIAN",
                    file="F5TTS_v1_Base_v4_winter/model_212000.safetensors",
                    vocab=("Misha24-10/F5-TTS_RUSSIAN", "F5TTS_v1_Base/vocab.txt"),
                    arch=dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512,
                              text_mask_padding=True, qk_norm=None, conv_layers=4,
                              pe_attn_head=None)),
}

PROBE = [
    "Ты постарался, у тебя получается! Молодец, что попробовал.",
    "Скажи за мной: ва, во, ву, вы.",
    "Вода, корова, сова, вертолёт.",
    "Ва-ва-ва, вот высокая трава.",
]

TR = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y',
      'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f',
      'х':'h','ц':'c','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}
def slug(s):
    o = ''.join(TR.get(c, c if c.isalnum() else '-') for c in s.lower())
    return re.sub(r'-+', '-', o).strip('-')[:40] or 'x'

def phrases_from_app(path="index.html"):
    """Единственный источник правды — сам index.html, чтобы списки не разъезжались."""
    s = open(path, encoding="utf-8").read()
    out = []
    def add(t):
        t = t.strip()
        if t and t.lower() not in {x.lower() for x in out}: out.append(t)
    for arr in ("PRAISE", "SHORT"):
        blk = s[s.index("const %s" % arr):]
        blk = blk[:blk.index("];") + 1] if "];" in blk[:2000] else blk[:2000]
        for m in re.finditer(r'"([^"]+)"', blk): add(m.group(1))
    plan = s[s.index("const PLAN"):s.index("const VOW")]
    for m in re.finditer(r'voice:"([^"]+)"', plan): add(m.group(1))
    for m in re.finditer(r'say:"([^"]+)"', plan): add(m.group(1))
    # слова с картинками: ["💧","ВОДА"] — произносим второй элемент, не эмодзи
    for p in re.finditer(r'\["[^"]*","([^"]+)"\]', plan): add(p.group(1))
    # слоги: items:["ВА","ВО",…] — без вложенных скобок
    for m in re.finditer(r'items:\[([^\[\]]+)\]', plan):
        for p in re.finditer(r'"([^"]+)"', m.group(1)): add(p.group(1))
    for m in re.finditer(r'"[^"]+","([^"]+)"\]', s[s.index("const ALBUMS"):s.index("const ALL = []")]):
        add(m.group(1))
    for v in re.findall(r'"([АОУИЭЫ])"', s[s.index("const VOW"):s.index("const VOW")+120]): add(v)
    add("Ты сделал всё!"); add("Ничего, слушай ещё разок")
    return out

def save_mp3(path, a, sr):
    a = np.asarray(a, dtype=np.float32)
    peak = float(np.abs(a).max()) or 1.0
    x = (np.clip(a / peak * 0.92, -1, 1) * 32767).astype('<i2')
    tmp = "/tmp/_f5.wav"
    with wave.open(tmp, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(x.tobytes())
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp,
                    '-ar', '24000', '-ac', '1', '-b:a', '48k', path], check=True)

def trim(a, rel=0.02):
    e = np.abs(a)
    if not len(e) or e.max() == 0: return a
    i = np.where(e > e.max() * rel)[0]
    if not len(i): return a
    return a[max(0, i[0] - 600): i[-1] + 1200]

def patch_torchaudio():
    """torchaudio 2.10 отдаёт всё декодирование torchcodec, а тот требует
    ровно ту версию библиотек FFmpeg, под которую собран. Читаем звук через
    soundfile — ему хватает системного libsndfile."""
    import torch, torchaudio, soundfile as sf
    def load(path, *a, **kw):
        x, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(x.T.copy()), sr
    torchaudio.load = load


def patch_ruaccent():
    """Модели RUAccent собраны под transformers 4.x: новый токенизатор больше не
    отдаёт token_type_ids, а onnx-граф их требует. Дополняем нулями (это и есть
    правильное значение для одиночного сегмента) и отбрасываем лишние входы."""
    from onnxruntime import InferenceSession
    orig = InferenceSession.run
    def run(self, out_names, feed, *a, **kw):
        if isinstance(feed, dict):
            want = {i.name for i in self.get_inputs()}
            feed = {k: v for k, v in feed.items() if k in want}
            missing = want - set(feed)
            if missing and feed:
                ref = next(iter(feed.values()))
                for name in missing:
                    feed[name] = np.zeros_like(ref)
        return orig(self, out_names, feed, *a, **kw)
    InferenceSession.run = run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS), default="espeech")
    ap.add_argument("--ref", required=True, help="образец голоса, 6-12 секунд")
    ap.add_argument("--ref-text", default="", help="что сказано в образце (пусто — распознает сам)")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default="audio")
    ap.add_argument("--speed", type=float, default=0.95)
    a = ap.parse_args()

    import torch
    from ruaccent import RUAccent
    from huggingface_hub import hf_hub_download
    from f5_tts.infer.utils_infer import (infer_process, load_model, load_vocoder,
                                          preprocess_ref_audio_text)
    from f5_tts.model import DiT

    cfg = MODELS[a.model]
    print("→ модель", a.model, "| CUDA", torch.cuda.is_available(),
          torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
    ckpt = hf_hub_download(cfg["repo"], cfg["file"])
    vocab = hf_hub_download(cfg["vocab"][0], cfg["vocab"][1])

    patch_torchaudio()

    print("→ ударения (RUAccent)")
    patch_ruaccent()
    acc = RUAccent(); acc.load(omograph_model_size='turbo3.1', use_dictionary=True, tiny_mode=False)
    stress = lambda t: t if '+' in t else acc.process_all(t)

    print("→ вокодер и модель")
    vocoder = load_vocoder()
    model = load_model(DiT, cfg["arch"], ckpt, vocab_file=vocab)

    if not a.ref.lower().endswith(".wav"):
        w = "/tmp/_ref.wav"
        subprocess.run(["ffmpeg","-y","-v","error","-i",a.ref,"-ar","24000","-ac","1",w], check=True)
        a.ref = w
    ref_audio, ref_text = preprocess_ref_audio_text(a.ref, stress(a.ref_text) if a.ref_text else "")
    print("→ образец распознан как:", ref_text.strip()[:90])

    os.makedirs(a.out, exist_ok=True)
    texts = PROBE if a.probe else phrases_from_app()
    if a.probe:
        os.makedirs("proby", exist_ok=True)

    man = {}
    for i, t in enumerate(texts, 1):
        wave_, sr, _ = infer_process(ref_audio, ref_text, stress(t), model, vocoder,
                                     speed=a.speed, nfe_step=32, cross_fade_duration=0.15)
        if a.probe:
            save_mp3(f"proby/{a.model}_{i}.mp3", trim(wave_), sr)
        else:
            fn = slug(t)
            save_mp3(f"{a.out}/{fn}.mp3", trim(wave_), sr)
            man[t.strip().lower()] = fn
        print(f"  {i}/{len(texts)}  {t[:52]}")

    if man:
        json.dump(man, open("/tmp/_manifest.json", "w"), ensure_ascii=False, indent=0)
        print("\nкарта фраз → /tmp/_manifest.json  (вставить в объект AUD в index.html)")

if __name__ == "__main__":
    main()
