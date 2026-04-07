"""Utility helpers shared across driver modules."""

import asyncio
import logging
from typing import Any


class BoundedQueue(asyncio.Queue):
    """FIFO queue that drops the oldest item when full."""

    def __init__(self, maxsize: int, drop_loglevel: int = logging.WARNING) -> None:
        """Initialize a bounded queue with a drop-notification log level.

        Args:
            maxsize: Maximum number of queued items.
            drop_loglevel: Log level used when dropping the oldest item.
        """
        super().__init__(maxsize)
        self.level = drop_loglevel

    async def put(self, item: Any) -> None:
        """Put an item, dropping the oldest queued item if capacity is reached.

        Args:
            item: Item to enqueue.
        """
        if self.full():
            try:
                dropped = self.get_nowait()
                logging.log(
                    self.level, "Queue is full, discarding oldest item: %s", dropped
                )

            except asyncio.QueueEmpty:
                pass

        await super().put(item)

    def put_nowait(self, item: Any) -> None:
        """Put an item without blocking, dropping the oldest item if needed.

        Args:
            item: Item to enqueue.
        """
        if self.full():
            try:
                dropped = self.get_nowait()
                logging.log(
                    self.level, "Queue is full, discarding oldest item: %s", dropped
                )

            except asyncio.QueueEmpty:
                pass

        super().put_nowait(item)

    def clear(self) -> None:
        """Remove all pending items from the queue."""
        while not self.empty():
            try:
                self.get_nowait()
            except asyncio.QueueEmpty:
                pass
