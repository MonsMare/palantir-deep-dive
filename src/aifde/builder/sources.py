"""In-memory append-only source and evidence registry."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from threading import RLock
from typing import Any

from .contracts import EvidenceFragment, SourceAsset, SourceSnapshot


_LINE_LOCATOR = re.compile(r"^line:(\d+)(?:-(\d+))?$")
_JSON_ARRAY_LOCATOR = re.compile(r"^\$\.([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]$")


def _copy_model(model: Any) -> Any:
    return type(model).model_validate(deepcopy(model.model_dump(mode="python")))


class SourceRegistry:
    """Register source identities and retain immutable snapshots and slices."""

    def __init__(self) -> None:
        self._assets: dict[str, SourceAsset] = {}
        self._snapshots: dict[str, SourceSnapshot] = {}
        self._snapshot_versions: dict[tuple[str, str], SourceSnapshot] = {}
        self._fragments: dict[str, EvidenceFragment] = {}
        self._lock = RLock()

    def register(self, asset: SourceAsset) -> SourceAsset:
        with self._lock:
            existing = self._assets.get(asset.source_asset_id)
            if existing is not None:
                if existing != asset:
                    raise ValueError("source asset identity is immutable")
                return _copy_model(existing)
            self._assets[asset.source_asset_id] = _copy_model(asset)
            return _copy_model(asset)

    def capture(
        self,
        asset_id: str,
        version: str,
        content: bytes,
        observed_at: Any,
        available_at: Any,
        extraction_version: str,
    ) -> SourceSnapshot:
        with self._lock:
            asset = self._assets.get(asset_id)
            if asset is None:
                raise KeyError(f"unknown source asset: {asset_id}")
            snapshot = SourceSnapshot.capture(
                asset, version, content, observed_at, available_at, extraction_version
            )
            key = (asset_id, snapshot.version)
            existing = self._snapshot_versions.get(key)
            if existing is not None:
                if (
                    existing.content != snapshot.content
                    or existing.observed_at != snapshot.observed_at
                    or existing.available_at != snapshot.available_at
                    or existing.extraction_version != snapshot.extraction_version
                ):
                    raise ValueError("source snapshot version is immutable")
                return _copy_model(existing)
            self._snapshot_versions[key] = snapshot
            self._snapshots[snapshot.snapshot_id] = snapshot
            return _copy_model(snapshot)

    def slice(
        self,
        snapshot_id: str,
        locator: str,
        content: str,
        normalized_content: str | None = None,
        extraction_method: str = "deterministic-text",
        event_time: Any = None,
        confidence: float = 1.0,
    ) -> EvidenceFragment:
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
            if snapshot is None:
                raise KeyError(f"unknown source snapshot: {snapshot_id}")
            replayed_content = self._replay_locator(snapshot, locator)
            if replayed_content != content:
                raise ValueError("evidence content does not match locator")
            fragment = EvidenceFragment.from_snapshot(
                snapshot,
                locator,
                content,
                normalized_content,
                extraction_method,
                event_time,
                confidence,
            )
            existing = self._fragments.get(fragment.evidence_id)
            if existing is not None and existing != fragment:
                raise ValueError("evidence fragment identity is immutable")
            self._fragments[fragment.evidence_id] = fragment
            return _copy_model(fragment)

    @staticmethod
    def _replay_locator(snapshot: SourceSnapshot, locator: str) -> str:
        try:
            source_text = snapshot.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("locator cannot be replayed from invalid UTF-8 content") from exc

        line_match = _LINE_LOCATOR.fullmatch(locator)
        if line_match is not None:
            start = int(line_match.group(1))
            end = int(line_match.group(2) or start)
            if start < 1 or end < start:
                raise ValueError("invalid line locator")
            lines = source_text.splitlines()
            if end > len(lines):
                raise ValueError("line locator is outside source content")
            return "\n".join(lines[start - 1 : end])

        json_match = _JSON_ARRAY_LOCATOR.fullmatch(locator)
        if json_match is not None:
            field_name = json_match.group(1)
            index = int(json_match.group(2))
            try:
                document = json.loads(source_text)
                values = document[field_name]
                value = values[index]
            except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("JSONPath locator cannot be replayed") from exc
            if not isinstance(document, dict) or not isinstance(values, list):
                raise ValueError("JSONPath locator cannot be replayed")
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        raise ValueError("unsupported locator")

    def get_snapshot(self, snapshot_id: str) -> SourceSnapshot:
        with self._lock:
            try:
                return _copy_model(self._snapshots[snapshot_id])
            except KeyError as exc:
                raise KeyError(f"unknown source snapshot: {snapshot_id}") from exc

    def get_fragment(self, fragment_id: str) -> EvidenceFragment:
        with self._lock:
            try:
                return _copy_model(self._fragments[fragment_id])
            except KeyError as exc:
                raise KeyError(f"unknown evidence fragment: {fragment_id}") from exc

    def list_fragments(self, snapshot_id: str | None = None) -> list[EvidenceFragment]:
        with self._lock:
            fragments = self._fragments.values()
            if snapshot_id is not None:
                fragments = (item for item in fragments if item.snapshot_id == snapshot_id)
            return [_copy_model(item) for item in fragments]
