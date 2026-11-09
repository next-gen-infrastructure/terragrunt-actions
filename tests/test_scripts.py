"""Self-checks. Run: PYTHONPATH=src python3 -m unittest discover -s tests"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import apply_all
import dag_graph
import detect_units
import plan_diff
import plan_graph
import tg_run

DOT = """digraph {
  "[root] helm_release.app (expand)" -> "[root] kubernetes_secret_v1.tls (expand)"
  "[root] helm_release.app (expand)" -> "[root] provider[\\"x/helm\\"]"
  "[root] kubernetes_secret_v1.tls (expand)" -> "[root] kubernetes_namespace_v1.ns (expand)"
  "[root] kubernetes_secret_v1.tls (expand)" -> "[root] var.token (expand, reference)"
  "[root] provider[\\"x/helm\\"] (close)" -> "[root] helm_release.app (expand)"
}"""

PLAN = {
    "resource_changes": [
        {"address": "helm_release.app", "change": {"actions": ["update"]}},
        {
            "address": 'kubernetes_secret_v1.tls["a"]',
            "change": {"actions": ["delete", "create"]},
        },
        {"address": "kubernetes_namespace_v1.ns", "change": {"actions": ["no-op"]}},
        {"address": "data.x.y", "change": {"actions": ["read"]}},
    ]
}

HELM = """  # helm_release.this will be updated in-place
  ~ resource "helm_release" "this" {
      ~ metadata = {
          ~ revision = 1 -> (known after apply)
          ~ values   = jsonencode(
                {
                  - config = {
                      - "git.user" = "ArgoCD"
                    }
                }
            )
          ~ version  = "1.0" -> (known after apply)
        }
      ~ values   = [
          + "replicas: 2",
        ]
    }

  # vault_x.y will be updated in-place
  ~ resource "vault_x" "y" {
      ~ metadata = {
          ~ values = (known after apply)
        }
    }

  # random_id.x must be replaced
