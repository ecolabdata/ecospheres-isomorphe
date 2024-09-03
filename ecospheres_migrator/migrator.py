import logging
import time
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from ecospheres_migrator.batch import Batch
from ecospheres_migrator.geonetwork import GeonetworkClient, Record, extract_record_info
from ecospheres_migrator.util import xml_to_string

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


@dataclass
class Transformation:
    path: Path

    @property
    def name(self) -> str:
        return self.path.stem


class Migrator:
    def __init__(
        self, *, url: str, username: str | None = None, password: str | None = None
    ) -> None:
        self.url = url
        self.gn = GeonetworkClient(url, username, password)

    def select(self, **kwargs) -> list[Record]:
        """
        Select data to migrate based on given params
        """
        log.debug(f"Selecting with {kwargs}")

        query = {"_isHarvested": "n"}
        q = kwargs.get("query", "")
        query |= dict(p.split("=") for p in q.split(","))

        selection = self.gn.get_records(query=query)

        log.debug(f"Selection contains {len(selection)} items")
        return selection

    def transform(self, transformation: Path, selection: list[Record]) -> bytes:
        """
        Transform data from a selection
        """
        log.debug(f"Transforming {selection} via {transformation}")
        sources = self.gn.get_sources()
        transform = Migrator.load_transformation(transformation)

        batch = Batch()
        for s in selection:
            original = self.gn.get_record(s.uuid)
            try:
                info = extract_record_info(original, sources)
                result = transform(original, CoupledResourceLookUp="'disabled'")
                # TODO: check if result != original
                batch.add_success(
                    uuid=s.uuid,
                    original=xml_to_string(original),
                    result=xml_to_string(result),
                    info=xml_to_string(info),
                )
            except Exception as e:
                batch.add_failure(uuid=s.uuid, original=xml_to_string(original), error=str(e))

        log.debug("Transformation done.")
        return batch

    def migrate(self, batch: Batch):
        log.debug(
            f"Migrating batch ({len(batch.successes())}/{len(batch.failures())}) for {self.url}"
        )
        for r in batch.successes():
            time.sleep(1)
        log.debug("Migration done.")

    @staticmethod
    def list_transformations(path: Path) -> list[Transformation]:
        return [Transformation(p) for p in path.glob("*.xsl")]

    @staticmethod
    def load_transformation(path: Path) -> etree.XSLT:
        xslt = etree.parse(path, parser=None)
        transform = etree.XSLT(xslt)
        return transform
