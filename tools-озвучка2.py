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

# Два режима речи. Похвалу мама читает своим обычным темпом — он живой и
# приятный. А то, за чем ребёнок повторяет, нужно произносить заметно
# медленнее и отчётливее: на обычной скорости «вода» проскакивает так,
# что пятилетка с нарушениями просто не расслышит звуки.
SPEED = {"norm": 1.0, "name": 0.85, "slow": 0.62}
# слогов в секунду: похвалу оставляем как прочитала мама, а то, за чем
# ребёнок повторяет, приводим к неторопливому темпу принудительно
RATE  = {}          # темп не подгоняем: связная речь даёт его сама
# Каждую фразу произносим отдельным высказыванием. Связками выходило хуже:
# вырезанная из середины связки фраза несёт интонацию перечисления, она
# звучит незаконченной и оттого механической. Отдельная фраза получает
# нормальную завершающую интонацию — ровно так была сделана первая проба,
# которую родитель одобрил.
BATCH = {"norm": 1, "name": 1, "slow": 1}

# тянущиеся звуки моделью не синтезируются вовсе: сшиваем их из гласной
HOLD = {"а-а-а-а": "а", "у-у-у-у": "у", "и-и-и-и": "и"}

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
    """Единственный источник правды — сам index.html, чтобы списки не разъезжались.
    Возвращает список (текст, режим речи)."""
    s = open(path, encoding="utf-8").read()
    out, seen = [], set()
    def add(t, reg):
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower()); out.append((t, reg))

    for arr in ("PRAISE", "SHORT"):
        blk = s[s.index("const %s" % arr):]
        blk = blk[:blk.index("];") + 1] if "];" in blk[:2000] else blk[:2000]
        for m in re.finditer(r'"([^"]+)"', blk): add(m.group(1), "norm")
    add("Ты сделал всё!", "norm"); add("Ничего, слушай ещё разок", "norm")

    plan = s[s.index("const PLAN"):s.index("const VOW")]
    # всё, за чем ребёнок повторяет, — медленно
    for m in re.finditer(r'voice:"([^"]+)"', plan): add(m.group(1), "slow")
    for m in re.finditer(r'say:"([^"]+)"', plan):   add(m.group(1), "slow")
    for p in re.finditer(r'\["[^"]*","([^"]+)"\]', plan): add(p.group(1), "slow")
    for m in re.finditer(r'items:\[([^\[\]]+)\]', plan):
        for p in re.finditer(r'"([^"]+)"', m.group(1)): add(p.group(1), "slow")
    for v in re.findall(r'"([АОУИЭЫ])"', s[s.index("const VOW"):s.index("const VOW")+120]):
        add(v, "slow")

    # названия наклеек ребёнок тоже повторяет, но это награда, не урок
    for m in re.finditer(r'"[^"]+","([^"]+)"\]', s[s.index("const ALBUMS"):s.index("const ALL = []")]):
        add(m.group(1), "name")
    return out


def period(x, sr):
    x = x - x.mean(); n = len(x)
    ac = np.correlate(x, x, "full")[n - 1:]
    lo, hi = int(sr / 400), int(sr / 70)
    return lo + int(np.argmax(ac[lo:hi]))


