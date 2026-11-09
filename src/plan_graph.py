"""Render a tofu/terraform dependency graph as Mermaid, colour-coding the
resources that a plan will change."""

import re

MAX_NODES = 120
DROP = re.compile(r"^(provider\[|var\.|local\.|output\.|module\.[^.]+$|root$)")
SUFFIX = re.compile(r"\s*\((expand|close)(,\s*reference)?\)\s*$")
EDGE = re.compile(r'"\[root\]\s*([^"]+)"\s*->\s*"\[root\]\s*([^"]+)"')

# highest-priority action wins when a resource has several instances
PRIORITY = ["replace", "delete", "create", "update"]
STYLE = {
    "create": "fill:#dcfce7,stroke:#16a34a,color:#14532d",
    "update": "fill:#dbeafe,stroke:#2563eb,color:#1e3a8a",
    "replace": "fill:#fef9c3,stroke:#ca8a04,color:#713f12",
    "delete": "fill:#fee2e2,stroke:#dc2626,color:#7f1d1d",
}


def clean(node: str) -> str:
    return SUFFIX.sub("", node).strip()


def keep(node: str) -> bool:
    return not DROP.match(node) and "." in node


def actions_kind(actions):
    a = sorted(actions)
    if a == ["create"]:
        return "create"
    if a == ["update"]:
        return "update"
    if a == ["delete"]:
        return "delete"
    if a == ["create", "delete"]:
        return "replace"
    return None


def load_changes(plan: dict) -> dict:
    changes: dict[str, str] = {}
    for rc in plan.get("resource_changes", []):
        kind = actions_kind(rc["change"]["actions"])
        if not kind:
            continue
        base = re.sub(r"\[[^\]]*\]$", "", rc["address"])  # strip instance key
        cur = changes.get(base)
        if cur is None or PRIORITY.index(kind) < PRIORITY.index(cur):
            changes[base] = kind
    return changes


def aggregate_kind(changes: dict) -> str:
    for kind in PRIORITY:
        if kind in changes.values():
            return kind
    return "none"


def render(plan: dict, dot: str) -> tuple[str, str]:
    """Mermaid block for `tofu show -json` (plan) and `tofu graph` (dot) output, plus the
    unit's aggregate change kind (create/update/replace/delete/none)."""
    changes = load_changes(plan)
    kind = aggregate_kind(changes)

    edges: set[tuple[str, str]] = set()
    nodes: set[str] = set()
    for m in EDGE.finditer(dot):
        a, b = clean(m.group(1)), clean(m.group(2))
        if keep(a) and keep(b):
            edges.add((a, b))
            nodes.update((a, b))

    if not changes:
        return '```mermaid\nflowchart LR\n  none["no resource changes"]\n```', kind
    if not nodes:  # graph unavailable - degrade to a flat list
        nodes = set(changes)
    if len(nodes) > MAX_NODES:
        n = len(changes)
        return (
            f"_dependency graph too large to render ({len(nodes)} nodes); "
            f"{n} resource change{'s' if n != 1 else ''} - see plan output below._"
        ), kind

    ids = {name: f"n{i}" for i, name in enumerate(sorted(nodes))}
    out = ["```mermaid", "flowchart LR"]
    for name in sorted(nodes):
        suffix = f":::{changes[name]}" if name in changes else ""
        out.append(f'  {ids[name]}["{name}"]{suffix}')
    for a, b in sorted(edges):
        out.append(f"  {ids[a]} --> {ids[b]}")
    for k, style in STYLE.items():
        if k in changes.values():
            out.append(f"  classDef {k} {style};")
    out.append("```")
    return "\n".join(out), kind
