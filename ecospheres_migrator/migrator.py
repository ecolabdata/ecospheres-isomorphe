import logging
import time

from lxml import etree

from ecospheres_migrator.geonetwork import GeonetworkClient, Record, MefArchive, extract_record_info

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


class Migrator:

    TRANSFORMATIONS = [
        {
            "id": "all",
            "label": "Toutes les transformations",
            "xslt": None
        },
        {
            "id": "license",
            "label": "Champ licence",
            "xslt": "licence.xslt",
        },
        {
            "id": "error",
            "label": "Retournera une erreur",
            "xslt": "error.xslt",
        },
    ]

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

        query = {
            '_isHarvested': 'n'
        }
        q = kwargs.get('query', '')
        query = dict(p.split('=') for p in q.split(','))

        selection = self.gn.get_records(query=query)

        log.debug(f"Selection contains {len(selection)} items")
        return selection

    def transform(self, transformation: dict, selection: list[Record]) -> bytes:
        """
        Transform data from a selection
        """
        log.debug(f"Transforming {selection} via {transformation}")
        if transformation["id"] == "error":
            raise Exception("You asked for an error, here you are!")

        sources = self.gn.get_sources()

        # TODO: load transformation xsl

        mef = MefArchive()
        for s in selection:
            record = self.gn.get_record(s.uuid)
            info = extract_record_info(record, sources)
            # TODO: apply transformation
            mef.add(s.uuid, record, info)

        log.debug("Transformation done.")
        return mef.finalize()

    def migrate(self, output_file: bytes):
        log.debug(f"Migrating for {self.url}")
        time.sleep(10)
        log.debug("Migration done.")
