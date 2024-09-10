from dataclasses import dataclass

from ecospheres_migrator.geonetwork import MefArchive


@dataclass(kw_only=True)
class BatchRecord:
    uuid: str
    template: bool
    original: str
    url: str


@dataclass(kw_only=True)
class SuccessBatchRecord(BatchRecord):
    result: str
    info: str


@dataclass(kw_only=True)
class FailureBatchRecord(BatchRecord):
    error: str


class Batch:
    def __init__(self):
        self.records: list[BatchRecord] = []

    def add(self, batch: BatchRecord):
        self.records.append(batch)

    def successes(self) -> list[SuccessBatchRecord]:
        return [r for r in self.records if isinstance(r, SuccessBatchRecord)]

    def failures(self) -> list[FailureBatchRecord]:
        return [r for r in self.records if isinstance(r, FailureBatchRecord)]

    # FIXME: needed?
    def to_mef(self):
        mef = MefArchive()
        for r in self.records:
            if isinstance(r, SuccessBatchRecord):
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


class MigrateBatch:
    def __init__(self, mode: str):
        self.records: list[MigrateBatchRecord] = []
        self.mode = mode

    def add(self, batch: MigrateBatchRecord):
        self.records.append(batch)

    def successes(self) -> list[SuccessMigrateBatchRecord]:
        return [r for r in self.records if isinstance(r, SuccessMigrateBatchRecord)]

    def failures(self) -> list[FailureMigrateBatchRecord]:
        return [r for r in self.records if isinstance(r, FailureMigrateBatchRecord)]
