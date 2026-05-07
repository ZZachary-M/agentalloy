# OSS Cleanup TODO — NaviStone branding scrub

**Created:** 2026-05-07 · **Status:** deferred — pick up before public OSS announcement

Repo is now MIT licensed (`LICENSE` + `pyproject.toml` updated 2026-05-07, copyright Nate Meyers). No proprietary NaviStone code or data found in the corpus, but the name appears as branding/attribution in several places that should be scrubbed before broad OSS distribution.

## Audit summary

**No proprietary content found.** No customer data, no internal APIs, no business logic, no NaviStone-specific source material in any skill body. All shipped skills are derived from public upstream docs.

The "navistone" string appears purely as authorship attribution and planning-doc references to packs that were never authored.

## Cleanup items

### 1. YAML `author:` field (~140 files)

Every shipped skill in `src/skillsmith/_packs/**/*.yaml` carries `author: navistone`. Pure metadata — no content impact.

**Action:** Bulk replace `author: navistone` → `author: nrmeyers` (or chosen handle) across all pack yamls. Also update the authoring fixtures and reference docs that document the convention:
- `fixtures/skill-authoring-agent.md`
- `fixtures/skill-qa-agent.md`
- `docs/skillsmith-authoring-reference.md`
- `docs/PACK-AUTHORING.md`

Sample command:
```bash
grep -rl "author: navistone" src/skillsmith/_packs/ | xargs sed -i 's/author: navistone/author: nrmeyers/g'
```

### 2. Hardcoded `github.com/navistone/...` URL pattern

`src/skillsmith/install/subcommands/install_pack.py` uses
`https://github.com/navistone/skill-pack-{name}/releases/latest/download/manifest.json`
as the default external-pack fetch URL. The `navistone` org is a placeholder — likely doesn't exist on GitHub.

**Action:** either
- Change to `nrmeyers` (or whatever org will actually host third-party packs), OR
- Make it env-configurable via `SKILLSMITH_PACK_REGISTRY_URL_TEMPLATE` and remove the hardcoded org.

Affected file: `src/skillsmith/install/subcommands/install_pack.py` (and possibly `INSTALL.md` if documented).

### 3. Planning-doc references to unbuilt "NaviStone-internal" packs

Several planning docs flag packs as `[NaviStone-internal]` — `martech-saas`, `direct-mail`, `arr-metrics`, `governance`. **None of these were ever authored.** They're aspirational planning notes only.

Files mentioning them:
- `docs/skillsmith-pack-inventory.md`
- `docs/NEXT-STEPS.md`
- `docs/ARCHITECTURE.md`
- `docs/skillsmith-authoring-reference.md`
- Various session-handoff docs in `docs/`

**Action options:**
- (a) Strip "NaviStone-internal" markers and rephrase as generic "internal/private packs" examples.
- (b) Move planning docs to `docs/internal/` and add to `.gitignore` (preserves history but keeps future churn private).
- (c) Delete the unbuilt-pack lines entirely since they have no shipped artifact.

Recommended: (a) for active reference docs; (c) for stale session handoffs that won't be read again.

### 4. Code-review of remaining mentions

Run a final sweep before publishing:

```bash
grep -rni "navistone" --include="*.yaml" --include="*.yml" --include="*.py" \
  --include="*.md" --include="*.toml" --include="*.json" \
  | grep -v "^archive/"
```

Confirm zero hits (or only intentional ones, e.g., a CHANGELOG note crediting the original author).

### 5. Archive directory

`archive/pre-poc-packs-2026-05-04/**` contains many `author: navistone` references in retired pack yamls. Low-priority since `archive/` is not loaded by the runtime, but consider:
- Keeping it as historical artifact, OR
- Moving the entire `archive/` tree out of the public repo before OSS publish (it's ~50+ retired files).

## Skipping for now because

User instruction (2026-05-07): "write this into a cleanup doc please. We'll need to come back to it." Not blocking the MIT license switch — repo is publishable as-is, but tidier branding before any announcement.

## Done definition

- `grep -rni navistone` (excluding `archive/`) returns 0 hits OR only ones intentionally preserved
- `install_pack.py` URL pattern doesn't reference an org that doesn't exist
- README, INSTALL.md, ARCHITECTURE.md, NEXT-STEPS.md read cleanly to a stranger with no NaviStone context
