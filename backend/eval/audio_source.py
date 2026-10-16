"""Fetch evaluation audio without keeping it.

Benchmark audio is large — PriMock57 is ~1.9 GB in full, and a `git clone` with
LFS stores it twice (once checked out, once in `.git/lfs/objects`). None of that
needs to persist: a WER run reads each file exactly once, and what we keep
afterwards is the transcript and the metrics, which are kilobytes.

So audio is streamed one file at a time and deleted as soon as it has been
transcribed. Peak disk is one recording (~26 MB) instead of the whole corpus.
Pass a `cache_dir` to trade that back for repeat-run speed.
"""

from __future__ import annotations

import shutil
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# GitHub serves the real bytes behind an LFS pointer from this host, so a public
# LFS-backed repo can be read file by file over plain HTTPS — no git, no
# git-lfs, no local clone.
GITHUB_LFS_MEDIA = "https://media.githubusercontent.com/media"

_CHUNK = 1 << 20  # 1 MiB
_USER_AGENT = "mediscribe-eval/1.0 (+evaluation harness)"


def primock57_audio_url(filename: str, ref: str = "main") -> str:
    return f"{GITHUB_LFS_MEDIA}/babylonhealth/primock57/{ref}/audio/{filename}"


def download(url: str, destination: Path, *, timeout: int = 300) -> Path:
    """Stream `url` to `destination`. Never holds the file in memory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})

    # Write to a sibling temp file and move into place, so an interrupted
    # download cannot leave a truncated file that a cached run would trust.
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as handle:
            shutil.copyfileobj(response, handle, _CHUNK)
        partial.replace(destination)
    except (urllib.error.URLError, TimeoutError, OSError):
        partial.unlink(missing_ok=True)
        raise
    return destination


@contextmanager
def local_audio(
    audio_path: str | None,
    audio_url: str | None,
    *,
    cache_dir: Path | None = None,
) -> Iterator[Path]:
    """Yield a readable local path for a case's audio.

    Resolution order, cheapest first:

    1. `audio_path` that already exists — used in place, never deleted.
    2. a cached download, when `cache_dir` is set and the file is there.
    3. a fresh download, deleted on exit unless `cache_dir` is set.
    """
    if audio_path:
        existing = Path(audio_path)
        # A stale LFS pointer is a ~130 byte text file, not audio. Treat it as
        # absent so the URL path takes over rather than handing Whisper garbage.
        if existing.exists() and existing.stat().st_size > 10_000:
            yield existing
            return

    if not audio_url:
        raise FileNotFoundError(
            f"No usable audio: path={audio_path!r} does not exist and no audio_url was given."
        )

    filename = audio_url.rsplit("/", 1)[-1]

    if cache_dir is not None:
        cached = Path(cache_dir) / filename
        if not (cached.exists() and cached.stat().st_size > 10_000):
            download(audio_url, cached)
        yield cached
        return

    temporary_dir = Path(tempfile.mkdtemp(prefix="mediscribe-eval-"))
    try:
        yield download(audio_url, temporary_dir / filename)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
