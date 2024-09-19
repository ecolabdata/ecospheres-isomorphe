from conftest import Fixture

from ecospheres_migrator.geonetwork import GeonetworkClient, MetadataType


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
