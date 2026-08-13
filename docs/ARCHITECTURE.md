# Remote Viewing Scoring Engine — Architecture Specification

**Version 2.** Rewritten to incorporate: a curated pool drawn from Wikipedia-Image-Text, no access to human judges, a single RTX 5090 plus OpenRouter API access, no model training, submission structure defined by the user interface rather than by parsing, and a hard real-time latency requirement.

---

## Table of contents

1. [What this system does](#1-what-this-system-does)
2. [Glossary](#2-glossary)
3. [The five design rules](#3-the-five-design-rules)
4. [The pool](#4-the-pool)
5. [Pool preparation](#5-pool-preparation)
6. [The submission](#6-the-submission)
7. [Layer stack overview](#7-layer-stack-overview)
8. [Layer 0 — Intake](#8-layer-0--intake)
9. [Layer 1 — Atom assembly](#9-layer-1--atom-assembly)
10. [Layer 2 — Encoders](#10-layer-2--encoders)
11. [Layer 3 — The style bridge](#11-layer-3--the-style-bridge)
12. [Layer 4 — Channels](#12-layer-4--channels)
13. [Layer 5 — Normalization](#13-layer-5--normalization)
14. [Layer 6 — Fusion](#14-layer-6--fusion)
15. [Layer 7 — Deferred rerank](#15-layer-7--deferred-rerank)
16. [Layer 8 — Ranking](#16-layer-8--ranking)
17. [Layer 9 — Aggregation](#17-layer-9--aggregation)
18. [Latency architecture](#18-latency-architecture)
19. [Fitting without human judges](#19-fitting-without-human-judges)
20. [Frontloading](#20-frontloading)
21. [Versioning](#21-versioning)
22. [Protocol integrity](#22-protocol-integrity)
23. [Validation](#23-validation)
24. [Hardware plan](#24-hardware-plan)
25. [Build order](#25-build-order)
26. [Failure index](#26-failure-index)
27. [Worked example](#27-worked-example)

---

## 1. What this system does

Each day the application picks one image at random from a fixed collection and hides it. A player is given only a random identifier and attempts to describe or draw what the image shows. They submit some mixture of written impressions and sketches. The system must convert that submission into a number that measures how well it corresponds to the hidden image — and it must do so in a way where "no ability at all" produces a known, fixed baseline score.

The core design decision is that **the number is a rank, not a similarity.** The system compares the submission against every image in the collection, sorts them, and reports where the true image landed. If the player has no information about the target, the true image is just as likely to land anywhere in that sorted list, so the average score is exactly the midpoint. That baseline holds by construction — it does not depend on any calibration, threshold, or property of the models involved.

Everything else in this document exists to make that ranking meaningful, fast, and honest.

---

## 2. Glossary

Every specialized term used in this document, defined once. Terms are used consistently throughout; no synonyms are introduced later.

### Data objects

**Pool** — The fixed, curated set of images the system uses. Written `P`. Its size is written `N`. Every ranking is against the pool. Around 20,000 images.

**Target** — The single hidden image chosen for a given day's trial. Written `t`. Always a member of the pool.

**Decoy** — Every pool image that is not the target on a given trial. The player is ranked against these.

**Trial** — One player's attempt at one day's target.

**Submission** — Everything a player sends for one trial. Written `q`.

**Atom** — One unit of a submission. Either a written impression ("tall metallic structure"), a group of sketch strokes, or a stated relationship between two other atoms. A submission is a set of atoms.

**Element** — One named thing or property present in a pool image. A short text string: `"lighthouse"`, `"stone"`, `"white"`, `"windy"`.

**Element list** — All elements extracted from one pool image. Around 20 strings. Written `[b₁ … b_k]`.

**Vocabulary** — The set of all distinct element strings appearing anywhere in the pool. Around 15,000 strings. Written `V`.

**Background set** — A collection of a few thousand submissions used to measure how images behave against a *typical* submission. Written `Q_bg`.

**Synthetic submission** — A submission manufactured from a pool image by a program rather than produced by a player. Used for fitting and testing, never scored on the leaderboard.

### Quantities

**Rarity weight** — How informative an atom is, measured against the pool. An atom matching 60% of pool images is nearly worthless; one matching a single image is extremely informative. Written `rarity(a)`. Measured in nats (a unit of information; one nat corresponds to a factor of about 2.7 in probability).

**Similarity table** — A grid of numbers, one per (atom, element) pair, saying how well each atom matches each element of a given image. Written `C`.

**Match table** — The result of deciding which atoms correspond to which elements, allowing partial credit. Written `Π`. Each entry is between 0 and 1.

**Channel** — One method of scoring a submission against an image. This system has three. Each channel independently produces one number for every image in the pool.

**Channel score vector** — What a channel outputs: one number per pool image, so a list of length `N`.

**Commonness score** — How well a given pool image scores against a typical submission, for a given channel. High commonness means the image is a "crowd-pleaser" that scores decently against everything. Written `common_c(x)`.

**Fused score** — The single combined number per pool image, after all channels are merged. Written `s(q, x)`.

**Decoy count** — The number of images the target was actually ranked against, after removing near-duplicates and applying any frontload filter. Written `D`.

**Trial score** — The final per-trial output: the fraction of decoys the target beat. Between 0 and 1. Chance is 0.5. Written `p`.

**Skill number** — A single number summarizing a player's ability across all their trials. 1.0 means chance; above 1.0 suggests better than chance. Written `θ`.

### Operations

**Standardizing** — Rescaling a list of numbers so their average becomes 0 and their spread becomes 1. Used to put different channels on a common scale so they can be combined.

**Commonness correction** — Subtracting each image's commonness score from its raw channel score, so images stop earning points merely for being generic.

**Soft matching** — Deciding which atoms correspond to which elements while allowing partial and split credit, rather than forcing a hard one-to-one pairing. Implemented by a standard iterative algorithm (Sinkhorn's algorithm), described in §12.

**Style bridge** — The step that converts a pool photograph into a line drawing, so it can be compared against a player's sketch without the comparison being dominated by the fact that one is a photo and one is a drawing.

**Frontloading** — Telling the player something about the target before they attempt it, such as "the target is a man-made structure."

### Models used

**Text encoder** — A pretrained model that converts a short text string into a list of numbers (a "vector") such that similar meanings produce similar vectors.

**Image encoder** — The same idea for images.

**Vision-language model** — A pretrained model that looks at an image and produces text about it. Abbreviated VLM throughout.

**Line-drawing model** — A pretrained model that converts a photograph into a clean line drawing.

---

## 3. The five design rules

Every decision in this document follows from one of these.

### Rule 1 — Channels never see the answer

> A channel is a function of (submission, pool). It produces one score for **every** pool image. It is never told which image is the target.

If a channel could return "similarity to the target," you could never swap it without redoing the whole score scale, and you could never detect if it had a built-in bias. Producing a score for every image means the baseline is computed from the channel's own output, so any channel — a fast model, a slow model, a hand-written rule, an external judge — drops into the same slot and produces trial scores on the same scale automatically.

The identity of the target enters the system for the first time at Layer 8.

### Rule 2 — Rank, never similarity

Raw similarity numbers are meaningless. A similarity of 0.71 tells a player nothing, and any fixed threshold can be gamed by matching what's common in the pool rather than what's in the target. The output is where the target landed in a sorted list.

**Useful consequence:** any *additive* adjustment that depends only on the submission cannot change the sorted order, and is therefore free. The qualifier is load-bearing: a submission-only *multiplicative* factor applied before the commonness correction rescales `raw` against the image-dependent baseline in `2 × raw − common(x)`, and does change the order — the Phase 4 review measured this defect in the placement channel's first form. Standardizing comes after the correction and stays free. Anything that depends on the *image* — commonness correction, for instance — does change the order and is genuinely part of the scoring method.

### Rule 3 — The target must be indistinguishable from the decoys

The whole baseline argument rests on this: before the player's input is considered, the target must be exactly as likely to be any pool image as any decoy is. Every threat to the baseline is a violation of this rule:

- Choosing targets for being "visually interesting" but not filtering decoys the same way.
- Applying a frontload filter to the target but not to the decoys.
- Leaving near-duplicates of the target among the decoys.
- Scoring different players against differently-filtered decoy sets.

When the numbers look wrong, audit this first.

### Rule 4 — Raw inputs are permanent, everything else is a cache

Store stroke coordinates and text forever. Every derived thing — vectors, element lists, line drawings, scores — is a cache keyed by a hash of the configuration that produced it, and must be rebuildable from raw. Any component you cannot re-run over your entire history is a component you cannot replace.

### Rule 5 — Modality is never a special case

A submission is a set of atoms. Text-only, sketch-only, and mixed submissions all produce atom sets; they differ only in which atom types are present and therefore which channels fire. The scoring code never branches on modality. Comparability survives because under Rule 2 the baseline is 0.5 no matter which channels ran.

---

## 4. The pool

### Three things that could be called "the pool"

| Name | What it is | Size |
|---|---|---|
| Source corpus | Wikipedia-Image-Text, as downloaded | ~11 million |
| **Pool** | The curated, fixed, versioned working set. **This is what "pool" means everywhere in this document.** | ~20,000 |
| Decoy set | The pool minus the target's near-duplicates, optionally filtered by frontload | ≈ 20,000 |

**The daily target is drawn uniformly from the pool, never from the source corpus.** Images outside the pool do not exist as far as the system is concerned.

### Why the pool must be bounded at ~20,000

**Preparation cost.** Each image needs a VLM pass, a line-drawing pass, and encoding. At 20,000 that is one overnight job on your hardware. At 11 million it is months of compute, repeated every time you change an encoder.

**Scoring cost.** The outline channel scales freely — it is one matrix multiplication regardless of pool size. The element channel does not: it requires a matching computation per image. §18 describes a three-tier structure that makes 20,000 comfortable and around 100,000 the practical ceiling. **The element channel is what bounds pool size.**

**Rule 3.** Drawing the target uniformly from the pool and ranking against that same pool satisfies indistinguishability by construction. Drawing from a larger corpus and ranking against a smaller one breaks it.

**Rarity weights are defined against the pool.** An atom's informativeness is relative to what the player is choosing among. That is the correct definition, and it requires a fixed, known pool.

**Image quality.** Wikipedia-Image-Text is overwhelmingly not viewable material: coats of arms, charts, maps, logos, screenshots, scanned documents, thumbnails, and hundreds of near-identical photos of the same subject. Remote viewing protocols have always used curated sets of visually distinct, salient photographs, and the reason is discriminability. If half the pool is indistinguishable municipal buildings, ranking measures nothing but noise.

### Curation filter: source corpus → pool

Run in this order, cheapest filters first:

```
1.  Resolution: short side ≥ 512 px
2.  Aspect ratio between 0.5 and 2.0
3.  Text detection: reject if text covers > 5% of image area
    (removes scans, screenshots, diagrams with labels)
4.  Image encoder zero-shot classification:
    keep "photograph", reject "diagram", "chart", "logo",
    "map", "screenshot", "coat of arms", "line drawing"
5.  Object detection: largest detected object must cover > 15% of area
    (favours a single clear subject over cluttered scenes)
6.  Near-duplicate removal at 0.95 cosine similarity
7.  Diversity cap: cluster all remaining images by encoder vector,
    keep at most ~15 per cluster
8.  Human spot-check on a random sample of 200
```

**Step 7 is the one that gets skipped and shouldn't.** Wikipedia-Image-Text is heavily skewed toward buildings, plants, and portraits. Without a cap you end up with a pool that is 30% church exteriors, and your rarity weights become wrong in a way that is very hard to notice from the inside.

### On the captions that ship with Wikipedia-Image-Text

The dataset includes captions, but they are *contextual* rather than *visual*: "Figure 3", "The subject in 1923", "Location within Bavaria". They describe the article's use of the image, not the image's content.

**Use them as a curation signal** — a caption that is pure boilerplate flags a low-value image — **but not as the element list.** You still need the VLM pass described in §5.

### The pool is versioned

Adding images changes the rarity weights and changes the decoy count, which shifts every historical trial score. Treat the pool version exactly like a model version: hash it, store it with every trial, rescore history when it changes. Growing the pool is a deliberate release event, not a background job.

---

## 5. Pool preparation

Runs once per image per configuration hash. Fully offline. The interactive path never touches an image file.

### What gets produced and cached

| Artifact | How it is made | Used by |
|---|---|---|
| Element list | VLM, fixed output schema | element channel, rarity weights |
| Element vectors | text encoder over the element list | element channel |
| Element boxes (optional) | open-vocabulary object detector | placement channel |
| Line drawing | line-drawing model | outline channel |
| Outline vectors | image encoder over the line drawing, whole plus crops | outline channel |
| Tag vector | VLM or classifier | frontload filtering |
| Near-duplicate group | clustering on encoder vectors | Layer 8 |
| Commonness scores | background set, see §13 | Layer 5 |

### The element list schema

The VLM emits a fixed structure per image, not free text:

```json
{
  "objects":   ["lighthouse", "breakwater", "gull"],
  "materials": ["stone", "painted metal", "seawater"],
  "colors":    ["white", "slate grey", "deep blue"],
  "shapes":    ["tall cylinder", "horizontal band"],
  "scale":     "large",
  "setting":   "outdoor coastal",
  "ambience":  ["exposed", "windy", "isolated"]
}
```

Flattened, this becomes the element list: `["lighthouse", "breakwater", "gull", "stone", ..., "isolated"]`, around 16 entries.

**Why a fixed schema rather than free captions.** Free captions vary in length and word choice between images, and that variation leaks into rarity weights and match counts in a way that correlates with image type. That is a bias, not noise.

**Cap the element list at 20 entries and keep the length roughly constant.** This matters more than it looks. If one image yields 60 elements and another yields 5, the 60-element image is easier to match by accident, because each player atom has more chances to find something. That is a commonness problem manufactured by your own preprocessing. If the VLM produces more than 20, keep the 20 with the highest rarity weights.

### Building the vocabulary and the incidence matrix

After all element lists are extracted:

1. Collect every distinct element string into the **vocabulary** `V` (expect 10,000–20,000 entries after light normalization: lowercase, strip articles, singularize).
2. Encode every vocabulary entry once with the text encoder. This gives a matrix `E_V` of shape `|V| × d`.
3. Build an **incidence table**: for each pool image, the list of vocabulary indices its elements occupy. Store as a dense padded array of shape `N × 20`.

These two structures are what make the element channel fast enough to run in real time. They are described in §18.

### Near-duplicate grouping

Cluster all pool images by outline vector at a tight threshold (start at 0.95 cosine similarity and inspect). Store a group identifier per image.

This is required by Rule 3. If the pool contains three nearly identical lighthouse photos and one is the target, a perfect lighthouse sketch ranks fourth — and which of the three wins is decided by encoder noise rather than by the player. The trial score becomes noise exactly in the cases where the player did best. Layer 8 removes the target's whole group from the decoy set.

---

## 6. The submission

**The user interface is the atom assembler.** Layer 1 does not parse anything.

### Form design

| Interface element | Produces |
|---|---|
| "Impressions" — a repeating single-line field, Enter commits a row | one `DESCRIPTION` atom per row, text only |
| Drawing canvas, taken as a whole | one `WHOLE-DRAWING` atom, strokes only |
| Group tool — player lassos a set of strokes | one `DESCRIPTION` atom per group, strokes only |
| Optional label field attached to a group | adds text to that group's atom |
| Relationship builder — pick two groups, pick a relation | one `RELATION` atom |

A submission of four written impressions, a sketch with two labeled groups, and one stated relationship yields eight atoms:

```
a1  DESCRIPTION    text: "tall vertical structure"
a2  DESCRIPTION    text: "cold and exposed"
a3  DESCRIPTION    text: "metallic"
a4  DESCRIPTION    text: "water nearby"
a5  DESCRIPTION    text: "tower",  strokes: [...]
a6  DESCRIPTION    text: "waves",  strokes: [...]
a7  WHOLE-DRAWING  strokes: [...all strokes...]
a8  RELATION       relation: "left-of",  refers to: [a5, a6]
```

### Why the interface does this instead of a parser

Layer 1 is permanent infrastructure — you can never change it without invalidating every stored atom. If Layer 1 contained a text parser, then the parser's version would determine where atom boundaries fall, atom boundaries determine rarity weights, and rarity weights determine everything downstream. You would be unable to rescore history faithfully, because the parse itself would have changed.

Pushing segmentation into the interface means **the player fixed the boundaries at submission time, permanently.** No model version can move them.

If you must accept a pasted free-text block (someone transcribing paper notes), split it deterministically on newlines and commas, one atom per fragment. No model. A fixed rule is acceptable here precisely because it is not a versioned artifact.

### Atom structure

```
Atom := {
  id:       stable identifier
  type:     DESCRIPTION | RELATION | WHOLE-DRAWING
  subtype:  optional free string — recorded, never acted on
  payload:  { text?, strokes? }
}
```

**`id`** — bookkeeping only. It indexes rows of the match table, so after scoring you can report "atom 3 matched the lighthouse at 0.71." It is the join key between scoring output and player feedback. Never encoded, never scored. Must remain stable across rescoring.

**`type`** — three values, because routing is a three-way decision:

| type | goes to | channel |
|---|---|---|
| `DESCRIPTION` | text encoder, or image encoder if strokes only | element |
| `WHOLE-DRAWING` | image encoder | outline |
| `RELATION` | read directly, never encoded | placement |

`type` also determines which channels are active for this submission, which drives the fusion step in Layer 6. That is the entire mechanism by which arbitrary mixtures of words and sketches work without any branching.

Within the element channel, `type` additionally masks impossible pairings: a `RELATION` can never be scored as though it were an object.

**Why only three types.** An earlier design had nine (`OBJECT`, `MATERIAL`, `COLOR`, `SHAPE`, `SCALE`, `AMBIENCE`, and so on). They all routed identically and were all weighted identically, so the distinction did no work. The apparent argument for keeping them — that atmosphere words are weak evidence and object names are strong — is **already handled by rarity weights.** If "peaceful" appears in 40% of pool element lists, its rarity weight is automatically low. Type-specific weights would only add value if two atoms with *equal* rarity had *unequal* reliability, which is a question you cannot answer before you have data.

A three-value list is also safe to freeze forever. A nine-value one you would be guessing at is not.

**`subtype`** — recorded, displayed, never acted on in scoring. Carried because adding a field later is cheap but populating it retroactively is impossible. If you later discover that colour atoms are less reliable than object atoms at equal rarity, you will have the historical data to prove it.

**`payload`** — the only field that becomes a number.

- `text` → text encoder → vector. Used for the atom's rarity weight and its row of the similarity table.
- `strokes` → rendered on the server → image encoder. Feeds the outline channel if the atom is `WHOLE-DRAWING`. Also yields a centre point and bounding box, stored separately from the vector, which is what lets a `RELATION` resolve.
- Both present (a labeled sketch group) is the richest case. Combine at the *similarity table* level, not by averaging vectors:

```
C[i][j] = α · similarity(text_vector(aᵢ), element_vector(bⱼ))
        + (1−α) · similarity(sketch_vector(aᵢ), element_vector(bⱼ))
```

Averaging vectors from two different encoders is not meaningful unless they were trained to share an output space. Averaging similarities is always safe, and `α` is one number you can tune. **Start at `α = 1.0` — text only — and raise it only if the sketch path measurably helps** on the tests in §23.

---

## 7. Layer stack overview

```
        OFFLINE (§5)                        INTERACTIVE (per submission)
        ════════════                        ═══════════════════════════

  ┌────────────────────────┐          ┌────────────────────────────────┐
  │ Pool preparation       │          │ L0  Intake                     │
  │  element lists         │          │     validate, render strokes   │
  │  element vectors       │          └───────────────┬────────────────┘
  │  line drawings         │                          ▼
  │  outline vectors       │          ┌────────────────────────────────┐
  │  vocabulary            │          │ L1  Atom assembly              │
  │  incidence table       │          │     read interface fields      │
  │  duplicate groups      │          └───────────────┬────────────────┘
  │  tag vectors           │                          ▼
  └───────────┬────────────┘          ┌────────────────────────────────┐
              │                       │ L2  Encoders      [replaceable]│
              │                       │ L3  Style bridge  [replaceable]│
              │                       └───────────────┬────────────────┘
              │  cached vectors                       ▼
              └──────────────────────► ┌────────────────────────────────┐
                                       │ L4  Channels      [replaceable]│
  ┌────────────────────────┐           │     element / outline /        │
  │ Commonness scores      │           │     placement                  │
  │  from background set   │           │     each → one number per      │
  └───────────┬────────────┘           │     pool image                 │
              │                        └───────────────┬────────────────┘
              └──────────────────────► ┌────────────────────────────────┐
                                       │ L5  Normalization              │
                                       │     commonness correction,     │
                                       │     then standardize           │
                                       └───────────────┬────────────────┘
                                                       ▼
                                       ┌────────────────────────────────┐
                                       │ L6  Fusion                     │
                                       │     weighted average over      │
                                       │     active channels            │
                                       └───────────────┬────────────────┘
                                                       ▼
                                       ┌────────────────────────────────┐
                                       │ L8  Ranking                    │
                                       │     where did the target land? │
                                       │     → trial score p            │
                                       └───────────────┬────────────────┘
                                                       ▼
                                       ┌────────────────────────────────┐
                                       │ L9  Aggregation                │
                                       │     → skill number, evidence   │
                                       └────────────────────────────────┘

        DEFERRED (runs after submission closes, not in the interactive path)
        ═══════════════════════════════════════════════════════════════════
                                       ┌────────────────────────────────┐
                                       │ L7  Rerank  [optional]         │
                                       │     VLM judge over top 25      │
                                       │     → revised ranking → L8     │
                                       └────────────────────────────────┘
```

**Note the position of Layer 7.** It is numbered between 6 and 8 because that is where it acts on the ranking, but it does not run in the interactive path. See §15 and §18.

### Stability tiers

| Layers | Change frequency | Why |
|---|---|---|
| L0, L1 | Never | Changing them invalidates stored submissions |
| L2, L3, L4, L7 | Freely | Isolated by the "one number per pool image" interface |
| L5, L6 | Rarely | Formula is fixed; only the weights change |
| L8, L9 | Never | Changing them invalidates published scores |

---

## 8. Layer 0 — Intake

Converts whatever the client sent into a canonical, validated form. Deterministic, no model involved, never changes.

### Strokes are accepted as coordinates, not as images

```
Stroke := { points: [(x, y, time?, pressure?)], group_id?, color? }
```

The server renders them at a fixed resolution, fixed line width, fixed background colour, and fixed anti-aliasing setting. `color` is an optional lowercase `#rrggbb` value (owner ruling 2026-08-12, `docs/specs/color-sketches.md`). A stroke without it renders as ink.

**Reason 1 — re-renderability.** This is the decisive one, and it follows from Rule 4. When you swap the image encoder, the new one may want a different input resolution or line weight. From coordinates you re-render natively at whatever the new encoder wants. From a stored image you can only resample, which loses exactly the detail the encoder is sensitive to. Storing coordinates is what makes historical rescoring faithful rather than approximate.

**Reason 2 — canonicalization.** Encoder output is strongly affected by line width relative to image size. Client-side rendering gives you uncontrolled variation across devices, screen densities, and canvas sizes — pure noise in a dimension you do not care about.

**Reason 3 — adversarial inputs.** Once a leaderboard has stakes, someone will submit an image with imperceptible modifications designed to score high against many pool images. Accepting coordinates only removes this possibility rather than requiring you to detect it.

**Bonus, free of charge:** stroke order and timing come along automatically. You may never use them, but you cannot recover them later.

If you must accept a photograph of a paper sketch, normalize hard — binarize, thin the lines, re-render at the canonical width — and tag it as a separate input class, because its statistics will not match native input.

### Validation gates

Reject before scoring:

- **Minimum total ink** — a single dot produces a degenerate vector that can score strangely.
- **Minimum stroke count** for `WHOLE-DRAWING` atoms.
- **Maximum text length per atom** — prevents a whole essay being stuffed into one atom, which would distort its rarity weight.
- **Maximum atom count** — soft cap, see §12 on why flooding does not actually help.

---

## 9. Layer 1 — Atom assembly

Reads the structured interface fields described in §6, assigns identifiers and types, and emits the atom set. No parsing, no model, no configuration. Around fifty lines of code that you write once and never touch.

Its output is the permanent record of what the player submitted, and it must be reproducible byte-for-byte from the raw stored submission forever.

---

## 10. Layer 2 — Encoders

Replaceable. Each encoder is identified by a hash of its model identifier, weights, and preprocessing settings.

| Slot | Input | Output | Suggested model |
|---|---|---|---|
| Text encoder | atom text, vocabulary entries | vector | SigLIP or CLIP text tower |
| Sketch encoder | rendered player strokes | vector | same image tower, sketch-prompted |
| Image encoder | pool line drawings and crops | vector | same image tower |

### Why the sketch encoder and image encoder are separate slots when they may be the same model

They must output into the same space, because the outline channel takes a similarity between them. In the initial build **they are literally the same weights used twice.**

They are kept as separate slots because their swap costs are wildly different. Changing the image encoder forces a full recomputation of the pool cache — hours of work over 20,000 images. Changing the sketch encoder costs nothing but refitting the fusion weights. Separate slots mean the configuration hash tracks them separately, so a sketch-side improvement does not invalidate the pool cache.

They genuinely diverge only if you later adopt a sketch-retrieval model, which are typically two-tower designs with different weights on each side, jointly trained to share an output space. You are not training models, so this would mean adopting someone else's pretrained pair.

### Universal preprocessing

**Always normalize vectors to unit length.** Otherwise vector magnitude leaks into scores, and magnitude correlates with how much ink is in a drawing and how complex an image is — both irrelevant.

**Subtract the pool mean vector before comparing.** Encoder spaces have a dominant average direction that adds a constant offset to every similarity, compressing the useful range.

---

## 11. Layer 3 — The style bridge

This layer manages the single largest technical risk in the system.

### The problem, stated plainly

A pencil sketch and a photograph of the same object are **not** close together in encoder space. Style dominates content: sketches cluster with other sketches. In practice, the similarity between a sketch of a lighthouse and a photo of a lighthouse is frequently *lower* than the similarity between a sketch of a lighthouse and a sketch of a cat.

Compared naively, the outline channel would mostly be measuring "is this a line drawing," which is constant across all submissions, leaving a tiny and noisy residual signal.

### The fix: convert the photograph into a line drawing

Done offline, once per pool image.

| Approach | What it is | Verdict |
|---|---|---|
| Canny edge detection | Classical gradient thresholding | No. Falls apart on foliage, water, and texture — produces noise, not structure. |
| HED | Neural edge detector | Workable, fast, well understood. |
| PiDiNet | Lighter, faster successor to HED | Good if you want speed. |
| **Informative Drawings** | Photo-to-drawing model trained with geometry and semantic objectives rather than as an edge detector | **Best.** Output actually resembles a hand drawing — it suppresses texture and keeps meaningful contours. |

### Implementing Informative Drawings on your hardware

**No training required.** The authors released pretrained weights; you are running inference on a small generator network.

The easiest path is through the `controlnet_aux` package, which ships these exact weights as its "lineart" preprocessor:

```python
from controlnet_aux import LineartDetector

detector = LineartDetector.from_pretrained("lllyasviel/Annotators").to("cuda")
line = detector(image, coarse=False)   # coarse=False selects the detail model
```

On a 5090 this is not a bottleneck. The network is a few hundred megabytes, and 20,000 images at 512 pixels batch through in well under an hour.

**The post-processing matters more than the model choice:**

```python
line = binarize(line, threshold)
line = remove_short_segments(line, min_length)
line = render_canonical(line)     # SAME resolution, line width, background,
                                  # and anti-aliasing as player sketches
```

The canonical re-render is easy to skip and expensive to skip. If pool drawings use one line weight and player sketches another, you have reintroduced the exact style gap this layer exists to close.

### Honest limitation

This only *partly* closes the gap. Even a good photo-derived drawing is far denser than a human sketch: a person draws eight strokes, the model produces four hundred contours. Segment pruning helps. Aggressive downsampling helps.

**Do not assume the bridge works. Measure it** (test V1 in §23). If it fails, the fallback is to drop the sketch encoder entirely and require players to label their stroke groups, so the signal flows through text instead. The architecture does not change; one model is replaced by human annotation. That substitutability is the reason this is its own layer.

---

## 12. Layer 4 — Channels

Three channels. Each produces one number for every pool image, and none of them knows which image is the target.

They fail in different directions, which is why all three exist rather than one.

| Channel | Measures | Blind to |
|---|---|---|
| **Element** | *What* things are present | Where they are |
| **Outline** | *What shape* the whole drawing is | What the things are |
| **Placement** | *Where* things sit relative to each other | Everything else |

**A worked contrast.** Target: a lighthouse on a breakwater. Player draws a tall vertical mass with water below, but places it right of centre when the photo has it left of centre.

- The **element channel** scores well: "tall vertical" matches "tall cylinder", "water" matches "seawater". Position never enters its computation.
- The **outline channel** scores poorly: a mirrored composition produces a genuinely different vector.

Now invert it — a player draws a windmill with correct composition. The outline channel scores well, the element channel does not.

Remote viewing output is characteristically "right things, wrong arrangement," which suggests the element channel should carry more weight. But that is a hypothesis to fit, not to assert. See §19.

### 12.1 Element channel

**Step 1 — rarity weight per atom.** For an atom that matches vocabulary entries, its rarity is:

```
rarity(a) = −log( fraction of pool images containing something this atom matches )
```

Computed once per submission against the precomputed vocabulary, not per image.

*What this means.* "Outdoor" in a pool that is 60% outdoor gives about 0.5 nats. "Brass sextant" appearing in one image out of 20,000 gives about 10 nats. This single quantity is why vague submissions score at chance without any explicit penalty being written.

**This is why flooding the form with generic words does not work.** Sixty generic atoms raise the score against *every* pool image roughly equally, and ranking responds only to *differences* between images. A submission of "outdoor, natural, large, blue" scores about 0.5 no matter how many pool images it technically matches.

**Step 2 — similarity table.** For a given pool image with element list `[b₁ … b_k]`:

```
C[i][j] = similarity(vector(aᵢ), vector(bⱼ))     if types are compatible
        = −infinity                              otherwise
```

**Step 3 — soft matching.** Decide which atoms correspond to which elements, allowing partial credit:

```
Π = argmax over match tables of:  (total matched similarity) + ε · (spread of the match)
```

The second term rewards spreading credit rather than committing hard. It is computed by a standard iterative procedure (Sinkhorn's algorithm): set `K = exp(C/ε)`, then alternately rescale rows and columns about twenty times. `ε` controls how soft the matching is and is a tunable number with real effect on the results.

*Why soft rather than a hard one-to-one assignment.* Remote viewing output is genuinely ambiguous. An atom "tall, vertical" might partially correspond to three different elements, and hard assignment throws that information away.

*Allow unmatched atoms and unmatched elements.* Do not force every atom to be used or every element to be covered. Players produce noise atoms, and they produce partial impressions. Forcing full matching manufactures spurious correspondences whenever the atom count and element count differ. (This relaxation is standard and is usually called "unbalanced" matching.)

**Step 4 — channel score.**

```
score = Σ over i,j of  Π[i][j] × C[i][j] × rarity(aᵢ)
```

Total rarity-weighted correspondence.

**Note:** a precision-style penalty for unmatched atoms would depend only on the submission, and by Rule 2 therefore cannot change the ranking. Compute it if you want to show it as feedback; it contributes nothing to the score.

### 12.2 Outline channel

Compares the player's whole drawing against the pool's precomputed line drawings.

```
score = max over crops of  similarity( sketch_vector, outline_vector(image, crop) )
```

**Why take a maximum over crops.** Players frequently lock onto one salient object rather than reproducing the whole scene. Comparing whole-image to whole-image systematically penalizes this. Storing whole-image plus a small crop grid (say five crops) and taking the best fixes it.

**Stated weakness.** A single pooled vector describes a whole scene. It punishes correct things in wrong positions and rewards overall layout regardless of content — close to the opposite of how a human judge assigns credit. This is exactly why it is one channel among three rather than the whole method.

### 12.3 Placement channel

Scores stated relationships against the pool image's element boxes.

**It only fires when both referenced atoms are actually located** — either they are stroke groups with positions on the canvas, or they are text atoms that matched a pool element carrying a bounding box. A relationship between two atoms that matched nothing scores nothing.

```
score = average over stated relations of  soft_check(relation, box_of_A, box_of_B)
```

where `soft_check` returns a value near 1 when the relation clearly holds, near 0 when it clearly does not, and something in between near the boundary.

**This channel is optional.** If it proves fiddly, cut it and keep the `RELATION` atom type. Layer 6 handles a missing channel automatically. That is the entire point of the active-channel mechanism.

---

## 13. Layer 5 — Normalization

Two adjustments, doing different jobs. **This layer runs independently for each channel** — each channel has its own commonness table, its own average, and its own spread. Nothing crosses between channels until Layer 6.

**Reading the notation.** `q` is the submission — one per trial, fixed while the pipeline runs. `x` is a pool image; it ranges over all `N` images. Every formula containing `x` is evaluated `N` times, but as vectorized array operations, not a loop. A channel hands Layer 5 a list of `N` numbers and gets back a list of `N` numbers.

### 13.1 Commonness correction — this changes the ranking

Some pool images score decently against *any* submission. Typically these are visually busy scenes with many common elements, or edge-dense images like forests. A player who happens to draw one of these gets free points they did not earn.

```
corrected(q, x) = 2 × raw(q, x) − common(x)
```

*Why the factor of two.* This is the standard form of the correction, chosen so that the adjustment removes the image's baseline appeal without over-subtracting into negative territory for genuinely good matches. (In the literature this is known as cross-domain similarity local scaling, and the standard form also subtracts a term for the query side — but that term is the same for every image, so by Rule 2 it cannot change the ranking and is dropped.)

### 13.2 How the commonness table is computed

`common_c(x)` answers: *how well does image `x` score against a typical submission, under channel `c`?*

```python
# offline, once per channel, per pool version
for x in pool:
    common[c][x] = mean( channel_c(q_bg, x) for q_bg in background_set )
```

The background set needs a few thousand submissions. You have no players yet, so manufacture them from two sources:

**Source A — real human sketches paired with the wrong targets.** Take drawings from a public sketch dataset. They are genuine human drawings, unrelated to your pool, which is exactly the no-information condition you want to measure.

**Source B — synthetic submissions built from your own pool.** For a random pool image, degrade its element list into something a player might plausibly produce:

```python
def synthetic_submission(image, n_atoms=5):
    picked = sample(element_list(image), k=n_atoms)
    atoms  = [generalize(e) for e in picked]      # "brass sextant" -> "metal instrument"
    atoms += sample(random_elements_from_pool(), k=2)   # player noise
    return atoms
```

`generalize()` can be a dictionary-based lookup of broader terms, or a single cheap language model call.

**Source B is the more important one**, because it matches your pool's vocabulary and element-list statistics. Source A serves as a check that you have not simply overfitted to your own generator.

**Recompute on a schedule.** Migrate to real player submissions once you have a few thousand. As players learn the game their submission style drifts, and a stale commonness table becomes a systematic bias favouring whatever was common under the old style.

### 13.3 Standardizing — this does not change the ranking

```
standardized(q, x) = ( corrected(q, x) − average over pool ) / ( spread over pool )
```

*What this means.* Every number now reads as "how many standard deviations above a typical pool image, for this particular submission." The element channel outputs unbounded rarity-weighted mass; the outline channel outputs similarities near zero to one. After standardizing they are directly comparable.

**This is the only reason a single set of fusion weights can span both channels.** Within a single channel it changes nothing, exactly as Rule 2 predicts.

---

## 14. Layer 6 — Fusion

```
                Σ over active channels of  weight_c × standardized_c(q, x)
fused(q, x) =  ─────────────────────────────────────────────────────────────
                          Σ over active channels of  weight_c
```

**The active channel set is determined by which atom types are present.** A submission with no `WHOLE-DRAWING` atom simply has no outline term.

**The division by the sum of active weights is what makes missing modalities safe.** A text-only submission uses the same weights over fewer terms, and the denominator preserves the scale. There is no branch, no special case, no separate code path for text-only versus sketch-only versus mixed.

### Are different modalities comparable?

**Under the no-information baseline, yes, unconditionally.** The trial score is the target's rank among decoys under whatever channels ran. With no information the target is just as likely to be anywhere in the sorted list regardless of how the score was computed. Chance is 0.5 for everyone, always.

This robustness is the strongest single argument for ranking over any threshold-based scheme, and it is why the mixed-input requirement is cheap here and would be painful in an absolute-similarity design.

**What does differ is sensitivity.** A richer submission has more room to separate from chance when the player does have information. So:

- Record which channels fired with every trial and show it on the leaderboard.
- Consider separate leaderboard tracks, if you want the ranking to reflect viewing ability rather than willingness to type.

---

## 15. Layer 7 — Deferred rerank

Optional. **Does not run in the interactive path.** See §18 for why this costs you nothing.

Layers 4–6 produce a full ranking cheaply. They are good at pulling the right image into the top of the list and weaker at fine discrimination *within* the top — which is the only region that determines the trial score. A slower, more careful judge applied to just the top candidates fixes that.

### Procedure

1. Take the top 25 from the fast ranking. **Force the target into the candidate set if it is not already there.** Otherwise you would only ever rerank trials where the fast path already succeeded, which biases scores upward.
2. Send the submission plus the 25 candidate images to a VLM through OpenRouter, with a fixed instruction describing how to assess correspondence.
3. **Randomize the presentation order and repeat three times, then average.** VLM judges have a strong tendency to favour whichever item appears first. This is a large effect, not a small correction.
4. Reorder the candidates by the averaged result.

### Stitching the two rankings together

```python
if target in candidates:
    rank = position_among_reranked_candidates(target)      # 0 to 24
else:
    rank = fast_path_rank(target)                          # 25 or worse
```

**The assumption this rests on** is that everything outside the top 25 really does belong below everything inside it. That holds when the fast path has good recall. **Measure it:** on synthetic submissions with known targets, what fraction of true targets land in the top 25? Below about 90%, enlarge the candidate set or fix the fast path rather than papering over it.

### Cost

Three calls per trial, each showing 25 images. On OpenRouter with a mid-tier VLM, single-digit cents per trial. Fine once per player per day; not fine on any interactive path.

**Log every judgment.** These accumulate into training data should you ever want to distill this judge into a fast local model.

---

## 16. Layer 8 — Ranking

The first and only place the identity of the target enters the system.

```python
decoys = pool − duplicate_group(target)
if frontload_active:
    decoys = decoys ∩ images_matching(frontload_tag)

D = len(decoys)                                    # the decoy count

beaten = count(fused[x] < fused[target] for x in decoys)
tied   = count(fused[x] == fused[target] for x in decoys)

p = (beaten + 0.5 × tied) / D                      # the trial score
```

### Why removing the duplicate group is mandatory

If three nearly identical lighthouse photos sit in the pool and one is the target, a perfect lighthouse sketch ranks fourth. Which of the three wins is decided by encoder noise, not by the player. The trial score becomes noise precisely in the trials where the player performed best.

### Decoy count and resolution

The trial score can only take `D` distinct values, so resolution is `1/D`. A tight frontload filter leaving 40 images caps resolution at 2.5%.

**Enforce a floor of `D ≥ 200`** when the player selects a frontload option, and store `D` with the trial — it is needed to interpret the aggregate.

### The baseline

With no information, the trial score is equally likely to be anywhere between 0 and 1, with average exactly 0.5. This holds **by construction**, independent of any calibration, any threshold, or any property of the encoders. Given that a substantial share of your players will be skeptics — reasonably — a baseline that holds structurally is worth more than any amount of scoring sophistication.

The small effect of `D` being finite rather than infinite makes downstream tests very slightly conservative. At `D ≥ 200` this is negligible and the half-credit-for-ties rule above handles it.

---

## 17. Layer 9 — Aggregation

### The skill number

With no ability, trial scores are spread evenly between 0 and 1. With ability, they cluster high. Model that with a single parameter:

```
skill number θ = −n / Σ log(pᵢ)          over a player's n trials
```

`θ = 1` is chance. `θ > 1` means the trial scores are clustered high.

### Evidence

The same quantity gives a significance test. Under the no-ability assumption:

```
−2 × Σ log(pᵢ)   follows a chi-squared distribution with 2n degrees of freedom
```

Small values are the evidence direction. **One computation serves as the ability estimate, the likelihood, and the hypothesis test** — this is Fisher's method for combining independent results, read backwards.

It is also more sensitive than simply averaging the trial scores to the pattern you would actually expect if the effect were real: occasional strong hits rather than uniformly slight elevation.

### Uncertainty

Writing `S = −Σ log(pᵢ)`:

- `θ = n/S` is slightly biased upward; `(n−1)/S` is unbiased.
- The uncertainty in `log θ` is approximately `1/√n`, **independent of θ itself.**

That last property is what makes `log θ` the right quantity to average across players.

### Shrinking toward the average

A player with three lucky days should not outrank a player with two hundred solid ones. Fit a population distribution for `log θ` across all players, then pull each player's estimate toward the population average by an amount reflecting how few trials they have:

```
                     ( population_average / spread² ) + ( n × log θ )
shrunk log θ  =      ─────────────────────────────────────────────────
                              ( 1 / spread² ) + n
```

Rank the leaderboard by this, or more conservatively by its lower confidence bound.

**Without this the leaderboard is a competition to be lucky recently**, and the top position will be permanently occupied by whoever joined most recently and got two good days. This is not cosmetic — it destroys the meaning of the ranking, and it is the first thing a statistically literate player will notice.

### Two threats specific to this layer

**Players choose when to stop.** Someone who quits after a hot streak has an inflated skill number. Daily cadence with everyone starting from zero limits this, but the honest defense is to **display the trial count prominently** and require a minimum (around 30) for leaderboard eligibility.

**Many players means many accidents.** With 10,000 players, dozens will clear a 1-in-100 threshold every week by chance alone, and every one of them will believe they have discovered something about themselves. Report values adjusted for the number of players tested (a false discovery rate adjustment). This is an integrity obligation, and also a practical one — the statistically literate players will notice, and they will say so publicly.

**What is actually interesting.** If the no-ability assumption is correct, the population spread of `log θ` should be exactly what sampling noise predicts and no more. If you observe genuine extra spread between players, *that* is the finding — far more than any individual score. It is also the number a skeptic will ask for, so compute it from the beginning.

---

## 18. Latency architecture

The application must feel instant. This section is the plan for that.

### The key structural insight

**The daily trial does not need fast scoring, because scoring is deliberately hidden until reveal.**

Section 22 requires that no score feedback of any kind reaches the player before the submission window closes — otherwise players iterate against the score and optimize their way into the target. That requirement, adopted for integrity reasons, hands you the latency budget for free: the player submits, sees an acknowledgment, and receives the result at reveal time. The slow rerank in Layer 7 has hours to run.

**So what actually needs to be fast?**

| Interaction | Requirement | Path |
|---|---|---|
| Drawing on the canvas | 16 ms | Client only, no server involvement |
| Submission acknowledgment | < 200 ms | L0, L1, validation, store |
| Reveal screen opening | < 100 ms | Fully precomputed at reveal time |
| Leaderboard | < 100 ms | Precomputed, cached |
| **Practice mode** | **< 100 ms** | **Full fast path, L0 through L8** |

Practice mode — replaying past targets for immediate feedback — is the only place the scoring path is genuinely interactive. Build for it anyway: it makes practice mode possible, it makes rescoring your entire history cheap, and it costs almost nothing extra.

### The fast path budget

Target: **under 50 ms** for Layers 0 through 8, with a pool of 20,000.

| Step | Time | Notes |
|---|---|---|
| Render strokes | 3 ms | CPU, small canvas |
| Encode 8 text atoms | 4 ms | One batched pass |
| Encode 2 sketch renders | 8 ms | One batched pass |
| Element channel, tier 1 (all 20,000) | 4 ms | See below |
| Element channel, tier 2 (top 500) | 6 ms | See below |
| Outline channel (all 20,000) | 1 ms | One matrix-vector product |
| Layer 5 normalization | 1 ms | Vector arithmetic |
| Layer 6 fusion | < 1 ms | Vector arithmetic |
| Layer 8 ranking | 1 ms | One sort or one comparison sweep |
| **Total** | **~30 ms** | |

### Why the element channel needed restructuring

The outline channel scales for free: all pool outline vectors sit in one matrix, and scoring is a single matrix-vector product.

The element channel does not. A naive implementation runs the soft-matching procedure once per pool image — 20,000 iterative solves per submission. That is seconds, not milliseconds.

The fix is **three tiers**, with a cheap approximation over everything and the exact computation only where it matters.

#### Tier 1 — approximate, over the whole pool

Uses the vocabulary and incidence table built during pool preparation (§5).

```python
# once per submission
A = atom_vectors @ vocabulary_vectors.T        # shape (m, |V|), one matmul

# gather each image's own vocabulary entries
gathered = A[:, incidence_table]                # shape (m, N, 20)
best     = gathered.max(axis=2)                 # each atom takes its best element
scores   = (best * rarity[:, None]).sum(axis=0) # shape (N,)
```

*What this is doing.* Instead of running a matching procedure, each atom simply grabs its single best-matching element in the image, with no competition between atoms. This is slightly optimistic — two atoms may claim the same element — but it preserves ordering well enough to shortlist candidates.

*Cost.* The gather produces `8 × 20,000 × 20` numbers, about 13 MB. On a 5090 this is a few milliseconds.

#### Tier 2 — exact, over the top 500

Run the real soft matching on the tier-1 shortlist. Batched as a single tensor of shape `(500, m, k)`, roughly twenty rescaling iterations. About 6 ms.

Take the top 500 rather than the top 25 so that the shortlist boundary sits far from the region that determines the score.

#### Tier 3 — VLM judge, over the top 25, deferred

Layer 7. Seconds, run after the window closes.

### Memory plan on a 32 GB card

Everything stays resident. Nothing is loaded per request.

| Item | Size |
|---|---|
| Outline vectors, 20,000 × 5 crops × 1024 dims, half precision | 200 MB |
| Vocabulary vectors, 15,000 × 1024, half precision | 30 MB |
| Incidence table, 20,000 × 20 integers | 1.6 MB |
| Commonness tables, three channels | negligible |
| Rarity weight table | negligible |
| Text encoder + image encoder loaded | ~3 GB |
| **Total** | **~3.5 GB** |

Twenty-eight gigabytes spare. You could grow the pool tenfold before memory becomes the constraint — though tier-1 gather time would grow proportionally, which is the real ceiling at around 100,000 images.

### Concurrency

If a thousand players submit simultaneously, batch their submissions into a single pass. The pool-side data is shared, so per-submission marginal cost drops sharply — roughly 5 ms each when batched. A single 5090 handles the daily submission spike of a large user base without difficulty.

### What to precompute at day start

The moment the day's target is chosen, precompute and cache:

- The decoy set for each available frontload option.
- The decoy count `D` for each.
- The target's duplicate group.

None of this depends on any submission, and it removes set operations from the request path.

---

## 19. Fitting without human judges

You have no human judges. This section describes what replaces them, and one trap that must be avoided.

### The trap, stated first

**Never fit fusion weights using real player trials with the real target as the label.**

If players have no ability, there is no recoverable signal — so the fitting objective has no true optimum. But it does have a *noise* optimum, and any optimizer will find it. You would be choosing weights that make targets rank high in your specific historical sample, then publishing trial scores computed with those same weights.

**That manufactures apparent ability out of nothing, and it would look exactly like success.** It is the most dangerous thing you could build here.

Fit only on data where correspondence is known to exist by construction. Freeze the weights. Then score live trials.

### What replaces human preference labels

You do not need preference judgments. You need **correspondence with a known answer**, and that is free to manufacture.

**Source 1 — public sketch-photo datasets.** Sketch datasets pair each drawing with the photograph it depicts. Insert the photograph into your pool, treat the drawing as a submission, and the correct answer is known. This directly tests the sketch path and the style bridge.

**Source 2 — synthetic submissions from your own pool.** The same generator that builds the background set (§13.2), except now you keep the label. Vary the degradation level to simulate weak, medium, and strong players.

This is the main source, because it matches your pool's vocabulary and element-list statistics, which an external dataset does not.

**Source 3 — a VLM as judge, through OpenRouter.** You do have a judge, just not a human one. Show a VLM a submission and two candidate images and ask which corresponds better. A few thousand such comparisons give you preference data.

*Caveat:* this makes the VLM's opinion your ground truth. **Validate the judge itself** on Source 2 cases where you already know the answer. If it cannot recover known-correct targets, it cannot calibrate your weights either.

### The fitting objective

Maximize the average trial score on labeled examples where the true target is known.

**With two or three channels, do not use an optimizer.** Weights are scale-invariant, so `K` channels give `K−1` free numbers. Two channels is one number. Grid search it:

```python
for alpha in linspace(0, 1, 21):
    weights = {"element": alpha, "outline": 1 - alpha}
    quality = mean(trial_score(q, true_target, weights)
                   for q, true_target in validation_pairs)
```

Plot the curve.

- **Flat curve** → one channel is contributing nothing. Cut it.
- **Sharp peak** → you have learned something real about the relative value of content versus composition.

Twenty-one evaluations, no gradients, fully interpretable, and you can look at the result and understand it. Move to a proper fitting procedure only when you have four or more channels.

---

## 20. Frontloading

Frontloading means telling the player something about the target in advance: "the target is a man-made structure."

Done naively, it inflates scores, so a frontloaded player beats a blind one, and the leaderboard becomes a measure of how much you told people.

### The fix: filter the decoys, not the score

**If the frontload says "man-made structure," every decoy must also be a man-made structure.**

The trial score then measures only what the player supplied *beyond* the frontload, and the baseline stays at 0.5 regardless of how strong the hint was. No handicap multiplier, no tuning, fully defensible.

This is a direct application of Rule 3: decoys must be drawn from the same conditional distribution as the target.

### Requirements

- **A tag vocabulary** on every pool image: category, indoor/outdoor, natural/man-made, scale, animate, dominant colour.
- **Frontload options drawn only from that vocabulary.** Free-text frontloading cannot be filtered on and should not be offered.
- **Minimum decoy count.** Each tag combination must leave `D ≥ 200`. Enforce at selection time — grey out options whose filtered pool is too small.
- **Commit before viewing, and log it.** Otherwise players request the hint after forming an impression, which is a materially easier task.

### Separate leaderboards per frontload level

Filtering fixes the *average* but not the *spread*. Narrower pools have more internal similarity, which compresses the score distribution and changes its tails. Mixing frontload levels on one leaderboard makes cross-player comparison unsound even though each individual trial score is valid.

---

## 21. Versioning

The layer boundaries only survive production if these are in place.

**Content addressing.** Every stored vector, element list, and line drawing carries a hash of the configuration that produced it — model identifier, weights, and preprocessing settings. Cache keys include it. A change you thought was cosmetic, like a different resize method or line width, produces a different hash and a clean rebuild rather than a cache silently mixing two incompatible representations.

**Raw submissions are the source of truth.** Stroke coordinates and text, never only vectors. Every historical trial must be rescorable from scratch.

**Shadow scoring.** New components run against live traffic producing trial scores that are logged but not shown. Before promoting, check:

- Do the shadow scores still spread evenly between 0 and 1 on no-information submissions?
- How much did the ranking move relative to the current system?
- Did it move in the direction the labeled test set says is correct?

**Rescore, do not migrate.** On promotion, rescore all history under the new configuration and republish. Because the trial score is a rank, this is coherent — old and new scores mean the same thing even though the underlying numbers do not. Keep the previous version visible for a window so players can see what changed.

**Fusion weights are pinned to the channel set.** Swapping an encoder inside a channel invalidates that channel's weight. Refit before promoting.

### Cost of change

| Change | Cost |
|---|---|
| Swap an encoder | Rebuild pool cache, refit weights, rescore. Routine. |
| Add or remove a channel | Refit weights, rescore. Routine. |
| Add a field to the atom structure | Backfill with a constant. Cheap. |
| **Change the atom type list** | **Invalidates every stored atom and every rarity weight. Avoid.** |
| Change the aggregation formula | Recompute from stored trial scores. Cheap — trial scores are the durable artifact. |

The `payload` field is the only part of an atom with a model dependency. `id`, `type`, and `subtype` survive every model swap, and every stored atom is re-encodable from its raw payload without loss.

---

## 22. Protocol integrity

Failures here invalidate results no matter how good the scoring is.

**No feedback before the window closes.** If any endpoint returns score information before reveal, players will iterate against it and optimize their way into the target. One submission per trial, scoring on the server, nothing returned until the window closes. As §18 notes, this constraint is also what frees your latency budget.

**Stroke coordinates only.** Covered in §8. Removes the adversarial-image class rather than requiring detection.

**Identifier hygiene.** The trial identifier must be a fresh random value with no derivation from image content, filename, pool index, or timestamp. Do not send the image to the client before reveal. Do not use guessable content addresses. Check that response size and timing do not correlate with properties of the target.

**Shared-target leakage.** One shared daily target means one leak spoils the day for everyone. Either use per-player targets — which breaks cross-player comparison on a given day, but you are scoring ranks anyway, so it does not matter much — or accept the risk and add a submission lockout.

**Commitment.** Publish a hash of the target identifier plus a secret when the day opens; publish the secret at close. Cheap, and it is the difference between "trust our database" and a claim anyone can verify.

**Autocomplete leakage.** If the impressions field offers autocomplete built from pool element lists, **it reveals the pool's composition to the player.** This is an integrity bug independent of scoring. Either build the suggestion list from an external dictionary, or drop autocomplete — do not build it from the pool and still call the trial blind.

---

## 23. Validation

Run in order. Each gates the next.

**V1 — Does the style bridge work?** Take 200 sketch-photo pairs from a public dataset. Run them through the pipeline. Report how often the correct photo ranks first, and how often it ranks in the top ten.

If this is near chance, the bridge is not working, and no downstream cleverness saves it. Fall back to text-only scoring with player-labeled stroke groups.

**V2 — Is the baseline correct?** Feed submissions that carry no information: real sketches paired with random targets. The resulting trial scores must spread evenly between 0 and 1. Test this formally with a Kolmogorov–Smirnov test, which measures the largest gap between your observed distribution and a perfectly even one.

**Failures here are always violations of Rule 3.** Check duplicate removal, frontload filter symmetry, and pool curation before touching anything else. With no human validation available, this test is your primary evidence that the system is not fabricating signal.

**V3 — Does the score respond to quality?** On synthetic submissions held out from fitting, report the average trial score at each degradation level. **The curve must be monotone**: stronger submissions must score higher. A metric that does not respond monotonically to submission quality is not measuring quality.

**V4 — Does each channel earn its place?** Refit the weights with each channel removed, and report the change in V3 performance. Cut any channel whose removal does not measurably hurt.

**V5 — Is commonness correction working?** Count how often each pool image appears in the top ten across the whole background set. A heavy tail means the correction is under-correcting; re-estimate on a more representative background set.

**V6 — Does the fast path find the right candidates?** On labeled synthetic submissions, what fraction of true targets land in the tier-1 top 500 and the tier-2 top 25? Below 90% for the top 25, enlarge the shortlist.

---

## 24. Hardware plan

### One-time pool preparation, 20,000 images

| Task | Where | Time | Cost |
|---|---|---|---|
| Curation filtering | 5090 | 2–4 hours | — |
| Line drawings | 5090 | < 1 hour | — |
| Element lists via local VLM | 5090 | 3–6 hours | — |
| Element lists via OpenRouter (alternative) | API | 1 hour | $10–25 |
| Encoding everything | 5090 | 20 minutes | — |
| Object detection (optional) | 5090 | 1–2 hours | — |
| Vocabulary and incidence table | CPU | minutes | — |
| Background set and commonness tables | 5090 | 1 hour | — |

**Run element extraction locally.** A 7-billion-parameter vision-language model fits comfortably in 32 GB at half precision. It is reproducible, versionable, and free — and you will re-run it every time you revise the element schema.

### Ongoing

| Task | Where | Cost |
|---|---|---|
| Fast path scoring | 5090, resident | ~30 ms per submission |
| Deferred rerank | OpenRouter | cents per player per day |
| Nightly rescoring | 5090 | minutes for the whole history |

**Nothing in this system requires training a model.** Every component is pretrained inference or classical computation.

---

## 25. Build order

**Phase 1 — Build the pool.** Curation filter, element extraction, line drawings, encoding, vocabulary, incidence table. Nothing else can be built or tested until the pool exists, because the pool is what every other quantity is defined against.

**Phase 2 — Prove the style bridge, or don't.** Layers 0, 1, 2, 3, the outline channel, Layer 5, Layer 8. Run V1 and V2. This is the smallest thing that produces a valid, calibrated trial score.

**Phase 3 — The element channel, in parallel not after.** Rarity weights, similarity table, soft matching, all three tiers. If V1 failed, this is the escape route — and it is probably the better product regardless, because it is the only channel that can tell a player *which* of their impressions were right.

**Phase 4 — Fuse and validate.** Add the placement channel if it proves workable. Build the synthetic submission generator. Grid-search the weights. Run V3 through V6. **Do not launch a public leaderboard before V2 and V3 both pass.**

**Phase 5 — Optimize the fast path.** Tier the element channel, make everything resident, batch concurrent submissions. Enables practice mode.

**Phase 6 — Deferred rerank.** Layer 7 through OpenRouter, once quality justifies the cost. Log every judgment.

**Freeze early, freeze narrowly.** The atom type list and the element schema are the two things to get right before you have data, because everything else is recomputable and they are not.

---

## 26. Failure index

| Symptom | Likely cause | Section |
|---|---|---|
| Everything scores near chance no matter the effort | Style bridge not working | §11, V1 |
| Trial scores not spread evenly on no-information tests | Rule 3 violation | §16, §20 |
| Certain images always rank high | Commonness table stale or wrong | §13.2 |
| Vague submissions score well | Rarity weights missing or computed against the wrong pool | §12.1 |
| Good sketches rank oddly low | Duplicate group not removed | §5, §16 |
| Leaderboard top position churns weekly | No shrinking toward the average | §17 |
| Score changed after a "cosmetic" edit | Missing configuration hash | §21 |
| Text-only players systematically beaten | Fusion denominator not renormalized | §14 |
| Position matters more than content | Outline weight too high | §14, §19 |
| Rerank helps in testing, not in production | Fast path shortlist too small | §15, V6 |
| Rerank inconsistent between runs | Not enough order permutations | §15 |
| Players report the hints gave it away | Autocomplete built from the pool | §22 |
| Pool is 30% churches | Diversity cap skipped in curation | §4 |
| Some images match everything | Element list length not capped | §5 |
| Scoring takes seconds | Element channel not tiered | §18 |
| Apparent ability appears out of nowhere | **Weights fitted on live trials** | §19 |

---

## 27. Worked example

Pool of 20,000. Target is a lighthouse. Player submits four written impressions and a sketch with two labeled groups.

**Layer 0.** Validate: 6 atoms, ink above threshold. Render strokes at canonical settings. Store raw. *3 ms.*

**Layer 1.** Assemble: five `DESCRIPTION` atoms, one `WHOLE-DRAWING` atom. Active channels: element and outline. *< 1 ms.*

**Layer 2.** Encode five text payloads and three renders in two batched passes. *12 ms.*

**Rarity weights**, from one matrix multiplication against the vocabulary:

| atom | pool frequency | rarity |
|---|---|---|
| "tall vertical structure" | 0.09 | 2.4 |
| "cold and exposed" | 0.31 | 1.2 |
| "metallic" | 0.22 | 1.5 |
| "water nearby" | 0.18 | 1.7 |
| "tower" (labeled group) | 0.11 | 2.2 |

**Layer 4, element channel, tier 1.** Approximate scores for all 20,000. Shortlist the top 500. *4 ms.*

**Tier 2.** Exact soft matching on those 500. For the lighthouse image the match table reads:

```
"tall vertical structure" → "tall cylinder"   Π=0.81  C=0.74
"water nearby"            → "seawater"        Π=0.76  C=0.68
"cold and exposed"        → "isolated"        Π=0.44  C=0.51
"metallic"                → "stone"           Π=0.12  C=0.29   (weak — correctly)

score = 0.81×0.74×2.4 + 0.76×0.68×1.7 + 0.44×0.51×1.2 + 0.12×0.29×1.5
      = 1.44 + 0.88 + 0.27 + 0.05 = 2.64
```

The two specific, correct atoms supply 88% of the total. That is rarity weighting doing its job. *6 ms.*

**Layer 4, outline channel.** One matrix-vector product against all outline vectors, max over five crops. *1 ms.*

**Layer 5.** Per channel: subtract commonness, then standardize. The lighthouse ends at +1.51 on element, +0.80 on outline. *1 ms.*

**Layer 6.** With weights 0.7 and 0.3: `(0.7 × 1.51 + 0.3 × 0.80) / 1.0 = 1.30`. *< 1 ms.*

**Layer 8.** Now, and only now, the target's identity is used. Duplicate group has 3 members, so the decoy count is 19,997. The lighthouse ranks 4th, beating 19,993 decoys.

```
trial score p = 19,993 / 19,997 = 0.99980
```

*1 ms.* **Total elapsed: about 29 ms.**

**Layer 7, deferred.** After the window closes, the top 25 go to the VLM judge across three randomized orderings. The lighthouse moves from 4th to 2nd. Trial score revised to 0.99990.

**Layer 9.** This player now has 12 trials:

```
0.99  0.62  0.15  0.88  0.94  0.31  0.77  0.99  0.45  0.83  0.68  0.91

S = −Σ log p = 5.48
skill number = 12 / 5.48 = 2.19
evidence: 2S = 10.96 against a chi-squared with 24 degrees of freedom → 0.011
```

With a population spread of 0.15, shrinking toward the average:

```
                 0 + 12 × 0.784
shrunk log θ  =  ───────────────  = 0.167    →    skill number 1.18
                   44.4 + 12
```

**A raw 2.19 becomes 1.18 on twelve trials.** That gap is the leaderboard's entire integrity story. The raw number would place this player near the top; twelve trials do not support that claim.

**Feedback shown at reveal:** the target image, "you beat 19,993 of 19,997 images," and the per-atom report read directly from the match table — which impressions matched, which did not, and what they matched. That report is the retention mechanism. A number alone gives a player nothing to improve on.
