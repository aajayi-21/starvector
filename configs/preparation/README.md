# Preparation configuration files

Each file here is the full parameter surface of one preparation
pipeline run. The loader (`pool/preparation/config.py`) validates in
full: an unknown or missing field stops the run with an error that
names the JSON path. JSON has no comments, thus this file documents the
fields.

**Each edit changes the preparation config hash.** The hash keys the
pool artifact tree and the preparation version, thus an edited config
starts a new preparation lineage. That is correct behavior, not an
accident — see `docs/specs/pool-preparation.md` section 6. Image-level
caches (element responses, line drawings, outline vectors, box
responses) are keyed by the slot hashes alone, thus a config edit that
does not touch a slot reuses that slot's responses at zero cost (U1).

## The headline knobs

- **Input pool** — `input.release_record` names the committed curation
  release record. The pool membership and the artifact tree key come
  from it.
- **OpenRouter chat model** — `providers.openrouter.default_model`
  serves the `describer` and `element_boxes` slots. A slot can
  override it: set `providers.<slot>.model`.
- **Encoder model** — `providers.text_encoder.model` and
  `providers.image_encoder.model` name an OpenRouter embeddings model
  (spec U2 as amended — the embeddings endpoint was checked live
  2026-08-07). One multimodal model for the two slots keeps text and
  image vectors in one shared space. `provider` can also be `local`
  (a SigLIP checkpoint through the torch stack) or `fake`.

## Field notes

- `elements.counts` — the D2 contract: the describer response schema
  pins these counts for each field, thus element lists keep a roughly
  constant length by construction.
- `elements.normalize_rule` — the identifier of the D7 normalization
  rule table. In the config, thus a rule change moves the hash.
- `linedraw` — the D5 canonical render parameters. These are shared
  constants with the future Layer 0 sketch render: pool drawings and
  player sketches must render identically, or the style difference the
  bridge closes opens again. Read them from here — one source.
- `outline.source` — `linedraw` (the default, method A) embeds the
  cached p05 drawing. `photo` (method B) bypasses p05 and embeds the
  source photograph with the same p06 six-crop layout and image encoder
  used by A. Sketch encoding and downstream ranking stay unchanged.
- `providers.text_encoder.dimension` — the expected embedding width.
  A response with a different width raises (R14). The first live run
  confirms the served width of `google/gemini-embedding-2`. When it is
  not 3072, correct this value — a one-line edit and a new lineage.
- `providers.line_drawer` — `local` is the one implementation with a
  model behind it. No remote line-drawing capability exists. The torch
  stack installs with `uv sync --group local-cuda` (NVIDIA) or
  `uv sync --group local-xpu` (Intel GPUs, through the PyTorch XPU
  wheels). The offline test suite runs without it.
- `runtime.device` — where the local providers run: `auto`, `cuda`,
  `xpu`, or `cpu`. `auto` selects the first available of cuda, xpu,
  cpu at wiring time. An explicit device that is not available raises.
  This is the one section that is not part of the preparation config
  hash — the device is machine-local, and a device change must not
  fork the artifact lineage. Numbers can be different across devices,
  thus keep one lineage on one machine (spec section 14).
- `release.tag` — must start with `dev-` when `dev_only` is `true`,
  and only then. A preparation of a development pool is
  development-only (R15).
