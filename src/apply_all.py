#!/usr/bin/env python3
"""Step summary for `terragrunt apply --all`: a table of the units that changed or did not
succeed, the output of each applied unit and the error of each failed one.

    apply_all.py <apply output> <report.json>  ->  /tmp/apply-summary.md and $GITHUB_STEP_SUMMARY

The output is terragrunt's own log, where each tofu line is prefixed with its unit
(`16:53:09.343 STDERR [d] tofu: ...`), so run it without --log-level error / --tf-forward-stdout.
The report comes from `--report-file report.json --report-format json` (an array of
{Name, Result, Reason, Cause, Started, Ended}). Units that applied with no changes are only counted.
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from tg_run import CHATTER

LINE = re.compile(
    r"^\d\d:\d\d:\d\d\.\d+\s+(?:STDOUT|STDERR)\s+\[([^\]]+)\]\s+tofu: ?(.*)$"
)
UNCHANGED = re.compile(
    r"^(No changes\.|Apply complete! Resources: 0 added, 0 changed, 0 destroyed)",
    re.MULTILINE,
)
ICON = {"succeeded": "✅", "failed": "❌", "early exit": "⏭️", "excluded": "➖"}
ORDER = list(ICON)[1:] + ["succeeded"]  # failures first
MAX_TEXT = 20000
SUMMARY_PATH = Path("/tmp/apply-summary.md")


def unit_outputs(log: str) -> dict[str, str]:
    """tofu output per unit, without refresh chatter."""
    lines: dict[str, list[str]] = {}
    for raw in log.splitlines():
        if (m := LINE.match(raw)) and not CHATTER.search(m[2]):
            lines.setdefault(m[1], []).append(m[2])
    return {unit: "\n".join(v).strip() for unit, v in lines.items()}


def seconds(entry: dict) -> float:
    # fromisoformat reads the trailing "Z" of a UTC runner's report from Python 3.11 on
    return (
        datetime.fromisoformat(entry["Ended"])
        - datetime.fromisoformat(entry["Started"])
    ).total_seconds()


def human(secs: float) -> str:
    s = round(secs)
    return f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s"


def clean_cause(cause: str) -> str:
    """Drops the throwaway cache path from `Failed to execute "tofu apply" in <path>` and the
    trailing spaces terragrunt leaves on blank lines."""
    cause = re.sub(r" in \S*\.terragrunt-cache\S*", "", cause)
    return re.sub(r"[ \t]+$", "", cause, flags=re.MULTILINE).strip()


def clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n... (truncated)"


def details(summary: str, body: str, open_: bool = False) -> str:
    return (
        f"<details{' open' if open_ else ''}><summary>{summary}</summary>\n\n"
        f"```text\n{clip(body)}\n```\n\n</details>\n"
    )


def render(report: list[dict], outputs: dict[str, str]) -> str:
    # a succeeded unit that printed no changes is only counted; one without output stays listed
    unchanged = {
        r["Name"]
        for r in report
        if r["Result"] == "succeeded" and UNCHANGED.search(outputs.get(r["Name"], ""))
    }
    shown = sorted(
        (r for r in report if r["Name"] not in unchanged),
        key=lambda r: (ORDER.index(r["Result"]), r["Name"]),
    )
    counts = Counter(r["Result"] for r in report)
    head = " · ".join(f"{ICON[k]} {counts[k]} {k}" for k in ICON if counts[k])
    out = [
        f"**{len(report)} units: {head}**"
        + (f" ({len(unchanged)} without changes)" if unchanged else ""),
        "",
    ]
    if not shown:
        return "\n".join(out)

    out += ["| Unit | Result | Duration | Reason |", "|---|---|---|---|"]
    for r in shown:
        cause = r.get("Cause", "")
        reason = r.get("Reason", "") + (
            f" ({cause})" if r.get("Reason") == "ancestor error" else ""
        )
        out.append(
            f"| `{r['Name']}` | {ICON[r['Result']]} {r['Result']} | {human(seconds(r))} | {reason} |"
        )
    out.append("")

    for r in shown:
        name, text = r["Name"], outputs.get(r["Name"], "")
        if r["Result"] == "failed":
            # the report's Cause holds terragrunt's full error; fall back to the unit's own output
            out.append(
                details(
                    f"❌ <code>{name}</code> failed",
                    clean_cause(r.get("Cause", "")) or text or "no output",
                    True,
                )
            )
        elif r["Result"] == "succeeded" and text:
            out.append(details(f"✅ <code>{name}</code>", text))
    return "\n".join(out)


def main() -> int:
    log_path, report_path = map(Path, sys.argv[1:3])
    log = log_path.read_text() if log_path.exists() else ""
    try:
        report = json.loads(report_path.read_text())
    except (
        OSError,
        ValueError,
    ):  # run died before writing a report: show the end of the log
        text = "\n".join(log.splitlines()[-80:]) or "no output"
        out = "**No run report was written.**\n\n" + details(
            "last lines of output", text, True
        )
    else:
        out = render(report, unit_outputs(log))
    SUMMARY_PATH.write_text(out + "\n")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/stdout"), "a") as f:
        f.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
