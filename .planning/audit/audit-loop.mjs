export const meta = {
  name: 'audit-loop',
  description: 'Self-running rotating audit+fix loop: pick the next risk dimension from the coverage ledger, reality-anchor, fan-out finders, adversarially verify, root-cause triage, auto-fix low/med only when the full suite stays green, then update the ledger. One invocation = one rotation.',
  whenToUse: 'Continuous whole-codebase hardening across every risk dimension (reality, security, data/state, correctness, output-hygiene, meta) — not a single lens. Safe to schedule on a cron; it self-limits by budget and auto-stops when all dimensions go quiescent.',
  phases: [
    { title: 'Load' },
    { title: 'Reality' },
    { title: 'Find' },
    { title: 'Verify' },
    { title: 'Triage' },
    { title: 'Fix' },
    { title: 'Persist' },
  ],
}

// ── Config paths + mode ──────────────────────────────────────────────────────
const CFG_PATH = '.planning/audit/config.json'
const LEDGER_PATH = '.planning/audit/ledger.json'
const REPORT_DIR = '.planning/audit/reports'
// args may arrive as an object OR as a JSON string (the harness sometimes serializes it) — parse defensively.
const _args = (typeof args === 'string')
  ? ((() => { try { return JSON.parse(args) } catch (_e) { return {} } })())
  : (args || {})
const MODE = (_args && _args.mode) || 'round'      // 'round' (full) | 'validate' (cheap wiring smoke-test)
const SEV_RANK = { none: 0, low: 1, medium: 2, high: 3, critical: 4 }

// ── Schemas ──────────────────────────────────────────────────────────────────
const LOAD_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['config', 'ledger', 'head', 'baselineFailures'],
  properties: {
    config: { type: 'object', additionalProperties: true },
    ledger: { type: 'object', additionalProperties: true },
    head: { type: 'string' },
    baselineFailures: { type: 'array', items: { type: 'string' } },
    // Authoritative CI-config baseline (config.ci_test_cmd). The final green-gate diffs against
    // THIS, not just the operator-config baseline, so operator config can never mask a CI failure.
    ciBaselineFailures: { type: 'array', items: { type: 'string' } },
  },
}
const REALITY_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['healthy', 'replyQuality'],
  properties: {
    healthy: { type: 'boolean' },
    firstTokenMs: { type: ['number', 'null'] },
    warmMs: { type: ['number', 'null'] },
    replyQuality: { type: 'string', enum: ['good', 'degraded', 'broken', 'unknown'] },
    notes: { type: 'string' },
    errors: { type: 'array', items: { type: 'string' } },
  },
}
const FINDING = {
  type: 'object', additionalProperties: true,
  required: ['title', 'severity', 'file', 'root_cause'],
  properties: {
    title: { type: 'string' }, severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
    file: { type: 'string' }, line: { type: ['number', 'null'] },
    root_cause: { type: 'string' }, evidence: { type: 'string' },
    failing_input: { type: 'string' }, fix_sketch: { type: 'string' },
    symptom_or_root: { type: 'string', enum: ['root', 'symptom', 'unclear'] },
  },
}
const FINDINGS_SCHEMA = { type: 'object', additionalProperties: true, required: ['findings'], properties: { findings: { type: 'array', items: FINDING } } }
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['verdict', 'corrected_severity', 'reason'],
  properties: {
    verdict: { type: 'string', enum: ['CONFIRMED', 'REFUTED', 'PLAUSIBLE'] },
    corrected_severity: { type: 'string', enum: ['none', 'low', 'medium', 'high', 'critical'] },
    reason: { type: 'string' }, real_failing_input: { type: 'string' },
    ambiguous: { type: 'boolean' },
  },
}
const TRIAGE_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['plan'],
  properties: {
    plan: {
      type: 'array', items: {
        type: 'object', additionalProperties: true, required: ['id', 'action'],
        properties: {
          id: { type: 'number' }, action: { type: 'string', enum: ['auto_fix', 'report_only'] },
          root_cause_note: { type: 'string' }, cluster: { type: 'string' },
        },
      },
    },
  },
}
const FIX_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['applied', 'reverted', 'pushed'],
  properties: {
    applied: { type: 'array', items: { type: 'string' } },
    reverted: { type: 'array', items: { type: 'string' } },
    pushed: { type: 'boolean' },
    newFailures: { type: 'array', items: { type: 'string' } },
    finalHead: { type: 'string' }, notes: { type: 'string' },
  },
}

