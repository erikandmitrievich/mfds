#!/usr/bin/env python3

import mlx_whisper, pathlib

SRC   = pathlib.Path.home() / "personal/mfds/01_coursework/02_semester/00_algorithms/01_material/lec_recordings"
OUT   = SRC / "transcripts"; OUT.mkdir(exist_ok=True)
MODEL = "mlx-community/whisper-large-v3-turbo"

for f in sorted(SRC.glob("lec_*.mp3")):
    out = OUT / f"{f.stem}.txt"
    if out.exists():
        print("skip", f.name); continue
    print("---->", f.name)
    r = mlx_whisper.transcribe(str(f), path_or_hf_repo=MODEL, language="en")  # condition_on_previous_text defaults True
    out.write_text(r["text"].strip() + "\n", encoding="utf-8")
print("done")
