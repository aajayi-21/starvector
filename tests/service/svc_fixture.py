"""The shared server test fixture: pool, tables, configs, fakes.

Builds the hand-built pool artifacts, stores image bytes for the reveal
source, writes a mixed-mode scoring config and a server config to
disk, and prebuilds the commonness tables warm with fake providers -
thus the day commands run offline against a warm lineage, as the
live server does.
"""

import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_tables)
from pipeline.config import (element_config, intake_gates, outline_config,
                             parse_scoring_config, placement_config)
from pipeline.context import load_pool_index
from pipeline.score import Encoders
from pool.artifacts import image_path, write_bytes_atomic
from service.config import ServiceConfig
from validation import harness

FIXED_CLOCK = "2026-08-12T00:00:00+00:00"


def _png_bytes(seed: int) -> bytes:
    buffer = BytesIO()
    color = ((seed * 37) % 256, (seed * 91) % 256, 40)
    Image.new("RGB", (8, 8), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def build_service_fixture(root: Path, count: int = 40,
                          prep_overrides: dict | None = None) -> dict:
    """One warm offline server world below root. Output keys:
    service_config, providers, store, data, scoring_config_path,
    image_ids. prep_overrides reaches the preparation config - the
    spec C1 tests build an rgb world with
    {"linedraw.stroke_color": "rgb"}.
    """
    from conftest import (build_direct_prepared_pool, scoring_config_dict,
                          scoring_fakes)

    prepared = build_direct_prepared_pool(root / "pool", count,
                                          overrides=prep_overrides)
    data = prepared["data"]
    for position, image_id in enumerate(prepared["image_ids"]):
        write_bytes_atomic(image_path(data, image_id), _png_bytes(position))

    document = scoring_config_dict(
        prepared["prep_record_path"],
        **{"validation.submission_mode": "mixed",
           "commonness.dataset.fake_pair_count": 24,
           "commonness.background_count": 6,
           "validation.tag": "dev-service-test"})
    scoring_config_path = root / "scoring-config.json"
    scoring_config_path.write_text(json.dumps(document, indent=2) + "\n",
                                   encoding="utf-8")
    config = parse_scoring_config(document, str(scoring_config_path))
    providers = scoring_fakes(pair_count=24)

    loaded = load_pool_index(prepared["prep_record_path"], data,
                             dev_only=True)
    slot_hashes = harness.scoring_provider_hashes(config, providers)
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], slot_hashes["sketch_pairs"], None)
    encoders = Encoders(sketch=providers["sketch_encoder"],
                        text=providers["text_encoder"])

    def background():
        return harness.full_background(
            config, providers["sketch_pairs"], "mixed", loaded.index,
            placement_config(config), data)

    ensure_commonness_tables(
        data_root=data, index=loaded.index,
        commonness_hash=commonness_hash, background=background,
        gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement_config(config), encoders=encoders,
        submission_mode="mixed", clock=lambda: FIXED_CLOCK)

    service_config = ServiceConfig(
        player="ade", scoring_config=str(scoring_config_path),
        data_root=str(data), store_root=str(root / "store"), port=8399)
    return {
        "service_config": service_config,
        "providers": providers,
        "store": root / "store",
        "data": data,
        "scoring_config_path": str(scoring_config_path),
        "image_ids": prepared["image_ids"],
    }


def colored_wire_record() -> dict:
    """The mixed record with a color on each stroke (spec C1)."""
    record = mixed_wire_record()
    record["canvas_strokes"][0]["color"] = "#1a73e8"
    record["canvas_strokes"][1]["color"] = "#c5221f"
    return record


def mixed_wire_record() -> dict:
    """One complete mixed submission: impressions, strokes, a
    group, a relation."""
    return {
        "impressions": ["tall vertical structure", "cold and exposed"],
        "canvas_strokes": [
            {"points": [[0.1, 0.4], [0.3, 0.4], [0.3, 0.6], [0.1, 0.6],
                        [0.1, 0.4]], "group_id": "g1"},
            {"points": [[0.6, 0.4], [0.9, 0.4], [0.9, 0.6], [0.6, 0.6],
                        [0.6, 0.4]], "group_id": "g2"},
        ],
        "groups": [{"id": "g1", "label": "tower"},
                   {"id": "g2", "label": "sea"}],
        "relations": [{"relation": "left-of", "of": ["g1", "g2"]}],
        "pasted_text": None,
    }
