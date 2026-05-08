"""AuthoringConfig dataclass — authoring-specific settings narrowed to non-Optional.

Separated from skillsmith.config so the runtime package has no dependency on
authoring types. Obtained via Settings.require_authoring_config().
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthoringConfig:
    """Authoring fields narrowed to non-Optional str. Obtained via Settings.require_authoring_config()."""

    lm_studio_base_url: str
    authoring_lm_base_url: str
    authoring_embed_base_url: str
    authoring_model: str
    critic_model: str
    authoring_embedding_model: str
