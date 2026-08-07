# CLAUDE.md

Working agreement for this repository. Read this before writing any code.

---

## 1. What this project is

A scoring engine for a daily remote-viewing game. A player is shown only a random
identifier and submits written impressions and/or a sketch describing a hidden image
(the **target**). The system ranks the target against every other image in a fixed
**pool** and reports the fraction of decoys it beat.

**The output is a rank, not a similarity.** With no information the target is equally
likely to land anywhere in the sorted list, so chance is exactly 0.5 by construction —
independent of any threshold, calibration, or model quality. Every design decision in
this repo exists to keep that guarantee true.

### Where the documents live

| Document | Role |
|---|---|
| `docs/ARCHITECTURE.md` | The full architecture spec. **Canonical.** Contains the glossary, all layer definitions, formulas, and rationale. |
| `docs/specs/*.md` | Per-stage and per-feature implementation specs. Each is scoped to one build phase or component. |
| `CLAUDE.md` (this file) | How to write code here. Does not restate the architecture. |

**When you need a definition, a formula, or a rationale, read `docs/ARCHITECTURE.md`
rather than inferring it.** Do not guess at numbers (thresholds, dimensions, weights,
tier sizes) — they are specified. If a value is genuinely unspecified, say so and ask;
do not invent a plausible-looking constant and bury it in the code.

**Implement only what the current stage spec asks for.** If a spec is ambiguous or
appears to contradict the architecture, stop and flag it. Do not resolve the
contradiction silently.

---

## 2. The invariants

These are the load-bearing rules. Violating any of them breaks the scoring guarantee,
not just the code. They come from §3 of the architecture; the short forms are here so
they are always in front of you.

**I1 — Channels never see the answer.** A channel is a function of
`(submission, pool)` returning one number for *every* pool image. The target's identity
does not exist in the code path until Layer 8. Do not add a `target_id` parameter to
anything upstream of ranking, not even "for logging."

**I2 — Rank, never similarity.** Nothing downstream may threshold or interpret a raw
score. Any transform that depends only on the submission cannot change the ranking and
is therefore cosmetic; any transform that depends on the *image* is genuinely part of
the method and needs justification.

**I3 — The target must be indistinguishable from the decoys.** Whatever filter is
applied to the target must be applied identically to the decoy set. Near-duplicates of
the target are removed from the decoy set, always. Most "the numbers look wrong" bugs
are violations of this.

**I4 — Raw inputs are permanent, everything else is a cache.** Stroke coordinates and
text are stored forever. Vectors, element lists, line drawings, and scores are caches
keyed by a hash of the configuration that produced them, and must be rebuildable from
raw. If a component cannot be re-run over the entire history, it cannot be replaced.

**I5 — Modality is never a special case.** A submission is a set of atoms. Text-only,
sketch-only, and mixed all produce atom sets and differ only in which channels are
active. **Never write `if submission.has_sketch:` in scoring code.** Missing channels
are handled by the fusion denominator, not by branching.

**I6 — Never fit fusion weights on live player trials using the real target as the
label.** There is no recoverable signal if players have no ability, but there *is* a
noise optimum, and any optimizer will find it. That manufactures apparent ability out
of nothing and looks exactly like success. Fit only on data where correspondence is
known to exist by construction (see §19 of the architecture), freeze the weights, then
score live trials. If you find yourself writing code that touches both live trial data
and weight optimization, stop and raise it.

**I7 — No score feedback before the submission window closes.** No endpoint, no debug
route, no response-size or timing correlation with the target.

---

## 3. Code style

### Functional core, imperative shell

The scoring logic is a pipeline of pure functions over immutable data. All I/O —
storage, network, model loading, caching, request handling — lives at the edges in
`pipeline/` and `providers/`, and is kept as thin as possible.

**In `core/`:**

- Pure functions. Same inputs, same outputs, no hidden state, no ambient config.
- No file reads, no network calls, no logging side effects, no clocks, no RNG unless a
  seed or generator is passed in explicitly.
- Immutable data: frozen dataclasses and `NamedTuple`s. Never mutate an argument.
- No classes as state containers. A class is acceptable only as a frozen record or a
  `Protocol` definition.
- No inheritance for behaviour. Interchangeability comes from `Protocol` types and
  plain function signatures, not from base classes.
- Compose with plain function calls and `functools.partial`. Avoid decorators that
  hide control flow.

