"""LadybugDB / Kuzu schema definitions.

Separate module so the migration path and tests share a single source of truth.

Fragment embeddings live in DuckDB ``fragment_embeddings`` (see
``skillsmith.storage.vector_store``), not LadybugDB — per v5.3 the VECTOR
extension is incompatible with restartable FastAPI service lifecycle. The
``EMBEDDING_DIM`` constant remains here for the DuckDB column type.
"""

from __future__ import annotations

EMBEDDING_DIM = 1024

NODE_TABLES: tuple[str, ...] = (
    """
    CREATE NODE TABLE IF NOT EXISTS Skill(
        skill_id STRING,
        canonical_name STRING,
        category STRING,
        skill_class STRING,
        domain_tags STRING[],
        deprecated BOOLEAN DEFAULT false,
        always_apply BOOLEAN DEFAULT false,
        phase_scope STRING[],
        category_scope STRING[],
        tier STRING,
        PRIMARY KEY(skill_id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS SkillVersion(
        version_id STRING,
        version_number INT64,
        authored_at TIMESTAMP,
        author STRING,
        change_summary STRING,
        status STRING,
        raw_prose STRING,
        PRIMARY KEY(version_id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Fragment(
        fragment_id STRING,
        fragment_type STRING,
        sequence INT64,
        content STRING,
        PRIMARY KEY(fragment_id)
    )
    """,
)

REL_TABLES: tuple[str, ...] = (
    "CREATE REL TABLE IF NOT EXISTS HAS_VERSION(FROM Skill TO SkillVersion)",
    "CREATE REL TABLE IF NOT EXISTS CURRENT_VERSION(FROM Skill TO SkillVersion)",
    "CREATE REL TABLE IF NOT EXISTS DECOMPOSES_TO(FROM SkillVersion TO Fragment)",
    "CREATE REL TABLE IF NOT EXISTS REQUIRES_COMPOSITIONAL(FROM Skill TO Skill)",
    "CREATE REL TABLE IF NOT EXISTS REFERENCES_CONCEPTUAL(FROM Skill TO Skill)",
)
