from dataclasses import dataclass

from ecospheres_migrator.geonetwork import MefArchive


@dataclass(kw_only=True)
class BatchRecord:
    uuid: str
    template: bool
    original: str


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
