"""Exercise the real slot Lua against a private, temporary Redis socket."""
import shutil
import subprocess
import tempfile
import time
from unittest import skipUnless
from unittest.mock import patch

import redis
from django.test import SimpleTestCase, override_settings

from core.services import concurrency_service as slots


@skipUnless(shutil.which('redis-server'), '未安装 Redis，跳过独立槽位集成测试')
@override_settings(AI_SCREEN_MAX_GLOBAL_THREADS=16)
class AddonRedisSlotTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.directory = tempfile.TemporaryDirectory(prefix='addon-slots-', dir='/tmp')
        cls.addClassCleanup(cls.directory.cleanup)
        socket = f'{cls.directory.name}/redis.sock'
        cls.server = subprocess.Popen([
            shutil.which('redis-server'), '--port', '0', '--unixsocket', socket,
            '--save', '', '--appendonly', 'no', '--dir', cls.directory.name,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        cls.redis = redis.Redis(unix_socket_path=socket, decode_responses=True)
        cls.addClassCleanup(cls.redis.close)
        for _ in range(100):
            try:
                cls.redis.ping()
                return
            except redis.ConnectionError:
                if cls.server.poll() is not None:
                    raise RuntimeError('临时 Redis 启动失败')
                time.sleep(.02)
        raise RuntimeError('临时 Redis 启动超时')

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        cls.server.wait(timeout=5)

    def setUp(self):
        self.redis.flushdb()  # Only this test's private Unix socket, never project Redis.
        self.connection = patch.object(slots, '_get_redis', return_value=self.redis)
        self.connection.start()
        self.addCleanup(self.connection.stop)

    def test_shared_user_limit_and_global_capacity(self):
        self.assertTrue(slots.try_acquire(1, 4, user_id=10, user_limit=8))
        self.assertTrue(slots.try_acquire(2, 4, user_id=10, user_limit=8))
        self.assertFalse(slots.try_acquire(3, 1, user_id=10, user_limit=8))
        slots.release(1)
        self.assertTrue(slots.try_acquire(3, 1, user_id=10, user_limit=8))
        self.assertEqual(slots.get_queue_info(3, 1, user_id=10, user_limit=8)['user_slots_used'], 5)

    def test_downgrade_keeps_inflight_lease_but_blocks_new_calls(self):
        self.assertTrue(slots.try_acquire(1, 8, user_id=10, user_limit=8))
        self.assertFalse(slots.try_acquire(2, 1, user_id=10, user_limit=4))
        self.assertEqual(self.redis.zcard(slots._LEASES_KEY), 1)
        slots.release(1)
        self.assertTrue(slots.try_acquire(2, 1, user_id=10, user_limit=4))

    def test_queued_task_resizes_without_blocking_itself(self):
        self.assertTrue(slots.try_acquire(1, 8, user_id=10, user_limit=8))
        self.assertFalse(slots.try_acquire(2, 8, user_id=10, user_limit=8))
        slots.release(1)
        self.assertTrue(slots.try_acquire(2, 4, user_id=10, user_limit=4))
        self.assertEqual(self.redis.zcard(slots._QUEUE_KEY), 0)
        self.assertEqual(self.redis.zrange(slots._LEASES_KEY, 0, -1), ['2:10:4'])