// ── Phase 1 · Load config + ledger + test baseline; pick the dimension ────────
phase('Load')
const loaded = await agent(
  `Read two JSON files at the repo root and return them verbatim: ${CFG_PATH} as {config} and ${LEDGER_PATH} as {ledger}. ` +
  `Run \`git rev-parse HEAD\` and return it as {head}. ` +
  (MODE === 'round'
    ? `Then establish TWO baselines. (1) OPERATOR baseline: run config.test_cmd exactly and return {baselineFailures} = the array of currently FAILING pytest node ids (the "FAILED tests/..." lines; may be empty). (2) AUTHORITATIVE CI baseline: run config.ci_test_cmd exactly (it swaps in CI's clean stub config, runs with CI=true, then restores the operator config itself) and return {ciBaselineFailures} = the array of FAILED node ids from ITS output. This is the set the final green-gate diffs against, so operator config can never mask a CI-only failure. `
    : `In validate mode, set {baselineFailures} to [] and {ciBaselineFailures} to []. `) +
  `Do NOT modify any file (ci_test_cmd manages its own config backup/restore).`,
  { label: 'load+baseline', phase: 'Load', schema: LOAD_SCHEMA, agentType: 'general-purpose', effort: 'low' },
)
if (!loaded || !loaded.config || !loaded.ledger) {
  log('Load failed — cannot read config/ledger. Aborting round (no changes made).')
  return { ok: false, reason: 'load_failed' }
}
const config = loaded.config
const ledger = loaded.ledger
const baseline = loaded.baselineFailures || []
const ciBaseline = loaded.ciBaselineFailures || []
const roundNo = (ledger.round_counter || 0) + 1

// Dimension selection: never-run first, then stalest (smallest last_round), then highest weight.
const dims = (ledger.dimensions || []).filter((d) => d && d.key && !d.is_anchor)
const active = dims.filter((d) => !d.quiescent)
const allQuiescent = dims.length > 0 && active.length === 0
const pool = (active.length ? active : dims).slice()
pool.sort((a, b) => {
  const aNever = (a.last_round || 0) === 0 ? 1 : 0
  const bNever = (b.last_round || 0) === 0 ? 1 : 0
  if (aNever !== bNever) return bNever - aNever
  if ((a.last_round || 0) !== (b.last_round || 0)) return (a.last_round || 0) - (b.last_round || 0)
  return (b.weight || 0) - (a.weight || 0)
})
const chosen = pool[0]
if (!chosen) { log('No dimensions in ledger — aborting.'); return { ok: false, reason: 'no_dimensions' } }
log(`Round ${roundNo}: dimension="${chosen.key}" (${chosen.family}). ${active.length}/${dims.length} active${allQuiescent ? ' — ALL QUIESCENT (maintenance sweep)' : ''}. Baseline failing: operator=${baseline.length} ci=${ciBaseline.length} (CI is authoritative).`)

// ── Phase 2 · Reality anchor (best-effort, read-only) ─────────────────────────
phase('Reality')
let reality = null
const realityDue = ((ledger.round_counter || 0) % (config.reality_anchor_every_n_rounds || 1)) === 0
if (MODE === 'round' && realityDue) {
  reality = await agent(
    `REALITY ANCHOR — read-only, do NOT edit any code. The Layla app should be serving at ${config.app_url}.\n` +
    `1) curl ${config.app_url}/health — report status + whether a model is loaded.\n` +
    `2) If healthy, drive ONE real end-to-end chat turn by POSTing a substantive coding prompt to the /agent endpoint (non-stream JSON is fine), e.g. {"message":"Write a Python function that returns the nth Fibonacci number, with a docstring."}. Measure first-token / total latency if observable.\n` +
    `3) Judge the reply: is it correct & complete (good), present-but-poor (degraded), or missing/error (broken)? Note any leaked scaffold, wrong aspect, or per-turn errors.\n` +
    `If the app is not reachable, report healthy=false with a note (do not fail the round). Return the schema.`,
    { label: 'reality-anchor', phase: 'Reality', schema: REALITY_SCHEMA, agentType: 'general-purpose' },
  )
  log(`Reality: ${reality && reality.healthy ? 'healthy' : 'UNREACHABLE/unhealthy'} — quality=${(reality && reality.replyQuality) || 'n/a'}${reality && reality.errors && reality.errors.length ? ` — errors: ${reality.errors.length}` : ''}`)
}

