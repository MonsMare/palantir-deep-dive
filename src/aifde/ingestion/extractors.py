"""Deterministic evidence extraction with replayable locators."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from aifde.builder.contracts import EvidenceFragment, SourceSnapshot


class ExtractionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    extractor_version: str
    fragments: tuple[EvidenceFragment, ...]
    warnings: tuple[str, ...] = ()
    passed: bool


class EvidenceExtractor:
    """Extract source-native fragments without asserting business meaning."""

    extractor_version = "evidence-extractor-v1"

    def extract(self, snapshot: SourceSnapshot) -> ExtractionReport:
        if not isinstance(snapshot, SourceSnapshot):
            raise TypeError("snapshot must be a SourceSnapshot")
        try:
            text = snapshot.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("source content must be UTF-8 for deterministic extraction") from exc
        source_type = snapshot.source_type or _infer_from_content(text)
        if source_type == "json":
            fragments = self._extract_json(snapshot, text)
        elif source_type == "csv":
            fragments = self._extract_rows(snapshot, text, locator_prefix="csv:row")
        elif source_type in {"markdown", "text"}:
            fragments = self._extract_lines(snapshot, text)
        else:
            raise ValueError(f"unsupported source type for extraction: {source_type}")
        warnings: tuple[str, ...] = () if fragments else ("source produced no non-empty evidence fragments",)
        return ExtractionReport(
            snapshot_id=snapshot.snapshot_id,
            extractor_version=self.extractor_version,
            fragments=tuple(fragments),
            warnings=warnings,
            passed=bool(fragments),
        )

    def _extract_json(self, snapshot: SourceSnapshot, text: str) -> list[EvidenceFragment]:
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON source content") from exc
        fragments: list[EvidenceFragment] = []
        if isinstance(document, dict):
            for key in sorted(document):
                values = document[key]
                if isinstance(values, list):
                    for index, value in enumerate(values):
                        content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        fragments.append(
                            EvidenceFragment.from_snapshot(
                                snapshot,
                                f"$.{key}[{index}]",
                                content,
                                normalized_content=content,
                                extraction_method="json-array-item",
                                confidence=1.0,
                            )
                        )
        if not fragments:
            lines = text.splitlines()
            if lines and "".join(lines).strip():
                fragments.append(
                    EvidenceFragment.from_snapshot(
                        snapshot,
                        f"line:1-{len(lines)}" if len(lines) > 1 else "line:1",
                        "\n".join(lines),
                        normalized_content="\n".join(lines).strip(),
                        extraction_method="json-document",
                        confidence=1.0,
                    )
                )
        return fragments

    def _extract_rows(
        self, snapshot: SourceSnapshot, text: str, *, locator_prefix: str
    ) -> list[EvidenceFragment]:
        fragments: list[EvidenceFragment] = []
        for index, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            fragments.append(
                EvidenceFragment.from_snapshot(
                    snapshot,
                    f"{locator_prefix}:{index}",
                    line,
                    normalized_content=line.strip(),
                    extraction_method="csv-row",
                    confidence=1.0,
                )
            )
        return fragments

    def _extract_lines(self, snapshot: SourceSnapshot, text: str) -> list[EvidenceFragment]:
        fragments: list[EvidenceFragment] = []
        for index, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            fragments.append(
                EvidenceFragment.from_snapshot(
                    snapshot,
                    f"line:{index}",
                    line,
                    normalized_content=line.strip(),
                    extraction_method="line-text",
                    confidence=1.0,
                )
            )
        return fragments


def _infer_from_content(text: str) -> str:
    try:
        json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        return "json"
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first.startswith(("#", "-", "*")):
        return "markdown"
    if "," in first:
        return "csv"
    return "text"


__all__ = ["EvidenceExtractor", "ExtractionReport"]
