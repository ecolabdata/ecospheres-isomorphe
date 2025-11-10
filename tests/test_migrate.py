from datetime import datetime
from time import sleep
from unittest.mock import patch

from conftest import GN_TEST_URL, XPATH_ISO_DATE_STAMP, Fixture
from test_transform import get_transform_results

from isomorphe.batch import MigrateMode, SuccessTransformBatchRecord, TransformBatch
from isomorphe.geonetwork import MetadataType
from isomorphe.migrator import Migrator
from isomorphe.xml import string_to_xml, xpath_eval


def get_records(migrator: Migrator, md_fixtures: list[Fixture]) -> dict[str, str]:
    records = {}
    for fixture in md_fixtures:
        content = migrator.gn.get_record(fixture.uuid)
        records[fixture.uuid] = content
    return records


def get_datetime(content: str, xpath: str) -> datetime:
    value = xpath_eval(string_to_xml(content), xpath)[0].string_value
    return datetime.fromisoformat(value)


def test_migrate_change_language_overwrite(migrator: Migrator, md_fixtures: list[Fixture]):
    """`change-language` migration in overwrite mode should update content"""
    records_before = get_records(migrator, md_fixtures)

    sleep(1)  # datestamp resolution is 1s
    batch, _ = get_transform_results("change-language", migrator)
    migrate_batch = migrator.migrate(batch, overwrite=True, group=None)
    assert len(migrate_batch.successes()) == len(batch.successes())
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(migrator, md_fixtures)

    # content has changed on original records (especially the metadata date stamp)
    for uuid in [f.uuid for f in md_fixtures]:
        assert records_before[uuid] != records_after[uuid]
        dt_before = get_datetime(records_before[uuid], XPATH_ISO_DATE_STAMP)
        dt_after = get_datetime(records_after[uuid], XPATH_ISO_DATE_STAMP)
        assert dt_after > dt_before


def test_migrate_change_language_overwrite_preserve_date_stamp(
    migrator: Migrator, md_fixtures: list[Fixture]
):
    """`change-language` migration in overwrite mode with update_date_stamp=False should preserve the existing date stamp"""
    records_before = get_records(migrator, md_fixtures)

    sleep(1)  # datestamp resolution is 1s
    batch, _ = get_transform_results("change-language", migrator)
    migrate_batch = migrator.migrate(batch, overwrite=True, group=None, update_date_stamp=False)
    assert len(migrate_batch.successes()) == len(batch.successes())
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(migrator, md_fixtures)

    # content has changed on original records (but not the metadata date stamp)
    for uuid in [f.uuid for f in md_fixtures]:
        dt_before = get_datetime(records_before[uuid], XPATH_ISO_DATE_STAMP)
        dt_after = get_datetime(records_after[uuid], XPATH_ISO_DATE_STAMP)
        assert dt_after == dt_before


def test_migrate_change_language_duplicate(
    migrator: Migrator, clean_md_fixtures: list[Fixture], group_fixture: int
):
    """
    `change-language` migration in duplicate mode should create new records in specific group.
    Use `clean_md_fixtures` to remove all records from the group before running the test.
    """
    records_before = get_records(migrator, clean_md_fixtures)

    batch, _ = get_transform_results("change-language", migrator)
    migrate_batch = migrator.migrate(batch, overwrite=False, group=group_fixture)
    assert len(migrate_batch.successes()) == len(batch.successes())
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(migrator, clean_md_fixtures)

    # content has not changed on original records (especially geonet:info//changedDate)
    # but new records have been created in the test group (see below)
    for uuid in [f.uuid for f in clean_md_fixtures]:
        assert records_after[uuid] == records_before[uuid]

    # new records have been created in the test group
    records = migrator.gn.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    assert len(records) == len(clean_md_fixtures)


def test_migrate_error_overwrite(migrator: Migrator, md_fixtures: list[Fixture]):
    """`error` migration in overwrite mode should not touch content"""
    records_before = get_records(migrator, md_fixtures)

    batch, _ = get_transform_results("error", migrator)
    migrate_batch = migrator.migrate(batch, overwrite=True, group=None)
    assert len(migrate_batch.successes()) == len(batch.successes()) == 0
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(migrator, md_fixtures)

    # content has not changed on original records (especially geonet:info//changedDate)
    for uuid in [f.uuid for f in md_fixtures]:
        assert records_after[uuid] == records_before[uuid]


