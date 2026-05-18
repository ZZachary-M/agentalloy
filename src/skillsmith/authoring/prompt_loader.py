"""Version-pinned prompt loader for the authoring pipeline.

Reads a fixture markdown file, extracts the HTML-comment version pin,
and returns (text, version). Emits a prompt_loaded event for telemetry
(Phase D wires the actual table; here we just log it).
"""

from __future__ import annotations

import logging
import re
import time as _time
from pathlib import Path

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"<!--\s*prompt_version:\s*([^\s]+)\s*-->")


def load_prompt(path: Path | str) -> tuple[str, str]:
    """Load a versioned prompt markdown file.

    Returns (text, version) where version is the parsed version pin or
    "" if no pin is found.
    """
    text = Path(path).read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    version = m.group(1) if m else ""
    _emit_prompt_loaded(Path(path).name, version)
    return text, version


def _emit_prompt_loaded(prompt_name: str, version: str) -> None:
    """Log the prompt_loaded event. Phase D wires this into the DB; for now, just log."""
    logger.debug("prompt_loaded name=%s version=%s ts=%d", prompt_name, version, int(_time.time()))
