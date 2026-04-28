# Pack Authoring Guide

Skillsmith uses a pack-based corpus model: skills are organized into named packs that users opt into at install time. This guide covers authoring a new pack and publishing it.

## What is a pack?

A pack is a directory containing:

- One `pack.yaml` manifest
- One or more skill YAML files (the actual skill definitions)

Example layout:

```
seeds/packs/nodejs/
  pack.yaml
  node-async-patterns.yaml
  node-streams.yaml
  node-error-handling.yaml
  ...
```

## `pack.yaml` schema

```yaml
name: nodejs                          # required, unique pack identifier
version: 1.0.0                        # required, semver
description: |                        # required, one-line summary
  Node.js (Node 22+) backend patterns — async, streams, errors, perf.
author: navistone                     # required
embed_model: qwen3-embedding:0.6b     # required, model the YAMLs were authored against
embedding_dim: 1024                   # required, hard-blocked on mismatch with corpus
license: MIT                          # required
homepage: https://...                 # optional
always_install: false                 # optional, default false; only `core` + `engineering` set true
depends_on:                           # optional list of pack names
  - typescript
skills:                               # required, inventory check
  - skill_id: node-async-patterns
    file: node-async-patterns.yaml
    fragment_count: 7
  - skill_id: node-streams
    file: node-streams.yaml
    fragment_count: 5
```

### Required fields

| Field | Notes |
|---|---|
| `name` | Lowercase, hyphenated. Must match the directory name. |
| `version` | Semver. Bump on any skill content change. |
| `description` | One sentence. Shown in the install picker. |
| `embed_model` | The model name the YAML content was authored against. Soft-warned on mismatch. |
| `embedding_dim` | The vector dimension. **Hard-blocked** on mismatch with the running corpus — install-pack will refuse. |
| `skills` | List of `{skill_id, file, fragment_count}` for every YAML in the pack. |

### Soft-blocked vs hard-blocked

- **Soft-blocked (warning only):** `embed_model` differs from the running corpus's model. The pack may work but retrieval quality could degrade.
- **Hard-blocked (refuses install):** `embedding_dim` differs. Mixing dimensions in DuckDB silently corrupts vector search.

## Authoring a new pack

### 1. Create the directory

```bash
mkdir -p seeds/packs/<pack-name>
```

### 2. Author skill YAMLs

Each skill follows the standard skillsmith ingest format (see `seeds/packs/core/test-driven-development.yaml` for a reference). Required fragment types: at least one `execution` fragment per skill, sequences must be contiguous.

### 3. Run the QA pipeline

Before adding to a pack, every authored skill should pass:

- **Deterministic checks** (schema, fragment types, sequences) — `python -m skillsmith.ingest <file> --yes` will reject malformed YAMLs.
- **Dedup against the live corpus** at 0.92 hard / 0.80 soft thresholds.
- **Critic review** — manual or via `python -m skillsmith.authoring qa`.

### 4. Generate the manifest

The `scripts/migrate-seeds-to-packs.py` script can regenerate `pack.yaml` for any pack directory by reading every YAML inside it. For new packs, copy an existing `pack.yaml` and edit by hand, or extend the migration script's `PACK_RULES` to classify your skill IDs.

### 5. Test the pack locally

```bash
skillsmith install-pack ./seeds/packs/<pack-name>
```

Verify:
- The action is `ingested` (not `ingested_with_errors`).
- The corpus skill count went up by `len(skills)`.
- Test queries hit the new skills.

## Versioning

Bump `pack.yaml` `version` whenever:
- A skill is added/removed
- A skill's `raw_prose` or fragments change materially
- `embed_model` or `embedding_dim` changes (these usually require re-publishing)

Use semver:
- **MAJOR** — breaking changes (skill removed, embedding_dim changed)
- **MINOR** — additive (new skills, new fragments)
- **PATCH** — small content fixes

Future: `skillsmith pack-bump <pack>` will automate this.

## Dependencies

`depends_on` declares hard prerequisites. The interactive picker installs deps automatically. Example:

```yaml
# seeds/packs/nestjs/pack.yaml
depends_on:
  - nodejs
  - typescript
```

Dependencies should reflect technical reality: `nestjs` IS Node.js + TypeScript, so picking `nestjs` should pull both.

## Publishing remotely (future)

Once `install-pack` supports manifest URLs (already implemented), publish a pack via:

1. Tarball the pack directory: `tar czf <name>-<version>.tar.gz seeds/packs/<name>/`
2. Compute sha256: `sha256sum <name>-<version>.tar.gz`
3. Publish a `manifest.json` to a stable URL:

   ```json
   {
     "tarball_url": "https://github.com/<org>/<repo>/releases/download/<tag>/<name>-<version>.tar.gz",
     "sha256": "<hex-digest>"
   }
   ```

4. Users install via:

   ```bash
   skillsmith install-pack <name>                    # uses default URL pattern
   skillsmith install-pack <name> --manifest-url ... # custom URL
   ```

## Pack boundaries — when to split

Don't bundle multiple decisions. A pack should answer one yes/no question.

| Good | Bad |
|---|---|
| `nestjs` (one framework) | `nestjs-stack` (NestJS + Redis + S3 — three decisions) |
| `vue` (one framework) | `frontend` (Vue + React + Next.js — three decisions) |
| `auth` (auth as a domain) | `nestjs-with-auth` (framework + domain mixed) |

If two skills always go together, they belong in the same pack. If they're orthogonal user choices, split them.

## Anti-patterns

- **Junk-drawer packs** — collecting unrelated skills under a generic name like `misc` or `polyglot`. Either the pack has a coherent answer to "do I want this?" or it shouldn't exist.
- **Opinion bundles** — packaging the maintainer's preferred stack. Different teams compose differently.
- **Empty packs** — don't create a pack for a future topic; create it when the first skill exists.
- **Hidden dependencies** — every dep should be in `depends_on`. Don't rely on the user installing both packs.
