# Downstream Fork — navistone/skillsmith

**Canonical home:** `https://github.com/nrmeyers/skillsmith` (MIT, public)
**Downstream fork:** `https://github.com/navistone/skillsmith` (private, NaviStone-internal)

The NaviStone fork carries select commits from upstream plus any NaviStone-internal packs (e.g. `martech-saas`, `direct-mail`, `governance`) that don't belong in the public OSS distribution.

## Two-remote setup

```bash
git remote -v
# origin     https://github.com/nrmeyers/skillsmith.git   (canonical)
# navistone  https://github.com/navistone/skillsmith.git  (downstream)
```

If a fresh clone needs the downstream remote:

```bash
git remote add navistone https://github.com/navistone/skillsmith.git
git fetch navistone
git checkout -b navistone-main navistone/main
git checkout main
```

`navistone-main` is the local working branch for downstream commits. `main` stays canonical.

## What gets cherry-picked downstream

By default, **only ship things downstream that NaviStone needs internally** that aren't already in upstream — most upstream work doesn't need to flow downstream because the canonical repo is already public.

Reasonable downstream-only content:
- NaviStone-internal packs (martech-saas, direct-mail, arr-metrics, governance)
- NaviStone-specific configuration, deployment, or integration glue
- Internal documentation, runbooks, or onboarding material

Reasonable upstream→downstream cherry-picks (when needed):
- Bug fixes affecting NaviStone deployments specifically
- Security patches before they're public
- New shared packs / runtime features that NaviStone wants to adopt without waiting for an upstream release

Avoid mirroring everything — drift from upstream is cheap; reconciling a duplicated linear history isn't.

## Cherry-pick workflow

```bash
git checkout navistone-main
git pull --ff-only                   # sync with navistone/main first

git cherry-pick <sha>                 # one commit
# or:
git cherry-pick <sha1>..<sha2>        # exclusive range
# or:
git cherry-pick <sha1> <sha2> <sha3>  # multiple specific commits

git push navistone navistone-main:main
git checkout main
```

Each cherry-pick produces a new SHA on the navistone branch — expected, since parent and committer date change.

If a cherry-pick conflicts: resolve, `git cherry-pick --continue`. To abandon: `git cherry-pick --abort`.

## NaviStone-internal-only commits

For commits that should **only** exist downstream (e.g. an internal pack):

```bash
git checkout navistone-main
# make the change directly
git add <files>
git commit -m "feat(navistone-internal): ..."
git push navistone navistone-main:main
```

Never push these to `origin` — they live only on the navistone fork.

## Visibility note

`navistone/skillsmith` is currently **public** but should be flipped to **private** by an org owner:

```bash
gh api -X PATCH repos/navistone/skillsmith -f private=true
gh api -X PATCH repos/navistone/skillsmith -f delete_branch_on_merge=true
```

Until that happens, treat the fork as if it were public — i.e., don't push anything sensitive.

## Verifying remote state

```bash
gh api repos/navistone/skillsmith --jq '{visibility, default_branch, pushed_at}'
gh api repos/navistone/skillsmith/commits/main --jq '.sha'
git log --oneline navistone/main -5
```