// ── Phase 3 · Fan-out finders (distinct sub-lenses, read-only) ────────────────
phase('Find')
const lenses = (chosen.lenses && chosen.lenses.length) ? chosen.lenses : [chosen.key]
const nFinders = MODE === 'validate' ? 1 : (allQuiescent ? 2 : ((config.finders_per_dimension && (config.finders_per_dimension[chosen.key] || config.finders_per_dimension.default)) || 4))
const findResults = await parallel(
  Array.from({ length: nFinders }, (_, i) => () => agent(
    `You are auditing the Layla codebase (a local-first AI companion + engineering agent; FastAPI backend in agent/, vanilla-JS ES-module UI in agent/ui/) along the "${chosen.key}" (${chosen.family}) RISK DIMENSION.\n\n` +
    `Your assigned SUB-LENS (be exhaustive on THIS, ignore what other finders cover):\n  ${lenses[i % lenses.length]}\n\n` +
    `Working dir is the repo root. Read the ACTUAL code broadly (routers/, services/, agent_loop.py, orchestrator.py, ui/, layla/). ` +
    `Report only REAL, code-grounded defects you can cite by file:line — not style nits, not speculation. For each, prefer the ROOT cause over a surface symptom. ` +
    `Read-only: do NOT edit, run, or commit anything. Return the findings schema (empty array if the sub-lens is clean).`,
    { label: `find:${chosen.key}:${i}`, phase: 'Find', schema: FINDINGS_SCHEMA, agentType: 'general-purpose' },
  )),
)
let raw = findResults.filter(Boolean).flatMap((r) => (r.findings || []))
// Dedup by file + normalized title.
const seen = new Set()
const deduped = []
for (const f of raw) {
  if (!f || !f.title) continue
  const key = String(f.file || '') + '::' + String(f.title).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().slice(0, 48)
  if (seen.has(key)) continue
  seen.add(key)
  deduped.push(f)
}
log(`Find: ${raw.length} raw → ${deduped.length} unique findings from ${nFinders} lenses.`)

// Validate mode: prove the plumbing (load → pick → find → schema) works, then STOP — no verify,
// no fixes, no ledger mutation, no push. Pure wiring smoke-test.
if (MODE === 'validate') {
  log(`VALIDATE OK: dimension="${chosen.key}", ${deduped.length} finding(s) parsed. No changes made.`)
  return { ok: true, mode: 'validate', dimension: chosen.key, findings: deduped.length, head: loaded.head }
}

// ── Phase 4 · Adversarial verify (try to refute each) ─────────────────────────
phase('Verify')
const verified = deduped.length
  ? (await parallel(deduped.map((f) => () =>
      agent(
        `Adversarially VERIFY this "${chosen.key}" finding by reading the ACTUAL code. Try HARD to REFUTE it — default to REFUTED if you cannot independently reproduce it from the source.\n\n` +
        `FINDING: ${JSON.stringify({ title: f.title, file: f.file, line: f.line, severity: f.severity, root_cause: f.root_cause, evidence: f.evidence, failing_input: f.failing_input })}\n\n` +
        `Confirm ONLY if the cited code truly has the defect and it is reachable. Re-grade severity honestly (critical/high/medium/low/none). Flag ambiguous=true if the "fix" is a judgment call or risks regressing intended behavior. Read-only. Return the verdict schema.`,
        { label: `verify:${(f.file || '?').split('/').pop()}`, phase: 'Verify', schema: VERDICT_SCHEMA, agentType: 'general-purpose' },
      ).then((v) => (v ? { ...f, verdict: v } : null)),
    ))).filter(Boolean)
  : []
const confirmed = verified.filter((f) => f.verdict && f.verdict.verdict === 'CONFIRMED')
confirmed.forEach((f, i) => { f._id = i + 1 })
log(`Verify: ${confirmed.length}/${verified.length} CONFIRMED.`)

