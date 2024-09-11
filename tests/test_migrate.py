from conftest import Fixture
from lxml import etree
from test_transform import get_transform_results

from ecospheres_migrator.migrator import Migrator


def get_records(migrator: Migrator, md_fixtures: list[Fixture]) -> dict[str, str]:
    records = {}
    for fixture in md_fixtures:
        record = migrator.gn.get_record(fixture.uuid)
        records[fixture.uuid] = (etree.tostring(record),)
    return records


def test_migrate_noop_overwrite(migrator: Migrator, md_fixtures: list[Fixture]):
    """`noop` migration in overwrite mode should update content"""
    records_before = get_records(migrator, md_fixtures)

    batch, _ = get_transform_results("noop", migrator)
    migrator.migrate(batch, overwrite=True, group=None)

    records_after = get_records(migrator, md_fixtures)

    # content has changed on original records (especially geonet:info//changedDate)
    for uuid in [f.uuid for f in md_fixtures]:
        assert records_after[uuid] != records_before[uuid]


def test_migrate_noop_duplicate(
    migrator: Migrator, clean_md_fixtures: list[Fixture], group_fixture: int
):
    """
    `noop` migration in duplicate mode should create new records in specific group.
    Use `clean_md_fixtures` to remove all records from the group before running the test.
    """
    records_before = get_records(migrator, clean_md_fixtures)

    batch, _ = get_transform_results("noop", migrator)
    migrator.migrate(batch, overwrite=False, group=group_fixture)

    records_after = get_records(migrator, clean_md_fixtures)

    # content has not changed on original records (especially geonet:info//changedDate)
    for uuid in [f.uuid for f in clean_md_fixtures]:
        assert records_after[uuid] == records_before[uuid]

    # new records have been created in the test group
    records = migrator.gn.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    assert len(records) == len(clean_md_fixtures)


def test_migrate_error_overwrite(migrator: Migrator, md_fixtures: list[Fixture]):
    """`error` migration in overwrite mode should not touch content"""
    records_before = get_records(migrator, md_fixtures)

    batch, _ = get_transform_results("error", migrator)
    migrator.migrate(batch, overwrite=True, group=None)

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
    migrator.migrate(batch, overwrite=False, group=group_fixture)

    records_after = get_records(migrator, clean_md_fixtures)

    # content has not changed on original records (especially geonet:info//changedDate)
    for uuid in [f.uuid for f in clean_md_fixtures]:
        assert records_after[uuid] == records_before[uuid]

    # no records have been created in the test group
    records = migrator.gn.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    assert len(records) == 0
