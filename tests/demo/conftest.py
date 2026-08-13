from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from datetime import datetime, timezone

import pytest
import polars as pl

from software_delivery_demo.domain import ProjectConfig
from software_delivery_demo.data_products import DataProductBundle, build_data_products
from software_delivery_demo.generator import DatasetBundle, generate_dataset
from software_delivery_demo.analytics import ProjectSnapshot, build_project_snapshot


@pytest.fixture(scope="session")
def project_config() -> ProjectConfig:
    return ProjectConfig.load(Path("projects/software-delivery-demo/config/project.yaml"))


@pytest.fixture(scope="session")
def bundle(project_config: ProjectConfig) -> DatasetBundle:
    return generate_dataset(project_config)


@pytest.fixture(scope="session")
def products(bundle: DatasetBundle) -> DataProductBundle:
    return build_data_products(bundle)


@pytest.fixture(scope="session")
def snapshot(products: DataProductBundle) -> ProjectSnapshot:
    return build_project_snapshot(products, datetime(2026, 5, 1, tzinfo=timezone.utc))


@pytest.fixture
def bundle_with_dependency_cycle(bundle: DatasetBundle) -> DatasetBundle:
    cycle = bundle.dependencies.vstack(
        bundle.dependencies.head(1).with_columns(
            predecessor_id=pl.lit(bundle.dependencies[0, "successor_id"]),
            successor_id=pl.lit(bundle.dependencies[0, "predecessor_id"]),
        )
    )
    return replace(bundle, dependencies=cycle)


@pytest.fixture
def overloaded_snapshot(snapshot: ProjectSnapshot) -> ProjectSnapshot:
    overloaded_capacity = snapshot.capacity.with_columns(
        pl.lit(1.0).alias("capacity_hours"),
        pl.lit(999.0).alias("allocated_hours"),
    )
    return replace(snapshot, capacity=overloaded_capacity)


@pytest.fixture
def plans(snapshot: ProjectSnapshot):
    from software_delivery_demo.decisions import build_candidate_plans
    from software_delivery_demo.domain import ChangeRequest
    from software_delivery_demo.features import build_features
    from software_delivery_demo.labels import build_labels
    from software_delivery_demo.models import BaselineModel

    change = ChangeRequest.model_validate(snapshot.products.source_bundle.changes.row(0, named=True))
    features = build_features(snapshot.products, [snapshot.as_of_time])
    labels = build_labels(snapshot.products, [snapshot.as_of_time])
    predictions = BaselineModel.fit(features, labels).predict(features)
    return build_candidate_plans(snapshot, predictions, change)
