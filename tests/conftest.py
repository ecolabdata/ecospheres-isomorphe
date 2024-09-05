import logging
from pathlib import Path
from time import sleep
from typing import Final

import pytest
import requests

from ecospheres_migrator.geonetwork import GeonetworkClient

log = logging.getLogger(__name__)

GN_TEST_URL: Final = "http://localhost:8081/geonetwork/srv"


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
    return GeonetworkClient(f"{GN_TEST_URL}", "admin", "admin")


def seed_fixtures(gn_client: GeonetworkClient):
    """
    (Re)create records from fixtures directory.
    If a record with the same UUID already exists it will be deleted and recreated.
    Naming pattern of fixture files is: `<prefix>_<uuid>.xml` where prefix is the catalog
    and uuid is the record UUID.
    """
    fixtures = Path("tests/fixtures").glob("*.xml")
    for fixture in fixtures:
        uuid = fixture.stem.split("_")[1]
        try:
            gn_client.get_record(uuid)
        except requests.exceptions.HTTPError:
            pass
        else:
            gn_client.delete_record(uuid)
        with fixture.open() as ff:
            log.debug(f"Creating new record {uuid}...")
            gn_client.duplicate_record(
                uuid="test-uuid", metadata=ff.read(), template=False, group=None, uuid_processing="NOTHING"
            )


@pytest.fixture(scope="session", autouse=True)
def md_fixtures(gn_client: GeonetworkClient):
    log.debug("Seeding fixtures...")
    seed_fixtures(gn_client)


@pytest.fixture
def clean_md_fixtures(gn_client: GeonetworkClient):
    """Force fixtures recreation when used explicitely"""
    log.debug("Cleaning fixtures...")
    seed_fixtures(gn_client)
