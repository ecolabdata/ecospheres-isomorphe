import re
from abc import abstractmethod
from dataclasses import asdict, dataclass
from enum import IntEnum, IntFlag, StrEnum, auto
from typing import Any, Iterator, Self, final, override

from lxml.etree import _ListErrorLog as ETListErrorLog

from isomorphe.geonetwork import MetadataType, WorkflowState


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


class RecordStatus(IntFlag):
    # Base statuses, ordered (lower is more important in terms of reviewing)
    FAILURE = auto()
    SKIPPED = auto()
    SUCCESS = auto()
    # Modifiers
    CHECK = auto()
    NOCHECK = auto()


@dataclass(kw_only=True)
class TransformBatchRecord:
    status: RecordStatus = RecordStatus(0)
    uuid: str
    md_type: MetadataType
    state: WorkflowState | None
    original: bytes
    url: str

    @property
    @abstractmethod
    def messages(self) -> list[str]:
        pass

    @classmethod
    def derive_from(cls, obj: "TransformBatchRecord", **changes: Any) -> Self:
        return cls(**(asdict(obj) | changes))


@final
@dataclass(kw_only=True)
class FailureTransformBatchRecord(TransformBatchRecord):
    error: str

    def __post_init__(self):
        # FIXME: can't be as no-init attr, won't deserialize properly?
        self.status = RecordStatus.FAILURE

    @property
    @override
    def messages(self) -> list[str]:
        return [self.error]


@dataclass(kw_only=True)
class AppliedTransformBatchRecord(TransformBatchRecord):
    log: TransformLog | None = None

    def __post_init__(self):
        # We can have several [isomorphe] tags in the log, as multiple XSLT templates can trigger on a single record.
        # For now, we only care if at least once of those is a :check to flag the record for verification.
        if self.log and any(["[isomorphe:check]" in log.message for log in self.log]):
            self.status |= RecordStatus.CHECK  # FIXME: typechecker isn't happy
        else:
            self.status |= RecordStatus.NOCHECK

    @property
    @override
    def messages(self) -> list[str]:
        if self.log:
            return [re.sub(r"\[isomorphe:[^]]*\]\s*", "", log.message) for log in self.log]
        else:
            return []


@final
@dataclass(kw_only=True)
class SuccessTransformBatchRecord(AppliedTransformBatchRecord):
    result: bytes

    def __post_init__(self):
        self.status = RecordStatus.SUCCESS
        super().__post_init__()


class SkipReasonMessage(StrEnum):
    """
    We don't use `SkipReason.value` for this because we pickle the reason
    and want to be able to change the associated message inbetween jobs.
    """

    UNSUPPORTED_METADATA_TYPE = "Type d'enregistrement non supporté."
    HAS_WORKING_COPY = "L'enregistrement a une copie de travail (working copy)."


class SkipReason(IntEnum):
    UNSUPPORTED_METADATA_TYPE = 2
    HAS_WORKING_COPY = 3


@final
@dataclass(kw_only=True)
class SkippedTransformBatchRecord(AppliedTransformBatchRecord):
    reason: SkipReason | None = None

    def __post_init__(self):
        self.status = RecordStatus.SKIPPED
        super().__post_init__()

    @property
    @override
    def messages(self) -> list[str]:
        if self.reason:
            # Explicit reason => takes precedence over log messages
            return [SkipReasonMessage[self.reason.name].value]
        else:
            return super().messages


class TransformBatch:
    def __init__(self, transformation: str):
        self.records: list[TransformBatchRecord] = []
        self.transformation = transformation

    def add(self, batch: TransformBatchRecord):
        self.records.append(batch)

    # FIXME: remove successes/failures/skipped
    def successes(self) -> list[SuccessTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, SuccessTransformBatchRecord)]

    def failures(self) -> list[FailureTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, FailureTransformBatchRecord)]

    def skipped(self) -> list[SkippedTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, SkippedTransformBatchRecord)]

    def select(self, statuses: list[RecordStatus]) -> list[TransformBatchRecord]:
        return [r for r in self.records if r.status in statuses]

    def __repr__(self):
        return f"TransformBatch({len(self.records)} records, {len(self.failures())} failures, {len(self.successes())} successes, {len(self.skipped())} skipped)"

    # TODO: drop
    # def to_mef(self):
    #     mef = MefArchive()
    #     for r in self.records:
    #         if isinstance(r, SuccessTransformBatchRecord):
    #             mef.add(r.uuid, r.result, r.info)
    #     return mef.finalize()


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
