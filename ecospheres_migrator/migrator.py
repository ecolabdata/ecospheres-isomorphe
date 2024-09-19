import logging
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from ecospheres_migrator.batch import (
    FailureMigrateBatchRecord,
    FailureTransformBatchRecord,
    MigrateBatch,
    MigrateBatchRecord,
    MigrateMode,
    SkippedTransformBatchRecord,
    SkipReason,
    SuccessMigrateBatchRecord,
    SuccessTransformBatchRecord,
    TransformBatch,
    TransformBatchRecord,
)
from ecospheres_migrator.geonetwork import (
    GeonetworkClient,
    MetadataType,
    Record,
    WorkflowStage,
    extract_record_info,
)
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

    def transform(self, transformation: Path, selection: list[Record]) -> TransformBatch:
        """
        Transform data from a selection
        """
        log.debug(f"Transforming {selection} via {transformation}")
        sources = self.gn.get_sources()
        transform = Migrator.load_transformation(transformation)

        batch = TransformBatch()
        for r in selection:
            log.debug(f"Processing record {r.uuid}: md_type={r.md_type.name}, state={r.state}")
            original = self.gn.get_record(r.uuid)
            batch_record = TransformBatchRecord(
                url=self.gn.url,
                uuid=r.uuid,
                md_type=r.md_type,
                state=r.state,
                original=xml_to_string(original),
            )
            if r.md_type not in (MetadataType.METADATA, MetadataType.TEMPLATE):
                batch.add(
                    SkippedTransformBatchRecord(
                        **batch_record.__dict__,
                        reason=SkipReason.UNSUPPORTED_METADATA_TYPE,
                        info="",
                    )
                )
                continue
            if r.state and r.state.stage == WorkflowStage.WORKING_COPY:
                batch.add(
                    FailureTransformBatchRecord(
                        **batch_record.__dict__,
                        error="Record has a working copy",
                    )
                )
                continue
            try:
                # FIXME: extract_record_info() mutates original
                info = extract_record_info(original, sources)
                result = transform(original)
                result_str = xml_to_string(result)
                original_str = xml_to_string(original)
                if result_str != original_str:
                    batch.add(
                        SuccessTransformBatchRecord(
                            **batch_record.__dict__,
                            result=result_str,
                            info=xml_to_string(info),
                        )
                    )
                else:
                    batch.add(
                        SkippedTransformBatchRecord(
                            **batch_record.__dict__,
                            info=xml_to_string(info),
                            reason=SkipReason.NO_CHANGES,
                        )
                    )
            except Exception as e:
                batch.add(
                    FailureTransformBatchRecord(
                        **batch_record.__dict__,
                        error=str(e),
                    )
                )

        log.debug("Transformation done.")
        return batch

    def migrate(
        self,
        batch: TransformBatch,
        overwrite: bool = False,
        group: int | None = None,
        transform_job_id: str | None = None,
    ) -> MigrateBatch:
        log.debug(f"Migrating batch {batch} for {self.url} (overwrite={overwrite})")
        migrate_batch = MigrateBatch(
            mode=MigrateMode.OVERWRITE if overwrite else MigrateMode.CREATE,
            transform_job_id=transform_job_id,
        )
        for r in batch.successes():
            batch_record = MigrateBatchRecord(
                url=self.gn.url,
                source_uuid=r.uuid,
                md_type=r.md_type,
                source_content=r.original,
                target_content=r.result,
            )
            try:
                if overwrite:
                    self.gn.update_record(r.uuid, r.result, md_type=r.md_type)
                    migrate_batch.add(
                        SuccessMigrateBatchRecord(
                            **batch_record.__dict__,
                            target_uuid=r.uuid,
                        )
                    )
                else:
                    assert group is not None, "Group must be set when not overwriting"
                    # TODO: publish flag
                    new_record = self.gn.put_record(
                        r.uuid, r.result, md_type=r.md_type, group=group
                    )
                    migrate_batch.add(
                        SuccessMigrateBatchRecord(
                            **batch_record.__dict__,
                            target_uuid=new_record["new_record_uuid"],
                        )
                    )
            except Exception as e:
                migrate_batch.add(
                    FailureMigrateBatchRecord(
                        **batch_record.__dict__,
                        error=str(e),
                    )
                )
        log.debug("Migration done.")
        return migrate_batch

    @staticmethod
    def list_transformations(path: Path) -> list[Transformation]:
        return [Transformation(p) for p in path.glob("*.xsl")]

    @staticmethod
    def load_transformation(path: Path) -> etree.XSLT:
        xslt = etree.parse(path, parser=None)
        transform = etree.XSLT(xslt)
        return transform
