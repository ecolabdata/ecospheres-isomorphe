from unittest.mock import patch

from conftest import GN_TEST_URL, Fixture
from lxml import etree
from test_transform import get_transform_results

from isomorphe.batch import MigrateMode, TransformBatch
from isomorphe.geonetwork import MetadataType
from isomorphe.isomorphe import Isomorphe


def get_records(isomorphe: Isomorphe, md_fixtures: list[Fixture]) -> dict[str, str]:
    records = {}
    for fixture in md_fixtures:
        record = isomorphe.gn.get_record(fixture.uuid)
        records[fixture.uuid] = (etree.tostring(record),)
    return records


def test_migrate_change_language_overwrite(isomorphe: Isomorphe, md_fixtures: list[Fixture]):
    """`change-language` migration in overwrite mode should update content"""
    records_before = get_records(isomorphe, md_fixtures)

    batch, _ = get_transform_results("change-language", isomorphe)
    migrate_batch = isomorphe.migrate(batch, overwrite=True, group=None)
    assert len(migrate_batch.successes()) == len(batch.successes())
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(isomorphe, md_fixtures)

    # content has changed on original records (especially geonet:info//changedDate)
    for uuid in [f.uuid for f in md_fixtures]:
        assert records_after[uuid] != records_before[uuid]


def test_migrate_change_language_duplicate(
    isomorphe: Isomorphe, clean_md_fixtures: list[Fixture], group_fixture: int
):
    """
    `change-language` migration in duplicate mode should create new records in specific group.
    Use `clean_md_fixtures` to remove all records from the group before running the test.
    """
    records_before = get_records(isomorphe, clean_md_fixtures)

    batch, _ = get_transform_results("change-language", isomorphe)
    migrate_batch = isomorphe.migrate(batch, overwrite=False, group=group_fixture)
    assert len(migrate_batch.successes()) == len(batch.successes())
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(isomorphe, clean_md_fixtures)

    # content has not changed on original records (especially geonet:info//changedDate)
    # but new records have been created in the test group (see below)
    for uuid in [f.uuid for f in clean_md_fixtures]:
        assert records_after[uuid] == records_before[uuid]

    # new records have been created in the test group
    records = isomorphe.gn.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    assert len(records) == len(clean_md_fixtures)


def test_migrate_error_overwrite(isomorphe: Isomorphe, md_fixtures: list[Fixture]):
    """`error` migration in overwrite mode should not touch content"""
    records_before = get_records(isomorphe, md_fixtures)

    batch, _ = get_transform_results("error", isomorphe)
    migrate_batch = isomorphe.migrate(batch, overwrite=True, group=None)
    assert len(migrate_batch.successes()) == len(batch.successes()) == 0
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(isomorphe, md_fixtures)

    # content has not changed on original records (especially geonet:info//changedDate)
    for uuid in [f.uuid for f in md_fixtures]:
        assert records_after[uuid] == records_before[uuid]


def test_migrate_error_duplicate(
    isomorphe: Isomorphe, clean_md_fixtures: list[Fixture], group_fixture: int
):
    """
    `error` migration in duplicate mode should not create records or touch existing ones.
    Use `clean_md_fixtures` to remove all records from the group before running the test.
    """
    records_before = get_records(isomorphe, clean_md_fixtures)

    batch, _ = get_transform_results("error", isomorphe)
    migrate_batch = isomorphe.migrate(batch, overwrite=False, group=group_fixture)
    assert len(migrate_batch.successes()) == len(batch.successes()) == 0
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(isomorphe, clean_md_fixtures)

    # content has not changed on original records (especially geonet:info//changedDate)
    for uuid in [f.uuid for f in clean_md_fixtures]:
        assert records_after[uuid] == records_before[uuid]

    # no records have been created in the test group
    records = isomorphe.gn.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    assert len(records) == 0


def test_migrate_transform_job_id(isomorphe: Isomorphe):
    migrate_batch = isomorphe.migrate(TransformBatch(transformation="noop"), transform_job_id="xxx")
    assert migrate_batch.transform_job_id == "xxx"


def test_migrate_batch_records_success(
    isomorphe: Isomorphe, md_fixtures: list[Fixture], group_fixture: int
):
    batch, _ = get_transform_results("change-language", isomorphe)
    migrate_batch = isomorphe.migrate(batch, overwrite=False, group=group_fixture)
    assert len(migrate_batch.successes()) == len(batch.records)
    for record in migrate_batch.successes():
        assert record.source_uuid in [f.uuid for f in md_fixtures]
        assert record.target_uuid not in [f.uuid for f in md_fixtures]
        assert record.url == GN_TEST_URL
        assert record.source_content is not None
        assert record.target_content is not None
        assert record.source_content != record.target_content
        assert record.md_type == MetadataType.METADATA


def test_migrate_batch_records_failure(isomorphe: Isomorphe, md_fixtures: list[Fixture]):
    batch, _ = get_transform_results("change-language", isomorphe)
    with patch("isomorphe.geonetwork.GeonetworkClient.update_record") as mocked_method:
        mocked_method.side_effect = Exception("Mocked update_record error")
        migrate_batch = isomorphe.migrate(batch, overwrite=False, group=None)
    assert len(migrate_batch.failures()) == len(migrate_batch.records)
    for record in migrate_batch.failures():
        assert record.source_uuid in [f.uuid for f in md_fixtures]
        assert record.url == GN_TEST_URL
        assert record.source_content is not None
        assert record.target_content is not None
        assert record.source_content != record.target_content
        assert record.md_type == MetadataType.METADATA
        assert record.error is not None  # actual error is tested below


def test_migrate_overwrite_gn_error(isomorphe: Isomorphe, md_fixtures: list[Fixture]):
    batch, _ = get_transform_results("change-language", isomorphe)
    with patch("isomorphe.geonetwork.GeonetworkClient.update_record") as mocked_method:
        mocked_method.side_effect = Exception("Mocked update_record error")
        migrate_batch = isomorphe.migrate(batch, overwrite=True, group=None)
    assert migrate_batch.mode == MigrateMode.OVERWRITE
    assert len(migrate_batch.failures()) == len(md_fixtures)
    for record in migrate_batch.failures():
        assert record.error == "Mocked update_record error"


def test_migrate_duplicate_gn_error(isomorphe: Isomorphe, md_fixtures: list[Fixture]):
    batch, _ = get_transform_results("change-language", isomorphe)
    with patch("isomorphe.geonetwork.GeonetworkClient.put_record") as mocked_method:
        mocked_method.side_effect = Exception("Mocked put_record error")
        migrate_batch = isomorphe.migrate(batch, overwrite=False, group=1)
    assert migrate_batch.mode == MigrateMode.CREATE
    assert len(migrate_batch.failures()) == len(md_fixtures)
    for record in migrate_batch.failures():
        assert record.error == "Mocked put_record error"
