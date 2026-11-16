# Generated numeric checkpoint results

Generated from records.jsonl; authored controls and live Gemma replies are separate.

## Configuration

- Run status: completed
- BOOTH: 0.5.9
- Source commit: `ea28a68f62affd1b6f36001d181ca4730eea47fa`
- Model: `gemma3:12b`
- Model digest: `f4031aab637d1ffa37b42570452ae0e4fad0314754d17ded67322e4b95836f8a`
- Live provider calls: 20; warm-up calls: 1
- Questions: 20; one repetition; retries disabled.

## authored_controls

| Metric | check | validator | keyword evidence | numeric evidence |
|---|---:|---:|---:|---:|
| All answer-checks | 40 | 40 | 40 | 40 |
| Correct answers | 20 | 20 | 20 | 20 |
| Wrong answers | 20 | 20 | 20 | 20 |
| Unscoreable answers | 0 | 0 | 0 | 0 |
| Missing answers | 0 | 0 | 0 | 0 |
| Wrong accepted | 20 | 0 | 20 | 0 |
| Wrong withheld | 0 | 20 | 0 | 20 |
| Correct accepted | 20 | 20 | 17 | 20 |
| Correct withheld | 0 | 0 | 3 | 0 |
| Unscoreable accepted | 0 | 0 | 0 | 0 |
| Unscoreable withheld | 0 | 0 | 0 | 0 |
| Call failures | 0 | 0 | 0 | 0 |
| All-parse-failed | 0 | 0 | 0 | 0 |
| Checker failures | 0 | 0 | 0 | 0 |
| Status ACCEPTED | 40 | 20 | 37 | 20 |
| Status REPAIRED | 0 | 0 | 0 | 0 |
| Status BLOCKED | 0 | 0 | 3 | 20 |
| Status UNCERTAIN | 0 | 20 | 0 | 0 |
| Status AMBIGUOUS | 0 | 0 | 0 | 0 |

All answer-checks remain in the attempted denominator. Wrong-withheld rates use the wrong-answer count; correct-withheld rates use the correct-answer count. Unscoreable/missing answers are separate, never silently removed. 'Withheld' includes every non-ok status; literal BLOCKED is shown separately.

## live_gemma

| Metric | check | validator | keyword evidence | numeric evidence |
|---|---:|---:|---:|---:|
| All answer-checks | 20 | 20 | 20 | 20 |
| Correct answers | 19 | 19 | 19 | 19 |
| Wrong answers | 1 | 1 | 1 | 1 |
| Unscoreable answers | 0 | 0 | 0 | 0 |
| Missing answers | 0 | 0 | 0 | 0 |
| Wrong accepted | 1 | 0 | 1 | 0 |
| Wrong withheld | 0 | 1 | 0 | 1 |
| Correct accepted | 19 | 19 | 19 | 19 |
| Correct withheld | 0 | 0 | 0 | 0 |
| Unscoreable accepted | 0 | 0 | 0 | 0 |
| Unscoreable withheld | 0 | 0 | 0 | 0 |
| Call failures | 0 | 0 | 0 | 0 |
| All-parse-failed | 0 | 0 | 0 | 0 |
| Checker failures | 0 | 0 | 0 | 0 |
| Status ACCEPTED | 20 | 19 | 20 | 19 |
| Status REPAIRED | 0 | 0 | 0 | 0 |
| Status BLOCKED | 0 | 0 | 0 | 1 |
| Status UNCERTAIN | 0 | 1 | 0 | 0 |
| Status AMBIGUOUS | 0 | 0 | 0 | 0 |

All answer-checks remain in the attempted denominator. Wrong-withheld rates use the wrong-answer count; correct-withheld rates use the correct-answer count. Unscoreable/missing answers are separate, never silently removed. 'Withheld' includes every non-ok status; literal BLOCKED is shown separately.

## Limits

One authored synthetic demonstration, one model and one seed. The validator replays the first raw reply; no retry recovery or independent model-arm latency is measured. The numeric rule uses explicit labelled source fields and a bounded quantity grammar, not general financial-language understanding. See PROTOCOL.md.
