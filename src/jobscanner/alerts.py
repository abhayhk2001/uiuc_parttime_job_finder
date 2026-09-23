import platform
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from jobscanner import config


def _format_match_row(job: dict) -> str:
    title = (job.get("job_title") or job.get("title") or "").strip()
    company = (job.get("company") or "").strip()
    jid = job.get("job_id", "")
    matches = job.get("matched_keywords") or ""
    url = job.get("detail_url", "")
    return f"[{jid}] {title} @ {company}  ::  matched: {matches}\n    {url}"


def summarize(matches: Iterable[dict]) -> None:
    matches = list(matches)
    if not matches:
        print("\nNo new matching jobs.")
        return
    print(f"\n=== {len(matches)} NEW MATCHING JOB(S) ===")
    for j in matches:
        print(_format_match_row(j))
    print()


def play_sound() -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            sound = Path(config.SOUND_FILE)
            if sound.exists():
                subprocess.run(["afplay", str(sound)], check=False)
                return
        elif system == "Linux":
            for cmd in (["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                        ["aplay", "/usr/share/sounds/alsa/Front_Center.wav"]):
                if shutil.which(cmd[0]):
                    subprocess.run(cmd, check=False)
                    return
        elif system == "Windows":
            import winsound  # type: ignore
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            return
        print("\a", end="", flush=True)
    except Exception as exc:
        print(f"(sound alert failed: {exc})")
        print("\a", end="", flush=True)


def alert(matches: Iterable[dict]) -> None:
    matches = list(matches)
    summarize(matches)
    if matches:
        play_sound()
