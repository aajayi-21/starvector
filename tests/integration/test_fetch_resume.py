"""The s02 fetch journal: a stopped fetch continues, and gives equal bytes."""

import json
from pathlib import Path

import pytest
from conftest import (
    FIXED_CLOCK,
    assert_trees_identical,
    find_stage_dir,
    make_config,
    make_fake_corpus,
)

from pool.artifacts import ManifestError, append_journal, read_journal
from pool.curation import manifest as mf
from pool.curation.run import run_curation


class CountingCorpus:
    """A fake corpus that counts fetch batches and can stop at one.

    Each attribute the pipeline reads goes to the fake corpus, thus the
    corpus hash and the artifact tree are the ones of a plain run.
    """

    def __init__(self, stop_at: int | None = None) -> None:
        self._corpus = make_fake_corpus()
        self._stop_at = stop_at
        self.batches = 0

    def __getattr__(self, name: str):
        return getattr(self._corpus, name)

    def materialize_many(self, records):
        if self._stop_at is not None and self.batches == self._stop_at:
            raise RuntimeError("the fetch stopped")
        self.batches += 1
        return self._corpus.materialize_many(records)


def config():
    return make_config(**{"corpus.materialization.fetch_batch_size": 2})


def run(corpus: CountingCorpus, root: Path) -> None:
    run_curation(
        config(),
        config_path=Path("test-config.json"),
        data_root=root / "data",
        releases_root=root / "releases",
        code_version="test",
        through="s02",
        corpus=corpus,
        clock=lambda: FIXED_CLOCK,
    )


def stopped_run(root: Path, stop_at: int = 3) -> Path:
    """Run s02 to a stop after stop_at batches and give the journal path."""
    with pytest.raises(RuntimeError, match="the fetch stopped"):
        run(CountingCorpus(stop_at=stop_at), root)
    journal = next((root / "data").glob("curation/*/*/s02-materialize")) / mf.FETCH_JOURNAL
    assert len(read_journal(journal)) == stop_at
    assert not (journal.parent / "meta.json").exists()
    return journal


def reference_run(root: Path) -> int:
    corpus = CountingCorpus()
    run(corpus, root)
    return corpus.batches


def test_a_stopped_fetch_continues_from_its_journal(tmp_path: Path) -> None:
    total = reference_run(tmp_path / "reference")
    assert total > 3
    journal = stopped_run(tmp_path / "run")

    second = CountingCorpus()
    run(second, tmp_path / "run")
    # The three recorded batches are not fetched a second time.
    assert second.batches == total - 3
    assert not journal.exists()
    assert_trees_identical(tmp_path / "run" / "data", tmp_path / "reference" / "data")


def test_a_complete_stage_holds_no_journal(tmp_path: Path) -> None:
    reference_run(tmp_path)
    stage = find_stage_dir(tmp_path / "data", "s02-materialize")
    assert sorted(path.name for path in stage.iterdir()) == [
        "manifest.jsonl", "meta.json", "records.jsonl", "rejections.jsonl",
        "timings.json"]


def test_a_part_of_a_row_at_the_end_is_not_a_row(tmp_path: Path) -> None:
    total = reference_run(tmp_path / "reference")
    journal = stopped_run(tmp_path / "run")
    with journal.open("ab") as handle:
        handle.write(b'{"batch":3,"keys":["wi')
    second = CountingCorpus()
    run(second, tmp_path / "run")
    assert second.batches == total - 3
    assert_trees_identical(tmp_path / "run" / "data", tmp_path / "reference" / "data")


def rewrite(journal: Path, change) -> None:
    rows = read_journal(journal)
    change(rows)
    journal.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_a_journal_of_a_different_sequence_is_refused(tmp_path: Path) -> None:
    journal = stopped_run(tmp_path)

    def swap(rows: list[dict]) -> None:
        rows[1]["keys"] = list(reversed(rows[1]["keys"]))

    rewrite(journal, swap)
    with pytest.raises(ManifestError, match="different fetch sequence"):
        run(CountingCorpus(), tmp_path)


def test_a_byte_count_that_does_not_agree_is_refused(tmp_path: Path) -> None:
    journal = stopped_run(tmp_path)

    def grow(rows: list[dict]) -> None:
        image = next(outcome for row in rows for outcome in row["outcomes"]
                     if "image_id" in outcome)
        image["byte_count"] += 1

    rewrite(journal, grow)
    with pytest.raises(ManifestError, match="bytes in the store"):
        run(CountingCorpus(), tmp_path)


def test_a_damaged_complete_row_raises(tmp_path: Path) -> None:
    journal = stopped_run(tmp_path)
    journal.write_bytes(b"not json\n" + journal.read_bytes())
    with pytest.raises(ManifestError, match="bad JSON row"):
        run(CountingCorpus(), tmp_path)


def test_the_journal_helpers(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "journal.jsonl"
    assert read_journal(path) == []
    append_journal(path, {"batch": 0})
    append_journal(path, {"batch": 1})
    with path.open("ab") as handle:
        handle.write(b'{"batch"')
    assert read_journal(path) == [{"batch": 0}, {"batch": 1}]
    # The part of a row is out of the file, thus an append starts a line.
    assert path.read_bytes().endswith(b'{"batch":1}\n')
    append_journal(path, {"batch": 2})
    assert [row["batch"] for row in read_journal(path)] == [0, 1, 2]
