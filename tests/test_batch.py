from ecospheres_migrator.batch import MetadataType, SuccessTransformBatchRecord, TransformBatch


def test_order_migrate():
    batch = TransformBatch()
    info_str = '<info version="1.1"><general><changeDate>{}</changeDate></general></info>'
    batch.add(
        SuccessTransformBatchRecord(
            uuid="1",
            md_type=MetadataType.METADATA,
            state=None,
            original="",
            url="",
            result="",
            info=info_str.format("2024-09-19T19:43:10"),
        )
    )
    batch.add(
        SuccessTransformBatchRecord(
            uuid="2",
            md_type=MetadataType.METADATA,
            state=None,
            original="",
            url="",
            result="",
            info=info_str.format("2023-09-19T19:43:10"),
        )
    )
    # unordered by default
    assert batch.records[0].uuid == "1"
    ordered = batch.successes(order_by_changed_date=True)
    # oldest one is the first one
    assert ordered[0].uuid == "2"
