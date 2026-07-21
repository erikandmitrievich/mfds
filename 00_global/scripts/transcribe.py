#!/usr/bin/env python3

"""Audio -> text transcripts for lecture and recitation recordings.

Replaces m4a_to_txt.py and mp3_to_txt.py, which differed only in their glob.
ffmpeg normalises every container to the same mono 16 kHz wav, so the split
was duplication.

Two invariants from STRUCTURE.org are honoured here:

  - Preprocessed wavs are derived and transient. They go to a tempdir, not
    next to the sources: 00_resources/ admits notes/, transcripts/, papers/
    and nothing else, and its contract is "irreplaceable inputs only".
  - Transcripts land in <src>/transcripts/. The validator requires the stem
    to match lec_NN[-NN]; --check-names warns when it does not, rather than
    silently emitting files the pre-commit hook will reject.

Exit codes:
    0  every file transcribed or skipped
    1  one or more failures
    2  environment problem (no ffmpeg, no mlx_whisper)
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
DEFAULT_GLOBS = ("*.m4a", "*.mp3", "*.wav")

# EXAM_TRANSCRIPTS/E031 in validate_structure.py
STEM_RE = re.compile(r"^lec_\d{2}(-\d{2})?$")

# ffmpeg: mono, 16 kHz, rumble filtered, loudness normalised. Whisper is
# trained on 16 kHz mono; anything else is resampled internally anyway.
AF = "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11"

# Decode parameters. These are tuned, not defaults, and are deliberately not
# exposed as flags -- changing them changes transcript quality in ways that
# are not visible until a downstream extraction goes wrong.
#
#   condition_on_previous_text=False  is the fix for the repetition loop
#     Whisper falls into on lecture audio with long silences.
#   temperature ladder                fallback when a segment fails the
#     compression/logprob gates below.
DECODE = dict(
    condition_on_previous_text=False,
    compression_ratio_threshold=2.0,
    logprob_threshold=-0.8,
    no_speech_threshold=0.7,
    temperature=(0.0, 0.2, 0.4, 0.6, 0.8),
)


def preprocess(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-ac", "1", "-ar", "16000", "-af", AF, str(dst)],
        check=True,
    )


def transcribe(wav: Path, model: str, language: str, prompt: str) -> str:
    import mlx_whisper  # imported late so --help and --dry-run need no mlx

    kwargs = dict(DECODE)
    if prompt:
        kwargs["initial_prompt"] = prompt
    r = mlx_whisper.transcribe(
        str(wav), path_or_hf_repo=model, language=language, **kwargs
    )
    return r["text"].strip() + "\n"


def collect(src: Path, globs: list[str]) -> list[Path]:
    found: set[Path] = set()
    for g in globs:
        found.update(p for p in src.glob(g) if p.is_file())
    return sorted(found)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("src", type=Path,
                    help="directory holding the audio (typically .../03_exams/00_resources)")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="transcript directory (default: <src>/transcripts)")
    ap.add_argument("--glob", action="append", default=None, metavar="PAT",
                    help=f"audio pattern, repeatable (default: {' '.join(DEFAULT_GLOBS)})")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--language", default="en")

    g = ap.add_mutually_exclusive_group()
    g.add_argument("--prompt", default=None,
                   help="domain vocabulary primer passed to Whisper as initial_prompt")
    g.add_argument("--prompt-file", type=Path, default=None,
                   help="read the primer from a file")

    ap.add_argument("--force", action="store_true",
                    help="re-transcribe files whose transcript already exists")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the work and exit; touches nothing")
    ap.add_argument("--keep-prep", type=Path, default=None, metavar="DIR",
                    help="keep the normalised wavs here instead of a tempdir "
                         "(for debugging bad audio; the dir is derived, do not commit it)")
    ap.add_argument("--check-names", action=argparse.BooleanOptionalAction, default=True,
                    help="warn when an output stem violates EXAM_TRANSCRIPTS/E031")
    args = ap.parse_args(argv)

    src = args.src.resolve()
    if not src.is_dir():
        print(f"not a directory: {src}", file=sys.stderr)
        return 2

    out = (args.out or src / "transcripts").resolve()
    globs = args.glob or list(DEFAULT_GLOBS)

    prompt = args.prompt or ""
    if args.prompt_file:
        prompt = args.prompt_file.read_text().strip()

    audio = collect(src, globs)
    if not audio:
        print(f"no audio matching {' '.join(globs)} in {src}", file=sys.stderr)
        return 1

    todo = [f for f in audio if args.force or not (out / f"{f.stem}.txt").exists()]
    skipped = len(audio) - len(todo)

    if args.check_names:
        bad = [f.stem for f in todo if not STEM_RE.match(f.stem)]
        if bad:
            print(f"warning: {len(bad)} stem(s) do not match lec_NN[-NN]; the "
                  f"resulting .txt will fail validate_structure (E031): "
                  f"{', '.join(bad[:5])}{' ...' if len(bad) > 5 else ''}",
                  file=sys.stderr)

    if args.dry_run:
        print(f"src:    {src}")
        print(f"out:    {out}")
        print(f"model:  {args.model}")
        print(f"prompt: {(prompt[:60] + '...') if len(prompt) > 60 else (prompt or '(none)')}")
        print(f"\n{len(todo)} to transcribe, {skipped} already present")
        for f in todo:
            print(f"  {f.name} -> {out.name}/{f.stem}.txt")
        return 0

    if shutil.which("ffmpeg") is None:
        print("ffmpeg not on PATH", file=sys.stderr)
        return 2
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        print("mlx_whisper not installed (pip install mlx-whisper)", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    if args.keep_prep:
        args.keep_prep.mkdir(parents=True, exist_ok=True)

    failures = 0
    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp:
        prep_dir = args.keep_prep or Path(tmp)
        for i, f in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {f.name}", flush=True)
            wav = prep_dir / f"{f.stem}.wav"
            try:
                preprocess(f, wav)
                text = transcribe(wav, args.model, args.language, prompt)
            except subprocess.CalledProcessError as exc:
                print(f"  ffmpeg failed ({exc.returncode})", file=sys.stderr)
                failures += 1
                continue
            except Exception as exc:                    # mlx surfaces many types
                print(f"  transcription failed: {exc}", file=sys.stderr)
                failures += 1
                continue
            (out / f"{f.stem}.txt").write_text(text, encoding="utf-8")

    print(f"\n{len(todo) - failures} written, {skipped} skipped, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
