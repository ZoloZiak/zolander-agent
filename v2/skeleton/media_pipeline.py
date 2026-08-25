"""media_pipeline — shell-safe spracovanie médií (STT, video, obrázky).

ADRESUJE (REPORT.md):
- KONSENZUS #10 „STT/media pipeline blokovaná sandbox": `faster_whisper ...
  Operation not permitted`; `video_paths UNPROCESSED`. Nedekódované médiá ->
  agent generuje na prázdny obsah (viac bod 8).
- RIESENIA quick-win 4 [STT/video fallback]: try/except na Operation not
  permitted; agent NESMIE padať na exit 1; extrahovať video framy namiesto
  placeholderu.
- KONSENZUS #8 / quick-win 3 [No-narrative na short/empty input]:
  msg='' -> response=1399 chars [46813:L4237/4245/4262]. Ak médium nejde
  dekódovať, pipeline to OZNAČÍ a persona_hook/output_filter potlačia román.

Princíp: degradovaný výstup („nepodarilo sa dekódovať") je vždy lepší než
crash alebo halucinovaná narratíva nad prázdnym obsahom. Žiadna výnimka
neuniká z tohto modulu von.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class MediaResult:
    ok: bool                    # True = obsah úspešne dekódovaný
    text: str = ""              # transkript / popis; prázdne ak ok=False
    reason: str = ""            # pri ok=False: "access_blocked" | "unsupported" | "empty" | ...
    fallback_used: bool = False # či bežal fallback (napr. frame extraction)
    detail: dict = field(default_factory=dict)


#: injectovateľné backendy (unit cesta beží offline; produkcia doručí reálne fn)
TranscribeFn = Callable[[str], str]     # path -> transcript
DescribeFramesFn = Callable[[list[str]], str]  # frame paths -> popis


class MediaPipeline:
    """Dekóduje prílohy s shell-safe fallbackmi; nikdy nezastaví beh agenta."""

    def __init__(self,
                 stt_fn: Optional[TranscribeFn] = None,
                 describe_frames_fn: Optional[DescribeFramesFn] = None,
                 stt_endpoint_env: str = "ZOLANDER_STT_ENDPOINT",
                 env=None) -> None:
        self.stt_fn = stt_fn
        self.describe_frames_fn = describe_frames_fn
        self._stt_endpoint_env = stt_endpoint_env
        self._env = env if env is not None else os.environ

    # ------------------------------------------------------------------
    # audio
    # ------------------------------------------------------------------

    def process_audio(self, path: str) -> MediaResult:
        """STT cez lokálny whisper (injectovaný backend). Musí:
          1. try/except OSError 'Operation not permitted' (sandbox blok) ->
             vrátiť MediaResult(ok=False, reason='access_blocked'), NIE exit 1.
          2. Fallback: ak existuje povolený externý STT endpoint (env
             ZOLANDER_STT_ENDPOINT), skúsiť ho; inak degradovať čisto.
        """
        try:
            readable = self._readable(path)
            if readable is not True:
                return MediaResult(ok=False, reason=readable)

            if self.stt_fn is not None:
                try:
                    text = (self.stt_fn(path) or "").strip()
                except PermissionError:
                    return MediaResult(ok=False, reason="access_blocked")
                except OSError as exc:
                    if "operation not permitted" in str(exc).lower():
                        return MediaResult(ok=False, reason="access_blocked")
                    text = ""
                except Exception:  # noqa: BLE001 — STT backend padol => degrade
                    text = ""
                if text:
                    return MediaResult(ok=True, text=text)
                return MediaResult(ok=False, reason="empty")

            # žiadny lokálny backend; skús povolený endpoint (ak nastavený)
            endpoint = self._env.get(self._stt_endpoint_env, "")
            if endpoint:
                result = self._try_remote_stt(path, endpoint)
                if result is not None:
                    return result

            return MediaResult(ok=False, reason="stt_unavailable",
                               detail={"hint": "inject stt_fn or set "
                                               "ZOLANDER_STT_ENDPOINT"})
        except Exception as exc:  # noqa: BLE001 — nikdy nezastaviť agenta
            return MediaResult(ok=False, reason=f"error: {exc}")

    # ------------------------------------------------------------------
    # video
    # ------------------------------------------------------------------

    def process_video(self, path: str) -> MediaResult:
        """Extrahuj keyframy (ffmpeg ak je dostupný a povolený sandbox) a popíš ich.
        Nahradzuje placeholder `[User sent a video: url]` (~18395 v starom
        gateway run.py). sandbox blok => degradovaný MediaResult, žiadna výnimka von.
        """
        try:
            readable = self._readable(path)
            if readable is not True:
                return MediaResult(ok=False, reason=readable)

            frames = self._extract_frames(path)
            if frames:
                if self.describe_frames_fn is not None:
                    try:
                        desc = (self.describe_frames_fn(frames) or "").strip()
                        if desc:
                            return MediaResult(ok=True, text=desc, fallback_used=True,
                                               detail={"frames": len(frames)})
                    except PermissionError:
                        return MediaResult(ok=False, reason="access_blocked",
                                           fallback_used=True)
                    except Exception:  # noqa: BLE001
                        pass
                return MediaResult(
                    ok=True,
                    text=f"[video: {len(frames)} keyframe(s) extracted]",
                    fallback_used=True,
                    detail={"frames": len(frames), "described": False},
                )
            return MediaResult(ok=False, reason="frame_extraction_failed")
        except Exception as exc:  # noqa: BLE001
            return MediaResult(ok=False, reason=f"error: {exc}")

    def undecoded_reply_policy(self, result: MediaResult) -> Optional[str]:
        """Politika odpovede keď ok=False: krátke ľudské upovedomenie
        (niekoľko slov, bez em-dash, bez korpo tónu) alebo None (= neodpovedať).
        Nikdy narratíva nad prázdnym obsahom (KONS. #8)."""
        if result.ok:
            return None
        short = {
            "access_blocked": "hlasovku/video mi zablokoval systém, pošli to textom?",
            "empty": "prázdny zvuk, pošli to ešte raz textom?",
            "unsupported": "toto médium neviem prehrať, napíš to textom?",
        }
        default = "médium sa mi nepodarilo otvoriť, pošli to textom?"
        reply = short.get(result.reason, default)
        # istota proti em-dash aj korpo tónu (KONS. #6)
        return reply.replace("—", ",").replace("–", "-")[:120]

    # ------------------------------------------------------------------
    # interné
    # ------------------------------------------------------------------

    @staticmethod
    def _readable(path: str):
        """Kontrola čitateľnosti; vráti True, alebo dôvod zlyhania (str)."""
        if not path or not os.path.exists(path):
            return "unsupported"
        try:
            with open(path, "rb") as fh:
                fh.read(16)
            return True
        except PermissionError:
            return "access_blocked"
        except OSError as exc:
            if "operation not permitted" in str(exc).lower():
                return "access_blocked"
            return "unsupported"

    def _extract_frames(self, path: str, max_frames: int = 3) -> list[str]:
        """ffmpeg keyframe extraction do temp adresára; každý problém => []."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return []
        outdir = tempfile.mkdtemp(prefix="zolander_frames_")
        pattern = os.path.join(outdir, "frame_%03d.jpg")
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", path,
               "-vf", f"select=not(mod(n\\,100)),scale=480:-1,tile",
               "-frames:v", str(max_frames), pattern]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            if proc.returncode != 0:
                return []
        except Exception:  # noqa: BLE001 — timeout/sandbox/chýbajúci ffmpeg
            return []
        return sorted(
            os.path.join(outdir, name) for name in os.listdir(outdir)
            if name.endswith(".jpg")
        )

    def _try_remote_stt(self, path: str, endpoint: str) -> Optional[MediaResult]:
        """Fallback na povolený STT endpoint; vracia None ak nie je k dispozícii.
        Bez externých volaní v unit ceste — urllib až tu a len s krátkym timeoutom."""
        try:
            import json as _json
            import urllib.request

            boundary = "----zolanderMediaBoundary"
            filename = os.path.basename(path)
            with open(path, "rb") as fh:
                payload = fh.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
            req = urllib.request.Request(  # noqa: S310
                endpoint, data=body, method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                data = _json.loads(resp.read().decode("utf-8"))
            text = (data.get("text") or "").strip() if isinstance(data, dict) else ""
            if text:
                return MediaResult(ok=True, text=text, fallback_used=True)
            return MediaResult(ok=False, reason="empty", fallback_used=True)
        except Exception:  # noqa: BLE001 — endpoint nedostupný => degrade
            return None
