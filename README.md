# terragrunt-actions

GitHub Actions for running [Terragrunt](https://terragrunt.gruntwork.io/) with [OpenTofu](https://opentofu.org/)
in CI: plan changed units on pull requests, plan and apply a whole environment, and get readable
summaries and Mermaid change diagrams.

They are composite actions, so secrets and credentials are **yours to set up**: run your own steps
(cloud credentials, VPN, kubeconfig, SOPS keys, ...) before these actions. Nothing here knows about a
specific cloud, secret store or approval process.

| Action | What it does |
|---|---|
| [`setup`](setup/action.yml) | Install OpenTofu and Terragrunt (Linux), enable the provider cache |
| [`detect-units`](detect-units/action.yml) | Environment from a base branch + the changed units as a matrix |
| [`run`](run/action.yml) | `plan`/`apply` in one unit, diagram, PR comment |
| [`plan-all`](plan-all/action.yml) | `plan --all`, per-unit step summary, dependency + change diagram, `has_changes` output |
| [`apply-all`](apply-all/action.yml) | `apply --all` with a step summary: unit table with durations, output of applied units, errors of failed ones, with `summary-path` / `report-path` / `log-path` outputs |

A [reusable workflow](.github/workflows/plan-units.yml) wires `detect-units`, `setup` and `run` into a
per-unit PR plan matrix.

## Layout it expects

```
<root-dir>/                  # default: terragrunt
  terragrunt.core.hcl        # shared config; a change re-plans every unit
  <env>/                     # e.g. development, production
    .shared.hcl              # per-env shared config; a change re-plans the env
    <unit>/terragrunt.hcl
```

`detect-units` maps the base branch to `<env>` with `env-map` (default `dev` -> `development`,
`main` -> `production`) and `root-dir` (default `terragrunt`).

## Usage

Per-unit plan on pull requests:

```yaml
on:
  pull_request:
    branches: [dev, main]

jobs:
  prepare:
    runs-on: ubuntu-latest
    outputs:
      env: ${{ steps.detect.outputs.env }}
      units: ${{ steps.detect.outputs.units }}
    steps:
      - uses: actions/checkout@v7
        with: { fetch-depth: 0, ref: "${{ github.event.pull_request.head.sha }}" }
      - id: detect
        uses: next-gen-infrastructure/terragrunt-actions/detect-units@v1
        with:
          base-ref: ${{ github.base_ref }}
          diff-spec: origin/${{ github.base_ref }}...HEAD

  plan:
    needs: prepare
    if: needs.prepare.outputs.units != '[]'
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.prepare.outputs.units) }}
    permissions: { contents: read, pull-requests: write }
    steps:
      - uses: actions/checkout@v7
        with: { ref: "${{ github.event.pull_request.head.sha }}" }
      # your credentials here (cloud, VPN, kubeconfig, ...)
      - uses: next-gen-infrastructure/terragrunt-actions/setup@v1
        with: { tofu-version: "1.12.6", tg-version: "1.1.4" }
      - uses: next-gen-infrastructure/terragrunt-actions/run@v1
        with:
          cmd: plan
          unit: ${{ matrix.unit }}
          pr-number: ${{ github.event.pull_request.number }}
```

Whole environment, after merge:

```yaml
      - uses: next-gen-infrastructure/terragrunt-actions/plan-all@v1
        id: plan
        with: { working-directory: terragrunt/development }
      # ...open an approval issue / ask a human when steps.plan.outputs.has_changes == 'true'...
      - uses: next-gen-infrastructure/terragrunt-actions/apply-all@v1
        with: { working-directory: terragrunt/development }
```

`apply-all` applies without asking: gate it yourself (environment protection rules, an approval
comment flow, ...).

### Reusable workflow

`plan-units.yml` does the matrix above for you. It cannot run your private setup steps, so it runs a
script from *your* repo (`setup_script`) with all secrets as JSON in `$SECRETS_JSON`, which needs
`secrets: inherit`. If you would rather not hand every secret to a shared workflow, use the composite
actions as shown above. See the header of the workflow for a call example.

## Details worth knowing

- **Plans are read from terragrunt's cache directory** with `tofu show` / `tofu graph`. A module pinned to
  a branch (`?ref=main`) is re-downloaded on every terragrunt call, which would delete `tf.plan`.
- **The step summary** shows each changed unit as a collapsible ```` ```diff ```` block with the change marker in
  column 0 (so GitHub colours it), without init or refresh noise. `helm_release` `metadata.values`
  (a huge, noisy diff) is dropped.
- Linux runners (`ubuntu-latest`); the scripts are stdlib-only Python 3.
- `run` posts its comment with `actions/github-script` and needs `pull-requests: write`.

## Versioning

Pin to a major tag (`@v1`), a full version (`@v1.2.3`) or, for the strictest setups, a commit SHA. Major
tags move to the latest release of that major; breaking changes ship as a new major.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests   # self-checks
```

CI runs actionlint and the self-checks. Publishing a `vX.Y.Z` release moves the `vX` tag
(`.github/workflows/release.yml`).

## License

[MIT](LICENSE)
