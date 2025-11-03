import pytest

from isomorphe.batch import (
    FailureMigrateBatchRecord,
    FailureTransformBatchRecord,
    MigrateBatch,
    MigrateBatchRecord,
    MigrateMode,
    SkippedTransformBatchRecord,
    SuccessMigrateBatchRecord,
    SuccessTransformBatchRecord,
    TransformBatch,
    TransformBatchRecord,
)
from isomorphe.geonetwork import MetadataType


@pytest.fixture
def dummy_tbr() -> TransformBatchRecord:
    return TransformBatchRecord(
        uuid="",
        url="",
        md_type=MetadataType.METADATA,
        original_content=bytes(),
        state=None,
    )


@pytest.fixture
def dummy_mbr() -> MigrateBatchRecord:
    return MigrateBatchRecord(
        uuid="",
        url="",
        md_type=MetadataType.METADATA,
        original_content=bytes(),
        transformed_content=bytes(),
    )


def test_log_markers(dummy_tbr: TransformBatchRecord):
    assert not SuccessTransformBatchRecord.derive_from(
        dummy_tbr, transformed_content=bytes(), log=["aaa", "[anything] bbb", "[] ccc"]
    ).needs_check
    assert not SuccessTransformBatchRecord.derive_from(
        dummy_tbr, transformed_content=bytes(), log=["aaa", "[isomorphe] bbb"]
    ).needs_check
    assert not SuccessTransformBatchRecord.derive_from(
        dummy_tbr, transformed_content=bytes(), log=["[isomorphe:foo]"]
    ).needs_check
    assert SuccessTransformBatchRecord.derive_from(
        dummy_tbr, transformed_content=bytes(), log=["[isomorphe:check]"]
    ).needs_check
    assert SuccessTransformBatchRecord.derive_from(
        dummy_tbr, transformed_content=bytes(), log=["aaa", "bbb [isomorphe:check] ccc", "ddd"]
    ).needs_check

    assert SuccessTransformBatchRecord.derive_from(
        dummy_tbr,
        transformed_content=bytes(),
        log=[
            "[isomorphe] aaa",
            "[isomorphe:check] bbb",
            "ccc [isomorphe] ddd",
            "eee [isomorphe]",
            "[anything] fff",
            "ggg []",
            "hhh iii",
        ],
    ).messages == ["aaa", "bbb", "ccc ddd", "eee", "[anything] fff", "ggg []", "hhh iii"]


def test_transform_class_statuses():
    # Ensure something breaks if statuses change, so modifications are voluntary
    assert FailureTransformBatchRecord.status_code_for() == 1
    assert SuccessTransformBatchRecord.status_code_for(needs_check=True) == 2
    assert SuccessTransformBatchRecord.status_code_for(needs_check=False) == 12
    assert SkippedTransformBatchRecord.status_code_for(needs_check=True) == 3
    assert SkippedTransformBatchRecord.status_code_for(needs_check=False) == 13


def test_transform_instance_statuses(dummy_tbr: TransformBatchRecord):
    assert (
        FailureTransformBatchRecord.status_code_for()
        == FailureTransformBatchRecord.derive_from(dummy_tbr, error="").status_code
    )
    assert (
        SuccessTransformBatchRecord.status_code_for(needs_check=False)
        == SuccessTransformBatchRecord.derive_from(
            dummy_tbr, transformed_content=bytes()
        ).status_code
    )
    assert (
        SuccessTransformBatchRecord.status_code_for(needs_check=True)
        == SuccessTransformBatchRecord.derive_from(
            dummy_tbr, transformed_content=bytes(), log=["[isomorphe:check]"]
        ).status_code
    )
    assert (
        SkippedTransformBatchRecord.status_code_for(needs_check=False)
        == SkippedTransformBatchRecord.derive_from(dummy_tbr).status_code
    )
    assert (
        SkippedTransformBatchRecord.status_code_for(needs_check=True)
        == SkippedTransformBatchRecord.derive_from(dummy_tbr, log=["[isomorphe:check]"]).status_code
    )


def test_migrate_class_statuses():
    assert FailureMigrateBatchRecord.status_code_for() == 1
    assert SuccessMigrateBatchRecord.status_code_for() == 2


def test_migrate_instance_statuses(dummy_mbr: MigrateBatchRecord):
    assert (
        FailureMigrateBatchRecord.status_code_for()
        == FailureMigrateBatchRecord.derive_from(dummy_mbr, error="").status_code
    )
    assert (
        SuccessMigrateBatchRecord.status_code_for()
        == SuccessMigrateBatchRecord.derive_from(dummy_mbr, transformed_uuid="").status_code
    )


def test_filter_transform_status(dummy_tbr: TransformBatchRecord):
    batch = TransformBatch(
        transformation="",
        records=[
            SuccessTransformBatchRecord.derive_from(dummy_tbr, transformed_content=bytes()),
            FailureTransformBatchRecord.derive_from(dummy_tbr, error=""),
            SkippedTransformBatchRecord.derive_from(dummy_tbr, reason=None),
            FailureTransformBatchRecord.derive_from(dummy_tbr, error=""),
        ],
    )
    filtered = batch.filter_status([FailureTransformBatchRecord.status_code_for()])
    assert len(filtered) == 2
    assert all([isinstance(r, FailureTransformBatchRecord) for r in filtered])


def test_transform_filter_status(dummy_tbr: TransformBatchRecord):
    batch = TransformBatch(
        transformation="",
        records=[
            SuccessTransformBatchRecord.derive_from(dummy_tbr, transformed_content=bytes()),
            FailureTransformBatchRecord.derive_from(dummy_tbr, error=""),
            SkippedTransformBatchRecord.derive_from(dummy_tbr, reason=None),
            FailureTransformBatchRecord.derive_from(dummy_tbr, error=""),
        ],
    )
    filtered = batch.filter_status([FailureTransformBatchRecord.status_code_for()])
    assert len(filtered) == 2
    assert all([isinstance(r, FailureTransformBatchRecord) for r in filtered])


def test_migrate_filter_status(dummy_mbr: MigrateBatchRecord):
    batch = MigrateBatch(
        mode=MigrateMode.CREATE,
        transform_job_id="",
        records=[
            SuccessMigrateBatchRecord.derive_from(dummy_mbr, transformed_uuid=""),
            FailureMigrateBatchRecord.derive_from(dummy_mbr, error=""),
            SuccessMigrateBatchRecord.derive_from(dummy_mbr, transformed_uuid=""),
        ],
    )
    filtered = batch.filter_status([SuccessMigrateBatchRecord.status_code_for()])
    assert len(filtered) == 2
    assert all([isinstance(r, SuccessMigrateBatchRecord) for r in filtered])
