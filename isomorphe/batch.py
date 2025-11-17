import re
from abc import abstractmethod
from collections import UserDict, UserList, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import IntEnum, StrEnum
from typing import Any, ClassVar, Self, override

from isomorphe.geonetwork import MetadataType, WorkflowState


@dataclass(kw_only=True, frozen=True, order=True)
class RecordStatus:
    priority: int  # first because order=True
    code: int
    label: str = "-"
    icon: str = "-"

    @property
    def legend(self) -> str:
        return f"{self.icon} {self.label}"


class RecordStatuses(UserDict[int, RecordStatus]):
    def __init__(self, *args: RecordStatus):
        super().__init__({s.code: s for s in args})


@dataclass(kw_only=True)
class BatchRecord:
    # Don't change STATUS_CODE once assigned or it'll mess up pickled jobs
    STATUS_CODE: ClassVar[int]
    uuid: str
    md_type: MetadataType
    original_content: str | None
    url: str  # TODO: store at Batch level

    @property
    def status_code(self) -> int:
        return self.status_code_for(**asdict(self))

    @classmethod
    def status_code_for(cls, **kwargs) -> int:
        return cls.STATUS_CODE

    @classmethod
    def derive_from(cls, obj: "BatchRecord", **changes: Any) -> Self:
        return cls(**(asdict(obj) | changes))


class Batch[R: BatchRecord](UserList[R]):
    RECORD_STATUSES: ClassVar[RecordStatuses]

    @property
    def records(self) -> list[R]:
        return self.data

    def status_info(self, status_code: int) -> RecordStatus:
        return self.RECORD_STATUSES[status_code]

    @override
    def __repr__(self):
        stats = defaultdict(int)
        for r in self.records:
            stats[self.status_info(r.status_code).label] += 1
        return f"{type(self).__name__}({len(self.records)} records, {dict(sorted(stats.items()))})"


@dataclass(kw_only=True)
class TransformBatchRecord(BatchRecord):
    state: WorkflowState | None

    @property
    @abstractmethod
    def messages(self) -> list[str]:
        pass


@dataclass(kw_only=True)
class FailureTransformBatchRecord(TransformBatchRecord):
    STATUS_CODE = 1
    error: str

    @property
    @override
    def messages(self) -> list[str]:
        return [self.error]


@dataclass(kw_only=True)
class AppliedTransformBatchRecord(TransformBatchRecord):
    log: list[str] | None = None
    needs_check: bool = False

    def __post_init__(self):
        # We can have several [isomorphe] tags in the log, as multiple XSLT templates can trigger on a single record.
        # For now, we only care if at least once of those is a :check to flag the record for verification.
        if self.log and any(["[isomorphe:check]" in log for log in self.log]):
            self.needs_check = True

    @classmethod
    @override
    def status_code_for(cls, **kwargs) -> int:
        # Don't change hash function once assigned or it'll mess up pickled jobs
        h = cls.STATUS_CODE + (0 if kwargs["needs_check"] else 10)
        return h

    @property
    @override
    def messages(self) -> list[str]:
        return (
            [re.sub(r"\[isomorphe[^]]*\]\s*", "", log).strip() for log in self.log]
            if self.log
            else []
        )


@dataclass(kw_only=True)
class SuccessTransformBatchRecord(AppliedTransformBatchRecord):
    STATUS_CODE = 2
    transformed_content: str


class SkipReasonMessage(StrEnum):
    # We don't use `SkipReason.value` for this because we pickle the reason
    # and want to be able to change the associated message inbetween jobs.
    UNSUPPORTED_METADATA_TYPE = "Type d'enregistrement non supporté."
    HAS_WORKING_COPY = "L'enregistrement a une copie de travail (working copy)."


class SkipReason(IntEnum):
    # Don't change codes once assigned or it'll mess up pickled jobs
    UNSUPPORTED_METADATA_TYPE = 2
    HAS_WORKING_COPY = 3


@dataclass(kw_only=True)
class SkippedTransformBatchRecord(AppliedTransformBatchRecord):
    STATUS_CODE = 3
    reason: SkipReason | None = None

    @property
    @override
    def messages(self) -> list[str]:
        if self.reason:
            # Explicit reason => takes precedence over log messages
            return [SkipReasonMessage[self.reason.name].value]
        else:
            return super().messages


