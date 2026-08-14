"""Source connectors, evidence extraction, and data-product quality."""

from .connectors import (
    CaptureRequest,
    ConnectorRegistry,
    LocalFileConnector,
    SourceConnector,
    SourceDescriptor,
)
from .extractors import EvidenceExtractor, ExtractionReport
from .quality import DataProductContract, DataQualityEngine, DataQualityReport

__all__ = [
    "CaptureRequest",
    "ConnectorRegistry",
    "DataProductContract",
    "DataQualityEngine",
    "DataQualityReport",
    "EvidenceExtractor",
    "ExtractionReport",
    "LocalFileConnector",
    "SourceConnector",
    "SourceDescriptor",
]
