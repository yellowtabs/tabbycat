"""Bounded regression for asgiref #535 (cancelled sync/async request bridge)."""
import asyncio
import faulthandler
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from asgiref.sync import async_to_sync, sync_to_async, ThreadSensitiveContext


def cancelled_requests(concurrent):
    async def inner():
        await asyncio.sleep(0.2)
        # Shutdown must not consume a slot needed by the remaining request.
        await sync_to_async(time.sleep, thread_sensitive=False)(0.01)

    async def request():
        started = threading.Event()

        def sync_code():
            started.set()
            async_to_sync(inner)()

        async with ThreadSensitiveContext():
            task = asyncio.create_task(sync_to_async(sync_code, thread_sensitive=True)())
            await asyncio.sleep(0)
            assert started.wait(3), 'Request worker did not start'
            # Hold loop while worker queues its async handoff, then cancel.
            time.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def main():
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=2))
        await asyncio.gather(*(request() for _ in range(concurrent)))
        # The loop must still serve work after cancelled request teardown.
        assert await sync_to_async(lambda: 'healthy', thread_sensitive=False)() == 'healthy'

    asyncio.run(main())


class AsgiCancellationTests(unittest.TestCase):
    def assert_requests_finish(self, concurrent):
        # A deadlocked event loop cannot enforce asyncio.wait_for's timeout.
        # Use a process boundary so regressions cannot hang CI or image checks.
        try:
            result = subprocess.run(
                [sys.executable, '-P', str(Path(__file__).resolve()), '--child', str(concurrent)],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(f'Cancelled request deadlocked event loop: {exc.stderr}')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cancelled_request_releases_event_loop(self):
        self.assert_requests_finish(1)

    def test_concurrent_cancellations_leave_default_executor_available(self):
        self.assert_requests_finish(2)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        faulthandler.dump_traceback_later(5)
        cancelled_requests(int(sys.argv[2]))
        faulthandler.cancel_dump_traceback_later()
    else:
        unittest.main()
