#!/usr/bin/env python3
"""Picks the environment from BASE_REF and the changed terragrunt units from DIFF_SPEC.

Writes `env=` and `units=` (matrix JSON) to $GITHUB_OUTPUT (stdout when unset).
Run from the repo root. Env:
  BASE_REF   branch that selects the environment (e.g. dev)
  DIFF_SPEC  git diff args selecting changed files ('origin/dev...HEAD' or '<before> <after>')
  ROOT_DIR   directory holding <env>/ unit trees (default: terragrunt)
  ENV_MAP    JSON map of base branch -> environment (default: {"dev":"development","main":"production"})
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def all_units(env_dir: str) -> list[str]:
    return sorted(
        {
            str(p.parent)
            for p in Path(env_dir).rglob("terragrunt.hcl")
            if ".terragrunt-cache" not in p.parts
        }
    )


def unit_of(path: str, env_dir: str) -> str | None:
    d = os.path.dirname(path)
    while d != env_dir and d != ".":
        if os.path.isfile(f"{d}/terragrunt.hcl"):
            break
        d = os.path.dirname(d)
    return d if os.path.isfile(f"{d}/terragrunt.hcl") else None


def changed_units(changed: list[str], root: str, env: str) -> list[str]:
    env_dir = f"{root}/{env}"
    # A change to shared config re-plans every unit in the env.
    if f"{root}/terragrunt.core.hcl" in changed or f"{env_dir}/.shared.hcl" in changed:
        return all_units(env_dir)
    units = {unit_of(f, env_dir) for f in changed if f.startswith(env_dir + "/")}
    return sorted(units - {None})


def main() -> int:
    base_ref = os.environ["BASE_REF"]
    root = os.environ.get("ROOT_DIR", "terragrunt")
    env_map = json.loads(
        os.environ.get("ENV_MAP") or '{"dev":"development","main":"production"}'
    )
    env = env_map.get(base_ref)
    if not env:
        print(f"unsupported base branch: {base_ref}", file=sys.stderr)
        return 1

    subprocess.run(["git", "fetch", "--no-tags", "origin", base_ref], check=True)
    diff = subprocess.run(
        ["git", "diff", "--name-only", *shlex.split(os.environ["DIFF_SPEC"])],
        check=True,
        capture_output=True,
        text=True,
    )
    units = changed_units(diff.stdout.split("\n"), root, env)

    with open(os.environ.get("GITHUB_OUTPUT", "/dev/stdout"), "a") as out:
        out.write(f"env={env}\n")
        out.write(
            "units="
            + (json.dumps({"unit": units}, separators=(",", ":")) if units else "[]")
            + "\n"
        )
    print("\n".join(units) or "<none>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
