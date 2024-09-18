from dataclasses import dataclass
from enum import Enum

from ecospheres_migrator.geonetwork import MefArchive, WorkflowState


@dataclass(kw_only=True)
class TransformBatchRecord:
    uuid: str
    template: bool
    state: WorkflowState | None
    original: str
    url: str


@dataclass(kw_only=True)
class SuccessTransformBatchRecord(TransformBatchRecord):
    result: str
    info: str


@dataclass(kw_only=True)
class FailureTransformBatchRecord(TransformBatchRecord):
    error: str


class SkipReason(Enum):
    NO_CHANGES = "no changes"


@dataclass(kw_only=True)
class SkippedTransformBatchRecord(TransformBatchRecord):
    reason: SkipReason
    info: str


class TransformBatch:
    def __init__(self):
        self.records: list[TransformBatchRecord] = []

    def add(self, batch: TransformBatchRecord):
        self.records.append(batch)

    def successes(self) -> list[SuccessTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, SuccessTransformBatchRecord)]

    def failures(self) -> list[FailureTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, FailureTransformBatchRecord)]

    def skipped(self) -> list[SkippedTransformBatchRecord]:
        return [r for r in self.records if isinstance(r, SkippedTransformBatchRecord)]

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
    source_content: str
    target_content: str
    template: bool
    url: str


@dataclass(kw_only=True)
class SuccessMigrateBatchRecord(MigrateBatchRecord):
    target_uuid: str


@dataclass(kw_only=True)
class FailureMigrateBatchRecord(MigrateBatchRecord):
    error: str


class MigrateMode(Enum):
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
