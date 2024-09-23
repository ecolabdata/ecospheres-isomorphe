from conftest import Fixture

from ecospheres_migrator.geonetwork import (
    GeonetworkClient,
    MetadataType,
    Record,
    extract_record_info,
)


def test_duplicate_uuid(
    md_fixtures: list[Fixture], gn_client: GeonetworkClient, group_fixture: int
):
    record = gn_client.put_record(
        uuid="test-uuid-put",
        metadata=md_fixtures[0].content,
        md_type=MetadataType.METADATA,
        # create in test group so that it can be cleaned up
        group=group_fixture,
        uuid_processing="GENERATEUUID",
    )
    assert record["new_record_uuid"] is not None
    new_record = gn_client.get_record(record["new_record_uuid"])
    assert new_record is not None


def test_records_order(gn_client: GeonetworkClient):
    """Records should be ordered by changeDate asc"""
    records = gn_client.get_records()
    assert len(records) >= 2

    def get_change_date_from_record(record: Record) -> str:
        full_record = gn_client.get_record(record.uuid)
        info = extract_record_info(full_record, sources=gn_client.get_sources())
        return info.xpath("//changeDate/text()")[0]

    assert records == sorted(records, key=get_change_date_from_record)