// ── Phase 5 · Root-cause triage → split auto-fix vs report-only ───────────────
phase('Triage')
const maxAuto = SEV_RANK[config.severity_auto_fix_max || 'medium']
let plan = confirmed.map((f) => {
  const sev = SEV_RANK[(f.verdict.corrected_severity || f.severity || 'low')]
  const ambiguous = !!f.verdict.ambiguous
  const auto = sev >= 1 && sev <= maxAuto && !ambiguous
  return { id: f._id, action: auto ? 'auto_fix' : 'report_only', cluster: '', root_cause_note: '' }
})
// Optional clustering pass (root-cause-not-symptom) when there are several confirmed findings.
if (MODE === 'round' && confirmed.length >= 3) {
  const t = await agent(
    `You are the ROOT-CAUSE TRIAGE for these verified "${chosen.key}" findings. Cluster ones that share a single underlying cause, and for each id decide action: "auto_fix" (a low/medium, mechanical, low-regression-risk fix) or "report_only" (high/critical, ambiguous, or a design change that needs a human). Prefer fixing the ROOT of a cluster over each symptom.\n\n` +
    `FINDINGS: ${JSON.stringify(confirmed.map((f) => ({ id: f._id, title: f.title, file: f.file, severity: f.verdict.corrected_severity, ambiguous: f.verdict.ambiguous, symptom_or_root: f.symptom_or_root, root_cause: f.root_cause })))}\n\n` +
    `Return the plan schema. Do NOT auto_fix anything critical/high or ambiguous. Read-only.`,
    { label: 'root-cause-triage', phase: 'Triage', schema: TRIAGE_SCHEMA, agentType: 'general-purpose', effort: 'high' },
  )
  if (t && Array.isArray(t.plan) && t.plan.length) {
    const byId = new Map(t.plan.map((p) => [p.id, p]))
    plan = plan.map((p) => {
      const tp = byId.get(p.id)
      if (!tp) return p
      // Safety intersection: triage may DOWNGRADE to report_only but may NOT upgrade a high/ambiguous to auto_fix.
      const f = confirmed.find((c) => c._id === p.id)
      const sev = SEV_RANK[(f.verdict.corrected_severity || f.severity || 'low')]
      const canAuto = sev >= 1 && sev <= maxAuto && !f.verdict.ambiguous
      const action = (tp.action === 'auto_fix' && canAuto) ? 'auto_fix' : (tp.action === 'report_only' ? 'report_only' : p.action)
      return { ...p, action, cluster: tp.cluster || '', root_cause_note: tp.root_cause_note || '' }
    })
  }
}
const autoIds = plan.filter((p) => p.action === 'auto_fix').map((p) => p.id)
const reportIds = plan.filter((p) => p.action === 'report_only').map((p) => p.id)
const autoFindings = confirmed.filter((f) => autoIds.includes(f._id))
log(`Triage: ${autoIds.length} auto-fix, ${reportIds.length} report-only.`)

// ── Phase 6 · Fix (single sequential integrator; green-gated push) ────────────
phase('Fix')
let fix = { applied: [], reverted: [], pushed: false, newFailures: [], finalHead: loaded.head, notes: '' }
if (MODE === 'round' && autoFindings.length) {
  const fixInput = autoFindings.map((f) => ({
    id: f._id, title: f.title, file: f.file, line: f.line,
    root_cause: f.root_cause, fix_sketch: f.fix_sketch, real_failing_input: f.verdict.real_failing_input || f.failing_input,
    root_cause_note: (plan.find((p) => p.id === f._id) || {}).root_cause_note || '',
  }))
  fix = (await agent(
    `You are the FIX INTEGRATOR for the Layla repo. Baseline HEAD is ${loaded.head}.\n` +
    `ALLOWED failing tests under the OPERATOR config (do NOT treat as regressions): ${JSON.stringify(baseline)}.\n` +
    `ALLOWED failing tests under the AUTHORITATIVE CI config (this is the set that actually gates a merge): ${JSON.stringify(ciBaseline)}.\n\n` +
    `STANDING RULES (must obey):\n` +
    `• Work on the "${config.branch}" branch directly. NEVER create a branch.\n` +
    `• NEVER stage or commit these protected globs: ${JSON.stringify(config.protected_paths)}. Check \`git status\` before every commit and unstage any protected/operator-state file.\n` +
    `• Keep the per-aspect sigils (⚔✦◎⚡⌖⊛) and Warframe aesthetic.\n` +
    `• End EVERY commit message with exactly: ${config.commit_trailer}\n` +
    `• Run pytest via the .venv-test interpreter; for JS use \`${config.js_check_cmd} <file>\`.\n\n` +
    `APPLY these verified low/medium fixes ONE AT A TIME (sequentially):\n${JSON.stringify(fixInput)}\n\n` +
    `For EACH finding: (a) edit the SOURCE to fix the ROOT cause (prefer the root_cause_note if present); (b) add or extend a regression test that fails before / passes after; (c) run ONLY the touched test file(s) as a scoped check (${config.scoped_test_hint}); for a UI/JS change also \`${config.js_check_cmd}\` it. If the scoped check passes, \`git add\` ONLY the source+test files (never protected globs) and \`git commit\` with the trailer. If the scoped check fails or you cannot cleanly fix it, run \`git checkout -- .\` to drop that finding's changes and record it in "reverted".\n\n` +
    `AFTER all findings, GREEN-GATE in two stages:\n` +
    `  1. Quick pass — run \`${config.test_cmd}\` (operator config). Its failing set must be a SUBSET of the operator baseline above (no NEW failures).\n` +
    `  2. AUTHORITATIVE pass — run \`${config.ci_test_cmd}\` (reproduces CI's clean stub config + CI=true; it backs up and restores runtime_config.json itself, so do NOT touch that file). Read its \`CI_GATE_RESULT exit=<code> failed=<n>\` line and its \`FAILED ...\` node ids. Its failing set must be a SUBSET of the CI baseline above (no NEW failures). This stage is decisive — a fix that passes stage 1 but adds a NEW failure under stage 2 is a regression and must NOT be pushed.\n` +
    `Only if BOTH stages have no new failures: \`git push origin ${config.branch}\` and set pushed=true. If EITHER stage shows any NEW failure, \`git reset --hard ${loaded.head}\` to drop the entire round's commits, set pushed=false, and list the new failures in newFailures. Return {applied,reverted,pushed,newFailures,finalHead=\`git rev-parse HEAD\`,notes}.`,
    { label: 'fix-integrator', phase: 'Fix', schema: FIX_SCHEMA, agentType: 'general-purpose', effort: 'high' },
  )) || fix
  log(`Fix: applied=${fix.applied.length} reverted=${fix.reverted.length} pushed=${fix.pushed}${fix.newFailures && fix.newFailures.length ? ` NEW-FAILURES=${fix.newFailures.length} (round reset)` : ''}`)
}

