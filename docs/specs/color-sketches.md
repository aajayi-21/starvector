# Spec C1 — color sketches

**Status:** ruled, in build.
**Ruling:** owner, 2026-08-12 — sketches have color, the canonical
render shows it to the model, and a measured gate decides if it
stays. If the gate fails, the system goes back to monochrome render
with no other change.
**Architecture sections:** §8 (Layer 0, the stroke shape), §21
(versioning).
**Related specs:** `scoring-path.md` (the frozen wire shape),
`trial-service.md` (the intake page).

---

## 1. The stroke shape change

The frozen wire shape gains one optional stroke key:

```
Stroke := { points, group_id, color? }
```

- `color` is a lowercase `#rrggbb` string. One spelling alone, thus
  equal drawings give one byte stream and one cache key.
- Layer 0 checks the format and nothing else. The palette belongs to
  the interface: a palette change does not touch the frozen tier.
- A stroke without the key renders as ink. Each stored record from
  before this change stays readable forever — the key is optional,
  and no stored record is edited (Rule 4).

This is the one recorded change to the frozen stroke shape. The
checker keeps strict key-set equality for the record, groups, and
relations. The stroke check alone permits the optional key.

## 2. The promotion rule

The render rule is a pure function of the record:

- **No stroke carries a `color` key** — the render is the monochrome
  canonical PNG, byte-for-byte equal to the render from before this
  change. This holds with the rgb config too.
- **One or more strokes have the key** — the render promotes to an
  RGB PNG: white background, no anti-aliasing, the same dilation
  rule, each stroke painted in its color in stroke sequence. At an
  overlap, the stroke that comes after paints above the one before.
  A stroke without the key paints as ink.

The first half of the rule is load-bearing. It keeps the background
and validation caches warm, it keeps colorless rescores byte-stable
(`trial-service.md` R8), and it makes the revert free. The key
itself decides, not the value: a hand-written `#000000` promotes
the render — deterministic, and the interface cannot make it.

## 3. Configuration and hashes

- The preparation config gains `linedraw.stroke_color`, one of
  `"mono"` or `"rgb"`, default `"mono"`. The field is out of the
  preparation config hash at `"mono"` (the `photo_render` precedent),
  thus each released config document and hash stays byte-stable.
- `RenderParams` gains `stroke_color` with default `"mono"`.
- The commonness config hash render entry gains a `stroke_color` key
  at `"rgb"` alone — each existing commonness hash stays byte-stable,
  and the rgb lineage forks its tables.
- With `"mono"`, colors are stripped at render: the stored record
  keeps them (Rule 4), the model does not see them.

## 4. Color through the layers

- `Atom` gains `stroke_colors`, aligned with `strokes` entry for
  entry, `None` when no member stroke carries a color. A colorless
  record assembles to the atom set it assembled to before this
  change.
- The canonical render alone reads `stroke_colors`. Placement reads
  geometry, the element channel reads text — color reaches the
  render and no other reader.
- Group atoms hold `stroke_colors` that nothing renders while the
  element channel runs text-only — recorded, not acted on, correct
  if a sketch-vector path arrives in a build that follows.

## 5. The palette

The interface offers eight fixed swatches. Ink emits no `color` key.

| name | value |
|---|---|
| ink | no key emitted — displays as the theme ink |
| red | `#bf616a` |
| orange | `#d08770` |
| yellow | `#ebcb8b` |
| green | `#a3be8c` |
| blue | `#81a1c1` |
| purple | `#b48ead` |
| teal | `#8fbcbb` |

A palette change is an interface change: Layer 0 accepts the format,
not the set.

### Amended 2026-08-14 (spec W1 ruling 6)

The set moved to the production theming's family, and the eighth
slot changed from brown to teal `#8fbcbb`. The 2026-08-12 values
were: red `#c5221f`, orange `#e8710a`, yellow `#f0b429`, green
`#1b6b3a`, blue `#1a73e8`, purple `#7a4ec9`, brown `#795548`, with
ink shown dark (`#1a1c1e`) on the light dev canvas. The effects,
recorded:

- Stored records keep the hex they hold. The format rule is
  unchanged, rescoring stays byte-equal, and the change reaches
  new submissions alone.
- The v2c gate re-runs on the new values before the first day
  played in color on the production app. The encoder reads color — the runs of
  2026-08-12 and 2026-08-13 measured mean absolute delta-p near
  0.12–0.14 on the earlier, higher-chroma set — and the new set
  is lower-chroma, thus the measurement does not hold for it.
  `validation/colorize.py` holds the seven non-ink values and
  updates with this table. The new record notes the palette
  revision.
- The dev page (`service/ui/trial.js`) keeps the 2026-08-12
  swatches until the backend phase retires it — a recorded
  difference, not drift. Records it sends stay correct: intake
  checks the format, not the set.

## 6. The soundness gate (V2c)

Color lands in an embedding space told to set aside color — the
pool-side instruction of the adopted base names "not the
photographic style, colors, or textures" — and the background
sketches have no color. The gate measures what color does before it
stays:

- `validation/colorize.py` gives each stroke of a pair sketch a
  seeded palette color — pure, keyed `v2c:{seed}:{pair_key}:{index}`.
- `validation/v2c.py` mirrors V2: the same pairs, the same targets,
  and it scores each pair sketch two ways — monochrome and
  colorized. It refuses a `"mono"` context, which strips colors and
  measures nothing.
- The record holds the KS statistic and significance for the two
  sides, the mean, largest, and signed trial-score difference, and
  the post counts. The verdict is the owner's.
- Cost: the colorized renders are new encoder items, batched. The
  monochrome side is warm after a V2 run on the same lineage.

## 7. The gate run (owner runbook)

The gate runs on the current pool first, before rgb lands in the
dev-wit-2 migration (`pool-curation.md` section 18) — the color
renders are pool-free bytes, thus their encoder cache moves to the
new pool with no cost.

1. `uv run python -m pool.preparation --config
   configs/preparation/dev-wit-photo-inst-rgb.json` — the sibling
   config differs in `stroke_color` and the tag alone. Each provider
   cache is warm at the same slot hashes: zero posts, and the run
   writes `pool/preparations/dev-wit-prep-photo-inst-rgb-a6071f0e.json`
   (the hash is precomputed — a different filename in the run output
   means the config drifted, stop and check).
2. `uv run python -m validation.v2c --config
   configs/scoring/dev-wit-v2c.json --report` — the committed config
   names that record. The commonness tables build again at the new
   key with about zero posts (the colorless background renders the
   monochrome bytes), the monochrome side is warm after a V2 run on
   this lineage, and the colorized side costs about 8 to 16 batched
   embedding posts.
3. Read the record: the color side must agree with `Uniform(0, 1)`,
   and the difference numbers say what color does. The verdict is
   the owner's. With a good verdict, `dev-wit-photo-inst-2.json`
   takes `"stroke_color": "rgb"`. With a bad one, the migration
   stays `"mono"`, colors ship in the interface alone, and the
   ruling lands here.

## 8. The revert

Set `linedraw.stroke_color` to `"mono"` or delete the key — the two
hash the same. Colors stay in the stored records and strip at
render. Nothing else moves: no store edit, no rescore break, no new
posts. The interface palette can stay or go — a stored color without
a rendering config is recorded, not acted on.
