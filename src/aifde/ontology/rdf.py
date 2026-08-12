"""RDF document loading, deterministic provenance, and safe graph copies.

The platform normally uses RDFLib.  A tiny, deterministic Turtle subset parser
is kept as a local fallback because the core package deliberately does not
require optional RDF dependencies at import time.  The fallback is sufficient
for the built-in software-delivery shapes and fails closed for malformed input.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Iterator

try:  # pragma: no cover - exercised when the optional dependency is installed
    from rdflib import BNode, Graph, Literal, URIRef
    from rdflib.compare import to_canonical_graph
except ImportError:  # pragma: no cover - the checked-in test environment path
    BNode = Graph = Literal = URIRef = None  # type: ignore[assignment]
    to_canonical_graph = None  # type: ignore[assignment]


RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
SHACL_NS = "http://www.w3.org/ns/shacl#"
DEFAULT_ONTOLOGY_VERSION = "1.0.0"
_SUPPORTED_FORMATS = {
    "turtle": "turtle",
    "ttl": "turtle",
    "nt": "nt",
    "ntriples": "nt",
}


class RDFParseError(ValueError):
    """Raised when an ontology or shape document is not valid RDF text."""


@dataclass(frozen=True, slots=True)
class _FallbackURI:
    value: str


@dataclass(frozen=True, slots=True)
class _FallbackBNode:
    value: str


@dataclass(frozen=True, slots=True)
class _FallbackLiteral:
    value: str
    datatype: str | None = None
    language: str | None = None


class _FallbackGraph:
    """Small read-oriented graph with the subset needed by local validation."""

    __slots__ = ("_triples",)

    def __init__(self, triples: Iterable[tuple[Any, Any, Any]] = ()) -> None:
        self._triples = tuple(sorted(set(triples), key=_triple_key))

    def __iter__(self) -> Iterator[tuple[Any, Any, Any]]:
        return iter(self._triples)

    def __len__(self) -> int:
        return len(self._triples)

    def serialize(self, *, format: str = "turtle") -> str:
        normalized = _normalize_format(format)
        if normalized not in {"turtle", "nt"}:
            raise ValueError(
                f"fallback RDF serializer does not support format {format!r}; "
                "install rdflib for additional formats"
            )
        return "".join(
            f"{_term_n3(subject)} {_term_n3(predicate)} {_term_n3(obj)} .\n"
            for subject, predicate, obj in self._triples
        )


def _is_rdflib_graph(value: Any) -> bool:
    return Graph is not None and isinstance(value, Graph)


def _require_text(value: Any, name: str) -> str:
    if type(value) is not str:  # deliberately reject bytes and string-like objects
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value


def _normalize_format(value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("format must be a non-empty string")
    key = value.strip().lower()
    try:
        return _SUPPORTED_FORMATS[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_SUPPORTED_FORMATS))
        raise ValueError(f"unsupported RDF format {value!r}; use one of {supported}") from exc


def _parse_rdf_text(text: str) -> Any:
    _require_text(text, "text")
    if Graph is not None:
        graph = Graph()
        try:
            graph.parse(data=text, format="turtle")
        except Exception as exc:
            raise RDFParseError(f"invalid Turtle RDF: {exc}") from exc
        return graph
    return _parse_fallback_turtle(text)


def _serialize_graph(graph: Any, format: str = "turtle") -> str:
    if type(format) is not str or not format.strip():
        raise ValueError("format must be a non-empty string")
    normalized = format.strip().lower()
    if not _is_rdflib_graph(graph):
        normalized = _normalize_format(normalized)
    try:
        serialized = graph.serialize(format=normalized)
    except Exception as exc:
        raise ValueError(f"could not serialize RDF graph as {normalized}: {exc}") from exc
    if isinstance(serialized, bytes):
        return serialized.decode("utf-8")
    if not isinstance(serialized, str):
        return str(serialized)
    return serialized


def _clone_graph(graph: Any) -> Any:
    """Copy a graph before handing it to a validator that may mutate it."""

    if _is_rdflib_graph(graph):
        cloned = Graph()
        for triple in graph:
            cloned.add(triple)
        return cloned
    if isinstance(graph, _FallbackGraph):
        return _FallbackGraph(graph)
    raise TypeError("graph must be an RDFLib Graph or local fallback graph")


def _iter_triples(graph: Any) -> Iterator[tuple[Any, Any, Any]]:
    if not (_is_rdflib_graph(graph) or isinstance(graph, _FallbackGraph)):
        raise TypeError("graph must be an RDFLib Graph or local fallback graph")
    yield from graph


def _term_key(term: Any) -> str:
    if isinstance(term, _FallbackURI):
        return f"U:{term.value}"
    if isinstance(term, _FallbackBNode):
        return f"B:{term.value}"
    if isinstance(term, _FallbackLiteral):
        return f"L:{term.value!r}|{term.datatype or ''}|{term.language or ''}"
    if hasattr(term, "n3"):
        return f"R:{term.n3()}"
    return f"X:{term!s}"


def _triple_key(triple: tuple[Any, Any, Any]) -> tuple[str, str, str]:
    return tuple(_term_key(item) for item in triple)  # type: ignore[return-value]


def _canonical_triples(graph: Any) -> list[tuple[Any, Any, Any]]:
    candidate = graph
    if _is_rdflib_graph(graph) and to_canonical_graph is not None:
        try:
            candidate = to_canonical_graph(graph)
        except Exception:
            candidate = graph
    return sorted(list(_iter_triples(candidate)), key=_triple_key)


def graph_hash(graph: Any) -> str:
    """Hash graph meaning, not source whitespace or RDFLib iteration order."""

    canonical = "\n".join(
        " ".join(_term_key(item) for item in triple)
        for triple in _canonical_triples(graph)
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _term_value(term: Any) -> str:
    if isinstance(term, (_FallbackURI, _FallbackBNode, _FallbackLiteral)):
        return term.value
    return str(term)


def _predicate_local_name(predicate: Any) -> str:
    value = _term_value(predicate)
    return value.rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _metadata(graph: Any) -> tuple[str, list[str]]:
    version: str | None = None
    source_refs: set[str] = set()
    version_names = {"version", "ontologyversion", "schemaversion"}
    source_names = {"source", "sourceref", "sourcereference", "sourcerefs"}
    for _subject, predicate, obj in _iter_triples(graph):
        local = _predicate_local_name(predicate).lower()
        value = _term_value(obj).strip()
        if not value:
            continue
        if local in version_names and version is None:
            version = value
        if local in source_names:
            source_refs.add(value)
    return version or DEFAULT_ONTOLOGY_VERSION, sorted(source_refs)


@dataclass(frozen=True)
class OntologyDocument:
    """Parsed RDF ontology plus stable provenance metadata.

    ``load`` owns the parsed graph.  Consumers that pass it to an untrusted or
    optional validator must use ``clone_graph``; the validator in this task does
    so internally and never mutates this document's graph.
    """

    graph: Any
    data_hash: str
    ontology_version: str
    source_refs: list[str]

    def __post_init__(self) -> None:
        if not (_is_rdflib_graph(self.graph) or isinstance(self.graph, _FallbackGraph)):
            raise TypeError("graph must be an RDFLib Graph or local fallback graph")
        if type(self.data_hash) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.data_hash):
            raise ValueError("data_hash must be a lowercase SHA-256 hex digest")
        if type(self.ontology_version) is not str or not self.ontology_version.strip():
            raise ValueError("ontology_version must be a non-empty string")
        if type(self.source_refs) is not list or any(
            type(item) is not str or not item.strip() for item in self.source_refs
        ):
            raise ValueError("source_refs must be a list of non-empty strings")
        object.__setattr__(self, "source_refs", list(dict.fromkeys(self.source_refs)))

    @classmethod
    def load(cls, text: str) -> "OntologyDocument":
        """Parse Turtle text and derive deterministic metadata."""

        graph = _parse_rdf_text(text)
        version, source_refs = _metadata(graph)
        return cls(
            graph=graph,
            data_hash=graph_hash(graph),
            ontology_version=version,
            source_refs=source_refs,
        )

    def serialize(self, format: str = "turtle") -> str:
        """Serialize without changing the owned graph."""

        return _serialize_graph(self.graph, format)


class _FallbackCursor:
    __slots__ = ("tokens", "index", "bnode_index")

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0
        self.bnode_index = 0

    def peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def pop(self) -> str:
        token = self.peek()
        if token is None:
            raise RDFParseError("unexpected end of Turtle document")
        self.index += 1
        return token

    def expect(self, expected: str) -> None:
        actual = self.pop()
        if actual != expected:
            raise RDFParseError(f"expected {expected!r}, got {actual!r}")


def _tokenize_fallback(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char == "#":
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if char in ";,[]":
            tokens.append(char)
            index += 1
            continue
        if char == ".":
            tokens.append(char)
            index += 1
            continue
        if char == "<":
            end = text.find(">", index + 1)
            if end < 0:
                raise RDFParseError("unterminated IRI")
            tokens.append(text[index : end + 1])
            index = end + 1
            continue
        if char == '"':
            end = index + 1
            escaped = False
            while end < length:
                current = text[end]
                if current == '"' and not escaped:
                    break
                if current == "\n" and not escaped:
                    raise RDFParseError("literal string cannot contain an unescaped newline")
                if current == "\\" and not escaped:
                    escaped = True
                else:
                    escaped = False
                end += 1
            if end >= length:
                raise RDFParseError("unterminated literal string")
            tokens.append(text[index : end + 1])
            index = end + 1
            continue
        start = index
        while index < length and not text[index].isspace() and text[index] not in ";,[]<>\"":
            if text[index] == "." and (
                index + 1 == length or text[index + 1].isspace() or text[index + 1] in ";,[]"
            ):
                break
            index += 1
        if start == index:
            raise RDFParseError(f"unexpected Turtle character {text[index]!r}")
        tokens.append(text[start:index])
    return tokens


def _parse_fallback_turtle(text: str) -> _FallbackGraph:
    tokens = _tokenize_fallback(text)
    cursor = _FallbackCursor(tokens)
    prefixes: dict[str, str] = {}
    triples: list[tuple[Any, Any, Any]] = []
    while cursor.peek() is not None:
        marker = cursor.peek()
        if marker is not None and marker.lower() in {"@prefix", "prefix"}:
            _parse_prefix_directive(cursor, prefixes)
            continue
        if marker is not None and marker.lower() in {"@base", "base"}:
            raise RDFParseError("@base is not supported by the local Turtle fallback")
        subject = _parse_fallback_term(cursor.pop(), prefixes, position="subject")
        _parse_predicate_objects(cursor, prefixes, subject, triples, stop_tokens={"."})
        cursor.expect(".")
    return _FallbackGraph(triples)


def _parse_prefix_directive(cursor: _FallbackCursor, prefixes: dict[str, str]) -> None:
    cursor.pop()
    prefix_token = cursor.pop()
    if not prefix_token.endswith(":"):
        raise RDFParseError("prefix declaration must name a prefix ending in ':'")
    iri_token = cursor.pop()
    if not (iri_token.startswith("<") and iri_token.endswith(">")):
        raise RDFParseError("prefix declaration must use an IRI")
    prefixes[prefix_token[:-1]] = iri_token[1:-1]
    try:
        cursor.expect(".")
    except RDFParseError as exc:
        raise RDFParseError("prefix declaration must terminate with '.'") from exc


def _parse_predicate_objects(
    cursor: _FallbackCursor,
    prefixes: dict[str, str],
    subject: Any,
    triples: list[tuple[Any, Any, Any]],
    *,
    stop_tokens: set[str],
) -> None:
    while cursor.peek() is not None and cursor.peek() not in stop_tokens | {"]"}:
        predicate = _parse_fallback_term(cursor.pop(), prefixes, position="predicate")
        while True:
            obj = _parse_fallback_object(cursor, prefixes, triples)
            triples.append((subject, predicate, obj))
            if cursor.peek() == ",":
                cursor.pop()
                continue
            break
        if cursor.peek() == ";":
            cursor.pop()
            continue
        break


def _parse_fallback_object(
    cursor: _FallbackCursor,
    prefixes: dict[str, str],
    triples: list[tuple[Any, Any, Any]],
) -> Any:
    if cursor.peek() == "[":
        cursor.pop()
        cursor.bnode_index += 1
        subject = _FallbackBNode(f"b{cursor.bnode_index}")
        _parse_predicate_objects(cursor, prefixes, subject, triples, stop_tokens={"]"})
        cursor.expect("]")
        return subject
    return _parse_fallback_term(cursor.pop(), prefixes, position="object")


def _parse_fallback_term(token: str, prefixes: dict[str, str], *, position: str) -> Any:
    if token == "a":
        return _FallbackURI(RDF_TYPE)
    if token.startswith("<") and token.endswith(">"):
        return _FallbackURI(token[1:-1])
    if token.startswith('"') and token.endswith('"'):
        try:
            return _FallbackLiteral(json.loads(token))
        except json.JSONDecodeError as exc:
            raise RDFParseError(f"invalid literal {token!r}") from exc
    if token.startswith("_:"):
        return _FallbackBNode(token[2:])
    if ":" in token:
        prefix, local = token.split(":", 1)
        if prefix not in prefixes:
            raise RDFParseError(f"unknown Turtle prefix {prefix!r}")
        return _FallbackURI(prefixes[prefix] + local)
    if position == "object" and re.fullmatch(r"(?:[+-]?\d+(?:\.\d+)?)|true|false", token):
        return _FallbackLiteral(token)
    raise RDFParseError(f"unsupported or invalid Turtle {position} term {token!r}")


def _term_n3(term: Any) -> str:
    if isinstance(term, _FallbackURI):
        return f"<{term.value}>"
    if isinstance(term, _FallbackBNode):
        return f"_:{term.value}"
    if isinstance(term, _FallbackLiteral):
        encoded = json.dumps(term.value, ensure_ascii=False)
        if term.language:
            encoded += f"@{term.language}"
        if term.datatype:
            encoded += f"^^<{term.datatype}>"
        return encoded
    if hasattr(term, "n3"):
        return term.n3()
    return json.dumps(str(term), ensure_ascii=False)


__all__ = [
    "DEFAULT_ONTOLOGY_VERSION",
    "OntologyDocument",
    "RDFParseError",
    "_FallbackBNode",
    "_FallbackGraph",
    "_FallbackLiteral",
    "_FallbackURI",
    "_clone_graph",
    "_iter_triples",
    "_parse_rdf_text",
    "_predicate_local_name",
    "_term_value",
    "graph_hash",
]
