import os

from redis import Redis
from rq import Queue as RQQueue
from rq.exceptions import NoSuchJobError
from rq.job import Job

_queue = None


def get_connection() -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://"))


def get_queue() -> RQQueue:
    global _queue
    if not _queue:
        _queue = RQQueue(connection=get_connection())
    return _queue


def get_job(job_id: str) -> Job | None:
    try:
        return Job.fetch(job_id, connection=get_connection())
    except NoSuchJobError:
        return None
