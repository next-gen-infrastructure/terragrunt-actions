"""Render terragrunt's unit dependency graph as Mermaid, colour-coding each
unit by whether/how its plan changed."""

import re

EDGE = re.compile(r'^\s*"([^"]+)"\s*->\s*"([^"]+)"')
NODE = re.compile(r'^\s*"([^"]+)"\s*;\s*$')

STYLE = {
    "create": "fill:#dcfce7,stroke:#16a34a,color:#14532d",
    "update": "fill:#dbeafe,stroke:#2563eb,color:#1e3a8a",
    "replace": "fill:#fef9c3,stroke:#ca8a04,color:#713f12",
    "delete": "fill:#fee2e2,stroke:#dc2626,color:#7f1d1d",
    "none": "fill:#f1f5f9,stroke:#94a3b8,color:#334155",
}


def render(dot: str, changes: dict[str, str]) -> str:
    """`terragrunt dag graph` output + {unit: kind}; units missing from changes are drawn as none."""
    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    for line in dot.splitlines():
        m = EDGE.match(line)
        if m:
            edges.add((m.group(1), m.group(2)))
            nodes.update(m.groups())
            continue
        m = NODE.match(line)
        if m:
            nodes.add(m.group(1))

    if not nodes:
        return '```mermaid\nflowchart LR\n  none["no units"]\n```'

    ids = {name: f"n{i}" for i, name in enumerate(sorted(nodes))}
    out = ["```mermaid", "flowchart LR"]
    for name in sorted(nodes):
        out.append(f'  {ids[name]}["{name}"]:::{changes.get(name, "none")}')
    for a, b in sorted(edges):
        out.append(f"  {ids[a]} --> {ids[b]}")
    for kind, style in STYLE.items():
        out.append(f"  classDef {kind} {style};")
    out.append("```")
    return "\n".join(out)
