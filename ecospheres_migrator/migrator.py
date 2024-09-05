import logging
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from ecospheres_migrator.batch import Batch, FailureBatchRecord, SuccessBatchRecord
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

    def transform(self, transformation: Path, selection: list[Record]) -> Batch:
        """
        Transform data from a selection
        """
        log.debug(f"Transforming {selection} via {transformation}")
        sources = self.gn.get_sources()
        transform = Migrator.load_transformation(transformation)

        batch = Batch()
        for r in selection:
            original = self.gn.get_record(r.uuid)
            try:
                info = extract_record_info(original, sources)
                result = transform(original, CoupledResourceLookUp="'disabled'")
                # TODO: check if result != original
                batch.add(
                    SuccessBatchRecord(
                        uuid=r.uuid,
                        template=r.template,
                        original=xml_to_string(original),
                        result=xml_to_string(result),
                        info=xml_to_string(info),
                    )
                )
            except Exception as e:
                batch.add(
                    FailureBatchRecord(
                        uuid=r.uuid,
                        template=r.template,
                        original=xml_to_string(original),
                        error=str(e),
                    )
                )

        log.debug("Transformation done.")
        return batch

    def migrate(self, batch: Batch, overwrite: bool = False, group: int | None = None):
        log.debug(
            f"Migrating batch ({len(batch.successes())}/{len(batch.failures())}) for {self.url} (overwrite={overwrite})"
        )
        failures = []
        for r in batch.successes():
            try:
                if overwrite:
                    self.gn.update_record(r.uuid, r.result, template=r.template)
                else:
                    assert group is not None
                    # TODO: publish flag
                    self.gn.put_record(r.uuid, r.result, template=r.template, group=group)
            except Exception:
                failures.append(r.uuid)

        if failures:
            # TODO: raise exception
            log.debug(f"Failures: {', '.join(failures)}")
        log.debug("Migration done.")

    @staticmethod
    def list_transformations(path: Path) -> list[Transformation]:
        return [Transformation(p) for p in path.glob("*.xsl")]

    @staticmethod
    def load_transformation(path: Path) -> etree.XSLT:
        xslt = etree.parse(path, parser=None)
        transform = etree.XSLT(xslt)
        return transform
