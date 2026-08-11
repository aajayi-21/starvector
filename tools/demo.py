"""The one-trial demo report (docs/specs/demo-tool.md).

A side development tool, out of the scoring path — no scoring module
imports this package. The tool makes one synthetic submission with
the Phase 4 generator, scores it against each pool image on the
production path, and writes one self-contained HTML report: the
submission, the fused ranking with element-box maps, each fused
channel's standardized scores, and the source image's rank and
trial score.
Dev-only: the numbers stay unpublished (CLAUDE.md section 7).
"""

import argparse
import sys
from collections.abc import Callable, Mapping
from html import escape
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue
from core.fusion import active_channels, fuse
from core.intake import validate_submission
from core.normalize import commonness_correct, standardize
from core.ranking import decoy_set, rank
from core.types import (ROUTING_TABLE, ChannelName, PoolScores,
                        ScoringContext, TrialScore)
from pipeline.commonness import commonness_config_hash, ensure_commonness_tables
from pipeline.config import (ConfigError, ScoringConfig, element_config,
                             fusion_weights, intake_gates, load_scoring_config,
                             outline_config, placement_config,
                             scoring_config_hash)
from pipeline.context import build_scoring_context, load_pool_index
from pipeline.score import Encoders, channel_scores, encode_submission
from validation import harness
from validation.fitconfig import FitConfig, load_fit_config, parse_fit_config
from validation.generator import SyntheticSubmission, synthetic_set

# The fixture fit document for --fixture mode. These are demo fixture
# values in the pattern of the test fixtures, not method numbers.
_FIXTURE_FIT: dict = {
    "config_version": 1,
    "generator": {"levels": [
        {"n_atoms": 3, "generalize_p": 0.0, "n_noise": 0, "relations": 1,
         "corrupt_relation": False},
        {"n_atoms": 2, "generalize_p": 0.5, "n_noise": 1, "relations": 1,
         "corrupt_relation": True},
        {"n_atoms": 1, "generalize_p": 0.8, "n_noise": 2, "relations": 0,
         "corrupt_relation": False},
        {"n_atoms": 0, "generalize_p": 0.0, "n_noise": 3, "relations": 0,
         "corrupt_relation": False},
    ]},
    "generalize": {"provider": "fake", "model": None,
                   "instruction_template": None},
    "openrouter": {"default_model": "test/fake", "max_concurrency": 1,
                   "requests_per_second": 100.0, "timeout_seconds": 5.0,
                   "retry_limit": 0, "response_format_mode": "json_schema"},
    "fit": {"split_salt": "demo-salt", "fit_count": 3, "holdout_count": 2,
            "synthetic_count": 6, "synthetic_seed": 11, "line_points": 5,
            "simplex_step": 0.25, "signal_line": 0.65,
            "ablation_line": 0.01},
    "harness": {"v3_trials_for_each_level": 4, "v3_seed": 5,
                "v3_bootstrap_count": 200, "v3_interval": 0.95,
                "v6_trial_count": 4, "v6_seed": 6,
                "v6_tier1_widths": [3, 10], "v6_tier2_widths": [1, 5],
                "v6_levels": [0, 1]},
    "tag": "demo-fixture",
}


class DemoData(NamedTuple):
    """The wired inputs of one demo run."""

    context: ScoringContext
    encoders: Encoders
    table: Mapping[str, str]
    scoring_hash: str
    commonness_hash: str
    generator_hash: str | None


