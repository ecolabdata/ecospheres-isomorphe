import copy
import re
from abc import abstractmethod
from collections import UserList, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import IntEnum, StrEnum
from typing import Any, ClassVar, Iterator, Self, final, override

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


# TODO: Extract all status stuff in a separate class, so it can be a key


@dataclass(kw_only=True)
class BatchRecord:
    STATUS_PRIORITY: ClassVar[int] = 0
    STATUS_LABEL: ClassVar[str] = "-"
    STATUS_ICON: ClassVar[str] = "-"
    uuid: str
    md_type: MetadataType
    original_content: bytes
    url: str  # store at Batch level?

    @property
    def status(self) -> int:
        return self.STATUS_PRIORITY

    @property
    def status_label(self) -> str:
        return self.STATUS_LABEL

    @property
    def status_icon(self) -> str:
        return self.STATUS_ICON

    @property
    def status_legend(self) -> str:
        return f"{self.status_icon} {self.status_label}"

    @classmethod
    def derive_from(cls, obj: "BatchRecord", **changes: Any) -> Self:
        return cls(**(asdict(obj) | changes))

    # TODO: add ordering


class Batch[R: BatchRecord](UserList[R]):
    def select(self, statuses: Sequence[int] | None = None) -> Self:
        if statuses is None:  # not the same as []
            return self
        obj = copy.copy(self)
        obj.data = [r for r in self.data if r.status in statuses]
        return obj

    @override
    def __repr__(self):
        stats = defaultdict(int)
        for r in self.data:
            stats[r.status_label] += 1
        return f"{type(self).__name__}({len(self.data)} records, {dict(sorted(stats.items()))})"


@dataclass(kw_only=True)
class TransformBatchRecord(BatchRecord):
    MAX_STATUS_PRIORITY: ClassVar[int] = 10  # must be higher than all subclasses.STATUS_PRIORIY
    state: WorkflowState | None

    @property
    @abstractmethod
    def messages(self) -> list[str]:
        pass


@final
@dataclass(kw_only=True)
class FailureTransformBatchRecord(TransformBatchRecord):
    STATUS_PRIORITY = 1
    STATUS_LABEL = "Erreur"
    STATUS_ICON = "⚠️"
    error: str

    @property
    @override
    def messages(self) -> list[str]:
        return [self.error]


@dataclass(kw_only=True)
class AppliedTransformBatchRecord(TransformBatchRecord):
    log: TransformLog | None = None
    needs_check: bool = False

    def __post_init__(self):
        # We can have several [isomorphe] tags in the log, as multiple XSLT templates can trigger on a single record.
        # For now, we only care if at least once of those is a :check to flag the record for verification.
        if self.log and any(["[isomorphe:check]" in log.message for log in self.log]):
            self.needs_check = True

    @property
    @override
    def status(self) -> int:
        return (0 if self.needs_check else self.MAX_STATUS_PRIORITY) + self.STATUS_PRIORITY

    @property
    @override
    def status_label(self) -> str:
        return self.STATUS_LABEL + (", à vérifier" if self.needs_check else "")

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
    STATUS_PRIORITY = 2
    STATUS_LABEL = "Modifié"
    transformed_content: bytes

    @property
    @override
    def status_icon(self) -> str:
        return "🟠" if self.needs_check else "🟢"


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
    STATUS_PRIORITY = 3
    STATUS_LABEL = "Ignoré"
    reason: SkipReason | None = None

    @property
    @override
    def status_icon(self) -> str:
        return "🟡" if self.needs_check else "⚪️"

    @property
    @override
    def messages(self) -> list[str]:
        if self.reason:
            # Explicit reason => takes precedence over log messages
            return [SkipReasonMessage[self.reason.name].value]
        else:
            return super().messages


class TransformBatch(Batch[TransformBatchRecord]):
    def __init__(self, transformation: str, data: Sequence[TransformBatchRecord] | None = None):
        self.transformation = transformation
        super(TransformBatch, self).__init__(data or [])

    # TODO: drop
    # def to_mef(self):
    #     mef = MefArchive()
    #     for r in self.records:
    #         if isinstance(r, SuccessTransformBatchRecord):
    #             mef.add(r.uuid, r.result, r.info)
    #     return mef.finalize()


@dataclass(kw_only=True)
class MigrateBatchRecord(BatchRecord):
    transformed_content: bytes


@final
@dataclass(kw_only=True)
class FailureMigrateBatchRecord(MigrateBatchRecord):
    STATUS_PRIORITY = 1
    STATUS_LABEL = "Erreur"
    STATUS_ICON = "⚠️"
    error: str


@final
@dataclass(kw_only=True)
class SuccessMigrateBatchRecord(MigrateBatchRecord):
    STATUS_PRIORITY = 2
    STATUS_LABEL = "Mis à jour"
    STATUS_ICON = "✅️"
    target_uuid: str


class MigrateMode(StrEnum):
    CREATE = "create"
    OVERWRITE = "overwrite"


class MigrateBatch(Batch[MigrateBatchRecord]):
    def __init__(self, mode: MigrateMode, transform_job_id: str | None):
        self.mode = mode
        self.transform_job_id = transform_job_id
        super(MigrateBatch, self).__init__()
