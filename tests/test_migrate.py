from datetime import datetime

from conftest import Fixture
from test_transform import get_transform_results

from ecospheres_migrator.geonetwork import extract_record_info
from ecospheres_migrator.migrator import Migrator


def get_change_dates(migrator: Migrator, md_fixtures: list[Fixture]) -> dict[str, datetime]:
    sources = migrator.gn.get_sources()
    change_dates = {}
    for fixture in md_fixtures:
        record = migrator.gn.get_record(fixture.uuid)
        record_info = extract_record_info(record, sources)
        change_date = record_info.xpath(".//changeDate")
        change_dates[fixture.uuid] = datetime.fromisoformat(change_date[0].text)
    return change_dates


def test_migrate_noop_overwrite(migrator: Migrator, md_fixtures: list[Fixture]):
    """`noop` migration in overwrite mode should update change date"""
    change_dates_before = get_change_dates(migrator, md_fixtures)

    batch, _ = get_transform_results("noop", migrator)
    migrator.migrate(batch, overwrite=True, group=None)

    change_dates_after = get_change_dates(migrator, md_fixtures)

    for uuid in [f.uuid for f in md_fixtures]:
        # TODO: maybe compare on something else, precision is only to the second
        assert change_dates_after[uuid] > change_dates_before[uuid]


def test_migrate_noop_duplicate(
    migrator: Migrator, clean_md_fixtures: list[Fixture], group_fixture: int
):
    """
    `noop` migration in duplicate mode should create new records in specific group.
    Use `clean_md_fixtures` to remove all records from the group before running the test.
    """
    change_dates_before = get_change_dates(migrator, clean_md_fixtures)

    batch, _ = get_transform_results("noop", migrator)
    migrator.migrate(batch, overwrite=False, group=group_fixture)

    change_dates_after = get_change_dates(migrator, clean_md_fixtures)

    # dates have not changed on original records
    for uuid in [f.uuid for f in clean_md_fixtures]:
        assert change_dates_after[uuid] == change_dates_before[uuid]

    # new records have been created in the test group
    records = migrator.gn.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    assert len(records) == len(clean_md_fixtures)


def test_migrate_error_overwrite(migrator: Migrator, md_fixtures: list[Fixture]):
    """`error` migration in overwrite mode should not touch change date"""
    change_dates_before = get_change_dates(migrator, md_fixtures)

    batch, _ = get_transform_results("error", migrator)
    migrator.migrate(batch, overwrite=True, group=None)

    change_dates_after = get_change_dates(migrator, md_fixtures)

    for uuid in [f.uuid for f in md_fixtures]:
        assert change_dates_after[uuid] == change_dates_before[uuid]


def test_migrate_error_duplicate(
    migrator: Migrator, clean_md_fixtures: list[Fixture], group_fixture: int
):
    """
    `error` migration in duplicate mode should not create records or touch existing ones.
    Use `clean_md_fixtures` to remove all records from the group before running the test.
    """
    change_dates_before = get_change_dates(migrator, clean_md_fixtures)

    batch, _ = get_transform_results("error", migrator)
    migrator.migrate(batch, overwrite=False, group=group_fixture)

    change_dates_after = get_change_dates(migrator, clean_md_fixtures)

    # dates have not changed on original records
    for uuid in [f.uuid for f in clean_md_fixtures]:
        assert change_dates_after[uuid] == change_dates_before[uuid]

    # no records have been created in the test group
    records = migrator.gn.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    assert len(records) == 0
