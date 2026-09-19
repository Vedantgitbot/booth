# Security Policy

## Supported Versions

BOOTH is pre-1.0 and moves quickly. Only the latest released version
on [PyPI](https://pypi.org/project/boothpy/) receives fixes. If
you're on an older version, please upgrade before reporting — the
issue may already be resolved.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for a security concern.

Instead, use GitHub's private vulnerability reporting:

**[Report a vulnerability](https://github.com/Vedantgitbot/booth/security/advisories/new)**
(Security tab → "Report a vulnerability")

This keeps the report private between you and the maintainer until
there's a fix, rather than disclosing it to everyone (including
anyone who might misuse it) the moment it's filed.

BOOTH is maintained solo. I'll do my best to acknowledge a report
within a few days and will keep you updated as I work through it —
but please don't expect an enterprise-grade SLA.

## What's In Scope

BOOTH has zero runtime dependencies and makes no network calls
itself, so its realistic attack surface is narrow. Reports that are
genuinely useful here:

- **Prompt-injection risk in BOOTH's own retry-prompt construction.**
  `check()`/`acheck()` interpolate a previous attempt's `answer` and
  `validation_error` directly into the next retry prompt. If you can
  show a concrete way that untrusted model output, once fed back
  through this path, causes something worse than "the model behaves
  oddly on the next attempt" — please report it.
- **Anything that causes a crash, hang, or resource exhaustion from a
  crafted `call_fn` return value, `answer`, or `evidence` input** —
  not just an ordinary `UNCERTAIN`/`TypeError`/`ValueError`, but
  something that escapes BOOTH's normal error handling.
- **Supply-chain concerns** — a compromised or typosquatted release
  on PyPI, a broken/malicious dependency (BOOTH has none today, but
  if that ever changes), or anything in the packaging/release process
  itself.

## What's Out of Scope

- **"The model gave a wrong or misleading answer."** This is BOOTH's
  documented, permanent limitation, not a vulnerability — see
  [USECASES.md §14](../USECASES.md#14-booth-does-not-prove-factual-correctness).
  BOOTH checks structure, ambiguity, validation, and evidence
  agreement; it does not and cannot independently verify truth.
- **Bugs in your own `call_fn`, `validator`, or `compare_fn`.** BOOTH
  isn't responsible for what your own callback does — that's a bug
  report against your code, not BOOTH's.
- **General correctness bugs with no security impact** (a status that
  should have been `REPAIRED` but came back `UNCERTAIN`, say). Please
  use the normal [issue templates](ISSUE_TEMPLATE/) for these — a
  security report isn't the right channel and will just slow down
  something that isn't urgent in the way a security issue is.

## Disclosure

Once a reported issue is fixed, it'll be credited (if you'd like) in
the `CHANGELOG.md` entry for the release that fixes it, and via a
GitHub Security Advisory if the severity warrants one.