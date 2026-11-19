import json
from pathlib import Path

import pytest
import requests_mock
from conftest import XPATH_GN_DATE_STAMP, Fixture
from requests.cookies import RequestsCookieJar

from isomorphe.geonetwork import (
    GeonetworkClient,
    GeonetworkClientV3,
    GeonetworkClientV4,
    GeonetworkConnectionError,
    MetadataType,
    Record,
)
from isomorphe.xml import string_to_xml, xpath_eval

GN_FAKE_DOMAIN = "example.com"
GN_FAKE_PATH = "/geonetwork"
GN_FAKE_URL = f"http://{GN_FAKE_DOMAIN}{GN_FAKE_PATH}/srv"


def connect(
    requests_mock: requests_mock.Mocker,
    version: str | None = "4.4.5",
    needs_auth: bool = False,
    cookies: RequestsCookieJar | None = None,
):
    # GeonetworkClient._server_version(...)
    json = {"system/platform/version": version} if version else {}
    requests_mock.get(f"{GN_FAKE_URL}/api/site", json=json)
    # client.authenticate(...)
    status_code = 403 if needs_auth else 200
    requests_mock.post(f"{GN_FAKE_URL}/api/info", status_code=status_code, cookies=cookies)

    return GeonetworkClient.connect(GN_FAKE_URL)


def xsrf_cookies(paths: list[str]) -> RequestsCookieJar:
    cookies = RequestsCookieJar()
    for path in paths:
        cookies.set("XSRF-TOKEN", f"token{path}", domain=GN_FAKE_DOMAIN, path=path)
    return cookies


def test_client_v3(requests_mock: requests_mock.Mocker):
    client = connect(requests_mock, version="3.10.4")
    assert client.version == 3


def test_client_v4(requests_mock: requests_mock.Mocker):
    client = connect(requests_mock, version="4.4.5")
    assert client.version == 4


def test_client_unsupported(requests_mock: requests_mock.Mocker):
    with pytest.raises(GeonetworkConnectionError):
        connect(requests_mock, version="2.10")


def test_client_unknown(requests_mock: requests_mock.Mocker):
    with pytest.raises(GeonetworkConnectionError):
        connect(requests_mock, version=None)


def test_xsrf_token_present(requests_mock: requests_mock.Mocker):
    client = connect(requests_mock, needs_auth=True, cookies=xsrf_cookies([GN_FAKE_PATH]))
    assert client.session.headers["X-XSRF-TOKEN"] == f"token{GN_FAKE_PATH}"


def test_xsrf_token_missing_required(requests_mock: requests_mock.Mocker):
    with pytest.raises(GeonetworkConnectionError):
        connect(requests_mock, needs_auth=True)


def test_xsrf_token_missing_optional(requests_mock: requests_mock.Mocker):
    # accept missing token if the authentication POST request didn't return an error
    client = connect(requests_mock, needs_auth=False)
    assert "X-XSRF-TOKEN" not in client.session.headers


def test_xsrf_token_other_paths(requests_mock: requests_mock.Mocker):
    # don't leak tokens from other paths (including near-matches)
    with pytest.raises(GeonetworkConnectionError):
        connect(
            requests_mock,
            needs_auth=True,
            cookies=xsrf_cookies(["/geo", "/geonetwork2", "/datahub"]),
        )


def test_xsrf_token_subpath(requests_mock: requests_mock.Mocker):
    # a "/" token should be valid for "/geonetwork" (and "/whatever"...)
    client = connect(requests_mock, needs_auth=True, cookies=xsrf_cookies(["/"]))
    assert client.session.headers["X-XSRF-TOKEN"] == "token/"


@pytest.mark.parametrize(
    "cookies_list", [[GN_FAKE_PATH, "/"], ["/", GN_FAKE_PATH]], ids=["first", "last"]
)
def test_xsrf_token_multiple(requests_mock: requests_mock.Mocker, cookies_list):
    # most specific path wins
    client = connect(requests_mock, needs_auth=True, cookies=xsrf_cookies(cookies_list))
    assert client.session.headers["X-XSRF-TOKEN"] == f"token{GN_FAKE_PATH}"


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
        content = gn_client.get_record(record.uuid, query={"withInfo": "true"})
        return xpath_eval(string_to_xml(content), XPATH_GN_DATE_STAMP)[0].string_value

    assert records == sorted(records, key=get_change_date_from_record, reverse=True)


def test_get_records_v3(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV3("http://example.com/geonetwork/srv")

    results_pages = [
        json.load(Path(f"tests/fixtures/search-response-gn3-page-{i + 1}-of-3.json").open())
        for i in range(4)
    ]
    results_uuids = [
        x["geonet:info"]["uuid"]
        for p in results_pages
        for x in p.get("metadata", [])
        if x["geonet:info"].get("edit") == "true"
    ]

    requests_mock.get(f"{client.api}/q", response_list=[{"json": p} for p in results_pages])

    records = client.get_records()

    assert len(records) == 7
    assert [r.uuid for r in records] == results_uuids

    history = requests_mock.request_history
    assert len(history) == 4
    assert history[0].qs == {
        "_content_type": ["json"],
        "buildsummary": ["false"],
        "fast": ["index"],
        "sortby": ["changedate"],
        "from": ["1"],
        "_istemplate": ["y or n"],
    }


def test_get_records_with_native_filters_v3(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV3("http://example.com/geonetwork/srv")
    requests_mock.get(f"{client.api}/q", json={})

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
    results_uuids = [
        x["_source"]["uuid"] for p in results_pages for x in p["hits"]["hits"] if x.get("edit")
    ]

    requests_mock.post(
        f"{client.api}/search/records/_search",
        response_list=[{"json": p} for p in results_pages],
    )

    records = client.get_records()

    assert len(records) == 7
    assert [r.uuid for r in records] == results_uuids

    history = requests_mock.request_history
    assert len(history) == 4
    assert history[0].qs == {"bucket": ["metadata"]}
    assert history[0].json() == {
        "size": 20,
        "sort": [{"changeDate": "desc"}],
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


def test_get_records_param_template_v3(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV3("http://example.com/geonetwork/srv")
    requests_mock.get(f"{client.api}/q", json={})

    client.get_records(query={})
    qs = requests_mock.request_history[0].qs
    assert qs["_istemplate"] == ["y or n"]

    requests_mock.reset_mock()
    client.get_records(query={"template": "y"})
    qs = requests_mock.request_history[0].qs
    assert qs["_istemplate"] == ["y"]

    requests_mock.reset_mock()
    client.get_records(query={"template": "n"})
    qs = requests_mock.request_history[0].qs
    assert qs["_istemplate"] == ["n"]


def test_get_records_param_template_v4(requests_mock: requests_mock.Mocker):
    client = GeonetworkClientV4("http://example.com/geonetwork/srv")
    requests_mock.post(f"{client.api}/search/records/_search", json={})

    client.get_records(query={})
    data = requests_mock.request_history[0].json()
    assert "query" not in data

    requests_mock.reset_mock()
    client.get_records(query={"template": "y"})
    data = requests_mock.request_history[0].json()
    query = data["query"]["bool"]["filter"][0]["query_string"]["query"]
    assert query == "+isTemplate:y"

    requests_mock.reset_mock()
    client.get_records(query={"template": "n"})
    data = requests_mock.request_history[0].json()
    query = data["query"]["bool"]["filter"][0]["query_string"]["query"]
    assert query == "+isTemplate:n"


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