```python
# Yes — everything the function needs is in the signature.
def commonness_correct(raw: FloatArray, commonness: FloatArray) -> FloatArray:
    """Remove each image's baseline appeal.  raw and commonness are both length N."""
    return 2.0 * raw - commonness

# No — reaches for global config, mutates in place, hides its dependencies.
class Normalizer:
    def apply(self, scores):
        scores -= CONFIG.commonness_table
        return scores
```

### Readability

- Type hints on every public function. Use named array aliases
  (`PoolScores = NDArray[np.float32]`) so shapes are documented by the type.
- Name identifiers exactly as the glossary in `docs/ARCHITECTURE.md` names them: `pool`,
  `target`, `decoy`, `atom`, `element`, `rarity`, `commonness`, `trial score`,
  `skill number`. Do not introduce synonyms. A reader holding the spec should be able
  to grep.
- Small functions with one job. If a function needs section headers as comments, split
  it.
- Docstrings and comments follow §4, and are linted.
- Prefer boring, explicit code over clever code. No metaprogramming, no dynamic
  attribute access, no string-keyed dispatch where a `match` statement would do.
- Vectorize the array work (numpy/torch) — but never at the cost of being unreadable.
  Annotate every non-obvious array operation with the resulting shape.

### Errors

- Validate at the boundary (Layer 0, provider responses, config loading) and fail loudly
  there. Downstream code may then assume well-formed inputs.
- No silent fallbacks. A missing cache entry, a failed provider call, or an unexpected
  shape raises. Silently returning zeros or an empty vector produces plausible-looking
  scores that are wrong, which is the worst outcome in this system.

---

## 4. Documentation style

Documentation is a deliverable here, not a courtesy. This system's correctness argument
lives in prose — the invariants in §2 are enforced by people reading them, not by the
type checker — so unclear documentation is a correctness risk.

### What to write

- **Docstrings state the contract.** Inputs, outputs, array shapes, units, and any
  invariant relied on. Not a paraphrase of the function name.
- **Module docstrings state the layer** the module implements and point at the section
  of `docs/ARCHITECTURE.md` that defines it. One or two sentences.
- **Use the glossary terms and no synonyms.** `pool`, `target`, `decoy`, `atom`,
  `element`, `rarity`, `commonness`, `trial score`, `skill number`. The same term means
  the same thing in the spec, the docstrings, and the code.
- **Comments explain why.** The formula is in the spec; the comment says why this form
  was chosen or what breaks without it.
- **Don't restate the architecture.** Link to it. Duplicated prose drifts, and when the
  two copies disagree nobody knows which is authoritative.
- Prefer plain declarative sentences, active voice, and present tense. Define an
  abbreviation on first use in each document.

### Vale

