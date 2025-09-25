import asyncio
import logging


class BoundedQueue(asyncio.Queue):
    def __init__(self, maxsize: int, drop_loglevel=logging.WARNING):
        super().__init__(maxsize)
        self.level = drop_loglevel

    async def put(self, item):
        if self.full():
            try:
                dropped = self.get_nowait()
                logging.log(
                    self.level, "Queue is full, discarding oldest item: %s", dropped
                )

            except asyncio.QueueEmpty:
                pass

        await super().put(item)
