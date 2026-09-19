# Contributing to BOOTH

Thanks for considering contributing. Please read this before opening an
issue or a pull request — it'll save you time either way.

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md). By
participating, you're expected to uphold it.

## BOOTH is small on purpose

That's a design constraint, not a lack of ambition. See the Philosophy
section in [README.md](README.md) and [USECASES.md](USECASES.md) for
what BOOTH is trying to be — and just as importantly, what it's
deliberately choosing not to become.

**Bug reports and confirmed edge cases are the most valuable kind of
contribution right now.** Every fix BOOTH has shipped so far started
from a reproduced failure, not a guess — check `CHANGELOG.md` and
you'll see every release named the specific input that broke and the
specific test that now locks it in. That bar stays the same for
outside contributions.

**Feature proposals are welcome as issues for discussion, but a PR that
expands scope without a prior discussion is unlikely to be merged.**
If you're not sure whether something fits, open an issue first and ask
— that's a five-minute conversation that can save you from writing a
PR that doesn't land. Things that are very unlikely to be accepted
without a strong, specific justification: new required dependencies,
a parser/validator plugin architecture, retrieval or RAG functionality
built into BOOTH itself, or anything that makes BOOTH responsible for
things it currently and deliberately leaves to the caller (see
USECASES.md §17–19, §23).

## Reporting a bug

Please use the **Bug Report** issue template, not a blank issue. It
will ask you for a minimal reproduction — this isn't bureaucracy, it's
the single thing that makes a report actionable. A good reproduction
is:

- **Self-contained.** A `call_fn` (or `answer`/`evidence`/`compare_fn`)
  someone can paste and run with no other setup.
- **Minimal.** Strip anything not needed to trigger the bug. If your
  real `call_fn` calls OpenAI, replace it with a `lambda p:
  '{"answer": "...", "confidence": ...}'` that returns the exact
  problem string — BOOTH's bugs live in how it parses and evaluates
  text, not in any particular provider's SDK.
- **Exact, not paraphrased.** If the bug involves a specific string
  shape (malformed JSON, an unexpected type, a particular Unicode
  character), paste it exactly. Paraphrasing it tends to accidentally
  fix the very thing that broke.

If what you're reporting is a *raw LLM output* that BOOTH mishandled —
nested braces, an unexpected type, a model-specific quirk — use the
**Edge Case / LLM Output Quirk** template instead. That's been the
source of nearly every bugfix release so far (v0.4.4 through v0.4.9),
and it's a genuinely distinct category worth its own template.

## Reporting a security issue

Don't open a public issue for this. See [SECURITY.md](.github/SECURITY.md).

## Contributing a fix

1. **Open an issue first if you're not sure it'll be accepted** —
   see "BOOTH is small on purpose" above. Skip this step for a
   straightforward bug fix with a clear reproduction; go straight to a
   PR.
2. **Clone and install in editable mode with dev dependencies:**
   ```bash
   git clone https://github.com/Vedantgitbot/booth.git
   cd booth
   pip install -e ".[dev]"
   ```
3. **Write a failing test first**, in the style of the existing files
   under `tests/`. If you're fixing a bug, this test should fail
   against the current code and pass once your fix is in — that's how
   every fix in this project has been verified, not just assumed
   correct by inspection.
4. **Run the full suite before opening a PR:**
   ```bash
   pytest -v
   ```
   All tests need to pass, including the ones you didn't touch. A fix
   that breaks an existing test needs to explain why the old test's
   assumption was wrong, not just be pushed anyway.
5. **Add a `CHANGELOG.md` entry** if your change affects public
   behavior — follow the format of existing entries (what broke, why,
   what changed, what the new regression test covers). A pure internal
   refactor with no behavior change doesn't need one.
6. **Open the PR.** The PR template has a short checklist — it mirrors
   the steps above, it's not extra work on top of them.

## What a release actually requires

For context on the bar a change needs to clear: every BOOTH release so
far has followed the same shape — a real, reproduced failure; a fix;
a new test that would have caught it; the full existing suite still
green with zero modifications beyond what the fix itself required; and
a changelog entry explaining the reasoning, not just the diff. That's
not a formal policy so much as what's actually happened every time,
and it's the standard a contributed fix is held to as well.

## Questions

If you're not sure whether something is a bug, a design decision, or a
misunderstanding of how BOOTH is meant to be used, check
[TUTORIAL.md](TUTORIAL.md) and [USECASES.md](USECASES.md) first — a
lot of "why doesn't this do X" questions are already answered there,
usually with the reasoning included. If it's still unclear, open an
issue.