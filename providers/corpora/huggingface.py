"""Hugging Face source corpus adapter.

Spec: docs/specs/pool-curation.md section 7. The adapter resolves the
pinned revision, enumerates the configured metadata columns with a
streaming read, maps each row to a SourceRecord, and delegates
materialization to the Wikimedia fetcher. The datasets and
huggingface_hub imports occur in method bodies, thus the offline test
suite can import this module without them.
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, NamedTuple

from core.canonical import JsonValue, canonical_json, sha256_hex
from providers.corpora.transport import ByteMeter, metered_client_factory
from providers.corpora.wikimedia import WikimediaFetchConfig, WikimediaFetcher
from providers.protocols import (
    CorpusIdentity,
    MaterializedImage,
    MaterializeFailure,
    SourceRecord,
)


class HuggingFaceColumns(NamedTuple):
    """Column names that map dataset rows to SourceRecord fields."""

    source_key: str
    claimed_width: str | None
    claimed_height: str | None
    captions: tuple[str, ...]
    attribution: tuple[str, ...]


class HuggingFaceCorpusConfig(NamedTuple):
    """Frozen parameters for one Hugging Face corpus (spec section 7)."""

    repo_id: str
    revision: str            # branch, tag, or commit - resolved to a commit
    config_name: str | None
    split: str
    columns: HuggingFaceColumns
    license_note: str
    fetch: WikimediaFetchConfig


def _claimed_dimension(row: Mapping[str, Any], column: str | None) -> int | None:
    """The claimed dimension as an integer, or None when not given."""
    if column is None:
        return None
    value = row.get(column)
    if value is None:
        return None
    return int(value)


def row_to_source_record(
    row: Mapping[str, Any],
    columns: HuggingFaceColumns,
    license_note: str,
) -> SourceRecord:
    """Map one dataset row to a SourceRecord.

    A row without a non-empty source key raises ValueError - that is a
    corpus access defect, not a record-level rejection. Claimed
    dimensions become integers or None. Captions keep the non-empty
    configured caption columns. Attribution keeps the configured
    columns that hold non-empty strings, plus the license note.
    """
    source_key = row.get(columns.source_key)
    if not isinstance(source_key, str) or not source_key:
        raise ValueError(
            f"row has no usable source key in column {columns.source_key!r}"
        )
    captions: list[str] = []
    for name in columns.captions:
        value = row.get(name)
        if isinstance(value, str) and value:
            captions.append(value)
    attribution: dict[str, str] = {}
    for name in columns.attribution:
        value = row.get(name)
        if isinstance(value, str) and value:
            attribution[name] = value
    attribution["license"] = license_note
    return SourceRecord(
        source_key=source_key,
        claimed_width=_claimed_dimension(row, columns.claimed_width),
        claimed_height=_claimed_dimension(row, columns.claimed_height),
        captions=tuple(captions),
        attribution=attribution,
    )


class HuggingFaceCorpus:
    """SourceCorpus adapter for a pinned Hugging Face dataset revision.

    The first identity access resolves the configured revision to a
    commit hash and routes the hub HTTP traffic through a metered
    client, thus the scan bytes count against the budget (U1).
    """

    def __init__(
        self, config: HuggingFaceCorpusConfig, meter: ByteMeter | None = None
    ) -> None:
        self._config = config
        self._meter = meter if meter is not None else ByteMeter()
        self._identity: CorpusIdentity | None = None
        self._client_factory_installed = False
        self._fetcher = WikimediaFetcher(config.fetch, self._meter)

    @property
    def identity(self) -> CorpusIdentity:
        """The corpus identity, with the revision resolved to a commit hash."""
        if self._identity is None:
            self._install_metered_client()
            self._identity = CorpusIdentity(
                provider="huggingface",
                repo_id=self._config.repo_id,
                revision=self._resolve_revision(),
                config_name=self._config.config_name,
                split=self._config.split,
            )
        return self._identity

    @property
    def config_hash(self) -> str:
        """The hash that keys artifacts derived from this corpus (R12).

        The hashed document holds the resolved identity, the column
        mapping, the license note, and the fetch parameters - the
        values that change the bytes this adapter can supply.
        """
        identity = self.identity
        columns = self._config.columns
        fetch = self._config.fetch
        document: dict[str, JsonValue] = {
            "provider": identity.provider,
            "repo_id": identity.repo_id,
            "revision": identity.revision,
            "config_name": identity.config_name,
            "split": identity.split,
            "columns": {
                "source_key": columns.source_key,
                "claimed_width": columns.claimed_width,
                "claimed_height": columns.claimed_height,
                "captions": list(columns.captions),
                "attribution": list(columns.attribution),
            },
            "license_note": self._config.license_note,
            "fetch": {
                "thumbnail_width": fetch.thumbnail_width,
                "user_agent": fetch.user_agent,
                "max_concurrency": fetch.max_concurrency,
                "timeout_seconds": fetch.timeout_seconds,
                "retry_limit": fetch.retry_limit,
                "max_fetch_bytes": fetch.max_fetch_bytes,
            },
        }
        return sha256_hex(canonical_json(document))

    @property
    def bytes_retrieved(self) -> int:
        """Monotone count of transport bytes this adapter retrieved (U1)."""
        return self._meter.total

    def iter_records(self) -> Iterator[SourceRecord]:
        """Enumerate the corpus as SourceRecord values.

        The streaming read touches only the configured columns, thus
        shipped image bytes do not move during the metadata scan (U1).
        """
        import datasets

        identity = self.identity
        dataset = datasets.load_dataset(
            identity.repo_id,
            name=identity.config_name,
            split=identity.split,
            revision=identity.revision,
            streaming=True,
            columns=self._needed_columns(),
        )
        for row in dataset:
            yield row_to_source_record(
                row, self._config.columns, self._config.license_note
            )

    def materialize_many(
        self, records: Sequence[SourceRecord]
    ) -> list[MaterializedImage | MaterializeFailure]:
        """Fetch image bytes for each record. The output is index-aligned."""
        return self._fetcher.fetch_many(records)

    def _install_metered_client(self) -> None:
        """Install the metered hub client factory, one time for this adapter."""
        if self._client_factory_installed:
            return
        import huggingface_hub
        from huggingface_hub.utils._http import hf_request_event_hook

        # These keyword arguments copy the default hub client factory,
        # thus only the transport changes.
        factory = metered_client_factory(
            self._meter,
            event_hooks={"request": [hf_request_event_hook]},
            follow_redirects=True,
            timeout=None,
        )
        huggingface_hub.set_client_factory(factory)
        huggingface_hub.close_session()
        self._client_factory_installed = True

    def _resolve_revision(self) -> str:
        """Resolve the configured revision to a commit hash through the hub."""
        from huggingface_hub import HfApi

        info = HfApi().repo_info(
            self._config.repo_id,
            repo_type="dataset",
            revision=self._config.revision,
        )
        sha = info.sha
        if not sha:
            raise RuntimeError(
                f"cannot resolve revision {self._config.revision!r} of "
                f"{self._config.repo_id!r} to a commit hash"
            )
        return sha

    def _needed_columns(self) -> list[str]:
        """The unique configured column names, for parquet column pruning."""
        columns = self._config.columns
        names = [columns.source_key]
        for name in (columns.claimed_width, columns.claimed_height):
            if name is not None:
                names.append(name)
        names.extend(columns.captions)
        names.extend(columns.attribution)
        seen: set[str] = set()
        unique: list[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        return unique
