"""Integration: the season facts and the image credit (spec BR1 section 6).

GET /api/about names the test season, the photo count, and the
rollover hour, with no session. A revealed target carries a credit
line built from the pool's release manifest, and an open day carries
none.
"""

import dataclasses
import json
from pathlib import Path

from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from pipeline.config import load_scoring_config
from pipeline.context import load_preparation_record
from service import credits, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

DAY = "2026-08-12"


def test_a_commons_address_becomes_its_file_page() -> None:
    credit = credits.commons_credit(
        "https://upload.wikimedia.org/wikipedia/commons/a/ae/"
        "GM_Futurliner_%2832461868%29.jpg")
    assert credit == {
        "source": "Wikimedia Commons",
        "title": "GM Futurliner (32461868)",
        "page": "https://commons.wikimedia.org/wiki/File:"
                "GM_Futurliner_%2832461868%29.jpg",
    }


def test_other_addresses_and_other_text() -> None:
    assert credits.commons_credit("https://example.org/a.jpg") == {
        "source": "example.org", "title": "example.org",
        "page": "https://example.org/a.jpg"}
    for bad in ("fake://abc", "not an address", "", None, 7):
        assert credits.commons_credit(bad) is None


def _write_release(fixture) -> dict[str, str]:
    """A release record and manifest where the fixture's prep record
    points. Answers image id to source address.

    The fixture's release path is relative, thus each caller first
    moves the working directory to its temporary root: the record
    lands there and not in the repository.
    """
    config = load_scoring_config(Path(fixture["scoring_config_path"]))
    prep = load_preparation_record(Path(config.input.preparation_record))
    release_path = Path(prep.pool_release_record_path)
    release = {"corpus_id": "c" * 64, "curation_config_hash": "d" * 64}
    release_path.parent.mkdir(parents=True, exist_ok=True)
    release_path.write_text(json.dumps(release), encoding="utf-8")
    sources = {image_id: (f"https://upload.wikimedia.org/wikipedia/commons/"
                          f"1/12/Photo_{position}.jpg")
               for position, image_id in enumerate(fixture["image_ids"])}
    manifest = credits.manifest_path(fixture["data"], release)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("".join(
        json.dumps({"image_id": image_id, "source_key": source}) + "\n"
        for image_id, source in sources.items()), encoding="utf-8")
    return sources


def test_the_loader_reads_the_manifest_and_names_a_missing_one(
        tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    fixture = build_service_fixture(tmp_path)
    missing = credits.load_credits(tmp_path / "no-such.json", fixture["data"])
    assert missing == {}
    assert "no pool release record" in capsys.readouterr().err
    sources = _write_release(fixture)
    config = load_scoring_config(Path(fixture["scoring_config_path"]))
    prep = load_preparation_record(Path(config.input.preparation_record))
    loaded = credits.load_credits(Path(prep.pool_release_record_path),
                                  fixture["data"])
    assert set(loaded) == set(sources)
    first = fixture["image_ids"][0]
    assert loaded[first]["page"].endswith("File:Photo_0.jpg")


def test_the_season_facts_need_no_session(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"],
                                 closes_at_utc="22:00")
    from service import players

    players.mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK)
    client = TestClient(create_app(config, operator_token="t"))
    assert client.get("/api/me").status_code == 401
    answer = client.get("/api/about")
    assert answer.status_code == 200
    assert answer.json() == {"test_season": True, "photo_count": 40,
                             "closes_at_utc": "22:00"}


def test_a_revealed_target_carries_its_credit(tmp_path,
                                             monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    fixture = build_service_fixture(tmp_path)
    sources = _write_release(fixture)
    config = fixture["service_config"]
    record = open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
                      pick_seed="a" * 32, secret="b" * 64)
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    client = TestClient(create_app(config))
    # The open day: the reveal refuses and holds no credit.
    assert client.get("/api/reveal").status_code == 404
    assert "credit" not in client.get("/api/day").json()
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    credit = client.get("/api/reveal").json()["credit"]
    assert credit["source"] == "Wikimedia Commons"
    assert credit["page"].endswith(
        sources[record.target_id].rsplit("/", 1)[-1])
