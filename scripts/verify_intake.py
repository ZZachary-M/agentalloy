"""Verify intake skills in LadybugDB and run reembed."""
import sys
import subprocess
from pathlib import Path

from skillsmith.storage.ladybug import LadybugStore
from skillsmith.config import get_settings

def main():
    settings = get_settings()
    store = LadybugStore(settings.ladybug_db_path)
    try:
        store.open()
        store.migrate()
        rows = store.execute(
            "MATCH (s:Skill) WHERE s.skill_id CONTAINS 'intake' "
            "RETURN s.skill_id, s.skill_class, s.canonical_name"
        )
        if not rows:
            print("ERROR: No intake skills found in LadybugDB")
            return 1
        print(f"Found {len(rows)} intake skill(s) in LadybugDB:")
        for r in rows:
            skill_id, skill_class, name = r
            print(f"  {skill_id} | class={skill_class} | {name}")
            if skill_class != "workflow":
                print(f"  WARNING: expected skill_class='workflow', got '{skill_class}'")
        print("\nNow running reembed...")
        result = subprocess.run(
            [sys.executable, "-m", "skillsmith.install", "reembed"],
            capture_output=True, text=True, timeout=120
        )
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        return result.returncode
    finally:
        store.close()

if __name__ == "__main__":
    sys.exit(main())
