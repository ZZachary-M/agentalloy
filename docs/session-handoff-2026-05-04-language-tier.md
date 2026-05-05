# Session Handoff — Language Tier Authoring

**Date:** 2026-05-04
**Working dir:** `/home/nmeyers/dev/skillsmith`
**Last branch worked on:** `feat/lang-nodejs` (PR #10, awaiting merge)

## What you are doing

Authoring skill packs against the priority queue in `docs/skillsmith-pack-inventory.md`, one pack per PR, sourced via R1 tiered sourcing. Foundation tier is complete. **You are mid-language-tier**, three packs in.

## State of the corpus on `main`

| Pack | Class | Status |
|---|---|---|
| `meta` | system | merged (PR #5) |
| `conventions` | system | merged (PR #5) |
| `core` | foundation | 12 skills, merged (PR #5, #6) |
| `engineering` | foundation | 5 skills, merged (PR #6) |
| `documentation` | foundation | 4 skills, merged (PR #6) |
| `refactoring` | foundation | 4 skills, merged (PR #6) |
| `performance` | foundation | 4 skills, merged (PR #6) |
| `python` | language | 5 skills, merged (PR #7) |
| `typescript` | language | 5 skills, merged (PR #9) |
| `nodejs` | language | 5 skills, **PR #10 open** |

Other recent PRs:
- PR #8 merged — `chore/deps-and-lm-timeout` (asyncpg, pyjwt, LM read-timeout 900→1800s)
- Branch `experiments/skill-tax-and-scratch` parked (skill-tax harness, prompts, app/ scratch — no PR, just a parking branch). `experiments/**/*.duck` is in `.gitignore`.

## What's next on the priority queue

Next language-tier packs in inventory order (`docs/skillsmith-pack-inventory.md`):

1. **go** [ga] — rank 5
2. **rust** [ga] — rank 6
3. **shell-bash** [ga] — rank 7 (rationale in inventory: "everyone uses it daily and most use it badly — high-leverage")
4. **sql** [v1] — rank 8
5. **csharp-dotnet** [v1] — rank 9

Curated source files exist for all of these at `fixtures/upstream/curated/{go,rust,csharp,...}.yaml`. The user has been comfortable with you choosing the order; default to inventory rank.

**Start with `go` next.** Wait for PR #10 (nodejs) to merge before branching, then `git checkout main && git pull && git checkout -b feat/lang-go`.

## Authoring methodology (do not skip)

### Workflow per pack

1. `git checkout main && git pull && git checkout -b feat/lang-<name>`
2. Read `fixtures/upstream/curated/<lang>.yaml` for canonical sources, version anchor, and topics.
3. Create `src/skillsmith/_packs/<name>/pack.yaml` with `tier: language`, `depends_on: [core, engineering]`, `always_install: false`, empty `skills: []`.
4. Author 5 precision-favored skills as separate YAMLs.
5. Fill in `skills:` list in `pack.yaml` with `skill_id`, `file`, `fragment_count` for each.
6. Run `uv run python -m skillsmith.install install-pack src/skillsmith/_packs/<name>` — should produce `ingest_failures: 0`.
7. Remediate any soft warnings in source (see "Validation gotchas" below).
8. Commit, push, open PR with the standard summary shape (see PR #10 for the template).

### Skill YAML structure

Required top-level fields:
```yaml
skill_type: domain
skill_id: <kebab-case>
canonical_name: <Title Case With Subtitle In Parens>
category: engineering          # NOT "language" — only design/engineering/ops/quality/review/tooling allowed for domain skills
skill_class: domain
domain_tags: [tag-1, tag-2, tag-3, tag-4, tag-5]   # 5 tags, no stem-dups, no overlap with title stems
always_apply: false
phase_scope: null
category_scope: language        # OK to use "language" here — this is a different field
author: navistone
change_summary: |
  Initial authoring 2026-05-04. Sources — <name with URL> (verified 2026-05-04 against fixtures/upstream/curated/<lang>.yaml topic `<topic>`); <other authoritative sources>. Skill scope: <what this covers>; not <what's out of scope, with pointers to where it lives>.

raw_prose: |
  # <Skill Title>

  <Opening rationale paragraph: rule-in-one-sentence + why-most-people-fail-it.>

  ## <Section 1>
  ...

  ## Verification

  - [ ] <mechanically checkable item>
  - [ ] ...

fragments:
  - sequence: 1
    fragment_type: rationale
    content: |
      # <Skill Title>

      <Same opening text — must be CONTIGUOUS slice of raw_prose, no drift>
  - sequence: 2
    ...
```

### Fragment types — only these six

`setup`, `execution`, `rationale`, `example`, `guardrail`, `verification`. Anti-pattern fragments → `guardrail`. Code-heavy blocks → `example` (NOT `execution`). Step-by-step prose without code → `execution`.

**Each domain skill MUST have at least one `execution` fragment**, or ingest fails with validation error.

### Fragment sizing

- **Floor: 80 words.** Below this, qwen3-embedding:0.6b produces under-discriminative vectors. Soft warning at ingest; pad in source.
- **Ceiling: 800 words.** Split at semantic boundaries above this.
- **Self-contained.** No "see above" — name siblings explicitly.
- **Contiguous slice of `raw_prose`.** When you pad a fragment, also pad the corresponding span in `raw_prose` with the same text. Drift breaks BM25 retrieval; ingest warns.

### R1–R8 authoring rules

Live in `src/skillsmith/_packs/meta/sys-skill-authoring-rules.md`. The ones I hit most:

- **R1**: For fast-moving APIs, fetch authoritative docs before authoring. Cite verified date inline.
- **R2**: Every non-stdlib name in a code block must show its `import` once.
- **R3**: Verification items must be mechanically checkable.
- **R5**: Date-stamp version-specific claims `(verified 2026-05-04)`.
- **R8**: Short rationale fragments need 3+ obvious-query keywords for the embedder to land them on relevant queries.

## Validation gotchas (you WILL hit these)

When `install-pack` runs, expect some warnings. These are the recurring ones:

1. **`category: language` rejects.** Use `category: engineering` (or design/ops/quality/review/tooling). The string `language` lives in `category_scope`, not `category`.
2. **"domain skill requires at least one 'execution' fragment".** Promote one fragment from `example` or `rationale` to `execution`. Pick a fragment that's mostly prose with steps; avoid promoting code-heavy blocks (linter will then complain "code-fence-heavy — likely should be 'example'").
3. **Tag stem-dup warnings (R3-stem).** Two tags share word stems (e.g. `error-propagation` and `contextual-error`). Replace one with a distinct concept-tag.
4. **Tag redundant-with-title warning (R2).** Tag stem-overlaps the canonical_name. Replace.
5. **Fragment under 80 words.** Pad both the fragment AND the corresponding span in `raw_prose`. Use `Edit` with `replace_all: true` so both copies stay in sync.
6. **"raw_prose contiguity" warning.** You padded a fragment but forgot the raw_prose. Fix.
7. **`install-pack` has NO `--force` flag.** First successful ingest of a skill ID locks it; you cannot re-ingest the same skill_id. The user does not require re-ingest — fixing source for next clean install is enough (the corpus DB is rebuilt from scratch on user setup).

## Local environment

- `uv` for Python; runtimes via `mise`. Never `pip` directly into system, never `npm` (use `pnpm` if needed).
- `gh` works (the user has merge-rule bypass fixed; PRs can merge after CI passes).
- `glab` for GitLab — N/A for this repo (GitHub).
- DuckDB binaries (`*.duck`, `experiments/**/*.duck`) are gitignored. Never commit them.

## User preferences (from memory + observed)

- **Branch + PR for code, direct-to-main for docs only.** This handoff doc is borderline; user has been doing direct-to-main for similar in the past. Ask if unsure.
- **Brutally concise tone, no pleasantries, fix code silently.**
- **Auto mode is on** — execute autonomously, minimize interruptions, prefer action.
- **Trust but verify on agent claims** — when wrapping up a skill, do not assume tests pass; the ingest output is your verification surface.
- Memory at `/home/nmeyers/.claude/projects/-home-nmeyers-dev-skillsmith/memory/MEMORY.md` has the durable preferences.

## What NOT to do

- Do not commit `experiments/`, `app/`, `prompts/`, or any `*.duck` file. The first three are parked on `experiments/skill-tax-and-scratch`; the last is gitignored.
- Do not touch `pyproject.toml`, `uv.lock`, or `src/skillsmith/authoring/lm_client.py` unless the task explicitly calls for it. Those land in `chore/`-prefixed PRs of their own.
- Do not author skills outside the inventory's order without checking with the user. Inventory is the source of truth for sequencing.
- Do not skip the curated source check — the `change_summary` must cite which `fixtures/upstream/curated/<lang>.yaml` topic was used, with the verified date.

## To start the next session

```
You're continuing language-tier corpus authoring on the skillsmith repo.
Read docs/session-handoff-2026-05-04-language-tier.md first — it captures
state, methodology, and the next pack to author (go).
Auto mode is on; proceed.
```

Or, more terse:
```
Continue corpus authoring per docs/session-handoff-2026-05-04-language-tier.md.
Next pack: go.
```