**All documentation is checked with [Vale](https://vale.sh).** That covers `README`
files, everything under `docs/`, and **docstrings and comments**, which Vale reads
directly through its tree-sitter grammars — a docstring is documentation and is linted
as such.

- The configuration lives in `.vale.ini` with styles under `.vale/styles/`. Read it before
  writing; don't guess at the active rules.
- Run Vale on any prose you write or change, in the same turn you write it, and fix the
  alerts before handing the work back. Don't leave them for review.
- **Error-level alerts must be clean.** Warnings and suggestions are addressed when the
  fix genuinely improves the sentence and ignored when the rule is misfiring — say which
  you did.
- Report Vale results with numbers (`0 errors, 3 warnings in 4 files`), not "docs are
  clean."

**The code itself does not need to satisfy Vale.** Identifiers, type names, string
literals, and log messages are outside its scope. Don't rename a variable, weaken a
technical term, or reword a docstring into something less precise to silence a rule.

**If the configuration is too restrictive, ask to change it.** This is expected and
normal — the project vocabulary is not going to know `Sinkhorn`, `frontload`,
`decoy`, `commonness`, `OpenRouter`, or `nats` on its own, and the naming rule above
means those words are not negotiable. When a rule fights correct technical writing:

1. Say which rule fired, on which text, and why the flagged wording is the right one.
2. Propose the specific change — usually an addition to the accepted-terms vocabulary,
   occasionally a rule demotion or a scoped exception.
3. Wait for agreement before editing `.vale.ini` or anything under `styles/`. Config
   changes are reviewed like code; silently loosening a rule to make output green
   defeats the point of having the check.

Never add a blanket ignore over a file or directory to avoid fixing prose.

---

## 5. Component interchangeability

**Every component is blind to where its inputs came from and blind to where its outputs
go.** This is the property that makes the layer stack replaceable, and it is not
negotiable — it is what lets any channel, any encoder, and any judge drop into the same
slot and produce trial scores on the same scale automatically.

Concretely:

- A component's signature contains only the data it operates on. No pipeline objects,
  no request contexts, no "the caller will be Layer 6" assumptions.
- A component never imports another component. Shared types live in `core/types.py`;
  everything else is passed as an argument.
- A component never reads global config. Configuration arrives as a frozen parameter
  object in the call.
- A component does not log to a destination it chose, cache to a path it chose, or
  decide its own device placement. Those are shell concerns.

### The fixed contracts

Hold these signature shapes stable; the stage specs fill in the details.

```python
Channel  = Callable[[Submission, PoolIndex, ChannelConfig], PoolScores]  # length N, no target
Encoder  = Callable[[Sequence[Payload]], Vectors]                       # batched, unit-norm
Normalize = Callable[[PoolScores, PoolScores], PoolScores]              # raw, commonness -> corrected
Fuse     = Callable[[Mapping[ChannelName, PoolScores], Weights], PoolScores]
Rank     = Callable[[PoolScores, TargetId, DecoySet], TrialScore]       # the only place target enters
```

If you are tempted to widen one of these signatures, that is a signal the logic belongs
in a different layer.

### Stability tiers

| Layer | Change frequency | Consequence of changing |
|---|---|---|
| L0 intake, L1 atom assembly | **Never** | Invalidates every stored submission |
| L2 encoders, L3 style bridge, L4 channels, L7 rerank | Freely | Isolated by the "one number per pool image" contract |
| L5 normalization, L6 fusion | Rarely | Formula is fixed; only weights change |
| L8 ranking, L9 aggregation | **Never** | Invalidates published scores |

Treat the atom type list (`DESCRIPTION`, `RELATION`, `WHOLE-DRAWING`) and the element
schema as frozen. Changing either invalidates every stored atom and every rarity weight.
If a stage spec seems to require a fourth atom type, flag it rather than adding one.

---

## 6. Model provider agnosticism

**Nothing outside `providers/` may know whether a model runs locally or through
OpenRouter.** Channels, pool preparation jobs, and validation harnesses call protocols;
the concrete implementation is chosen by configuration at wiring time.

```
providers/
  protocols.py        # TextEncoder, ImageEncoder, LineDrawer, VlmDescriber, VlmJudge
  local/              # transformers / torch on the 5090
  openrouter/         # HTTP client
  fake/               # deterministic stubs for tests and offline dev
  caching.py          # provider-agnostic wrapper, keyed by config hash
```

Rules:

- **Protocols are defined by capability, not by vendor.** `VlmDescriber` returns an
  element list conforming to the schema. Whether that came from a 7B model on the GPU
  or an API call is invisible to the caller.
- **Batching is part of the contract.** Every encoder protocol takes a sequence and
  returns a stacked array. Providers handle their own chunking, concurrency, and
  retries internally; callers never loop.
- **Every provider exposes a stable `config_hash`** covering model identifier, weights
  revision, and preprocessing settings. This is what cache keys and stored artifacts are
  keyed by (I4). Two providers that produce different numbers must produce different
  hashes.
- **Caching wraps the protocol, not the implementation.** The cache layer is written
  once and works for every provider.
- **Provider-specific concerns stay inside the provider:** rate limits, backoff, API
  keys, prompt formatting, device placement, dtype, `torch.compile`. None of that leaks
  into a channel.
- **Output normalization happens at the provider boundary.** Vectors leave a provider
  already unit-normalized and in a documented dtype and dimension, so downstream code
  never asks "which encoder was this?"
- **Non-determinism is contained.** Sampling temperature, ordering randomization for the
  VLM judge, and retry behaviour are provider config, and the seed or permutation set is
  logged with the result.

For the same reason, keep the sketch encoder and image encoder as **separate protocol
slots even when they are literally the same weights**. Their swap costs differ by hours
of pool recomputation, and the config hash must track them independently.

---

## 7. Development build first

The current target is a working development build, not production. That changes
priorities, not standards.

**Do:**

- Work against a small dev pool (a few hundred to a few thousand images) with its own
  pool version identifier. Every quantity — rarity, commonness, decoy count — is defined
  against the pool, so dev results are dev-only and must never be published.
- Use `providers/fake/` for tests: deterministic hash-derived embeddings, a stub line
  drawer, a scripted judge. The full test suite must run with no GPU and no network.
- Make everything runnable end to end early, even if slow. A correct 3-second path beats
  a fast path with no validation behind it.
- Keep the tiered structure of the element channel as an *interface* from the start
  (tier 1 approximate → tier 2 exact → tier 3 deferred), even if the dev build runs the
  exact computation over everything. That way Phase 5 is an optimization, not a rewrite.
- Write the validation harnesses (V1–V6) alongside the code they validate, not after.

**Don't:**

- Don't optimize the fast path before the correctness gates pass. The 50 ms budget is a
  Phase 5 concern; §18 of the architecture explains why the daily trial does not need it
  at all.
- Don't build the public leaderboard, or anything that looks like one, before V2 (even
  baseline) and V3 (monotone response to quality) both pass.
