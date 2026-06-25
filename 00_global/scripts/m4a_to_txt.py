#!/usr/bin/env python3

import mlx_whisper, pathlib, subprocess

SRC = pathlib.Path.home() / "personal/mfds/01_coursework/02_semester/01_analysis/03_exams/00_resources"
OUT = SRC / "transcripts"
PREP = SRC / "preprocessed"
OUT.mkdir(exist_ok=True); PREP.mkdir(exist_ok=True)

MODEL = "mlx-community/whisper-large-v3-turbo"  # turbo is fine; downgrade only if still bad

PROMPT = ("Fréchet derivative, Jacobian, Banach space, Banach fixed point theorem, "
          "Taylor polynomial, Newton's method, gradient descent, convex function, "
          "Hessian, Lagrange multipliers, tangent space, submanifold, implicit "
          "function theorem, local extremum, KKT, positive definite, eigenvector, Julia.")

for f in sorted(SRC.glob("rec_*.m4a")):
    wav = PREP / f"{f.stem}.wav"
    out = OUT / f"{f.stem}.txt"
    if out.exists(): continue

    # Normalize + high-pass + mono 16k
    subprocess.run([
        "ffmpeg", "-y", "-i", str(f),
        "-ac", "1", "-ar", "16000",
        "-af", "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11",
        str(wav)
    ], check=True)

    r = mlx_whisper.transcribe(
        str(wav),
        path_or_hf_repo=MODEL,
        language="en",
        condition_on_previous_text=False,      # the fix
        compression_ratio_threshold=2.0,
        logprob_threshold=-0.8,
        no_speech_threshold=0.7,
        initial_prompt=PROMPT,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8), # keep fallback ladder
    )
    out.write_text(r["text"].strip() + "\n", encoding="utf-8")
