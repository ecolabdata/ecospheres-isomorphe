from dataclasses import dataclass

from ecospheres_migrator.geonetwork import MefArchive


@dataclass
class BatchRecord:
    uuid: str
    template: bool
    original: str
    result: str | None = None
    info: str | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None


class Batch:

    def __init__(self):
        self.records: list[BatchRecord] = []

    def add_success(self, uuid: str, template: bool, original: str, result: str, info: str):
        self.records.append(BatchRecord(
            uuid=uuid, template=template, original=original, result=result, info=info))

    def add_failure(self, uuid: str, template: bool, original: str, error: str):
        self.records.append(BatchRecord(
            uuid=uuid, template=template, original=original, error=error))

    def successes(self):
        return [r for r in self.records if r.success]

    def failures(self):
        return [r for r in self.records if not r.success]

    # FIXME: needed?
    def to_mef(self):
        mef = MefArchive()
        for r in self.records:
            if r.success:
                mef.add(r.uuid, r.result, r.info)
        return mef.finalize()
