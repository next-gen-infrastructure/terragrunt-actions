# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Public, org-agnostic GitHub Actions for Terragrunt + OpenTofu CI (see README.md for usage). Credentials, VPN, kubeconfig, approval flows etc. are the *caller's* job and must stay out of this repo.

## Commands

```sh
PYTHONPATH=src python3 -m unittest discover -s tests        # all tests
PYTHONPATH=src python3 -m unittest tests.test_scripts.PlanDiff.test_render   # one test
pre-commit run --all-files                                   # check-yaml, actionlint, ruff, unittest
```

Python code is stdlib-only and needs 3.10+ (`X | None`, `:=`); runners have 3.12. There is no build step.

## Architecture

- Each action is a composite `<name>/action.yml` at the repo root (consumed as `org/repo/<name>@v1`, so they must stay at the root). They call into `src/` via `${{ github.action_path }}/../src/...`.
- `src/` holds all logic; modules are flat (no package) and import each other by bare name, hence `PYTHONPATH=src`. `plan-comment.js` is the only JS: it is `require()`d by `actions/github-script` from `run/action.yml`.
- Data flow of a plan: `tg_run.py` runs `terragrunt plan -out=tf.plan` and writes `/tmp/raw.txt` + `/tmp/out.txt`; `plan_all.py unit-diagram` writes `/tmp/diagram.md`; `plan-comment.js` reads both files. `plan_all.py diagram` also writes `/tmp/diagram.md` for the `plan-all` action output.
- **Plans are read with `tofu show`/`tofu graph` run inside terragrunt's `.terragrunt-cache/**/tf.plan` dir, never via another `terragrunt` call.** Units pinned to a branch (`?ref=main`) are re-downloaded on every terragrunt call, which wipes `tf.plan`. Keep it that way.
- `plan_all.py` maps units to plans by the path prefix before `.terragrunt-cache`; `plan_graph.render` and `dag_graph.render` are pure functions returning Mermaid; `plan_diff.render` turns `tofu show` text into a ```diff block (markers moved to column 0, `helm_release` `metadata.values` dropped).
- `plan-all` and `apply-all` keep their `terragrunt ... | tee` and `grep` steps as inline shell in the YAML (needs `set -o pipefail`).
- `.github/workflows/plan-units.yml` is the reusable per-unit PR plan workflow; it refs `terragrunt-actions/<x>@v1`, so it cannot run until a `v1` tag exists. `release.yml` moves the floating `vN` tag when a `vX.Y.Z` release is published.
- Third-party actions are pinned by SHA with a `# vN` comment (Renovate maintains them). Linux runners only.

## Conventions

- Conventional Commits. Never push to `main`; use `feature/*` or `fix/*` branches. Show the full commit message and get approval before every commit/push; no `Co-Authored-By` trailers.
- Keep the repo free of org-specific logic.
