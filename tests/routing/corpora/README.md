# Routing evaluation corpora

Evaluation data for the router. JSONL, one object per line:

```json
{"text": "...", "expect": "web" | "local" | "ambiguous", "slice": "live_status", "why": "..."}
```

`expect` is the label. `slice` groups rows by the kind of need, so results can be reported per slice rather
than as one aggregate that hides a broken class. `why` is the one-clause justification — it exists so a
reviewer can disagree with a *label* rather than with a score.

`ambiguous` rows are excluded from scoring and counted in the report. They are the rows two reasonable people
would argue about, and pretending to be right about them would only inflate the numbers.

## Files

| File | Rows | Provenance |
|---|---|---|
| `sealed-a.jsonl` | 150 | Written 2026-10-30 by an author instructed to write as a small game-server and neighbourhood/city community. Forbidden from reading `src/routing/`, `src/smart_orchestrator.py`, `docs/routing/`, or any other corpus. 10 rows per slice, 72 web / 73 local / 5 ambiguous. |
| `sealed-b.jsonl` | 150 | Written the same day by a second author, from a developer-heavy and a music-production server, deliberately weighted toward surface-wording traps (a product name in a sentence that is not about the product; *down* / *live* / *worth* / *latest* used in a non-live sense; a personal anecdote with a date and a place). Same blindness rules. 42 web / 102 local / 6 ambiguous — the skew is the trap weighting, not a labelling accident. |

Each author saw neither the implementation, the design, nor the other's set. That is the only thing that makes
these evidence rather than a mirror of the code.

## Rules

- **Never edit a label to make a test pass.** If a label is wrong, that is a new corpus file and a note in the
  pull request saying which rows moved and why.
- **Never add a phrase to the lexicon because it appears here.** That converts this set into training data
  and the numbers stop meaning anything. Adding a *class* of evidence is legitimate; adding the sentence that
  failed is not.
- **Once a set has been read to fix failures it is development data.** It stays for regression, but no
  published claim may rest on it. The next claim needs a fresh set.
- Do not quote an aggregate without its per-slice table and the incumbent's score on the same rows.

## Scoring

```bash
python scripts/router_eval.py --corpus tests/routing/corpora/sealed-a.jsonl
python scripts/router_eval.py --corpus tests/routing/corpora/sealed-b.jsonl --baseline old
```

The evaluator reports recall first (a missed live question is a confidently stale reply, a needless search is
a slightly worse one), with a 95% Wilson interval, and per slice with `n`.

## A note on the numbers in the docs

An earlier pair of corpora (600 and 400 rows) was written in the same way but kept only in a temporary
directory, and was lost when the machine rebooted before they could be committed. Any figure in the design
record or changelog measured against them is marked as superseded. These files exist so that cannot happen
again: an evaluation set that is not in version control is not an evaluation set.
