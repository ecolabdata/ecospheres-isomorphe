from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import Fixture

from isomorphe.batch import TransformBatch
from isomorphe.geonetwork import (
    GeonetworkClient,
    MetadataType,
    Record,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
)
from isomorphe.migrator import Migrator, SkipReason, Transformation, TransformationParam


def get_transformation(name: str) -> Transformation:
    transformation = Migrator.get_transformation(name, Path("isomorphe/transformations/default"))
    if not transformation:
        raise ValueError(f"No transformation found with name {name}")
    return transformation


def get_transform_results(
    transformation_name: str,
    isomorphe: Migrator,
    selection: list[Record] = [],
    transformation_params: dict = {},
) -> tuple[TransformBatch, list[Record]]:
    if not selection:
        selection = isomorphe.select(filters={"type": "dataset"})
    transformation = get_transformation(transformation_name)
    assert len(selection) > 0
    return isomorphe.transform(
        transformation, selection, transformation_params=transformation_params
    ), selection


def test_transform_noop(migrator: Migrator):
    """`noop` transform is always skipped"""
    results, selection = get_transform_results("noop", migrator)
    assert len(results.skipped()) == len(selection)
    assert len(results.successes()) == 0
    assert len(results.failures()) == 0
    assert results.transformation == "noop"


def test_transform_error(migrator: Migrator):
    """`error` transform is never successful"""
    results, selection = get_transform_results("error", migrator)
    assert len(results.skipped()) == 0
    assert len(results.successes()) == 0
    assert len(results.failures()) == len(selection)
    assert results.transformation == "error"


def test_transform_noop_always(migrator: Migrator):
    """`noop~always` transform is always successful"""
    results, selection = get_transform_results("noop~always", migrator)
    assert len(results.skipped()) == 0
    assert len(results.successes()) == len(selection)
    assert len(results.failures()) == 0
    assert results.transformation == "noop~always"


def test_transform_change_language(migrator: Migrator, clean_md_fixtures: list[Fixture]):
    """`change-language` transform is always successful"""
    results, selection = get_transform_results("change-language", migrator)
    assert len(results.skipped()) == 0
    assert len(results.successes()) == len(selection)
    assert len(results.failures()) == 0
    assert results.transformation == "change-language"


def test_transform_working_copy(migrator: Migrator):
    """`change-language` transform is always skipped when record has working copy"""
    selection = migrator.select(filters={"type": "dataset"})
    assert len(selection) > 0
    for record in selection:
        record.state = WorkflowState(stage=WorkflowStage.WORKING_COPY, status=WorkflowStatus.DRAFT)
    results, _ = get_transform_results("change-language", migrator, selection=selection)
    assert len(results.skipped()) == len(selection)
    assert len(results.successes()) == 0
    assert len(results.failures()) == 0
    for result in results.skipped():
        assert result.reason == SkipReason.HAS_WORKING_COPY


def test_transform_change_language_params(migrator: Migrator, clean_md_fixtures: list[Fixture]):
    lang = "very-specific-language"
    results, selection = get_transform_results(
        "change-language", migrator, transformation_params={"language": lang}
    )
    assert len(selection) > 0
    assert len(results.skipped()) == 0
    assert len(results.successes()) == len(selection)
    assert len(results.failures()) == 0
    for result in results.successes():
        assert lang in result.transformed_content.decode("utf-8")


def test_transform_warning_error_log(migrator: Migrator):
    results, selection = get_transform_results("warning", migrator)
    assert len(selection) > 0
    assert len(results.skipped()) == len(selection)
    assert len(results.successes()) == 0
    assert len(results.failures()) == 0
    for result in results.successes():
        assert result.log and len(result.log) == 2
        assert any("Hello world" in log for log in result.log)


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
    def patched_get_metadata_type(self, md):
        """Force the metadata type in GN record to be the one in the test"""
        return md_type[0]

    with patch.object(GeonetworkClient, "_get_metadata_type", patched_get_metadata_type):
        results, selection = get_transform_results("change-language", migrator)

    assert len(selection) > 0

    if md_type[1] == "success":
        assert len(results.successes()) == len(selection)
    elif md_type[1] == "skipped":
        assert len(results.skipped()) == len(selection)


def test_load_transformation_params():
    transformation = get_transformation("noop-params")
    assert transformation.params == [
        TransformationParam(
            name="language-optional",
            default_value="eng",
            required=False,
        ),
        TransformationParam(
            name="language-required",
            default_value="eng",
            required=True,
        ),
        TransformationParam(
            name="language-no-default",
            default_value="",
            required=True,
        ),
    ]
