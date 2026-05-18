#!/usr/bin/env python3
"""Verify intake skills in LadybugDB."""
from skillsmith.config import get_settings
from skillsmith.storage.ladybug import LadybugStore
from skillsmith.storage.vector_store import open_or_create, _duckdb_path

s = get_settings()
with LadybugStore(s.ladybug_db_path) as store:
    rows = store.execute(
        "MATCH (s:Skill) "
        "WHERE s.skill_id IN ['sys-intake-workflow-and-handoff', "
        "'sys-intake-router-and-confidence', "
        "'intake-verification-and-workflow-execution'] "
        "RETURN s.skill_id, s.skill_class, s.canonical_name "
        "ORDER BY s.skill_id"
    )
    print("=== LadybugDB skills ===")
    for r in rows:
        print(f"  {r[0]:50s} skill_class={r[1]:10s} name={r[2]}")

    # Count fragments
    rows2 = store.execute(
        "MATCH (s:Skill)-[:CURRENT_VERSION]->(v:SkillVersion)-[:DECOMPOSES_TO]->(f:Fragment) "
        "WHERE v.status = 'active' AND s.deprecated = false "
        "AND s.skill_id IN ['sys-intake-workflow-and-handoff', "
        "'sys-intake-router-and-confidence', "
        "'intake-verification-and-workflow-execution'] "
        "RETURN s.skill_id, count(f)"
    )
    print("\n=== Fragment counts ===")
    for r in rows2:
        print(f"  {r[0]:50s} fragments={r[1]}")

# Check DuckDB embeddings
duck = _duckdb_path(s)
with open_or_create(duck) as vs:
    total = vs.count_embeddings()
    print(f"\n=== DuckDB total embeddings === {total}")
    for sid in ['sys-intake-workflow-and-handoff', 'sys-intake-router-and-confidence', 'intake-verification-and-workflow-execution']:
        # Check if fragments for this skill are embedded
        ids = vs.fragment_ids_present([f"{sid}-v1-f1"])
        print(f"  {sid:50s} f1 present={bool(ids)}")