// ── Phase 7 · Update ledger + write round report ──────────────────────────────
phase('Persist')
const foundCount = confirmed.length
const dryRounds = foundCount === 0 ? (chosen.dry_rounds || 0) + 1 : 0
const quiescent = dryRounds >= (config.quiescence_dry_rounds || 2)
const maxSev = confirmed.reduce((m, f) => Math.max(m, SEV_RANK[(f.verdict.corrected_severity || f.severity || 'none')]), 0)
const sevName = Object.keys(SEV_RANK).find((k) => SEV_RANK[k] === maxSev) || 'none'
const newLedger = {
  ...ledger,
  round_counter: roundNo,
  dimensions: (ledger.dimensions || []).map((d) => (d.key === chosen.key
    ? { ...d, last_round: roundNo, dry_rounds: dryRounds, quiescent, open_findings: reportIds.length + (fix.reverted ? fix.reverted.length : 0), max_severity: sevName }
    : d)),
}
const summary = {
  round: roundNo, dimension: chosen.key, mode: MODE,
  reality: reality ? { healthy: reality.healthy, quality: reality.replyQuality } : null,
  found: foundCount, autoFixed: fix.applied.length, reverted: fix.reverted.length,
  reportOnly: reportIds.length, pushed: fix.pushed, newFailures: fix.newFailures || [],
  quiescentNow: quiescent, allQuiescent: allQuiescent && quiescent,
  reportFindings: confirmed.filter((f) => reportIds.includes(f._id)).map((f) => ({
    id: f._id, severity: f.verdict.corrected_severity, title: f.title, file: f.file, line: f.line,
    root_cause: f.root_cause, fix_sketch: f.fix_sketch, real_failing_input: f.verdict.real_failing_input,
  })),
}
await agent(
  `Persist the audit round results. Do exactly two writes:\n` +
  `1) Overwrite ${LEDGER_PATH} with this JSON (pretty-printed, 2-space), but FIRST set its "updated" field to the current UTC timestamp from \`date -u +%Y-%m-%dT%H:%M:%SZ\`:\n${JSON.stringify(newLedger)}\n\n` +
  `2) Write a human-readable round report to ${REPORT_DIR}/round-${roundNo}-${chosen.key}.md summarizing: the dimension, reality-anchor result, counts (found/auto-fixed/reverted/report-only), whether it pushed, and the FULL list of REPORT-ONLY findings (these need a human) with their severity, file:line, root cause, fix sketch, and failing input. Report data: ${JSON.stringify(summary)}\n\n` +
  `These two files (.planning/audit/*) are safe to commit; \`git add\` them and \`git commit\` with the trailer "${config.commit_trailer}", then \`git push origin ${config.branch}\` (this is ledger/report bookkeeping only, no source change). Return "done".`,
  { label: 'persist-ledger', phase: 'Persist', agentType: 'general-purpose', effort: 'low' },
)

log(`Round ${roundNo} complete: dimension=${chosen.key}, found=${foundCount}, auto-fixed+pushed=${fix.pushed ? fix.applied.length : 0}, report-only=${reportIds.length}${summary.allQuiescent ? '. ALL DIMENSIONS QUIESCENT — the loop can stop.' : ''}`)
return summary
