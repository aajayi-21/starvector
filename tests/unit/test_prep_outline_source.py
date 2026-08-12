"""Unit: the P2c outline.source field and the canonical photograph render.

Spec docs/specs/photo-embedding-bridge.md sections 4 and 9 (D2), and
acceptance criterion 1: the missing field keeps the released hash
byte-for-byte, the photo value moves it, and the render rule is one
deterministic function.
"""

from io import BytesIO

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from conftest import make_prep_config, prep_config_dict
from pool.preparation.config import (ConfigError, parse_preparation_config,
                                     preparation_config_hash)
from pool.preparation.run import provider_config_hashes
from pool.preparation.stages.outline import (photo_canonical,
                                             photo_source_token)

RECORD = "pool-releases/record.json"


def _hash_of(config) -> str:
    return preparation_config_hash(config, provider_config_hashes(config))


def test_a_missing_source_field_parses_to_linedraw() -> None:
    config = make_prep_config(RECORD)
    assert config.outline.source == "linedraw"


def test_a_null_source_field_parses_to_linedraw() -> None:
    config = make_prep_config(RECORD, **{"outline.source": None})
    assert config.outline.source == "linedraw"


def test_an_unknown_source_value_raises() -> None:
    with pytest.raises(ConfigError, match="outline.source"):
        make_prep_config(RECORD, **{"outline.source": "sketch"})


def test_the_missing_field_hash_stays_byte_for_byte() -> None:
    # P2c R5: missing, null, and the spelled-out default give one hash.
    absent = make_prep_config(RECORD)
    spelled = make_prep_config(RECORD, **{"outline.source": "linedraw"})
    assert _hash_of(absent) == _hash_of(spelled)


def test_the_photo_source_moves_the_preparation_hash() -> None:
    control = make_prep_config(RECORD)
    photo = make_prep_config(RECORD, **{"outline.source": "photo"})
    assert photo.outline.source == "photo"
    assert _hash_of(control) != _hash_of(photo)


def test_the_photo_document_round_trips() -> None:
    from pool.preparation.config import config_to_json_value

    photo = make_prep_config(RECORD, **{"outline.source": "photo"})
    document = config_to_json_value(photo)
    assert document["outline"]["source"] == "photo"
    assert parse_preparation_config(document, "round-trip") == photo


def test_the_linedraw_document_omits_the_field() -> None:
    from pool.preparation.config import config_to_json_value

    control = make_prep_config(RECORD, **{"outline.source": "linedraw"})
    assert "source" not in config_to_json_value(control)["outline"]


def test_a_text_encoder_instruction_raises() -> None:
    with pytest.raises(ConfigError, match="text_encoder"):
        make_prep_config(
            RECORD, **{"providers.text_encoder.instruction_template": "x"})


def test_a_line_drawer_instruction_raises() -> None:
    with pytest.raises(ConfigError, match="line_drawer"):
        make_prep_config(
            RECORD, **{"providers.line_drawer.instruction_template": "x"})


def test_an_image_encoder_instruction_parses_and_moves_the_hash() -> None:
    plain = make_prep_config(RECORD)
    instructed = make_prep_config(
        RECORD, **{"providers.image_encoder.instruction_template": "sketch it"})
    assert instructed.providers.image_encoder.instruction_template == "sketch it"
    assert _hash_of(plain) != _hash_of(instructed)


def test_the_document_without_new_fields_is_unchanged() -> None:
    # The full R5 statement: the prep-002-shape document has no new
    # field after a parse and serialize cycle.
    from pool.preparation.config import config_to_json_value

    document = prep_config_dict(RECORD)
    round_tripped = config_to_json_value(
        parse_preparation_config(document, "r5"))
    assert round_tripped == document


