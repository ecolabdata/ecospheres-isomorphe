import logging
import time

from dataclasses import dataclass
from lxml import etree
from pathlib import Path

from ecospheres_migrator.geonetwork import GeonetworkClient, Record, MefArchive, extract_record_info

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

        query = {'_isHarvested': 'n'}
        q = kwargs.get('query', '')
        query |= dict(p.split('=') for p in q.split(','))

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

        mef = MefArchive()
        for s in selection:
            original = self.gn.get_record(s.uuid)
            info = extract_record_info(original, sources)
            result = transform(original, CoupledResourceLookUp="'disabled'")
            mef.add(s.uuid, result, info)

        log.debug("Transformation done.")
        return mef.finalize()

    def migrate(self, output_file: bytes):
        log.debug(f"Migrating for {self.url}")
        time.sleep(10)
        log.debug("Migration done.")

    @staticmethod
    def list_transformations(path: Path) -> list[Transformation]:
        return [Transformation(p) for p in path.glob("*.xsl")]

    @staticmethod
    def load_transformation(path: Path) -> etree.XSLT:
        xslt = etree.parse(path, parser=None)
        transform = etree.XSLT(xslt)
        return transform
