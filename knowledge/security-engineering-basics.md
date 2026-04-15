---
priority: core
domain: security
aspects: Lilith, Morrigan
difficulty: beginner
related: devops-cicd-patterns.md, containers-orchestration.md
---

# Security engineering basics

## Threat model (tiny version)

- **What are we protecting?** (secrets, user data, credentials, execution privileges)
- **Who could attack it?** (malicious input, compromised dependency, local malware)
- **How would it be attacked?** (RCE, path traversal, prompt injection, token theft)
- **What is the blast radius?** (files, network, credentials, system control)

## Secrets handling

- Never commit `.env`, tokens, keys, or local config files containing paths/secrets.
- Prefer environment variables for secrets, and short-lived tokens when possible.
- If a secret leaks: **rotate immediately**, don’t just delete history.

## Least privilege

- Tools that can write files or execute commands must be gated.
- Sandbox anything that touches the filesystem outside a safe root.
- Avoid “admin by default.”

## Dependency / supply chain

- Pin versions for reproducibility.
- Prefer minimal dependency surfaces.
- Audit for known vulnerabilities (SCA) on CI.

## Input validation

- Treat user input as hostile for:
  - file paths
  - URLs
  - shell commands
  - JSON payloads
- Normalize and constrain (allowlists > denylists).

## Logging and privacy

- Don’t log secrets.
- Be careful with storing raw transcripts; favor summaries for long-term memory.
- Keep local-first promises: avoid hidden network calls.

---
priority: core
domain: security
aspects: lilith, morrigan
difficulty: beginner
related: devops-cicd-patterns.md, api-design-patterns.md
---

## Security engineering basics (practical checklist)

### Secrets
- Never commit secrets (`.env`, tokens, API keys).
- Prefer **environment variables** or OS secret stores.
- Rotate leaked secrets immediately; assume compromise.

### Dependency / supply chain
- Review dependency additions.
- Pin versions where stability matters.
- Watch for typosquatting and abandoned packages.

### Least privilege
- Give the minimum permissions needed.
- Separate “read” vs “write” credentials.

### Common web/API risks (high level)
- **Injection**: validate/escape inputs; avoid shell concatenation.
- **Auth**: verify sessions/tokens; don’t trust client claims.
- **IDOR**: authorization checks per resource.
- **Rate limits**: prevent abuse and accidental overload.

### Operational safety
- Log safely: never log secrets.
- Use structured logging for auditing.
- Prefer explicit allowlists over deny lists for dangerous actions.

