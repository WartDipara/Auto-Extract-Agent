from __future__ import annotations

import queue
from models import Task

Q_DOWNLOAD: queue.Queue[Task] = queue.Queue()
Q_PATCH: queue.Queue[Task] = queue.Queue()
Q_DEVICE: queue.Queue[Task] = queue.Queue()
Q_EXTRACT: queue.Queue[Task] = queue.Queue()
Q_ARCHIVE: queue.Queue[Task] = queue.Queue()


def put_download(task: Task) -> None:
    Q_DOWNLOAD.put(task)


def put_patch(task: Task) -> None:
    Q_PATCH.put(task)


def put_device(task: Task) -> None:
    Q_DEVICE.put(task)


def put_extract(task: Task) -> None:
    Q_EXTRACT.put(task)


def put_archive(task: Task) -> None:
    Q_ARCHIVE.put(task)
