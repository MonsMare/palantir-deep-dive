"""Ontology package namespace.

Submodules are intentionally imported explicitly.  The RDF and compiler
modules are used during package bootstrap, so eager computation-contract
exports would create a circular import through ``CompileResult``.
"""

from importlib import import_module

_COMPUTATION_EXPORTS = {
    "ActionOutcomeLink",
    "ComputationChainReport",
    "ComputationChainValidator",
    "DecisionCandidate",
    "FeatureDefinition",
    "FeatureMaterializer",
    "FeatureRecord",
    "FeatureSnapshot",
    "FeedbackLink",
    "GovernedActionRequest",
    "LabelDefinition",
    "LabelMaterializer",
    "LabelRecord",
    "LabelSnapshot",
    "PredictionArtifact",
}


def __getattr__(name: str):
    if name in _COMPUTATION_EXPORTS:
        module = import_module(".computation", __name__)
        return getattr(module, name)
    raise AttributeError(name)


__all__ = sorted(_COMPUTATION_EXPORTS)