def demo_data(config: ScoringConfig, fit_config: FitConfig, *,
              data_root: Path,
              providers: Mapping[str, object] | None = None,
              clock: Callable[[], str] | None = None) -> DemoData:
    """Wire one scoring context through the harness machinery.

    A warm lineage makes this read-only. A cold lineage builds the
    same keyed artifacts a harness run makes — nothing that only the
    demo reads goes to disk.
    """
    providers = providers or {}
    clock = clock or harness.default_clock

    loaded = load_pool_index(Path(config.input.preparation_record),
                             data_root, dev_only=config.report.dev_only)
    source = providers.get("sketch_pairs") or harness.wire_sketch_pairs(
        config, data_root)
    encoders = harness.wire_encoders(config, data_root, providers)
    slot_hashes = harness.scoring_provider_hashes(config, providers)
    harness.check_element_space(dict(loaded.record.provider_config_hashes),
                                slot_hashes)
    scoring_hash = scoring_config_hash(config, slot_hashes)
    generator_hash = harness.resolved_generator_hash(
        config, loaded.index, data_root, providers.get("generalizer"))
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], slot_hashes["sketch_pairs"],
        generator_hash)
    gates = intake_gates(config)
    placement = placement_config(config)

    def background() -> list[tuple[str, JsonValue]]:
        return harness.full_background(
            config, source, config.validation.submission_mode,
            loaded.index, placement, data_root,
            providers.get("generalizer"))

    tables = ensure_commonness_tables(
        data_root=data_root, index=loaded.index,
        commonness_hash=commonness_hash, background=background,
        gates=gates, render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement, encoders=encoders,
        submission_mode=config.validation.submission_mode, clock=clock)
    context = build_scoring_context(
        index=loaded.index, gates=gates, render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement, weights=fusion_weights(config),
        commonness=tables.tables, scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)
    # The stored table alone — the build is a deliberate owner step
    # (spec P4 §17a item 7). Fixture mode gives a fake generalizer,
    # thus its scratch build proceeds.
    table = harness.stored_table(loaded.index, fit_config, data_root,
                                 providers.get("generalizer"))
    return DemoData(context=context, encoders=encoders, table=table,
                    scoring_hash=scoring_hash,
                    commonness_hash=commonness_hash,
                    generator_hash=generator_hash)


class ScoredDemo(NamedTuple):
    """One synthetic submission with its scores, set to render."""

    row: SyntheticSubmission
    standardized: dict[ChannelName, PoolScores]
    fused: PoolScores
    order: np.ndarray
    trial: TrialScore
    source_position: int


def score_demo(row: SyntheticSubmission, data: DemoData) -> ScoredDemo:
    """The production scoring prefix, then the Layer 8 rank.

    The label enters through decoy_set and rank alone — the same
    boundary each harness holds (I1).
    """
    context = data.context
    submission = validate_submission(row.record, context.gates,
                                     context.render.canvas_px)
    encoded = encode_submission(submission, context.render, data.encoders)
    standardized: dict[ChannelName, PoolScores] = {}
    for name in sorted(active_channels(encoded, ROUTING_TABLE)):
        if name not in context.weights:
            continue
        if name not in context.commonness:
            raise ValueError(f"channel {name!r} has no commonness table")
        raw = channel_scores(name, encoded, context.index, context.outline,
                             context.element, context.placement)
        standardized[name] = standardize(
            commonness_correct(raw, context.commonness[name]))
    fused = fuse(standardized,
                 {name: context.weights[name] for name in standardized})
    order = np.argsort(-fused, kind="stable")            # (N,) positions
    decoys = decoy_set(context.index, row.image_id)
    trial = rank(fused, row.image_id, decoys, context.index)
    source_position = list(context.index.image_ids).index(row.image_id)
    return ScoredDemo(row=row, standardized=standardized, fused=fused,
                      order=order, trial=trial,
                      source_position=source_position)


