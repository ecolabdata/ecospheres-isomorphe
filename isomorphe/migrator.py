import logging
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from lxml import etree

from isomorphe.batch import (
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
    TransformLog,
)
from isomorphe.geonetwork import (
    GeonetworkClient,
    MetadataType,
    Record,
    WorkflowStage,
    extract_record_info,
)
from isomorphe.util import xml_to_string

log = logging.getLogger(__name__)


@dataclass(kw_only=True)
class TransformationParam:
    name: str
    default_value: str
    required: bool


@dataclass
class Transformation:
    path: Path

    @property
    def name(self) -> str:
        return self.path.stem

    @cached_property
    def params(self) -> list[TransformationParam]:
        xslt = etree.parse(self.path, parser=None)
        root = xslt.getroot()
        params = []
        for param in root.xpath("/xsl:stylesheet/xsl:param", namespaces=root.nsmap):
            param_info = TransformationParam(
                name=param.attrib["name"],
                # remove string literal single quotes, they'll be added back by etree.XSLT.strparam()
                default_value=param.attrib.get("select", "").strip("'"),
                required=param.attrib.get("required") == "yes",
            )
            params.append(param_info)
        return params

    @property
    def transform(self) -> etree.XSLT:
        xslt = etree.parse(self.path, parser=None)
        transform = etree.XSLT(xslt)
        return transform


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
        log.info(f"Selecting with {kwargs}")

        query = {"_isHarvested": "n"}
        q = kwargs.get("query", "")
        query |= dict(p.split("=") for p in q.split(","))

        selection = self.gn.get_records(query=query)

        log.info(f"Selection contains {len(selection)} items")
        return selection

    def transform(
        self,
        transformation: Transformation,
        selection: list[Record],
        transformation_params: dict[str, str] = {},
    ) -> TransformBatch:
        """
        Transform data from a selection
        """
        log.info(f"Transforming {selection} via {transformation}")
        sources = self.gn.get_sources()

        batch = TransformBatch(transformation=transformation.name)
        for r in selection:
            log.debug(f"Processing record {r.uuid}: md_type={r.md_type.name}, state={r.state}")
            original = self.gn.get_record(r.uuid)
            # FIXME: extract_record_info() mutates `original`
            # In the mean time, this must happen before we store `original` in the BatchRecord
            info = extract_record_info(original, sources)
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
                    SkippedTransformBatchRecord(
                        **batch_record.__dict__,
                        reason=SkipReason.HAS_WORKING_COPY,
                        info="",
                    )
                )
                continue
            try:
                log.debug(
                    f"Applying transformation {transformation.name} to {r.uuid} with params {transformation_params}"
                )
                transformation_params_quoted = {
                    k: etree.XSLT.strparam(v)  # type: ignore (stub is wrong for strparam)
                    for k, v in transformation_params.items()
                }
                transformer = transformation.transform
                result = transformer(original, **transformation_params_quoted)
                transform_log = TransformLog(transformer.error_log)
                result_str = xml_to_string(result)
                original_str = xml_to_string(original)
                if result_str != original_str:
                    batch.add(
                        SuccessTransformBatchRecord(
                            **batch_record.__dict__,
                            result=result_str,
                            info=xml_to_string(info),
                            log=transform_log,
                        )
                    )
                else:
                    batch.add(
                        SkippedTransformBatchRecord(
                            **batch_record.__dict__,
                            info=xml_to_string(info),
                            reason=SkipReason.NO_CHANGES,
                            log=transform_log,
                        )
                    )
            except Exception as e:
                batch.add(
                    FailureTransformBatchRecord(
                        **batch_record.__dict__,
                        error=str(e),
                    )
                )

        log.info("Transformation done.")
        return batch

    def migrate(
        self,
        batch: TransformBatch,
        overwrite: bool = False,
        group: int | None = None,
        update_date_stamp: bool = True,
        transform_job_id: str | None = None,
    ) -> MigrateBatch:
        log.info(f"Migrating batch {batch} for {self.url} (overwrite={overwrite})")
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
                    self.gn.update_record(
                        r.uuid, r.result, md_type=r.md_type, update_date_stamp=update_date_stamp
                    )
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
        log.info("Migration done.")
        return migrate_batch

    @staticmethod
    def list_transformations(root_path: Path) -> list[Transformation]:
        return [Transformation(p) for p in sorted(root_path.glob("*.xsl"))]

    @staticmethod
    def get_transformation(name: str, root_path: Path) -> Transformation:
        return Transformation(root_path / f"{name}.xsl")
