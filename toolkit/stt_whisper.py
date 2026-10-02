#!/usr/bin/env python3
"""stt_whisper.py — Hermes STT command-provider: Slovak-finetuned Whisper
large-v3-turbo, cross-platform (Apple MLX / CPU / CUDA).

Called by Hermes as:   stt_whisper.py <input_path> <output_dir>
Writes <output_dir>/transcript.txt (Hermes reads the transcript from there).

Used by BOTH the Hermes desktop app (voice input) and the Matrix/WhatsApp
gateway (incoming voice messages). Wire it in ~/.hermes/config.yaml:

  stt:
    enabled: true
    provider: zolsk
    providers:
      zolsk:
        type: command
        command: <PY> <ROOT>/toolkit/stt_whisper.py {input_path} {output_dir}

Backend auto-selection (first that imports wins; override with STT_BACKEND=
mlx|faster|transformers):
  - mlx          -> Apple Silicon, mlx_whisper (fastest on a Mac)
  - faster       -> faster-whisper / CTranslate2 (fast on CPU/CUDA)
  - transformers -> HF pipeline (always works; torch is already a dep)

Model resolution (override with WHISPER_SK_MODEL):
  - a local dir if present (offline), else a public HF repo per backend:
      mlx          -> local SK MLX dir, else aitytech/Whisper-Large-V3-Turbo-MLX-FP16
      faster       -> deepdml/faster-whisper-large-v3-turbo-ct2
      transformers -> kinit/whisper-large-v3-turbo-sk  (Slovak fine-tune, MIT)

Why these decode settings (carried over from the reference Mac, measured):
  - temperature fallback tuple ON: the turbo model (4 decoder layers) otherwise
    DROPS a 30s window on a failed decode and stops (~40s cut). The tuple makes
    it retry and finish long files.
  - condition_on_previous_text=False: with it True the turbo model loops and
    truncates to ~40s (confirmed by ablation).
  - initial_prompt: a sample of casual Slovak speech (not instructions) that
    primes the model for the colloquial register and diacritics.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "0")  # allow download on a fresh box

# A sample of casual Slovak speech — primes register + diacritics (NOT a command).
PROMPT = ("No takže, toto je slovenská hovorová reč, oukej? Proste normálne "
          "rozprávam, hej, vlastne o tom, ako to celé funguje — model, whisper, "
          "nahrávka, správa, test, oukej.")

TEMPERATURE = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)  # fallback = finishes long audio


def _local_or(default_repo: str) -> str:
    """Return a local model dir if the user has one, else the HF repo id."""
    env = os.environ.get("WHISPER_SK_MODEL")
    if env and os.path.isdir(os.path.expanduser(env)):
        return os.path.expanduser(env)
    if env:  # explicit repo id (not a dir)
        return env
    # common local location on the reference Mac
    guess = os.path.expanduser("~/models/whisper-mlx-turbo-sk")
    if os.path.isdir(guess):
        return guess
    return default_repo


def _try_mlx(audio: str) -> str:
    import mlx_whisper  # Apple Silicon
    model = _local_or("aitytech/Whisper-Large-V3-Turbo-MLX-FP16")
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=model,
        language="sk",
        temperature=TEMPERATURE,
        condition_on_previous_text=False,
        initial_prompt=PROMPT,
        verbose=False,
    )
    return (result.get("text") or "").strip()


def _try_faster(audio: str) -> str:
    from faster_whisper import WhisperModel  # CTranslate2 (CPU/CUDA)
    model_id = _local_or("deepdml/faster-whisper-large-v3-turbo-ct2")
    compute = os.environ.get("STT_COMPUTE_TYPE", "int8")  # int8 = CPU-friendly
    device = os.environ.get("STT_DEVICE", "auto")
    model = WhisperModel(model_id, device=device, compute_type=compute)
    segments, _info = model.transcribe(
        audio,
        language="sk",
        temperature=TEMPERATURE,
        condition_on_previous_text=False,
        initial_prompt=PROMPT,
    )
    return "".join(seg.text for seg in segments).strip()


def _try_transformers(audio: str) -> str:
    # Always-available fallback: torch + transformers are already deps.
    import torch
    from transformers import pipeline
    model_id = _local_or("kinit/whisper-large-v3-turbo-sk")
    device = 0 if torch.cuda.is_available() else (
        "mps" if getattr(torch.backends, "mps", None)
        and torch.backends.mps.is_available() else -1)
    asr = pipeline(
        "automatic-speech-recognition",
        model=model_id,
        device=device,
        chunk_length_s=30,
    )
    out = asr(
        audio,
        return_timestamps=False,
        generate_kwargs={"language": "sk", "task": "transcribe"},
    )
    return (out.get("text") or "").strip()


BACKENDS = {"mlx": _try_mlx, "faster": _try_faster, "transformers": _try_transformers}
ORDER = ["mlx", "faster", "transformers"]


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: stt_whisper.py <input_path> <output_dir>", file=sys.stderr)
        return 2
    audio, out_dir = sys.argv[1], sys.argv[2]

    forced = os.environ.get("STT_BACKEND")
    order = [forced] if forced in BACKENDS else ORDER

    text, used, errors = None, None, []
    for name in order:
        try:
            text = BACKENDS[name](audio)
            used = name
            break
        except ImportError as e:
            errors.append(f"{name}: not installed ({e})")
        except Exception as e:  # noqa: BLE001 — try the next backend
            errors.append(f"{name}: {e}")

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    if text is None:
        # degrade loudly in stderr, but still write an (empty) transcript so
        # Hermes doesn't crash on a missing file.
        sys.stderr.write("[stt_whisper] all backends failed:\n  "
                         + "\n  ".join(errors) + "\n")
        (Path(out_dir) / "transcript.txt").write_text("", encoding="utf-8")
        return 1

    sys.stderr.write(f"[stt_whisper] transcribed via {used}\n")
    (Path(out_dir) / "transcript.txt").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
