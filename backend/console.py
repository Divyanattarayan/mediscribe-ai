"""Console configuration for the process entry points.

The pipeline prints diagnostics that interpolate model output, and model output
contains characters Windows' default cp1252 console cannot encode — a
non-breaking hyphen (U+2011) in a generated note was enough to raise
`UnicodeEncodeError` from inside a `print()` and abort the whole request.

A logging statement must never be able to destroy the work it is describing, so
the entry points force UTF-8 with replacement. This belongs at the entry point
rather than in the modules that print: the streams are process-wide state, and a
library reaching in to reconfigure them would surprise anything else sharing
them.
"""

from __future__ import annotations

import sys


def configure_console() -> None:
    """Make stdout and stderr total functions on any string."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - detached or odd stream
            pass
