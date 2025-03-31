import logging
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Final

import pytest
import requests

from isomorphe.geonetwork import GeonetworkClient, MetadataType
from isomorphe.migrator import Migrator

log = logging.getLogger(__name__)

GN_TEST_URL: Final = "http://localhost:57455/geonetwork/srv"
GN_TEST_USER: Final = "admin"
GN_TEST_PASSWORD: Final = "admin"

XPATH_ISO_DATE_STAMP = "/gmd:MD_Metadata/gmd:dateStamp/gco:DateTime/text()"


@dataclass(kw_only=True)
class Fixture:
    uuid: str
    name: str
    content: bytes


@pytest.fixture(scope="session", autouse=True)
def wait_for_gn():
    def is_service_ready(url: str):
        try:
            response = requests.get(url)
            return response.status_code == 200
        except requests.RequestException:
            return False

    url: str = f"{GN_TEST_URL}/api/info?_content_type=json&type=me"
    max_retries: int = 30
    retry_delay: int = 1  # seconds

    for attempt in range(max_retries):
        if is_service_ready(url):
            log.info(f"Geonetwork is ready after {attempt + 1} attempt(s).")
            break
        else:
            log.info(f"Attempt {attempt + 1}: Geonetwork not ready yet. Retrying...")
            sleep(retry_delay)

    assert is_service_ready(url), "Geonetwork failed to become ready within the timeout period."


@pytest.fixture(scope="session")
def gn_client(wait_for_gn) -> GeonetworkClient:
    return GeonetworkClient.connect(f"{GN_TEST_URL}", GN_TEST_USER, GN_TEST_PASSWORD)


def seed_fixtures(gn_client: GeonetworkClient, group_fixture: int) -> list[Fixture]:
    """
    (Re)create records from fixtures directory.
    If a record with the same UUID already exists it will be deleted and recreated.
    Naming pattern of fixture files is: `<prefix>_<uuid>.xml` where prefix is the catalog
    and uuid is the record UUID.
    """
    fixtures = []
    fixtures_files = Path("tests/fixtures").glob("*.xml")

    # remove records from test-group (used for duplicated records)
    group_records = gn_client.get_records(query={"facet.q": f"groupOwner/{group_fixture}"})
    for record in group_records:
        log.debug(f"Deleting record {record.uuid}...")
        gn_client.delete_record(record.uuid)

    # create records from fixtures directory
    for fixture in fixtures_files:
        uuid = fixture.stem.split("--")[1]
        try:
            gn_client.get_record(uuid)
        except requests.exceptions.HTTPError:
            pass
        else:
            gn_client.delete_record(uuid)
        with fixture.open("rb") as ff:
            log.debug(f"Creating new record {uuid}...")
            content = ff.read()
            gn_client.put_record(
                uuid="test-uuid",
                metadata=content,
                md_type=MetadataType.METADATA,
                group=None,
                uuid_processing="NOTHING",
            )
            fixtures.append(Fixture(uuid=uuid, name=fixture.stem, content=content))

    total_records = gn_client.get_records()
    assert len(total_records) == len(fixtures), "GN test instance records do not match fixtures"

    return fixtures


@pytest.fixture(scope="session", autouse=True)
def md_fixtures(gn_client: GeonetworkClient, group_fixture: int) -> list[Fixture]:
    log.debug("Seeding fixtures...")
    return seed_fixtures(gn_client, group_fixture)


@pytest.fixture(scope="session", autouse=True)
def group_fixture(gn_client: GeonetworkClient) -> int:
    log.debug("Creating group...")
    group_name = "test-group"
    groups = gn_client.get_groups()
    if any(group["name"] == group_name for group in groups):
        log.debug("Group already exists, skipping creation...")
        group = next(group for group in groups if group["name"] == group_name)
        return group["id"]
    return gn_client.add_group(group_name)


@pytest.fixture
def clean_md_fixtures(gn_client: GeonetworkClient, group_fixture: int) -> list[Fixture]:
    """Force fixtures recreation when used explicitely"""
    log.debug("Cleaning fixtures...")
    return seed_fixtures(gn_client, group_fixture)


@pytest.fixture
def migrator() -> Migrator:
    return Migrator(url=GN_TEST_URL, username=GN_TEST_USER, password=GN_TEST_PASSWORD)