-/+ resource "random_id" "x" {
      + id = (known after apply)
    }"""


class PlanDiff(unittest.TestCase):
    def test_render(self):
        out = plan_diff.render(HELM)
        lines = out.split("\n")
        self.assertEqual((lines[0], lines[-1]), ("```diff", "```"))
        for gone in ("jsonencode", "git.user", "config"):
            self.assertNotIn(gone, out)
        self.assertEqual(
            out.count("values"), 2
        )  # helm top-level values + vault_x metadata.values
        self.assertIn(
            'version  = "1.0"', out
        )  # attribute after the dropped block survives
        self.assertIn('!   resource "helm_release" "this" {', lines)
        self.assertIn('!   resource "random_id" "x" {', lines)  # -/+ at column 0
        self.assertIn("+       id = (known after apply)", lines)

    def test_unclosed_skip_keeps_next_resource(self):
        out = plan_diff.render(
            '  ~ resource "helm_release" "a" {\n      ~ metadata = {\n'
            "          ~ values = jsonencode(\n  # next.one will be created"
        )
        self.assertIn("next.one will be created", out)


class Graphs(unittest.TestCase):
    def test_plan_graph(self):
        out, kind = plan_graph.render(PLAN, DOT)
        self.assertEqual(kind, "replace")  # replace beats update
        self.assertIn('helm_release.app"]:::update', out)
        self.assertIn('kubernetes_secret_v1.tls"]:::replace', out)
        self.assertTrue(
            out.count('kubernetes_namespace_v1.ns"]\n')
        )  # no-op node uncoloured
        self.assertNotIn("provider[", out)
        self.assertNotIn("var.token", out)
        self.assertRegex(out, r"n\d+ --> n\d+")

    def test_plan_graph_empty(self):
        out, kind = plan_graph.render({"resource_changes": []}, DOT)
        self.assertIn("no resource changes", out)
        self.assertEqual(kind, "none")

    def test_dag_graph(self):
        dot = """digraph {
\t"argocd" ;
\t"argocd" -> "keycloak";
\t"keycloak" ;
\t"vault" ;
\t"vault-config" -> "vault";
}"""
        out = dag_graph.render(dot, {"argocd": "update", "vault": "replace"})
        self.assertIn('argocd"]:::update', out)
        self.assertIn('vault"]:::replace', out)
        self.assertIn('keycloak"]:::none', out)  # unlisted unit defaults to none
        self.assertRegex(out, r"n\d+ --> n\d+")
        self.assertIn("no units", dag_graph.render("digraph {}", {}))


LOG = """\
16:53:09.262 INFO   [d] Downloading OpenTofu/Terraform configurations from ./d into ./d/.terragrunt-cache/x
16:53:09.293 INFO   [d] tofu: Initializing the backend...
16:53:09.343 STDERR [d] tofu: Error: Reference to undeclared input variable
16:53:09.347 STDOUT [a] tofu: terraform_data.x: Refreshing state... [id=1]
16:53:09.347 STDOUT [a] tofu: terraform_data.x: Creating...
16:53:09.347 STDOUT [a] tofu: Apply complete! Resources: 1 added, 0 changed, 0 destroyed.
16:53:09.348 STDOUT [b] tofu: Apply complete! Resources: 0 added, 0 changed, 0 destroyed.
"""


def entry(name, result, secs=3, **extra):
    return {
        "Name": name,
        "Result": result,
        "Started": "2026-11-09T16:53:09+01:00",
        "Ended": f"2026-11-09T16:53:{9 + secs:02d}+01:00",
        **extra,
    }


class ApplyAll(unittest.TestCase):
    def test_unit_outputs(self):
        out = apply_all.unit_outputs(LOG)
        self.assertEqual(sorted(out), ["a", "b", "d"])  # INFO lines are not tofu output
        self.assertEqual(
            out["a"],
            "terraform_data.x: Creating...\nApply complete! Resources: 1 added, 0 changed, 0 destroyed.",
        )
        self.assertEqual(out["d"], "Error: Reference to undeclared input variable")

    def test_render(self):
        report = [
            entry("a", "succeeded"),
            entry("b", "succeeded"),
            entry("d", "failed", Reason="run error", Cause="boom: exit status 1"),
            entry("e", "early exit", Reason="ancestor error", Cause="d"),
        ]
        out = apply_all.render(report, apply_all.unit_outputs(LOG))
        self.assertIn(
            "**4 units: ✅ 2 succeeded · ❌ 1 failed · ⏭️ 1 early exit** (1 without changes)",
            out,
        )
        rows = [line for line in out.splitlines() if line.startswith("| `")]
        self.assertEqual(
            [r.split("`")[1] for r in rows], ["d", "e", "a"]
        )  # failures first, unchanged `b` left out
        self.assertIn("| `e` | ⏭️ early exit | 3s | ancestor error (d) |", out)
        self.assertIn(
            "<details open><summary>❌ <code>d</code> failed</summary>\n\n```text\nboom: exit status 1",
            out,
        )
        self.assertIn("<summary>✅ <code>a</code></summary>", out)
        self.assertNotIn("<code>b</code>", out)

    def test_failed_cause_drops_cache_path(self):
        cause = (
            'error occurred:\n\n* Failed to execute "tofu plan -no-color -input=false" in '
            "./d/.terragrunt-cache/EX4uby8Q/ehsSKtGe\n  \n  Error: Reference to undeclared input variable\n  \n"
            "  exit status 1\n"
        )
        out = apply_all.render(
            [entry("d", "failed", Reason="run error", Cause=cause)], {}
        )
        self.assertIn(
            '* Failed to execute "tofu plan -no-color -input=false"\n\n  Error: Reference',
            out,
        )
        self.assertNotIn("terragrunt-cache", out)
        self.assertNotIn(" \n", out)

    def test_main_writes_summary_file_and_step_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "log").write_text(LOG)
            (tmp / "report.json").write_text(json.dumps([entry("a", "succeeded")]))
            env = {"GITHUB_STEP_SUMMARY": str(tmp / "step.md")}
            with (
                mock.patch.object(apply_all, "SUMMARY_PATH", tmp / "summary.md"),
                mock.patch.dict(os.environ, env),
                mock.patch(
                    "sys.argv",
                    ["apply_all", str(tmp / "log"), str(tmp / "report.json")],
                ),
            ):
                self.assertEqual(apply_all.main(), 0)
                # no report at all (the run died early): the end of the log is shown instead
                (tmp / "report.json").unlink()
                self.assertEqual(apply_all.main(), 0)
            summary = (tmp / "summary.md").read_text()
            self.assertIn("No run report was written", summary)
            self.assertIn(
                "**No run report was written.**", (tmp / "step.md").read_text()
            )
            self.assertIn("✅ 1 succeeded", (tmp / "step.md").read_text())

    def test_all_unchanged_is_only_counted(self):
        out = apply_all.render([entry("b", "succeeded")], apply_all.unit_outputs(LOG))
        self.assertEqual(out.strip(), "**1 units: ✅ 1 succeeded** (1 without changes)")

    def test_durations(self):
        self.assertEqual(
            [apply_all.human(s) for s in (4.4, 59.6, 75)], ["4s", "1m00s", "1m15s"]
        )


class TgRun(unittest.TestCase):
    def test_strip_output(self):
        raw = (
            "noise before init\nOpenTofu has been successfully initialized!\n\n"
            'You may now begin working with OpenTofu. Try running "tofu plan"\n\n'
            "a.b: Refreshing state... [id=1]\n"
            "Plan: 1 to add, 0 to change, 0 to destroy.\n\n  + resource"
        )
        self.assertEqual(
            tg_run.strip_output(raw),
            "Plan: 1 to add, 0 to change, 0 to destroy.\n\n  + resource",
        )


class DetectUnits(unittest.TestCase):
    def test_changed_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            self.addCleanup(os.chdir, cwd)
            for u in ("vault", "minio"):
                Path(f"infra/development/{u}").mkdir(parents=True)
                Path(f"infra/development/{u}/terragrunt.hcl").touch()
            Path("infra/development/vault/sub").mkdir()
            Path("infra/development/minio/.terragrunt-cache/x").mkdir(parents=True)
            Path("infra/development/minio/.terragrunt-cache/x/terragrunt.hcl").touch()

            f = detect_units.changed_units
            # nested file maps to its unit, listed once; files outside the env are ignored
            self.assertEqual(
                f(
                    [
                        "infra/development/vault/sub/a.tf",
                        "infra/development/vault/b.tf",
                        "infra/production/x/c.tf",
                        "README.md",
                        "",
                    ],
                    "infra",
                    "development",
                ),
                ["infra/development/vault"],
            )
            # shared config re-plans every unit (cache dirs excluded)
            all_ = ["infra/development/minio", "infra/development/vault"]
            self.assertEqual(
                f(["infra/development/.shared.hcl"], "infra", "development"), all_
            )
            self.assertEqual(
                f(["infra/terragrunt.core.hcl"], "infra", "development"), all_
            )

    def test_main_env_map(self):
        env = {
            **os.environ,
            "BASE_REF": "nope",
            "DIFF_SPEC": "HEAD",
            "GITHUB_OUTPUT": "/dev/null",
        }
        r = subprocess.run(
            ["python3", str(Path(__file__).parent.parent / "src" / "detect_units.py")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("unsupported base branch", r.stderr)


if __name__ == "__main__":
    unittest.main()