TRANSFORM_RECORD_STATUSES = RecordStatuses(
    RecordStatus(
        code=FailureTransformBatchRecord.status_code_for(),
        priority=1,
        label="Erreur",
        icon="⚠️",
    ),
    RecordStatus(
        code=SuccessTransformBatchRecord.status_code_for(needs_check=True),
        priority=2,
        label="Modifié, à vérifier",
        icon="🟠",
    ),
    RecordStatus(
        code=SuccessTransformBatchRecord.status_code_for(needs_check=False),
        priority=12,
        label="Modifié",
        icon="🟢",
    ),
    RecordStatus(
        code=SkippedTransformBatchRecord.status_code_for(needs_check=True),
        priority=3,
        label="Ignoré, à vérifier",
        icon="🟡",
    ),
    RecordStatus(
        code=SkippedTransformBatchRecord.status_code_for(needs_check=False),
        priority=13,
        label="Ignoré",
        icon="⚪️",
    ),
)


class TransformBatch[R: TransformBatchRecord](Batch[R]):
    RECORD_STATUSES = TRANSFORM_RECORD_STATUSES

    def __init__(self, transformation: str, records: Sequence[R] | None = None):
        self.transformation = transformation
        super().__init__(records)

    def filter_status(self, statuses: Sequence[int] | None = None) -> "TransformBatch[R]":
        if statuses is None:  # not the same as []
            return self
        records = [r for r in self.records if r.status_code in statuses]
        return TransformBatch[R](self.transformation, records)

    def filter_type[T: TransformBatchRecord](self, t: type[T]) -> "TransformBatch[T]":
        records = [r for r in self.records if isinstance(r, t)]
        return TransformBatch[T](self.transformation, records)

    def successes(self) -> "TransformBatch[SuccessTransformBatchRecord]":
        return self.filter_type(SuccessTransformBatchRecord)

    def failures(self) -> "TransformBatch[FailureTransformBatchRecord]":
        return self.filter_type(FailureTransformBatchRecord)

    def skipped(self) -> "TransformBatch[SkippedTransformBatchRecord]":
        return self.filter_type(SkippedTransformBatchRecord)


@dataclass(kw_only=True)
class MigrateBatchRecord(BatchRecord):
    transformed_content: str


@dataclass(kw_only=True)
class FailureMigrateBatchRecord(MigrateBatchRecord):
    STATUS_CODE = 1
    error: str


@dataclass(kw_only=True)
class SuccessMigrateBatchRecord(MigrateBatchRecord):
    STATUS_CODE = 2
    transformed_uuid: str


class MigrateMode(StrEnum):
    CREATE = "create"
    OVERWRITE = "overwrite"


MIGRATE_RECORD_STATUSES = RecordStatuses(
    RecordStatus(
        code=FailureMigrateBatchRecord.status_code_for(),
        priority=1,
        label="Erreur",
        icon="⚠️",
    ),
    RecordStatus(
        code=SuccessMigrateBatchRecord.status_code_for(),
        priority=2,
        label="Mis à jour",
        icon="✅️",
    ),
)


class MigrateBatch[R: MigrateBatchRecord](Batch[R]):
    RECORD_STATUSES = MIGRATE_RECORD_STATUSES

    def __init__(
        self, mode: MigrateMode, transform_job_id: str | None, records: Sequence[R] | None = None
    ):
        self.mode = mode
        self.transform_job_id = transform_job_id
        super().__init__(records)

    def filter_status(self, statuses: Sequence[int] | None = None) -> "MigrateBatch[R]":
        if statuses is None:  # not the same as []
            return self
        records = [r for r in self.records if r.status_code in statuses]
        return MigrateBatch[R](self.mode, self.transform_job_id, records)

    def filter_type[T: MigrateBatchRecord](self, t: type[T]) -> "MigrateBatch[T]":
        records = [r for r in self.records if isinstance(r, t)]
        return MigrateBatch[T](self.mode, self.transform_job_id, records)

    def successes(self) -> "MigrateBatch[SuccessMigrateBatchRecord]":
        return self.filter_type(SuccessMigrateBatchRecord)

    def failures(self) -> "MigrateBatch[FailureMigrateBatchRecord]":
        return self.filter_type(FailureMigrateBatchRecord)