- Don't spend GPU hours on full-pool preparation while the element schema is still
  moving. Schema changes force re-extraction.
- Don't skip the integrity work just because it is a dev build — identifier hygiene,
  window-close gating, and pool-derived autocomplete are structural, and retrofitting
  them means re-running trials.

---

## 8. Repository layout

```
docs/
  ARCHITECTURE.md          # canonical spec
  specs/                   # per-stage and per-feature specs
core/                      # pure functions only, no I/O
  types.py                 # shared frozen types, array aliases
  intake.py                # L0
  atoms.py                 # L1
  channels/                # L4: element.py, outline.py, placement.py
  normalize.py             # L5
  fusion.py                # L6
  ranking.py               # L8  — the only module that knows the target
  aggregate.py             # L9
providers/                 # model access, see §6
pipeline/                  # imperative shell: wiring, caching, storage, jobs
pool/                      # offline preparation (curation, extraction, encoding)
validation/                # V1–V6 harnesses and the synthetic submission generator
tests/
.vale.ini                  # prose linting config, see §4
styles/                    # Vale styles and the project vocabulary
```

`core/` must not import from `pipeline/` or `providers/` implementations — only from
`providers/protocols.py` for type annotations. If that import direction ever reverses,
the interchangeability property is gone.

---

## 9. Testing

- **Unit tests** cover `core/` with fake providers. These are the bulk of the suite:
  pure functions with fixed inputs and asserted outputs.
- **Invariant tests** are non-optional and gate merges:
  - No module upstream of `core/ranking.py` references a target identifier.
  - Channel outputs always have length `N`.
  - The fusion denominator renormalizes correctly for every subset of active channels.
  - Trial scores from no-information submissions are uniform on [0, 1] (V2).
  - Rescoring stored raw submissions under a pinned config reproduces stored trial
    scores byte-for-byte.
- **Validation harnesses** (V1–V6) are the real quality gates and live in `validation/`.
  They are run deliberately, reported with numbers, and their results recorded — not run
  in CI.
- Property-based tests are a good fit for the normalization and fusion algebra
  (standardizing must not change ranking; adding a constant to all images must not
  change ranking).

---

## 10. Red flags — stop and ask

If you find yourself doing any of these, raise it instead of proceeding:

- Passing the target identifier into anything before Layer 8.
- Branching on submission modality in scoring code.
- Adding a fourth atom type or changing the element schema.
- Fitting anything on live player trials.
- Adding a threshold, a cutoff score, or a "good match" boolean.
- Filtering the target and the decoys through different paths.
- Writing a text parser in Layer 1 (the interface is the atom assembler).
- Caching a derived artifact without a configuration hash in its key.
- Returning a default value when a model call or cache lookup fails.
- Making a channel aware of another channel's output.
- Hardcoding a number that the spec does not contain.
- Editing `.vale.ini` or `styles/` without agreement, or ignoring a file to silence it.

---

## 11. Communication

- When a stage spec and the architecture disagree, say so explicitly and quote both.
- When an approach requires violating an invariant in §2, do not find a workaround —
  report the conflict.
- Report validation results as numbers, not as "it works." A style bridge that ranks the
  correct photo first 4% of the time is a failed V1, and the fallback (text-only scoring
  with player-labeled stroke groups) is already designed for.
- Prefer asking one focused question over building on an assumption.
