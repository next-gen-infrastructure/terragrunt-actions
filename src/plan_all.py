#!/usr/bin/env python3
"""Plan reports built from the tf.plan files terragrunt leaves in its cache dirs.

  plan_all.py summary          per-unit plan as ```diff blocks -> $GITHUB_STEP_SUMMARY
  plan_all.py diagram          unit dependency graph + per-unit change graphs
                               -> /tmp/diagram.md and $GITHUB_STEP_SUMMARY, `has_changes=` -> $GITHUB_OUTPUT
  plan_all.py unit-diagram DIR change graph of one unit -> stdout (exit 1 when it has no plan)

summary/diagram run from the environment's unit tree (e.g. terragrunt/<env>) after
`terragrunt plan --all`. Plans are read with `tofu` straight from the cache dir: another
terragrunt call would re-download a branch-pinned module (ref=main) and wipe tf.plan.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import dag_graph
import plan_diff
import plan_graph

CACHE = ".terragrunt-cache"


def plans() -> dict[str, Path]:
    """{unit dir: tf.plan} for every planned unit under the current directory."""
    found: dict[str, Path] = {}
    for p in sorted(Path(".").rglob("tf.plan")):
        if CACHE in p.parts:
            found.setdefault("/".join(p.parts[: p.parts.index(CACHE)]), p)
    return found


def tool(cwd: Path, *cmd: str) -> str | None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else None


def unit_diagram(plan: Path) -> tuple[str, str] | None:
    show = tool(plan.parent, "tofu", "show", "-no-color", "-json", "tf.plan")
    if show is None:
        return None
    return plan_graph.render(json.loads(show), tool(plan.parent, "tofu", "graph") or "")


def append(path: str, text: str) -> None:
    with open(path, "a") as f:
        f.write(text)


def summary() -> None:
    found = plans()
    sections = []
    for unit, plan in found.items():
        txt = tool(plan.parent, "tofu", "show", "-no-color", "tf.plan")
        if txt is None or re.search(r"^No changes\.", txt, re.MULTILINE):
            continue
        sections.append(
            f"<details><summary><code>{unit}</code></summary>\n\n"
            f"{plan_diff.render(txt.rstrip(chr(10)))}\n\n</details>\n"
        )
    append(
        os.environ.get("GITHUB_STEP_SUMMARY", "/dev/stdout"),
        f"**{len(sections)} of {len(found)} planned units have changes**\n\n"
        + "\n".join(sections),
    )


def diagram() -> None:
    found = plans()
    kinds: dict[str, str] = {}
    sections = []
    # every unit, planned or not (a failed run leaves some without a plan)
    for hcl in sorted(Path(".").rglob("terragrunt.hcl")):
        if CACHE in hcl.parts:
            continue
        unit = str(hcl.parent)
        res = None
        try:
            res = unit_diagram(found[unit]) if unit in found else None
        except ValueError:
            pass
        md, kind = res or ("", "none")
        kinds[unit] = kind
        if kind != "none" and md:  # only units with changes get a section
            sections.append(
                f"<details><summary><code>{unit}</code></summary>\n\n{md}\n\n</details>\n"
            )

    dag = subprocess.run(
        ["terragrunt", "dag", "graph", "--no-color", "--log-level", "error"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    text = (
        "### Unit dependency graph\n\n"
        + dag_graph.render(dag, kinds)
        + "\n\n### Per-unit resource changes\n\n"
        + "\n".join(sections)
    )
    Path("/tmp/diagram.md").write_text(text)
    append(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"), text)
    append(
        os.environ.get("GITHUB_OUTPUT", "/dev/stdout"),
        f"has_changes={str(any(k != 'none' for k in kinds.values())).lower()}\n",
    )


def main() -> int:
    cmd, *args = sys.argv[1:] or [""]
    if cmd == "summary":
        summary()
    elif cmd == "diagram":
        diagram()
    elif cmd == "unit-diagram" and len(args) == 1:
        os.chdir(args[0])
        found = plans()
        res = unit_diagram(next(iter(found.values()))) if found else None
        if not res:
            return 1
        print(res[0])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
