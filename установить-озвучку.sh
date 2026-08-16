#!/usr/bin/env bash
# Ставит подготовленную озвучку из audio_new/ в приложение.
# Запускать только после того, как родитель послушал и одобрил.
set -e
cd "$(dirname "$0")"
n=$(ls audio_new/*.mp3 2>/dev/null | wc -l)
[ "$n" -ge 119 ] || { echo "в audio_new только $n файлов, ожидалось 119"; exit 1; }
cp audio_new/*.mp3 audio/
/home/amolod/dev/.tts/bin/python - <<'PY'
import json, importlib.util
s = importlib.util.spec_from_file_location("g", "tools-озвучка2.py")
g = importlib.util.module_from_spec(s); s.loader.exec_module(g)
man = json.load(open("/tmp/_manifest.json"))
man["в-в-в-в"] = "v-v-v-v"          # звука раньше не было вовсе
for t in [l.strip() for l in open("звуки-для-записи.txt", encoding="utf-8")
          if l.strip() and not l.startswith("#")]:
    man[t.strip().lower()] = g.slug(t.strip().lower())
g.write_app(man)
PY
echo "готово: $(ls audio/*.mp3 | wc -l) файлов в audio/"
