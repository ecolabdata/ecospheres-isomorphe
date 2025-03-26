import logging
from collections.abc import Sequence
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
    RecordStatus,
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
    ALWAYS_APPLY_SUFFIX = "~always"

    path: Path

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def display_name(self) -> str:
        return self.path.stem.removesuffix(Transformation.ALWAYS_APPLY_SUFFIX)

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
    def always_apply(self) -> bool:
        """
        When true, Transformation expects never to be skipped, so only its only
        states can be Success or Failure.
        """
        return self.path.stem.endswith(Transformation.ALWAYS_APPLY_SUFFIX)

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
        self.gn = GeonetworkClient.connect(url, username, password)

    @property
    def geonetwork_version(self):
        return self.gn.version

    def select(self, **kwargs) -> list[Record]:
        """
        Select data to migrate based on given params
        """
        log.info(f"Selecting with {kwargs}")

        # order matters, so we can override via __extra__
        query = {"harvested": False} | kwargs.get("filters")

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
            # TODO: remove extract_record_info
            # extract_record_info() mutates `original`
            # this must happen before we store `original` in the BatchRecord
            _ = extract_record_info(original, sources)
            batch_record = TransformBatchRecord(
                url=self.gn.url,
                uuid=r.uuid,
                md_type=r.md_type,
                state=r.state,
                original=xml_to_string(original),
            )
            if r.md_type not in (MetadataType.METADATA, MetadataType.TEMPLATE):
                batch.add(
                    SkippedTransformBatchRecord.derive_from(
                        batch_record,
                        reason=SkipReason.UNSUPPORTED_METADATA_TYPE,
                    )
                )
                continue
            if r.state and r.state.stage == WorkflowStage.WORKING_COPY:
                batch.add(
                    SkippedTransformBatchRecord.derive_from(
                        batch_record,
                        reason=SkipReason.HAS_WORKING_COPY,
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
                if result_str != original_str or transformation.always_apply:
                    batch.add(
                        SuccessTransformBatchRecord.derive_from(
                            batch_record,
                            result=result_str,
                            log=transform_log,
                        )
                    )
                else:
                    batch.add(
                        SkippedTransformBatchRecord.derive_from(
                            batch_record,
                            log=transform_log,
                        )
                    )
            except Exception as e:
                batch.add(
                    FailureTransformBatchRecord.derive_from(
                        batch_record,
                        error=str(e),
                    )
                )

        log.info("Transformation done.")
        return batch

    def migrate(
        self,
        batch: TransformBatch,
        statuses: Sequence[RecordStatus] = (RecordStatus.SUCCESS,),
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
        successes = [s for s in statuses if RecordStatus.SUCCESS in s]
        for r in batch.select(statuses=successes):
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
