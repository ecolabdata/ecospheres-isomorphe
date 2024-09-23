from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import Fixture

from ecospheres_migrator.batch import TransformBatch
from ecospheres_migrator.geonetwork import (
    GeonetworkClient,
    MetadataType,
    Record,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
)
from ecospheres_migrator.migrator import Migrator, SkipReason


def get_transformation_path(name: str) -> Path:
    transformations = Migrator.list_transformations(Path("ecospheres_migrator/transformations"))
    transformation = next((t for t in transformations if t.name == name), None)
    if not transformation:
        raise ValueError(f"No transformation found with name {name}")
    return transformation.path


def get_transform_results(
    transformation: str, migrator: Migrator, selection: list[Record] = []
) -> tuple[TransformBatch, list[Record]]:
    if not selection:
        selection = migrator.select(query="type=dataset")
    assert len(selection) > 0
    return migrator.transform(get_transformation_path(transformation), selection), selection


def test_transform_noop(migrator: Migrator):
    """`noop` transform is always skipped"""
    results, selection = get_transform_results("noop", migrator)
    assert len(results.skipped()) == len(selection)
    assert len(results.successes()) == 0
    assert len(results.failures()) == 0


def test_transform_error(migrator: Migrator):
    """`error` transform is never successful"""
    results, selection = get_transform_results("error", migrator)
    assert len(results.skipped()) == 0
    assert len(results.successes()) == 0
    assert len(results.failures()) == len(selection)


def test_transform_change_language(migrator: Migrator, clean_md_fixtures: list[Fixture]):
    """`change-language` transform is always successful"""
    results, selection = get_transform_results("change-language", migrator)
    assert len(results.skipped()) == 0
    assert len(results.successes()) == len(selection)
    assert len(results.failures()) == 0


def test_transform_working_copy(migrator: Migrator):
    """`change-language` transform is always skipped when record has working copy"""
    selection = migrator.select(query="type=dataset")
    assert len(selection) > 0
    for record in selection:
        record.state = WorkflowState(stage=WorkflowStage.WORKING_COPY, status=WorkflowStatus.DRAFT)
    results, _ = get_transform_results("change-language", migrator, selection=selection)
    assert len(results.skipped()) == len(selection)
    assert len(results.successes()) == 0
    assert len(results.failures()) == 0
    for result in results.skipped():
        assert result.reason == SkipReason.HAS_WORKING_COPY


@pytest.mark.parametrize(
    "md_type",
    [
        # md_type, expected_result
        (MetadataType.METADATA, "success"),
        (MetadataType.TEMPLATE, "success"),
        (MetadataType.SUB_TEMPLATE, "skipped"),
        (MetadataType.TEMPLATE_OF_SUB_TEMPLATE, "skipped"),
    ],
)
def test_transform_metadata_type(
    migrator: Migrator,
    md_type: tuple[MetadataType, str],
):
    def patched_get_md_type(self, md):
        """Force the metadata type in GN record to be the one in the test"""
        return md_type[0]

    with patch.object(GeonetworkClient, "_get_md_type", patched_get_md_type):
        results, selection = get_transform_results("change-language", migrator)

    assert len(selection) > 0

    if md_type[1] == "success":
        assert len(results.successes()) == len(selection)
    elif md_type[1] == "skipped":
        assert len(results.skipped()) == len(selection)
