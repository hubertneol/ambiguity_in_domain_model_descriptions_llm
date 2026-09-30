# UML Model Generation — Status Report

**Project:** `domain_model_eval` — controlled experiment on LLM-generated UML domain models
**Date:** 2026-09-14
**Stage:** Model generation complete; evaluation partially complete

---

## 1. Summary

All **225 of 225** PlantUML domain models were generated successfully (45 benchmark
cases × 5 text conditions × 1 generation). No description was skipped, no output
file is empty, and every response was returned in the required
`@startuml … @enduml` form.

| Metric | Result |
|---|---|
| Models generated | **225 / 225** (100%) |
| Empty output files | 0 |
| Responses in valid `@startuml`/`@enduml` form | 225 / 225 |
| Failed requests | 2 (both authentication, same observation, later succeeded) |
| Retries needed for transient errors | 0 |
| Total wall-clock time | ~18 minutes |
| Total token usage | 177,147 |

---

## 2. Generation configuration

Identical for all 225 requests; centralised in `config/experiment_config.py`.

| Setting | Value |
|---|---|
| Provider | OpenAI (ChatGPT) |
| API model | `gpt-4o` |
| Temperature | `0.0` |
| Max output tokens | `4096` |
| API surface | Chat Completions |
| Runs per version | 1 |
| Prompt file | `prompts/model_generation_prompt.txt` |
| Prompt SHA-256 (prefix) | `9f418d63eab9` |

The generation log confirms a **single** distinct value for the model,
temperature, token cap and prompt hash across all 227 logged attempts — no
parameter drifted mid-experiment.

---

## 3. Experimental isolation

Each generation was an independent API request. The message list was rebuilt
from scratch per call and contained exactly two items:

1. the verbatim contents of `model_generation_prompt.txt`
2. the single description being processed

This was verified before the run using a stub client that captured every
outgoing payload. The assertions confirmed:

- exactly 2 messages on every request, with no growth across successive calls
- message 1 byte-identical to the fixed prompt every time
- message 2 exactly the current description
- no prior model response present in any later request
- no other case's or version's description present in any request
- no reference-model content present in any request
- request payload keys limited to `model`, `messages`, `temperature`,
  `max_completion_tokens`

No persistent conversation, no accumulated history, and exactly one generation
attempt per observation — no candidate sampling and no revision requests.

---

## 4. Execution

| Phase | Outcome |
|---|---|
| Dry run (no API calls) | 225 tasks enumerated, paths correct |
| Single-request smoke test | Failed — HTTP 401 `token_invalidated` |
| Cause | A previously revoked key was still exported in the running shell |
| Resolution | New shell picked up the rotated key from `~/.zshrc` |
| Re-test | HTTP 200, valid PlantUML returned |
| Full run | 224 remaining models generated without error |

First request `11:14:19Z`, last request `11:31:59Z`.

The two failures were both the 401 on `AirTravel/V0`. They were correctly
classified as non-retryable (no pointless re-sends against a dead credential),
logged, and no file was written. The observation was generated successfully on
the subsequent attempt.

### Security note

During setup an API key was inadvertently printed to the terminal by a
diagnostic command. The key was revoked at the provider, a replacement was
issued, and `~/.zshrc` was updated. No credential is stored anywhere in the
repository — the key is read at runtime from the `OPENAI_API_KEY`
environment variable.

---

## 5. Token usage

| | Total | Mean per request | Range |
|---|---|---|---|
| Prompt tokens | 118,880 | 528 | — |
| Completion tokens | 58,267 | 259 | 99 – 574 |
| **Total** | **177,147** | 787 | — |

No response approached the 4,096-token cap, so no model was truncated.

---

## 6. Output handling

Responses were saved exactly as returned, with only mechanical unwrapping of
Markdown code fences where present. No generated PlantUML was reformatted,
corrected or repaired, and no second API call was made to improve any response.

Every request attempt is recorded in `results/generation_log.csv` with:
timestamp, case, version, run, provider, API model, temperature, token cap,
input and output paths, prompt and description SHA-256 hashes, status, attempt
count, format check, token usage and error text.

---

## 7. Downstream status

Generation is complete. Evaluation is not yet complete, for reasons unrelated
to the generation stage.

| Stage | Status |
|---|---|
| Models generated | 225 / 225 |
| Models parsed by Metrik-4's strict parser | 199 / 225 |
| Pairs scored by Metrik-4 | 194 / 225 |

### Reference-model normalisation

An initial evaluation scored only 94 / 225. The dominant cause was **not** the
generated models: 25 of the 45 benchmark reference models used PlantUML
constructs the Metrik-4 parser rejects (`<<enum>>` stereotypes, reversed
association-class argument order, single-dash composition, bidirectional
arrows).

`scripts/normalize_reference_models.py` rewrites these into the equivalent
documented syntax. It changed 24 files and raised reference parsing from
**20 / 45 to 44 / 45**. The transformation was verified not to alter any model
that already parsed (class counts unchanged), is idempotent, and archives the
originals to `reference_models_original/` with a `--restore` path.

Two items required judgement rather than mechanical rewriting:

- **FilmSet, TransportCompany** — `note "{XOR}" as N1` is an XOR *constraint*,
  not a class. Rewriting it as an association class would have invented a
  spurious class `N1` and inflated those cases' class counts. The constraint is
  unrepresentable by the metric, so it was removed instead. This should be
  stated in the methods section.
- **Cruise** — uses an n-ary association diamond (`<> diamond`) with no
  mechanical equivalent. Left untouched pending a decision; currently costs
  5 unscored pairs.