def sustain(a, sr, seconds):
    """Тянущаяся гласная: берём установившуюся середину и сшиваем её саму с
    собой по границам периодов голоса. Ни одна модель тянуть звук не умеет."""
    a = trim(a, 0.05)
    m = len(a) // 2
    P = period(a[max(0, m - 2048):m + 2048], sr)
    K = max(1, int(0.12 * sr // P))
    st = max(0, m - K * P // 2)
    chunk = a[st:st + K * P]
    if len(chunk) < P * 2: return a
    xf = P
    out, body = list(a[:st]), []
    while (len(out) + len(body)) / sr < seconds - 0.2:
        if not body: body = list(chunk)
        else:
            f = np.linspace(0, 1, xf)
            body[-xf:] = list(np.array(body[-xf:]) * (1 - f) + chunk[:xf] * f)
            body += list(chunk[xf:])
    out = np.array(out + body + list(a[st + K * P:]), dtype=np.float32)
    r = int(0.12 * sr); out[-r:] *= np.linspace(1, 0, r)
    return out * (1 + 0.03 * np.sin(2 * np.pi * 4.5 * np.arange(len(out)) / sr))


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

SYL = "аеёиоуыэюя"

def chunks(x, sr, thr=0.04, gap=0.16):
    """Режет запись по паузам. Нужно, чтобы вынуть отдельный звук из фразы-зачина."""
    win = int(sr * 0.02)
    if len(x) < win * 3: return []
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
                out.append(x[max(0, st - 2) * win:(i - g + 2) * win]); st = None; g = 0
    if st is not None: out.append(x[max(0, st - 2) * win:])
    return [c for c in out if len(c) > sr * 0.10]

def pace(a, sr, text, rate):
    """Выравнивает темп до rate слогов в секунду. Модель на коротких словах
    частит непредсказуемо — «корова» может проскочить за полсекунды, и
    ребёнок не расслышит звуков. atempo тянет время, не трогая высоту голоса."""
    n = max(1, sum(c in SYL for c in text.lower()))
    have = len(a) / sr
    want = n / rate + 0.30
    if have <= 0.05 or have >= want: return a
    f = max(0.5, have / want)
    tmp, outp = "/tmp/_pace_in.wav", "/tmp/_pace_out.wav"
    x = (np.clip(a, -1, 1) * 32767).astype("<i2")
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(x.tobytes())
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tmp,
                    "-filter:a", f"atempo={f:.4f}", outp], check=True)
    with wave.open(outp, "rb") as w:
        y = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    return y


def write_app(man, path="index.html"):
    """Вписывает карту «фраза → файл» прямо в объект AUD внутри index.html.
    Руками её не перенести: 118 строк, ошибиться в одной — и фраза замолчит."""
    s = open(path, encoding="utf-8").read()
    head = "const AUD={"
    i = s.index(head)
    j = s.index("};", i) + 2

    rows, line = [], []
    for k in sorted(man):
        line.append('"%s":"%s"' % (k.replace('"', '\\"'), man[k]))
        if len(",".join(line)) > 92:
            rows.append(",".join(line) + ","); line = []
    if line: rows.append(",".join(line))

    block = head + "\n" + "\n".join("  " + r for r in rows) + "\n};"
    open(path, "w", encoding="utf-8").write(s[:i] + block + s[j:])

    check = open(path, encoding="utf-8").read()
    got = len(re.findall(r'"[^"]+":"[^"]+"', check[check.index(head):check.index("};", check.index(head))]))
    print(f"→ в {path} вписано фраз: {got} (ожидалось {len(man)})")
    if got != len(man):
        raise SystemExit("карта записалась не полностью — проверьте index.html")


def patch_torchaudio():
    """torchaudio 2.10 отдаёт всё декодирование torchcodec, а тот требует
    ровно ту версию библиотек FFmpeg, под которую собран. Читаем звук через
    soundfile — ему хватает системного libsndfile."""
    import torch, torchaudio, soundfile as sf
    def load(path, *a, **kw):
        x, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(x.T.copy()), sr
    torchaudio.load = load


# Короткая фраза модели не даётся: на «Вот это да!» ей не на чем построить
# интонацию, а «Собака» выходит и вовсе тишиной. Поэтому короткое произносим
# концом длинного предложения и зачин отрезаем — у концовки интонация
# завершённая, в отличие от фразы, вырезанной из середины перечисления.
# В зачинах нет запятых: лишние паузы внутри них сбивают поиск границы.
CARRIERS = [
    "Мы сегодня очень хорошо позанимались вместе.",
    "Смотри как здорово мы с тобой поработали сегодня.",
    "Я очень рада что мы с тобой сегодня позанимались.",
]
SHORT_LIMIT = 40          # короче — только через зачин

VOWELS_RU = "аеёиоуыэюя"

def clean_stress(s):
    """RUAccent метит ударение в каждом слове, включая односложные. Для модели
    метка — приказ выделить слово голосом, поэтому «Т+ы посл+ушай» звучит
    рублено, по слову за раз. В односложном слове ударение и так однозначно:
    метка там не несёт смысла, только ломает связность фразы."""
    def one(w):
        if sum(c in VOWELS_RU for c in w.lower().replace("+", "")) <= 1:
            return w.replace("+", "")
        return w
    return " ".join(one(w) for w in s.split(" "))


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
    ap.add_argument("--speed", type=float, default=0, help="0 — темп по режиму речи")
    ap.add_argument("--write-app", action="store_true", help="вписать карту в index.html")
    ap.add_argument("--only", default="", help="режимы через запятую: norm,name,slow")
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
    stress = lambda t: t if '+' in t else clean_stress(acc.process_all(t))

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
    if a.probe:
        os.makedirs("proby", exist_ok=True)
        items = [(t, "norm") for t in PROBE]
    else:
        items = phrases_from_app()

    def raw(text, speed):
        w, sr, _ = infer_process(ref_audio, ref_text, stress(text), model, vocoder,
                                 speed=speed, nfe_step=32, cross_fade_duration=0.15)
        return np.asarray(w, dtype=np.float32), sr

    def gaps(x, sr, thr=0.04, minlen=0.10):
        win = int(sr * 0.02)
        env = np.array([np.sqrt((x[i:i + win] ** 2).mean()) for i in range(0, len(x) - win, win)])
        if env.max() < 1e-6: return []
        hot = env > env.max() * thr
        out, s0 = [], None
        for i, h in enumerate(hot):
            if not h:
                if s0 is None: s0 = i
            elif s0 is not None:
                if (i - s0) * 0.02 >= minlen: out.append(((s0 + i) / 2) * 0.02)
                s0 = None
        return out

    def via_carrier(text, speed, idx):
        """Границу зачина ищем не по первой паузе — внутри зачина они тоже
        есть, — а по той, что ближе к ожидаемому месту: доля зачина в длине
        всего текста. Иначе в кусок попадает половина зачина."""
        car = CARRIERS[idx % len(CARRIERS)]
        tail = text if text.strip()[-1] in ".!?" else text + "."
        w, sr = raw(car + " " + tail, speed)
        g = gaps(w, sr)
        if not g: return trim(w), sr
        want = len(w) / sr * (len(car) / (len(car) + 1 + len(tail)))
        cut = min(g, key=lambda t: abs(t - want))
        # отступаем назад: срезать лишнюю тишину безопасно, а вот срезанный
        # первый звук превращает «носорог» в «сорок» — и это не слышно по цифрам
        start = max(0, int((cut - 0.14) * sr))
        return trim(w[start:], 0.012), sr

    def speak(text, speed):
        """Короткие слова синтез выдаёт как попало, а одну букву часто вовсе
        тишиной: ему не за что зацепиться. Тогда произносим её внутри фразы-зачина
        и вырезаем последний кусок между паузами."""
        if len(text) >= SHORT_LIMIT:
            for _ in range(3):                 # генерация случайна: осечку стоит перебросить
                w, sr = raw(text, speed)
                if float(np.abs(w).max()) > 0.05 and len(w) / sr > 0.15:
                    return w, sr
        for i in range(3):
            w, sr = via_carrier(text, speed, speak.n + i)
            if float(np.abs(w).max()) > 0.05 and 0.25 < len(w) / sr < 5.0:
                speak.n += 1
                return w, sr
        return w, sr
    speak.n = 0

    def ends(t):
        t = t.strip()
        return t if t and t[-1] in ".!?" else t + "."

    def synth_batch(texts, speed, depth=0):
        """Произносим связкой и режем по паузам. Если кусков вышло не столько,
        сколько фраз, делим связку пополам и пробуем снова — и лишь в самом
        конце произносим поодиночке."""
        if len(texts) == 1:
            t = texts[0]
            need = max(1, sum(ch in SYL for ch in t.lower())) / 5.0
            best = None
            for _ in range(3):                     # синтез случаен: берём удачную попытку
                w, sr = speak(t, speed); w = trim(w)
                if best is None or len(w) > len(best): best = w
                if len(w) / sr >= need: return [w], sr
            return [best], sr
        w, sr = raw(" ".join(ends(t) for t in texts), speed)

        def sane(cs):
            """Совпадения числа кусков мало: граница могла срезать конец слова.
            Больше пяти слогов в секунду наш голос не выдаёт — значит, обрезано."""
            for c, t in zip(cs, texts):
                n = max(1, sum(ch in SYL for ch in t.lower()))
                if len(c) / sr < n / 5.0: return False
            return True

        for gap in (0.20, 0.24, 0.16, 0.28, 0.12, 0.34):
            cs = chunks(w, sr, gap=gap)
            if len(cs) == len(texts) and sane(cs):
                return cs, sr
        if depth < 3:
            mid = len(texts) // 2
            l, sr = synth_batch(texts[:mid], speed, depth + 1)
            r, _  = synth_batch(texts[mid:], speed, depth + 1)
            return l + r, sr
        out = []
        for t in texts:
            w, sr = speak(t, speed); out.append(trim(w))
        print("   поодиночке:", ", ".join(texts))
        return out, sr

    # собираем подряд идущие фразы одного режима в связки
    groups, only = [], set(a.only.split(",")) if a.only else None
    for t, reg in items:
        if only and reg not in only: continue
        if groups and groups[-1][0] == reg and len(groups[-1][1]) < BATCH[reg]:
            groups[-1][1].append(t)
        else:
            groups.append((reg, [t]))

    man, bad, done = {}, [], 0
    for reg, texts in groups:
        names = [slug(t.strip().lower()) for t in texts]
        if not a.probe and all(os.path.exists(f"{a.out}/{n}.mp3") for n in names):
            for t, n in zip(texts, names): man[t.strip().lower()] = n
            done += len(texts); continue

        sp = a.speed if a.speed else SPEED[reg]
        hold = [t for t in texts if t.lower() in HOLD]
        if hold:                                   # тянущиеся звуки только поодиночке
            parts, sr = [], None
            for t in texts:
                w, sr = speak(HOLD.get(t.lower(), t), sp)
                parts.append(sustain(w, sr, 4.0) if t.lower() in HOLD else trim(w))
        else:
            parts, sr = synth_batch(texts, sp)

        for t, n, w in zip(texts, names, parts):
            done += 1
            if reg in RATE: w = pace(w, sr, t, RATE[reg])
            if w is None or float(np.abs(w).max()) < 0.02:
                bad.append(t); print("   НЕ ВЫШЛО:", t); continue
            if a.probe: save_mp3(f"proby/{a.model}_{done}.mp3", w, sr)
            else:       save_mp3(f"{a.out}/{n}.mp3", w, sr)
            man[t.strip().lower()] = n
            print(f"  {done}/{len(items)}  [{reg}] {t[:44]}  {len(w)/sr:.2f}с")

    if bad:
        print("\nне озвучились: " + ", ".join(bad))
    if man:
        json.dump(man, open("/tmp/_manifest.json", "w"), ensure_ascii=False, indent=0)
        if a.write_app:
            write_app(man)
        else:
            print("\nкарта фраз → /tmp/_manifest.json (или запустите с --write-app)")


if __name__ == "__main__":
    main()
