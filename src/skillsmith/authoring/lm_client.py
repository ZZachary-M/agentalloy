"""Backward-compat shim: lm_client has moved to skillsmith.lm_client.

Remove this file when the authoring subpackage is deleted (Phase 2).
"""

from skillsmith.lm_client import (  # noqa: F401
    DEFAULT_TIMEOUT,
    LMBadResponse,
    LMClientError,
    LMModelNotLoaded,
    LMTimeout,
    LMUnavailable,
    OpenAICompatClient,
    warmup_ollama,
)
