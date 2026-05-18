"""Authoring pipeline: SKILL.md → Author LLM → QA gate → pending-review.

Requires explicit configuration: authoring_model, critic_model, and
authoring_embedding_model must all be set in config before any authoring
code paths are invoked. Not part of the default install.
"""
