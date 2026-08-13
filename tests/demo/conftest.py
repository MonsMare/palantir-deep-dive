from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pytest

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
    from datetime import datetime, timezone

    return build_project_snapshot(products, datetime(2026, 5, 1, tzinfo=timezone.utc))


@pytest.fixture
def bundle_with_dependency_cycle(bundle: DatasetBundle) -> DatasetBundle:
    cycle = bundle.dependencies.vstack(
        bundle.dependencies.head(1).with_columns(
            predecessor_id=__import__("polars").lit(bundle.dependencies[0, "successor_id"]),
            successor_id=__import__("polars").lit(bundle.dependencies[0, "predecessor_id"]),
        )
    )
    return replace(bundle, dependencies=cycle)