### Remaining evaluation gaps (31 pairs)

| Cause | Pairs |
|---|---|
| Generated model uses `class X extends Y {` | 24 |
| Generated model uses `actor` or a relationship inside a class body | 2 |
| Cruise n-ary diamond (reference side) | 5 |

`extends` is valid PlantUML but unsupported by this parser. Affected cases:
BuildingManagement, CardGameApp, EUScienceConnect, GameArea, HospitalHouseMD,
House, SmartHomeAutomationSystem, Sober, TileOGame, TransportCompany.

---

## 8. Provisional scores — not yet interpretable

| Version | n | class | attribute | association |
|---|---|---|---|---|
| V0 | 40 | 0.6791 | 0.6492 | 0.7490 |
| V1 | 40 | 0.6695 | 0.6470 | 0.7223 |
| V2 | 39 | 0.6603 | 0.6340 | 0.7216 |
| V3 | 38 | 0.6680 | 0.6373 | 0.7398 |
| V4 | 37 | 0.6656 | 0.6337 | 0.7400 |

**These means must not be compared across conditions yet.** Each column is
computed over a different subset of cases, because the 31 unscored pairs are
distributed unevenly across versions. The observed differences (~0.02) are
small relative to the effect of dropping different cases. A valid comparison
requires either a complete 45 × 5 grid or restriction to cases where all five
versions scored.

### Observation worth following up

**14 variants scored byte-identically to their own V0** (V1: 3, V2: 4, V3: 6,
V4: 1) — the manipulated description produced exactly the same UML model as the
baseline. This is a genuine effect-size signal about how often a controlled text
manipulation fails to propagate into the model, and is worth quantifying
deliberately rather than treating as noise.

---

## 9. Open issues

1. **`extends` syntax** — the generation prompt does not constrain inheritance
   notation. Beyond costing 26 pairs, differing `extends` rates across
   conditions would be a confound in its own right.
2. **Cruise** — needs a ground-truth decision before the case can be scored.
3. **V2 condition** — a separate quality-control review found that 41 of 45 V2
   variants replaced a precise cardinality with a vague quantifier, and that in
   15 cases the multiplicity was changed rather than made ambiguous. This was
   reported and the variants were subsequently revised; the revision has not yet
   been re-verified against the original QC criteria.
4. **Prompt-version consistency.** Fixing issue 1 requires amending the
   generation prompt, which raises the question of whether to regenerate only
   the affected models or all 225. This is not merely a tidiness concern:

   - **The affected cases are not a random sample.** They are exactly the cases
     where the model chose `extends`, which plausibly correlates with having
     deeper inheritance hierarchies. Prompt version would therefore be
     correlated with a structural property of the case rather than randomly
     distributed, making "effect of the text condition" inseparable from
     "effect of the prompt version" in those cases.
   - **The notation constraints may change modelling behaviour, not only
     spelling.** Instructing the model to write `enum Name { ... }` may yield
     more enumerations; naming the composition and aggregation forms may shift
     associations toward them; naming the multiplicity form may make
     cardinalities more consistently explicit. Any of these would move
     `class_score` and `association_score` systematically.

   **This is empirically testable.** Regenerate a small number of cases that
   already parsed under the original prompt and compare the output. If the
   models are semantically equivalent — same classes, attributes and
   relationships, differing only in notation — the change is genuinely
   notation-only and partial regeneration is defensible. If they differ
   structurally, full regeneration is required.

   Note also that `gpt-4o` at temperature 0 is not strictly deterministic, so
   even regenerating under an unchanged prompt would not reproduce byte-identical
   output. This is an argument for generating the whole set in a single pass
   rather than for avoiding regeneration.

   **Recommendation:** regenerate all 225 under the final prompt (~30 minutes,
   ~180k tokens). The cost asymmetry is stark — under a dollar against a
   methodological gap that cannot be repaired after the fact.

---

## 10. Artefacts

| Path | Contents |
|---|---|
| `generated/<case>/<version>/generated_model.puml` | 225 generated models |
| `results/generation_log.csv` | 227 request attempts, full provenance |
| `results/records.jsonl` | 225 evaluation records (194 scored, 31 errored) |
| `reference_models/<case>/reference_model.puml` | Normalised reference models |
| `reference_models_original/<case>/reference_model.puml` | Pre-normalisation originals |
| `prompts/model_generation_prompt.txt` | Generation prompt — **current** version (`5a31d05b3689`) |

The prompt that produced the 225 models described in this report is
`9f418d63eab9`, which is **not** the version currently on disk. See the
addendum below. The per-request hash in `results/generation_log.csv` remains the
authoritative record of which prompt produced which model.

---

## 11. Addendum — changes made after this report

**2026-09-14 — generation prompt amended.** A notation block was appended to
`prompts/model_generation_prompt.txt` to address open issue 1, constraining
syntax only and leaving the modelling instructions unchanged:

- inheritance must be written `Parent <|-- Child`; the keyword `extends` is
  forbidden
- relationships must be declared outside class bodies
- association, composition, aggregation and enumeration forms are specified
- `actor`, `package`, `namespace`, `note`, `skinparam` and stereotypes such as
  `<<enum>>` are forbidden

This changed the prompt hash from `9f418d63eab9` to `5a31d05b3689`.

**All 225 models described in this report predate this change** and were
generated under `9f418d63eab9`. The amended prompt has not yet been used for any
generation, and its effect on output — notational only, or structural — has not
yet been tested. See open issue 4.
