import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class LifecycleScriptTests(SimpleTestCase):
    def test_start_and_stop_scripts_have_valid_bash_syntax(self):
        for script in ('start.sh', 'stop.sh'):
            with self.subTest(script=script):
                result = subprocess.run(
                    ['bash', '-n', str(ROOT / script)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_start_and_stop_use_the_same_pid_file_process_detection(self):
        content = (ROOT / 'start.sh').read_text(encoding='utf-8')
        stop_content = (ROOT / 'stop.sh').read_text(encoding='utf-8')
        self.assertIn('service_is_running', content)
        self.assertIn('matches_service_process', content)
        self.assertIn('matches_service_process', stop_content)
        self.assertNotIn('$SCRIPT_DIR/venv/bin/', content)
        self.assertNotIn('$SCRIPT_DIR/venv/bin/', stop_content)
        self.assertIn('PYTHON_BIN=${PYTHON_BIN:-python}', content)
        self.assertIn('PYTHON_BIN=${PYTHON_BIN:-python}', stop_content)
        worker_discovery = 'pgrep -o -f "$CELERY_BIN -A platform_backend worker"'
        beat_discovery = 'pgrep -o -f "$CELERY_BIN -A platform_backend beat"'
        self.assertIn(worker_discovery, content)
        self.assertIn(worker_discovery, stop_content)
        self.assertIn(beat_discovery, content)
        self.assertIn(beat_discovery, stop_content)
        self.assertIn('celery_beat.pid', content)
        self.assertIn('service_pid_is_running "celery_beat"', stop_content)
        self.assertIn('stop_with_timeout "celery_beat" 30', stop_content)
        self.assertIn('operations_status --json --no-celery', stop_content)
        self.assertNotIn('operations_safe()', stop_content)
        self.assertLess(
            content.index('ALREADY_RUNNING=false'),
            content.index('# ── 前端构建（非开发模式）'),
        )
        self.assertIn('run_manage migrate --check', content)
        self.assertIn('run_manage reconcile_interrupted_tasks --apply', content)
        self.assertIn('if redis_ping; then', content)
        self.assertIn('/opt/homebrew/bin/redis-server', content)
        self.assertIn('REDIS_SERVER_BIN', content)
        self.assertNotIn('if command -v redis-server > /dev/null; then', content)
        self.assertLess(
            content.index('if redis_ping; then'),
            content.index('REDIS_SERVER_PATH=$(resolve_redis_server || true)'),
        )

    def test_force_kill_is_explicitly_gated(self):
        content = (ROOT / 'stop.sh').read_text(encoding='utf-8')
        self.assertIn('if [ "$FORCE" = true ]', content)
        self.assertIn('kill -9 "$pid"', content)
        self.assertIn('maintenance_tasks pause', content)

    def test_stop_exits_immediately_when_no_managed_process_is_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / 'stop.sh'
            shutil.copy2(ROOT / 'stop.sh', script)
            pid_dir = Path(temp_dir) / 'pids'
            pid_dir.mkdir()
            stale_pid_file = pid_dir / 'celery.pid'
            stale_pid_file.write_text('99999999\n', encoding='utf-8')
            env = os.environ.copy()
            # Isolate process discovery from real developer services that may be
            # running while the test suite executes.
            env['CELERY_BIN'] = 'metaflow-test-no-celery-process'
            env['GUNICORN_BIN'] = 'metaflow-test-no-gunicorn-process'
            result = subprocess.run(
                ['bash', str(script)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('忽略 celery 的失效 PID 文件', result.stdout)
        self.assertIn('平台已处于停止状态', result.stdout)
        self.assertFalse(stale_pid_file.exists())
