import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

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
)
from isomorphe.geonetwork import (
    GeonetworkClient,
    MetadataType,
    Record,
    WorkflowStage,
)
from isomorphe.xml import (
    format_xml,
    path_to_xml,
    string_to_xml,
    xml_to_string,
    xpath_eval,
    xslt_apply,
)

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
        standard = self.path.parent.stem
        stem = self.path.stem
        return str(Path(standard, stem))

    @property
    def display_name(self) -> str:
        return self.path.stem.removesuffix(Transformation.ALWAYS_APPLY_SUFFIX)

    @cached_property
    def params(self) -> list[TransformationParam]:
        params = []
        for node in xpath_eval(path_to_xml(self.path), "/xsl:stylesheet/xsl:param"):
            param_info = TransformationParam(
                name=node.get_attribute_value("name"),
                default_value=(node.get_attribute_value("select") or "").strip(
                    "'"
                ),  # remove string literal single quotes
                required=node.get_attribute_value("required") == "yes",
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

    def transform(self, content: str, params: dict[str, Any] | None = None) -> tuple[str, list]:
        node, messages = xslt_apply(string_to_xml(content), path_to_xml(self.path), params)
        return xml_to_string(node), messages


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
        transformation_params: dict[str, str] | None = None,
    ) -> TransformBatch[TransformBatchRecord]:
        """
        Transform data from a selection
        """
        log.info(f"Transforming {selection} via {transformation}")

        batch = TransformBatch[TransformBatchRecord](transformation=transformation.name)
        for r in selection:
            log.debug(f"Processing record {r.uuid}: md_type={r.md_type.name}, state={r.state}")

            base_record = TransformBatchRecord(
                url=self.gn.url,
                uuid=r.uuid,
                md_type=r.md_type,
                state=r.state,
                original_content=None,
            )

            try:
                raw = self.gn.get_record(r.uuid)
                original = format_xml(raw)
            except Exception as e:
                batch.append(
                    FailureTransformBatchRecord.derive_from(
                        base_record,
                        error=str(e),
                    )
                )
                continue

            batch_record = TransformBatchRecord.derive_from(
                base_record,
                original_content=original,
            )

            if r.md_type not in (MetadataType.METADATA, MetadataType.TEMPLATE):
                batch.append(
                    SkippedTransformBatchRecord.derive_from(
                        batch_record,
                        reason=SkipReason.UNSUPPORTED_METADATA_TYPE,
                    )
                )
                continue

            if r.state and r.state.stage == WorkflowStage.WORKING_COPY:
                batch.append(
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
                transformed, messages = transformation.transform(original, transformation_params)
                if transformed != original or transformation.always_apply:
                    batch.append(
                        SuccessTransformBatchRecord.derive_from(
                            batch_record,
                            transformed_content=transformed,
                            log=messages,
                        )
                    )
                else:
                    batch.append(
                        SkippedTransformBatchRecord.derive_from(
                            batch_record,
                            log=messages,
                        )
                    )
            except Exception as e:
                batch.append(
                    FailureTransformBatchRecord.derive_from(
                        batch_record,
                        error=str(e),
                    )
                )

        log.info("Transformation done.")
        return batch

    def migrate(
        self,
        # TODO: pre-filter so it's TransformBatch[SuccessTransformBatchRecord]
        batch: TransformBatch[TransformBatchRecord],
        statuses: Sequence[int] | None = None,
        overwrite: bool = False,
        group: int | None = None,
        update_date_stamp: bool = True,
        transform_job_id: str | None = None,
    ) -> MigrateBatch[MigrateBatchRecord]:
        log.info(f"Migrating batch {batch} for {self.url} (overwrite={overwrite})")
        migrate_batch = MigrateBatch[MigrateBatchRecord](
            mode=MigrateMode.OVERWRITE if overwrite else MigrateMode.CREATE,
            transform_job_id=transform_job_id,
        )
        for r in batch.successes().filter_status(statuses):
            batch_record = MigrateBatchRecord(
                url=self.gn.url,
                uuid=r.uuid,
                md_type=r.md_type,
                original_content=r.original_content,
                transformed_content=r.transformed_content,
            )
            try:
                if overwrite:
                    self.gn.update_record(
                        r.uuid,
                        r.transformed_content,
                        md_type=r.md_type,
                        update_date_stamp=update_date_stamp,
                    )
                    migrate_batch.append(
                        SuccessMigrateBatchRecord.derive_from(batch_record, transformed_uuid=r.uuid)
                    )
                else:
                    assert group is not None, "Group must be set when not overwriting"
                    # TODO: publish flag
                    new_record = self.gn.put_record(
                        r.uuid, r.transformed_content, md_type=r.md_type, group=group
                    )
                    migrate_batch.append(
                        SuccessMigrateBatchRecord.derive_from(
                            batch_record, transformed_uuid=new_record["new_record_uuid"]
                        )
                    )
            except Exception as e:
                migrate_batch.append(
                    FailureMigrateBatchRecord.derive_from(batch_record, error=str(e))
                )
        log.info("Migration done.")
        return migrate_batch

    @staticmethod
    def list_transformations(root_path: Path) -> list[Transformation]:
        return [Transformation(p) for p in sorted(root_path.glob("*.xsl"))]

    @staticmethod
    def get_transformation(name: str, root_path: Path) -> Transformation:
        return Transformation(root_path / f"{name}.xsl")