def _strokes_svg(record: JsonValue) -> str:
    """The submission canvas as an SVG, unit square scaled to 100."""
    parts = ['<svg viewBox="-2 -2 104 104" class="canvas">',
             '<rect x="0" y="0" width="100" height="100" class="frame"/>']
    for stroke in record["canvas_strokes"]:
        points = " ".join(f"{100 * x:.1f},{100 * y:.1f}"
                          for x, y in stroke["points"])
        css = "grouped" if stroke.get("group_id") else "loose"
        parts.append(f'<polyline points="{points}" class="{css}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _box_map_svg(data: DemoData, position: int, source: bool) -> str:
    """One pool image as its element-box map — no image bytes."""
    index = data.context.index
    css = "map source" if source else "map"
    parts = [f'<svg viewBox="-2 -2 104 104" class="{css}">',
             '<rect x="0" y="0" width="100" height="100" class="frame"/>']
    row = index.incidence[position]
    for slot, entry in enumerate(row):
        if entry < 0 or not bool(index.box_mask[position, slot]):
            continue
        x0, y0, x1, y1 = (100 * float(v)
                          for v in index.box_table[position, slot])
        label = escape(index.vocabulary[int(entry)][:14])
        parts.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" '
            f'height="{y1 - y0:.1f}" class="box"/>'
            f'<text x="{x0 + 1.5:.1f}" y="{y0 + 5.5:.1f}">{label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _relation_lines(record: JsonValue) -> list[str]:
    labels = {group["id"]: group["label"] for group in record["groups"]}
    return [f'{labels[first]} — {row["relation"]} — {labels[second]}'
            for row in record["relations"]
            for first, second in [tuple(row["of"])]]


_STYLE = """
  body { font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto;
         max-width: 60rem; padding: 0 1rem; background: #f7f8fa;
         color: #1c2433; }
  h1 { font-size: 1.5rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
  .banner { display: inline-block; border: 1px solid #a03340;
            color: #a03340; border-radius: 999px; font-size: 0.72rem;
            font-weight: 700; letter-spacing: 0.08em;
            padding: 0.15rem 0.6rem; margin-left: 0.5rem;
            vertical-align: middle; }
  .cols { display: flex; gap: 1.5rem; flex-wrap: wrap; }
  .cols > div { flex: 1 1 16rem; }
  svg.canvas, svg.map { width: 100%; max-width: 15rem; display: block;
            background: #fff; border-radius: 6px; }
  svg .frame { fill: none; stroke: #c9cedb; stroke-width: 0.8; }
  svg .grouped { fill: none; stroke: #0e6f5c; stroke-width: 1.4; }
  svg .loose { fill: none; stroke: #5c667b; stroke-width: 1.4; }
  svg .box { fill: rgba(14, 111, 92, 0.08); stroke: #0e6f5c;
             stroke-width: 0.7; }
  svg text { font-size: 4.6px; fill: #40495e; }
  svg.source .frame { stroke: #a03340; stroke-width: 1.6; }
  table { border-collapse: collapse; width: 100%; font-size: 0.88rem; }
  th, td { text-align: left; padding: 0.45rem 0.6rem;
           vertical-align: top; border-top: 1px solid #e2e5ec; }
  th { font-size: 0.72rem; text-transform: uppercase;
       letter-spacing: 0.07em; color: #5c667b; border-top: none; }
  td.num { font-family: ui-monospace, monospace;
           font-variant-numeric: tabular-nums; white-space: nowrap; }
  tr.source td { background: rgba(160, 51, 64, 0.07); }
  .verdictline { border-left: 3px solid #0e6f5c; padding: 0.5rem 0.9rem;
            background: #e2f0ec; border-radius: 0 6px 6px 0; }
  .idline { color: #8b93a6; font-size: 0.78rem; margin-top: 2.5rem;
            font-family: ui-monospace, monospace; }
  ul { margin: 0.4rem 0; }
"""


def render_report(scored: ScoredDemo, data: DemoData, *, level: int,
                  seed: int, top: int) -> str:
    """The self-contained HTML report."""
    index = data.context.index
    record = scored.row.record
    channels = sorted(scored.standardized)
    impressions = "".join(f"<li>{escape(text)}</li>"
                          for text in record["impressions"])
    relations = "".join(f"<li>{escape(line)}</li>"
                        for line in _relation_lines(record)) or "<li>none</li>"

    rows = []
    shown = [int(p) for p in scored.order[:top]]
    if scored.source_position not in shown:
        shown.append(scored.source_position)
    ranks = {int(p): number + 1 for number, p in enumerate(scored.order)}
    for position in shown:
        source = position == scored.source_position
        cells = "".join(
            f'<td class="num">{scored.standardized[name][position]:+.2f}</td>'
            for name in channels)
        tag = " · source image" if source else ""
        rows.append(
            f'<tr class="{"source" if source else ""}">'
            f'<td class="num">{ranks[position]}</td>'
            f'<td>{_box_map_svg(data, position, source)}'
            f'<div>{escape(index.image_ids[position][:12])}…{tag}</div></td>'
            f'{cells}'
            f'<td class="num"><b>{scored.fused[position]:+.2f}</b></td>'
            "</tr>")
    heads = "".join(f"<th>{escape(name)} z</th>" for name in channels)

    trial = scored.trial
    return f"""<!doctype html><meta charset="utf-8">
<title>starvector demo trial</title><style>{_STYLE}</style>
<h1>One synthetic trial<span class="banner">DEV-ONLY</span></h1>
<p>Level {level}, seed {seed}. The generator sampled the source image,
the engine scored the submission against all {len(index.image_ids)}
pool images, and the label entered only at the rank step.</p>
<div class="cols">
  <div><h2>Impressions</h2><ul>{impressions}</ul>
       <h2>Stated relations</h2><ul>{relations}</ul></div>
  <div><h2>Canvas</h2>{_strokes_svg(record)}</div>
</div>
<h2>Trial score</h2>
<p class="verdictline">The source image ranks
<b>{ranks[scored.source_position]}</b> of {len(index.image_ids)}:
it outranks {trial.beaten} of {trial.decoy_count} decoys and ties
{trial.tied} — trial score <b>p&nbsp;=&nbsp;{trial.p:.3f}</b>.
A no-information submission scores even across [0,&nbsp;1], thus 0.5
is the reference point, with no threshold anywhere (I2).</p>
<h2>Ranking — top {top} element-box maps</h2>
<table><tr><th>rank</th><th>pool image</th>{heads}<th>fused z</th></tr>
{"".join(rows)}</table>
<p class="idline">scoring {data.scoring_hash[:8]} · commonness
{data.commonness_hash[:8]} · generator
{(data.generator_hash or "none")[:8]} · level {level} · seed {seed}
· dev pool — numbers stay unpublished (CLAUDE.md §7)</p>
"""


def _fixture_setup(root: Path) -> tuple[ScoringConfig, FitConfig, Path, dict]:
    """The demo-anywhere path: a fake pool in a scratch directory.

    The tests.conftest import is a reviewed dev-tool allowance (spec
    T1 section 3.4) — production wiring must not follow it.
    """
    from providers.fake.generalize import FakeGeneralizer
    from tests.conftest import build_direct_prepared_pool, make_scoring_config
    from tests.conftest import scoring_fakes

    from core.canonical import canonical_json_pretty

    prepared = build_direct_prepared_pool(root, 40)
    fit_path = root / "fit-config.json"
    fit_path.write_text(canonical_json_pretty(_FIXTURE_FIT) + "\n",
                        encoding="utf-8")
    config = make_scoring_config(
        prepared["prep_record_path"],
        **{"fusion.weights": {"outline": 1.0, "element": 1.0,
                              "placement": 1.0},
           "commonness.dataset.fake_pair_count": 24,
           "commonness.background_count": 12,
           "commonness.synthetic": {"fit_config": str(fit_path),
                                    "count": 6, "seed": 17},
           "validation.submission_mode": "mixed",
           "validation.v1_pair_count": 4,
           "validation.v2_trial_count": 4})
    fit_config = parse_fit_config(_FIXTURE_FIT, str(fit_path))
    providers = {**scoring_fakes(pair_count=24),
                 "generalizer": FakeGeneralizer()}
    return config, fit_config, prepared["data"], providers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.demo")
    parser.add_argument("--config", help="the scoring config")
    parser.add_argument("--fit-config", help="the fit config")
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--out", default="demo-report.html")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--fixture", action="store_true",
                        help="run against a scratch fake pool")
    parser.add_argument("--fixture-root", default=None,
                        help="scratch directory for --fixture")
    arguments = parser.parse_args(argv)

    providers: dict = {}
    try:
        if arguments.fixture:
            import tempfile

            root = Path(arguments.fixture_root
                        or tempfile.mkdtemp(prefix="demo-fixture-"))
            config, fit_config, data_root, providers = _fixture_setup(root)
        else:
            if not arguments.config or not arguments.fit_config:
                print("--config and --fit-config are required without "
                      "--fixture", file=sys.stderr)
                return 2
            config = load_scoring_config(Path(arguments.config))
            fit_config = load_fit_config(Path(arguments.fit_config))
            data_root = Path(arguments.data_root)
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2

    levels = fit_config.generator.levels
    if not 0 <= arguments.level < len(levels):
        print(f"--level must be in [0, {len(levels) - 1}]", file=sys.stderr)
        return 2

    data = demo_data(config, fit_config, data_root=data_root,
                     providers=providers)
    row = synthetic_set(
        data.context.index, fit_config, data.table,
        data.context.placement, seed=arguments.seed, count=1,
        level_index=arguments.level)[0]
    scored = score_demo(row, data)
    report = render_report(scored, data, level=arguments.level,
                           seed=arguments.seed, top=arguments.top)
    out = Path(arguments.out)
    out.write_text(report, encoding="utf-8")
    print(f"report={out} rank="
          f"{int(np.where(scored.order == scored.source_position)[0][0]) + 1}"
          f"/{len(data.context.index.image_ids)} p={scored.trial.p:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
