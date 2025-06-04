import json
from pathlib import Path

import pytest
import requests_mock
from conftest import XPATH_GN_DATE_STAMP, Fixture

from isomorphe.geonetwork import (
    GeonetworkClient,
    GeonetworkClientV3,
    GeonetworkClientV4,
    GeonetworkConnectionError,
    MetadataType,
    Record,
)

GN_FAKE_URL = "http://example.com/geonetwork/srv"


def test_client_v3(requests_mock: requests_mock.Mocker):
    requests_mock.post(f"{GN_FAKE_URL}/api/info", status_code=200)
    requests_mock.get(f"{GN_FAKE_URL}/api/site", json={"system/platform/version": "3.10.4"})
    client = GeonetworkClient.connect(GN_FAKE_URL)
    assert client.version == 3


def test_client_v4(requests_mock: requests_mock.Mocker):
    requests_mock.post(f"{GN_FAKE_URL}/api/info", status_code=200)
    requests_mock.get(f"{GN_FAKE_URL}/api/site", json={"system/platform/version": "4.4.5"})
    client = GeonetworkClient.connect(GN_FAKE_URL)
    assert client.version == 4


def test_client_unsupported(requests_mock: requests_mock.Mocker):
    requests_mock.post(f"{GN_FAKE_URL}/api/info", status_code=200)
    requests_mock.get(f"{GN_FAKE_URL}/api/site", json={"system/platform/version": "2.10"})
    with pytest.raises(GeonetworkConnectionError):
        GeonetworkClient.connect(GN_FAKE_URL)


def test_client_unknown(requests_mock: requests_mock.Mocker):
    requests_mock.post(f"{GN_FAKE_URL}/api/info", status_code=200)
    requests_mock.get(f"{GN_FAKE_URL}/api/site", json={})
    with pytest.raises(GeonetworkConnectionError):
        GeonetworkClient.connect(GN_FAKE_URL)


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


def test_records_order(gn_client: GeonetworkClient, clean_md_fixtures: list[Fixture]):
    """Records should be ordered by changeDate asc"""
    records = gn_client.get_records()
    assert len(records) >= 2

    def get_change_date_from_record(record: Record) -> str:
        r = gn_client.get_record(record.uuid, query={"withInfo": "true"})
        return r.xpath(XPATH_GN_DATE_STAMP, namespaces=r.nsmap)[0]

    assert records == sorted(records, key=get_change_date_from_record)


def test_get_records_v3(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV3("http://example.com/geonetwork/srv")

    results_pages = [
        json.load(Path(f"tests/fixtures/search-response-gn3-page-{i + 1}-of-3.json").open())
        for i in range(4)
    ]
    results_uuids = [x["geonet:info"]["uuid"] for p in results_pages for x in p.get("metadata", [])]

    requests_mock.get(f"{client.api}/q", response_list=[{"json": p} for p in results_pages])

    records = client.get_records()

    assert len(records) == 8
    assert [r.uuid for r in records] == results_uuids

    history = requests_mock.request_history
    assert len(history) == 4
    assert history[0].qs == {
        "_content_type": ["json"],
        "buildsummary": ["false"],
        "fast": ["index"],
        "sortby": ["changedate"],
        "sortorder": ["reverse"],
        "from": ["1"],
    }


def test_get_records_with_native_filters_v3(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV3("http://example.com/geonetwork/srv")
    requests_mock.get(f"{client.api}/q", json={})

    requests_mock.reset_mock()
    client.get_records(
        query={
            "type": "dataset",
            "_isHarvested": "y",
            "_isTemplate": "n",
        }
    )
    qs = requests_mock.request_history[0].qs
    assert qs["type"] == ["dataset"]
    assert qs["_isharvested"] == ["y"]
    assert qs["_istemplate"] == ["n"]


def test_get_records_with_abstract_filters_v3(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV3("http://example.com/geonetwork/srv")
    requests_mock.get(f"{client.api}/q", json={})

    requests_mock.reset_mock()
    client.get_records(
        query={
            "type": "dataset",
            "harvested": True,
            "template": "n",
        }
    )
    qs = requests_mock.request_history[0].qs
    assert qs["type"] == ["dataset"]
    assert qs["_isharvested"] == ["y"]
    assert qs["_istemplate"] == ["n"]


def test_get_records_v4(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV4("http://example.com/geonetwork/srv")

    results_pages = [
        json.load(Path(f"tests/fixtures/search-response-gn4-page-{i + 1}-of-3.json").open())
        for i in range(4)
    ]
    results_uuids = [x["_source"]["uuid"] for p in results_pages for x in p["hits"]["hits"]]

    requests_mock.post(
        f"{client.api}/search/records/_search",
        response_list=[{"json": p} for p in results_pages],
    )

    records = client.get_records()

    assert len(records) == 8
    assert [r.uuid for r in records] == results_uuids

    history = requests_mock.request_history
    assert len(history) == 4
    assert history[0].qs == {"bucket": ["metadata"]}
    assert history[0].json() == {
        "size": 20,
        "sort": [{"changeDate": "asc"}],
        "_source": [
            "uuid",
            "resourceTitleObject.default",
            "resourceType",
            "draft",
            "isTemplate",
            "mdStatus",
        ],
        "from": 0,
    }


def test_get_records_with_native_filters_v4(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV4("http://example.com/geonetwork/srv")
    requests_mock.post(f"{client.api}/search/records/_search", json={})

    client.get_records(
        query={
            "resourceType": "dataset",
            "isHarvested": "true",
            "isTemplate": "n",
        }
    )
    data = requests_mock.request_history[0].json()
    query = data["query"]["bool"]["filter"][0]["query_string"]["query"]
    assert query == "+resourceType:dataset +isHarvested:true +isTemplate:n"


def test_get_records_with_abstract_filters_v4(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV4("http://example.com/geonetwork/srv")
    requests_mock.post(f"{client.api}/search/records/_search", json={})

    client.get_records(
        query={
            "type": "dataset",
            "harvested": True,
            "template": "n",
        }
    )
    data = requests_mock.request_history[0].json()
    query = data["query"]["bool"]["filter"][0]["query_string"]["query"]
    assert query == "+resourceType:dataset +isHarvested:true +isTemplate:n"


def test_uuid_filter_v3():
    assert GeonetworkClientV3.uuid_filter([]) == {}
    assert GeonetworkClientV3.uuid_filter(["foo"]) == {"_uuid": "foo"}
    assert GeonetworkClientV3.uuid_filter(["foo", "bar"]) == {"_uuid": "foo or bar"}
    GeonetworkClientV3.uuid_filter(["foo", "bar", "baz"]) == {"_uuid": "foo or bar or baz"}


def test_uuid_filter_v4():
    assert GeonetworkClientV4.uuid_filter([]) == {}
    assert GeonetworkClientV4.uuid_filter(["foo"]) == {"uuid": '["foo"]'}
    assert GeonetworkClientV4.uuid_filter(["foo", "bar"]) == {"uuid": '["foo","bar"]'}
    assert GeonetworkClientV4.uuid_filter(["foo", "bar", "baz"]) == {"uuid": '["foo","bar","baz"]'}