def test_migrate_error_duplicate(
    migrator: Migrator, clean_md_fixtures: list[Fixture], group_fixture: int
):
    """
    `error` migration in duplicate mode should not create records or touch existing ones.
    Use `clean_md_fixtures` to remove all records from the group before running the test.
    """
    records_before = get_records(migrator, clean_md_fixtures)

    batch, _ = get_transform_results("error", migrator)
    migrate_batch = migrator.migrate(batch, overwrite=False, group=group_fixture)
    assert len(migrate_batch.successes()) == len(batch.successes()) == 0
    assert len(migrate_batch.failures()) == 0

    records_after = get_records(migrator, clean_md_fixtures)

    # content has not changed on original records (especially geonet:info//changedDate)
    for uuid in [f.uuid for f in clean_md_fixtures]:
        assert records_after[uuid] == records_before[uuid]

    # no records have been created in the test group
    records = migrator.gn.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    assert len(records) == 0


def test_migrate_transform_job_id(migrator: Migrator):
    migrate_batch = migrator.migrate(TransformBatch(transformation="noop"), transform_job_id="xxx")
    assert migrate_batch.transform_job_id == "xxx"


def test_migrate_batch_records_success(
    migrator: Migrator, md_fixtures: list[Fixture], group_fixture: int
):
    batch, _ = get_transform_results("change-language", migrator)
    migrate_batch = migrator.migrate(batch, overwrite=False, group=group_fixture)
    assert len(migrate_batch.successes()) == len(batch.records)
    for record in migrate_batch.successes():
        assert record.uuid in [f.uuid for f in md_fixtures]
        assert record.transformed_uuid not in [f.uuid for f in md_fixtures]
        assert record.url == GN_TEST_URL
        assert record.original_content is not None
        assert record.transformed_content is not None
        assert record.original_content != record.transformed_content
        assert record.md_type == MetadataType.METADATA


def test_migrate_batch_records_filtered_success(
    migrator: Migrator, md_fixtures: list[Fixture], group_fixture: int
):
    batch, _ = get_transform_results("change-language", migrator)

    nocheck = SuccessTransformBatchRecord.status_code_for(needs_check=False)
    assert (
        len(migrator.migrate(batch, overwrite=False, group=group_fixture, statuses=[nocheck])) == 2
    )
    check = SuccessTransformBatchRecord.status_code_for(needs_check=True)
    assert len(migrator.migrate(batch, overwrite=False, group=group_fixture, statuses=[check])) == 0


def test_migrate_batch_records_failure(migrator: Migrator, md_fixtures: list[Fixture]):
    batch, _ = get_transform_results("change-language", migrator)
    with patch("isomorphe.geonetwork.GeonetworkClient.update_record") as mocked_method:
        mocked_method.side_effect = Exception("Mocked update_record error")
        migrate_batch = migrator.migrate(batch, overwrite=False, group=None)
    assert len(migrate_batch.failures()) == len(migrate_batch.records)
    for record in migrate_batch.failures():
        assert record.uuid in [f.uuid for f in md_fixtures]
        assert record.url == GN_TEST_URL
        assert record.original_content is not None
        assert record.transformed_content is not None
        assert record.original_content != record.transformed_content
        assert record.md_type == MetadataType.METADATA
        assert record.error is not None  # actual error is tested below


def test_migrate_overwrite_gn_error(migrator: Migrator, md_fixtures: list[Fixture]):
    batch, _ = get_transform_results("change-language", migrator)
    with patch("isomorphe.geonetwork.GeonetworkClient.update_record") as mocked_method:
        mocked_method.side_effect = Exception("Mocked update_record error")
        migrate_batch = migrator.migrate(batch, overwrite=True, group=None)
    assert migrate_batch.mode == MigrateMode.OVERWRITE
    assert len(migrate_batch.failures()) == len(md_fixtures)
    for record in migrate_batch.failures():
        assert record.error == "Mocked update_record error"


def test_migrate_duplicate_gn_error(migrator: Migrator, md_fixtures: list[Fixture]):
    batch, _ = get_transform_results("change-language", migrator)
    with patch("isomorphe.geonetwork.GeonetworkClient.put_record") as mocked_method:
        mocked_method.side_effect = Exception("Mocked put_record error")
        migrate_batch = migrator.migrate(batch, overwrite=False, group=1)
    assert migrate_batch.mode == MigrateMode.CREATE
    assert len(migrate_batch.failures()) == len(md_fixtures)
    for record in migrate_batch.failures():
        assert record.error == "Mocked put_record error"
