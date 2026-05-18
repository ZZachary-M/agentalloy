#!/usr/bin/env python3
"""Check LadybugDB for intake skills."""
import sqlite3
import time
import sys

db = "/home/nmeyers/.local/share/skillsmith/corpus/ladybug"

for i in range(10):
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = conn.execute(
            "SELECT skill_id, canonical_name, skill_class, skill_type FROM skills "
            "WHERE skill_id LIKE '%intake%' ORDER BY skill_id"
        )
        rows = cur.fetchall()
        for r in rows:
            print(f"  skill_id={r[0]!r}, canonical_name={r[1]!r}, skill_class={r[2]!r}, skill_type={r[3]!r}")
        if not rows:
            print("No intake skills found in LadybugDB")
        conn.close()
        sys.exit(0)
    except sqlite3.OperationalError as e:
        print(f"Attempt {i}: {e}, waiting 2s...")
        time.sleep(2)

print("ERROR: could not open DB after 10 attempts")
sys.exit(1)
