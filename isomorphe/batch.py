from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Iterator

from lxml.etree import _ListErrorLog as ETListErrorLog

from isomorphe.geonetwork import MefArchive, MetadataType, WorkflowState


@dataclass(kw_only=True)
class TransformLogItem:
    message: str
    line: int
    column: int
    domain_name: str
    domain: int
    type_name: str
    type: int
    level_name: str
    level: int
    filename: str


class TransformLog:
    """An iterator over a list of TransformLogItem, defined from a lxml.etree._ListErrorLog."""

    errors: list[TransformLogItem]

    def __init__(self, error_log: ETListErrorLog):
        self.errors = [
            TransformLogItem(
                message=e.message,
                line=e.line,
                column=e.column,
                domain_name=e.domain_name,
                domain=e.domain,
                type_name=e.type_name,
                type=e.type,
                level_name=e.level_name,
                level=e.level,
                filename=e.filename,
            )
            for e in error_log.filter_from_warnings()
        ]

    def __iter__(self) -> Iterator[TransformLogItem]:
        return iter(self.errors)

    def __getitem__(self, index: int) -> TransformLogItem:
        return self.errors[index]

    def __len__(self) -> int:
        return len(self.errors)


@dataclass(kw_only=True)
class TransformBatchRecord:
    uuid: str
    md_type: MetadataType
    state: WorkflowState | None
    original: bytes
    url: str

    def needs_check(self) -> bool:
        if not self.log:
            return False
        return any(["CHECK" in log.message for log in self.log])

    @property
    def status(self) -> int:
        return 0

    # TODO: strip status codes
    @property
    def messages(self) -> list[str]:
        return []


@dataclass(kw_only=True)
class SuccessTransformBatchRecord(TransformBatchRecord):
    result: bytes
    info: str
    log: TransformLog | None = None
    # has_diff == False can happen when Transformation.always_apply
    has_diff: bool = True

    @property
    def status(self) -> int:
        return 1

    @property
    def foobar(self) -> str:
        return "apply-check" if self.needs_check() else "apply"

    @property
    def messages(self) -> list[str]:
        return [log.message for log in self.log] if self.log else []


@dataclass(kw_only=True)
class FailureTransformBatchRecord(TransformBatchRecord):
    error: str

    @property
    def status(self) -> int:
        return 2

    @property
    def foobar(self) -> str:
        return "error"

    @property
    def messages(self) -> list[str]:
        return [self.error]


class SkipReasonMessage(StrEnum):
    """
    We don't use `SkipReason.value` for this because we pickle the reason
    and want to be able to change the associated message inbetween jobs.
    """

    NO_CHANGES = "Pas de modification lors de la transformation."
    UNSUPPORTED_METADATA_TYPE = "Type d'enregistrement non supporté."
    HAS_WORKING_COPY = "L'enregistrement a une copie de travail (working copy)."


class SkipReason(IntEnum):
    NO_CHANGES = 1
    UNSUPPORTED_METADATA_TYPE = 2
    HAS_WORKING_COPY = 3


@dataclass(kw_only=True)
class SkippedTransformBatchRecord(TransformBatchRecord):
    reason: SkipReason | None = None
    info: str
    log: TransformLog | None = None

    @property
    def status(self) -> int:
        return 3

    @property
    def foobar(self) -> str:
        return "ignore-check" if self.needs_check() else "ignore"

    @property
    def messages(self) -> list[str]:
        if self.reason:
            return [SkipReasonMessage[self.reason.name].value]
        elif self.log:
            return [log.message for log in self.log]
        else:
            return []


class TransformBatch:
    def __init__(self, transformation: str):
        self.records: list[TransformBatchRecord] = []
        self.transformation = transformation

    def add(self, batch: TransformBatchRecord):
        self.records.append(batch)

    def successes(self) -> list[SuccessTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, SuccessTransformBatchRecord)]

    def failures(self) -> list[FailureTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, FailureTransformBatchRecord)]

    def skipped(self) -> list[SkippedTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, SkippedTransformBatchRecord)]

    def select(self, only_statuses: list[str] | None = None) -> list[TransformBatchRecord]:
        if only_statuses is None:
            return self.records
        return [r for r in self.records if r.foobar in only_statuses]

    def __repr__(self):
        return f"TransformBatch({len(self.records)} records, {len(self.failures())} failures, {len(self.successes())} successes, {len(self.skipped())} skipped)"

    # FIXME: needed?
    def to_mef(self):
        mef = MefArchive()
        for r in self.records:
            if isinstance(r, SuccessTransformBatchRecord):
                mef.add(r.uuid, r.result, r.info)
        return mef.finalize()


@dataclass(kw_only=True)
class MigrateBatchRecord:
    source_uuid: str
    source_content: bytes
    target_content: bytes
    md_type: MetadataType
    url: str


@dataclass(kw_only=True)
class SuccessMigrateBatchRecord(MigrateBatchRecord):
    target_uuid: str


@dataclass(kw_only=True)
class FailureMigrateBatchRecord(MigrateBatchRecord):
    error: str


class MigrateMode(StrEnum):
    CREATE = "create"
    OVERWRITE = "overwrite"


class MigrateBatch:
    def __init__(self, mode: MigrateMode, transform_job_id: str | None):
        self.records: list[MigrateBatchRecord] = []
        self.mode = mode
        self.transform_job_id = transform_job_id

    def add(self, batch: MigrateBatchRecord):
        self.records.append(batch)

    def successes(self) -> list[SuccessMigrateBatchRecord]:
        return [r for r in self.records if isinstance(r, SuccessMigrateBatchRecord)]

    def failures(self) -> list[FailureMigrateBatchRecord]:
        return [r for r in self.records if isinstance(r, FailureMigrateBatchRecord)]

    def __repr__(self):
        return f"MigrateBatch({len(self.records)} records, {len(self.failures())} failures, {len(self.successes())} successes)"
