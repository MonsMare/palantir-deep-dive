"""Load and inspect SHACL shape graphs without mutating caller input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aifde.ontology.rdf import (
    _iter_triples,
    _parse_rdf_text,
    _predicate_local_name,
    _term_value,
    graph_hash,
)


SHACL_NS = "http://www.w3.org/ns/shacl#"
SHACL_NODE_SHAPE = f"{SHACL_NS}NodeShape"
SHACL_PROPERTY = f"{SHACL_NS}property"
SHACL_TARGET_CLASS = f"{SHACL_NS}targetClass"
SHACL_PATH = f"{SHACL_NS}path"
SHACL_MIN_COUNT = f"{SHACL_NS}minCount"
SHACL_MESSAGE = f"{SHACL_NS}message"
SHACL_SEVERITY = f"{SHACL_NS}severity"
SHACL_VIOLATION = f"{SHACL_NS}Violation"
SHACL_WARNING = f"{SHACL_NS}Warning"


class ShapeParseError(ValueError):
    """Raised when shape text cannot be parsed or is structurally invalid."""


@dataclass(frozen=True, slots=True)
class ShapeConstraint:
    """The small, auditable SHACL property subset used by local fallback mode."""

    shape_id: str
    target_class: str
    path: str
    min_count: int = 0
    message: str = "SHACL property constraint failed."
    severity: str = SHACL_VIOLATION

    def __post_init__(self) -> None:
        for name in ("shape_id", "target_class", "path", "message", "severity"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.min_count) is not int or self.min_count < 0:
            raise ValueError("min_count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ShapeDocument:
    """Parsed SHACL graph and stable graph hash."""

    graph: Any
    shapes_hash: str
    constraints: tuple[ShapeConstraint, ...]

    def __post_init__(self) -> None:
        if type(self.shapes_hash) is not str or len(self.shapes_hash) != 64:
            raise ValueError("shapes_hash must be a SHA-256 hex digest")
        if type(self.constraints) is not tuple:
            raise TypeError("constraints must be a tuple")


def _uri(term: Any) -> str:
    return _term_value(term)


def _objects(graph: Any, subject: Any, predicate: str) -> list[Any]:
    return [obj for subj, pred, obj in _iter_triples(graph) if subj == subject and _uri(pred) == predicate]


def _first(graph: Any, subject: Any, predicate: str, *, required: bool = False) -> Any | None:
    values = _objects(graph, subject, predicate)
    if not values:
        if required:
            raise ShapeParseError(
                f"shape { _uri(subject)!r } is missing required predicate {predicate!r}"
            )
        return None
    return values[0]


def _as_int(value: Any, *, shape_id: str, predicate: str) -> int:
    text = _term_value(value)
    try:
        result = int(text)
    except (TypeError, ValueError) as exc:
        raise ShapeParseError(
            f"shape {shape_id!r} predicate {predicate!r} must be an integer"
        ) from exc
    if result < 0:
        raise ShapeParseError(f"shape {shape_id!r} minCount must not be negative")
    return result


def _build_constraints(graph: Any) -> tuple[ShapeConstraint, ...]:
    constraints: list[ShapeConstraint] = []
    shape_subjects = {
        subject
        for subject, predicate, obj in _iter_triples(graph)
        if _uri(predicate) == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        and _uri(obj) == SHACL_NODE_SHAPE
    }
    for shape in sorted(shape_subjects, key=lambda item: _uri(item)):
        shape_id = _uri(shape)
        target_class_term = _first(graph, shape, SHACL_TARGET_CLASS, required=True)
        target_class = _uri(target_class_term)
        for property_shape in _objects(graph, shape, SHACL_PROPERTY):
            path_term = _first(graph, property_shape, SHACL_PATH, required=True)
            path = _uri(path_term)
            min_count_term = _first(graph, property_shape, SHACL_MIN_COUNT)
            min_count = 0 if min_count_term is None else _as_int(
                min_count_term, shape_id=shape_id, predicate=SHACL_MIN_COUNT
            )
            message_term = _first(graph, property_shape, SHACL_MESSAGE)
            severity_term = _first(graph, property_shape, SHACL_SEVERITY)
            constraints.append(
                ShapeConstraint(
                    shape_id=shape_id,
                    target_class=target_class,
                    path=path,
                    min_count=min_count,
                    message=(
                        _term_value(message_term)
                        if message_term is not None
                        else f"{_local_name(path)} must contain at least {min_count} value(s)."
                    ),
                    severity=(
                        _uri(severity_term)
                        if severity_term is not None
                        else SHACL_VIOLATION
                    ),
                )
            )
    return tuple(constraints)


def _local_name(value: str) -> str:
    return value.rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]


class ShapeLoader:
    """Parse SHACL Turtle and expose deterministic fallback constraints."""

    @classmethod
    def load(cls, text: str) -> ShapeDocument:
        if type(text) is not str:
            raise TypeError("shapes text must be a string")
        if not text.strip():
            raise ValueError("shapes text must not be empty")
        try:
            graph = _parse_rdf_text(text)
            constraints = _build_constraints(graph)
        except ShapeParseError:
            raise
        except Exception as exc:
            raise ShapeParseError(f"invalid SHACL shape document: {exc}") from exc
        if not constraints:
            raise ShapeParseError("SHACL shape document contains no supported NodeShape property constraints")
        return ShapeDocument(
            graph=graph,
            shapes_hash=graph_hash(graph),
            constraints=constraints,
        )


def load_shapes(text: str) -> ShapeDocument:
    """Functional alias used by callers that do not need the loader class."""

    return ShapeLoader.load(text)


__all__ = [
    "ShapeConstraint",
    "ShapeDocument",
    "ShapeLoader",
    "ShapeParseError",
    "load_shapes",
]
