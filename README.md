# Tranche

Grants released milestone by milestone. Each tranche is paid when its terms are met — checked in code where the question is decidable, judged by a GenLayer validator jury where it is not.

**[Landing page and live registry](https://makabeez.github.io/tranche/)** · GenLayer Studio Next (chain 61997)

> **Status:** contract written, compile-checked against Studio Next (`gen_getContractSchemaForCode` returns the full schema) and exercised end to end in a local simulation. On-chain deployment is pending: Studio Next contract reads have been failing network-wide since 13 Oct 2026. The address and verified transactions will be added here.

## Why

Every grant program is a review queue. A funder pays in milestones so nobody pays for work that never ships — and then each milestone waits for a person to open the repository, decide whether it matches what was promised, and release the next payment. The party holding the money is the party judging the work.

Most of what a milestone promises is checkable: the directory exists, the test file is there, the release lists the right number of entries. A smaller part needs reading. Tranche runs the first in deterministic code and sends only the second to a validator jury.

## How a grant runs

```
open_grant(grant_id, brief, builder, tranches_json)   payable — value must equal the sum of tranches
submit(grant_id, index, evidence_url)                 builder only, current tranche only, pinned to a commit SHA
settle(grant_id, index)                               mechanical terms in code, jury only if needed
finalize(grant_id, index)                             approved → paid, next tranche opens; rejected → back to the builder
appeal(grant_id, index)                               payable — bond equal to the tranche, re-enters settle
cancel(grant_id)                                      funder only, only while the builder is up
get_grant · list_grants · get_registry_name
```

`tranches_json` fixes every tranche up front:

```json
[
  {"amount": "100000000000000000", "terms": ["contains: tranche.py", "contains: README.md"]},
  {"amount": "200000000000000000", "terms": ["array_min: $ >= 5", "contains: tests",
                                             "the README explains how to verify a deployment"]}
]
```

A term with a kind prefix is **mechanical**: `contains:`, `json_equals: path = value`, `json_exists: path`, `array_min: path >= n` (`$` is the document itself, so a top-level array can be counted). Anything else is **judged**.

## Design decisions

**Rejection is a retry, not a refund.** A failed tranche returns to `OPEN` with its rulings recorded and the escrow untouched. The builder submits new evidence; `attempts` counts how many times. A funder who has seen enough uses `cancel`, which is a separate, visible decision.

**The funder cannot interrupt a review.** `cancel` refunds every undelivered tranche, but only while the current one is waiting on the builder (`OPEN` or `INCONCLUSIVE`). While a tranche is submitted, under review, ruled or under appeal, the escrow cannot be pulled out from under the builder.

**Tranches are delivered in order, by the named builder.** The builder's address is fixed at opening. `submit`, `settle`, `finalize` and `appeal` all reject an index other than the current one, so a grant cannot be drained out of sequence.

**Either side can appeal.** The party the ruling went against — the funder against an approval, the builder against a rejection — stakes a bond equal to the tranche. The tranche re-enters `settle` on the same pinned evidence. Overturned, the appellant gets the bond back. Upheld, it goes to the other side. The tranche itself then resolves as the second ruling says.

**One adjudication path.** GenVM will not deploy a contract with non-deterministic blocks in two different methods (found while building BountyCourt's appeals). `settle` is the only method that fetches or prompts; appeals reopen the tranche and re-enter it, which also guarantees the second review runs fresh.

## Evidence guards

Carried over from [BountyCourt](https://github.com/Makabeez/bountycourt-app) and [Exhibit](https://github.com/Makabeez/exhibit), where each was found on chain:

| Guard | Status | Why |
| --- | --- | --- |
| URL must pin a 40-char commit SHA | revert at `submit` | a branch ref can be rewritten after submission |
| body fills the 6,000-char window | `INCONCLUSIVE`, builder may resubmit | validators shown a truncated artifact agree unanimously on false answers |
| body is a rate-limit notice, API error object, 404 page or near-empty | `INADMISSIBLE`, `settle` may be called again | a pinned URL fixes the artifact, not the response; every validator agrees on the error body |
| mechanical term fails | jury skipped | the deliverable is out of spec on a fact |
| jury output malformed | revert, nothing stored | 12 checks: shape, count, id range, duplicates, boolean types, full coverage |

The jury returns only `{"rulings": [{"id": 0, "met": true}]}`. Free text in a compared answer prevents consensus even when every verdict is identical — measured on BountyCourt, four leader rotations and `UNDETERMINED` with identical booleans.

## Local simulation

`tests/simulate.py` mocks the GenLayer runtime and drives the contract through every path: invalid openings, out-of-order and wrong-sender submissions, an unpinned URL, two inadmissible fetches then a mechanical approval with the jury forbidden to run, a jury rejection appealed and upheld, an approval appealed and overturned, an approval appealed and upheld, a mechanical failure that skips the jury, cancellation refused mid-review then allowed, truncation then resubmission, and four malformed jury outputs that must revert without writing state. It checks that every wei escrowed or bonded is paid out, refunded, or still held.

```bash
python3 tests/simulate.py tranche.py
# transfers: 6 | total paid out: 1.1 GEN
# still held by contract (g3): 0.1 GEN
# ALL PATHS OK
```

## Verifying the contract compiles

Studio Next exposes a schema endpoint that loads the contract in GenVM and returns either the schema or the real Python traceback — a free compile check before paying for a deploy:

```bash
python3 -c "import json;print(json.dumps({'jsonrpc':'2.0','id':1,'method':'gen_getContractSchemaForCode','params':['0x'+open('tranche.py','rb').read().hex()]}))" > probe.json
curl -s -X POST https://studio-next.genlayer.com/api -H 'content-type: application/json' --data-binary @probe.json
```

## Files

- `tranche.py` — the Intelligent Contract (GenVM v0.6)
- `index.html` — landing page and registry viewer, every tranche with its terms and per-term rulings
- `tests/simulate.py` — local simulation against a mocked runtime

## License

MIT