def _photo_png(width: int, height: int, chunks: dict[str, str]) -> bytes:
    info = PngInfo()
    for key, value in sorted(chunks.items()):
        info.add_text(key, value)
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(10, 200, 30)).save(
        buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def test_photo_canonical_scales_the_long_side() -> None:
    rendered = photo_canonical(_photo_png(100, 50, {}), 64)
    with Image.open(BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert image.size == (64, 32)


def test_photo_canonical_scales_a_small_image_up() -> None:
    rendered = photo_canonical(_photo_png(16, 8, {}), 64)
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == (64, 32)


def test_photo_canonical_keeps_text_chunks() -> None:
    rendered = photo_canonical(
        _photo_png(100, 50, {"embed_family": "fam-a", "embed_jitter": "dup"}),
        64)
    with Image.open(BytesIO(rendered)) as image:
        assert image.text["embed_family"] == "fam-a"
        assert image.text["embed_jitter"] == "dup"


def test_photo_canonical_is_deterministic() -> None:
    source = _photo_png(100, 50, {"embed_family": "fam-a"})
    assert photo_canonical(source, 64) == photo_canonical(source, 64)


def test_photo_canonical_reads_a_jpeg() -> None:
    buffer = BytesIO()
    Image.new("RGB", (80, 40), color=(1, 2, 3)).save(buffer, format="JPEG")
    rendered = photo_canonical(buffer.getvalue(), 64)
    with Image.open(BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.size == (64, 32)


def test_photo_canonical_rejects_a_bad_canvas() -> None:
    with pytest.raises(ValueError, match="not positive"):
        photo_canonical(_photo_png(10, 10, {}), 0)


def test_the_photo_source_token_covers_the_canvas() -> None:
    assert photo_source_token(512) == "photo-canonical-v1:512"
    assert photo_source_token(512) != photo_source_token(768)


def test_the_grayscale_token_keys_its_own_tree() -> None:
    assert photo_source_token(512, grayscale=True) \
        == "photo-canonical-v1:512:grayscale"


def test_a_missing_photo_render_parses_to_color() -> None:
    config = make_prep_config(RECORD, **{"outline.source": "photo"})
    assert config.outline.photo_render == "color"


def test_a_grayscale_render_needs_the_photo_source() -> None:
    with pytest.raises(ConfigError, match="photo_render"):
        make_prep_config(RECORD, **{"outline.photo_render": "grayscale"})


def test_the_grayscale_render_moves_the_preparation_hash() -> None:
    color = make_prep_config(RECORD, **{"outline.source": "photo"})
    gray = make_prep_config(
        RECORD,
        **{"outline.source": "photo", "outline.photo_render": "grayscale"})
    assert gray.outline.photo_render == "grayscale"
    assert _hash_of(color) != _hash_of(gray)


def test_the_color_render_document_omits_the_field() -> None:
    from pool.preparation.config import config_to_json_value

    spelled = make_prep_config(
        RECORD, **{"outline.source": "photo", "outline.photo_render": "color"})
    assert "photo_render" not in config_to_json_value(spelled)["outline"]
    assert _hash_of(spelled) == _hash_of(
        make_prep_config(RECORD, **{"outline.source": "photo"}))


def test_the_grayscale_document_round_trips() -> None:
    from pool.preparation.config import config_to_json_value

    gray = make_prep_config(
        RECORD,
        **{"outline.source": "photo", "outline.photo_render": "grayscale"})
    document = config_to_json_value(gray)
    assert document["outline"]["photo_render"] == "grayscale"
    assert parse_preparation_config(document, "round-trip") == gray


def test_photo_canonical_grayscale_gives_an_l_mode_png() -> None:
    source = _photo_png(100, 50, {"embed_family": "fam-a"})
    rendered = photo_canonical(source, 64, grayscale=True)
    with Image.open(BytesIO(rendered)) as image:
        assert image.format == "PNG"
        assert image.mode == "L"
        assert image.size == (64, 32)
        assert image.text["embed_family"] == "fam-a"
    assert rendered != photo_canonical(source, 64)
