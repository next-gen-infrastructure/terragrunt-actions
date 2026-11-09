// Posts (or updates / removes) the per-unit plan/apply comment on a PR.
// Called from actions/github-script; reads /tmp/out.txt and /tmp/diagram.md.
// Env: UNIT, OUTCOME (steps.tg.outcome), CMD (plan|apply), PR_NUMBER.
const fs = require('fs');

const MAX_BODY = 60000; // GitHub rejects comments over 65536 characters
const FENCE = '```';
const NO_CHANGES = '✅ no changes';

function readDiagram() {
  const path = '/tmp/diagram.md';
  return fs.existsSync(path) ? fs.readFileSync(path, 'utf8').trim() : '';
}

function truncate(text) {
  return text.length > MAX_BODY ? `${text.slice(0, MAX_BODY)}\n... (truncated)` : text;
}

function statusOf({ outcome, cmd, output }) {
  if (outcome === 'failure') return cmd === 'apply' ? '❌ apply failed' : '❌ error';
  if (cmd === 'apply') return '🚀 applied';
  return /No changes\./.test(output) ? NO_CHANGES : '📝 changes';
}

function commentBody({ marker, unit, status, cmd, output, diagram }) {
  return [
    marker,
    `### \`${unit}\` — ${status}`,
    '',
    ...(diagram ? [diagram, ''] : []),
    `<details><summary>${cmd} output</summary>`,
    '',
    `${FENCE}diff`,
    output,
    FENCE,
    '',
    '</details>',
  ].join('\n');
}

module.exports = async ({ github, context }) => {
  const { UNIT: unit, OUTCOME: outcome, CMD: cmd, PR_NUMBER } = process.env;
  const issue_number = Number(PR_NUMBER);
  const output = truncate(fs.readFileSync('/tmp/out.txt', 'utf8'));
  const status = statusOf({ outcome, cmd, output });
  // the marker identifies this unit's comment across pushes
  const marker = `<!-- tg-plan:${unit} -->`;

  const { data: comments } = await github.rest.issues.listComments({
    ...context.repo, issue_number, per_page: 100,
  });
  const existing = comments.find(c => c.body.startsWith(marker));

  // no changes: skip the comment, and drop a stale one from an earlier push
  if (status === NO_CHANGES) {
    if (existing) await github.rest.issues.deleteComment({ ...context.repo, comment_id: existing.id });
    return;
  }

  const body = commentBody({ marker, unit, status, cmd, output, diagram: readDiagram() });
  if (existing) {
    await github.rest.issues.updateComment({ ...context.repo, comment_id: existing.id, body });
  } else {
    await github.rest.issues.createComment({ ...context.repo, issue_number, body });
  }
};
