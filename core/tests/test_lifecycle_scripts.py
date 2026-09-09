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
        discovery = 'pgrep -o -f "$CELERY_BIN -A platform_backend"'
        self.assertIn(discovery, content)
        self.assertIn(discovery, stop_content)
        self.assertIn('operations_status --json --no-celery', stop_content)
        self.assertNotIn('operations_safe()', stop_content)
        self.assertIn(
            'if ! service_pid_is_running "celery" && ! service_pid_is_running "django"',
            stop_content,
        )
        self.assertLess(
            content.index('ALREADY_RUNNING=false'),
            content.index('# ── 前端构建（非开发模式）'),
        )
        self.assertIn('run_manage migrate --check', content)
        self.assertIn('run_manage reconcile_interrupted_tasks --apply', content)

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
            result = subprocess.run(
                ['bash', str(script)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('忽略 celery 的失效 PID 文件', result.stdout)
        self.assertIn('平台已处于停止状态', result.stdout)
        self.assertFalse(stale_pid_file.exists())
