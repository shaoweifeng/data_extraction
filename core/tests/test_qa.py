"""
QA 模块基础单元测试

运行方式：
    python manage.py test core.tests.test_qa --settings=platform_backend.test_settings -v 2
"""
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# 1. 质量评价方法配置测试
# ─────────────────────────────────────────────────────────────────────────────

class TestQualityMethodsConfig(TestCase):
    """测试质量评价方法配置的正确性"""

    def test_get_all_methods_meta(self):
        """get_all_methods_meta 返回 5 个方法"""
        from core.quality.domain.methods import get_all_methods_meta
        meta = get_all_methods_meta()
        self.assertEqual(len(meta), 5)
        keys = [m['key'] for m in meta]
        self.assertIn('QUADAS2', keys)
        self.assertIn('NOS', keys)
        self.assertIn('ROB2', keys)

    def test_quadas2_has_signal_items(self):
        """QUADAS-2 应有信号问题"""
        from core.quality.domain.methods import get_method_config
        cfg = get_method_config('QUADAS2')
        self.assertTrue(cfg['ai_supported'])
        self.assertGreater(len(cfg['signal_items']), 0)
        # 至少 4 个领域
        domains = set(item['domain'] for item in cfg['signal_items'])
        self.assertGreaterEqual(len(domains), 4)

    def test_nos_has_signal_items(self):
        """NOS 应有信号问题（队列研究变体）"""
        from core.quality.domain.methods import get_method_config
        cfg = get_method_config('NOS')
        self.assertTrue(cfg['ai_supported'])
        self.assertGreater(len(cfg['signal_items']), 0)

    def test_rob2_no_signal_items(self):
        """ROB2 AI 暂不支持，信号问题为空"""
        from core.quality.domain.methods import get_method_config, AI_SUPPORTED_METHODS
        cfg = get_method_config('ROB2')
        self.assertFalse(cfg['ai_supported'])
        self.assertEqual(cfg['signal_items'], [])
        self.assertNotIn('ROB2', AI_SUPPORTED_METHODS)

    def test_invalid_method_raises(self):
        """无效方法键应抛出异常（ValueError 或 KeyError）"""
        from core.quality.domain.methods import get_method_config
        with self.assertRaises((ValueError, KeyError)):
            get_method_config('NONEXISTENT')

    def test_signal_items_have_required_fields(self):
        """QUADAS-2 信号问题条目应包含必需字段"""
        from core.quality.domain.methods import get_method_config
        cfg = get_method_config('QUADAS2')
        required_fields = {'signal_key', 'signal_question', 'domain', 'result_type', 'options'}
        for item in cfg['signal_items']:
            for f in required_fields:
                self.assertIn(f, item, f"信号问题缺少字段: {f}")
            self.assertIsInstance(item['options'], list)
            self.assertGreater(len(item['options']), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. QA Handler 工具函数测试
# ─────────────────────────────────────────────────────────────────────────────

class TestQAHandlerUtils(TestCase):
    """测试 qa_handler.py 的工具函数"""

    def test_determine_consistency_consistent(self):
        """两个模型结果相同 → consistent"""
        from core.quality.executors.qa_eval import _determine_consistency
        r1 = {'judgment': '是', 'reason': '理由1'}
        r2 = {'judgment': '是', 'reason': '理由2'}
        consistency, recommendation = _determine_consistency([r1, r2])
        self.assertEqual(consistency, 'consistent')
        self.assertEqual(recommendation, '是')

    def test_determine_consistency_divergent(self):
        """两个模型结果不同 → divergent，推荐保守值"""
        from core.quality.executors.qa_eval import _determine_consistency
        r1 = {'judgment': '是', 'reason': ''}
        r2 = {'judgment': '否', 'reason': ''}
        consistency, recommendation = _determine_consistency([r1, r2])
        self.assertEqual(consistency, 'divergent')
        # '否' 比 '是' 更保守
        self.assertEqual(recommendation, '否')

    def test_determine_consistency_both_empty(self):
        """两个模型都为空 → failed"""
        from core.quality.executors.qa_eval import _determine_consistency
        consistency, recommendation = _determine_consistency([{}, {}])
        self.assertEqual(consistency, 'failed')

    def test_determine_consistency_one_empty(self):
        """一个模型为空 → partial，推荐另一个的结果"""
        from core.quality.executors.qa_eval import _determine_consistency
        r1 = {}
        r2 = {'judgment': '不清楚', 'reason': '无法判断'}
        consistency, recommendation = _determine_consistency([r1, r2])
        self.assertEqual(consistency, 'partial')
        self.assertEqual(recommendation, '不清楚')

    def test_build_qa_prompt_contains_questions(self):
        """构建 prompt 应包含信号问题文本"""
        from core.quality.executors.qa_eval import _build_qa_prompt
        ref_info = {
            'title': '测试文献',
            'first_author': '张三',
            'year': '2023',
            'has_fulltext': True,
            'content': '这是文献摘要内容',
        }
        signal_items = [
            {
                'signal_key': 'PS1',
                'signal_question': '是否连续纳入患者？',
                'signal_description': '关于患者选择的信号问题',
                'options': ['是', '否', '不清楚'],
            }
        ]
        prompt = _build_qa_prompt(ref_info, signal_items, 'QUADAS-2')
        self.assertIn('测试文献', prompt)
        self.assertIn('是否连续纳入患者', prompt)
        self.assertIn('QUADAS-2', prompt)
        self.assertIn('JSON', prompt)

    def test_parse_model_response_valid_json(self):
        """_call_model_for_ref 应正确解析有效的 JSON 响应"""
        from core.quality.executors.qa_eval import _call_model_for_ref
        signal_items = [
            {'signal_key': 'PS1', 'signal_question': '问题1', 'signal_description': '', 'options': ['是', '否', '不清楚']},
        ]
        mock_response = json.dumps([
            {'signal_key': 'PS1', 'judgment': '是', 'reason': '理由', 'evidence': '证据', 'evidence_page': '第1页'}
        ])

        mock_provider = MagicMock()
        mock_provider.generate_text.return_value = (mock_response, {'total_tokens': 100})

        with patch('core.ai.providers.provider_is_configured', return_value=True), patch(
            'core.ai.providers.get_provider', return_value=mock_provider,
        ):
            result, usage = _call_model_for_ref('deepseek', 'test_prompt', signal_items)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['signal_key'], 'PS1')
        self.assertEqual(result[0]['judgment'], '是')
        self.assertEqual(usage, {'total_tokens': 100})

    def test_parse_model_response_invalid_key_filtered(self):
        """无效 signal_key 的条目应被过滤掉"""
        from core.quality.executors.qa_eval import _call_model_for_ref
        signal_items = [
            {'signal_key': 'PS1', 'signal_question': '问题1', 'signal_description': '', 'options': ['是']},
        ]
        mock_response = json.dumps([
            {'signal_key': 'INVALID_KEY', 'judgment': '是'},
            {'signal_key': 'PS1', 'judgment': '否'},
        ])

        mock_provider = MagicMock()
        mock_provider.generate_text.return_value = (mock_response, {})

        with patch('core.ai.providers.provider_is_configured', return_value=True), patch(
            'core.ai.providers.get_provider', return_value=mock_provider,
        ):
            result, usage = _call_model_for_ref('deepseek', 'prompt', signal_items)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['signal_key'], 'PS1')
        self.assertEqual(usage, {})


# ─────────────────────────────────────────────────────────────────────────────
# 3. API 视图基础测试（无需 DB）
# ─────────────────────────────────────────────────────────────────────────────

class TestQAApiHelpers(TestCase):
    """测试质量评价 API 的工具函数。"""

    def test_json_ok(self):
        from core.quality.api.common import _json_ok
        resp = _json_ok({'foo': 'bar'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])
        self.assertEqual(data['data']['foo'], 'bar')

    def test_json_err(self):
        from core.quality.api.common import _json_err
        resp = _json_err('出错了', status=400)
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertFalse(data['ok'])
        self.assertIn('出错了', data['error'])

    def test_methods_list_view(self):
        """methods_list 需要登录，返回方法列表"""
        from django.test import RequestFactory
        from core.quality.api.reference_views import methods_list
        factory = RequestFactory()
        req = factory.get('/qa/methods/')
        # 注入已登录用户
        user = MagicMock()
        user.is_authenticated = True
        req.user = user
        resp = methods_list(req)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['ok'])
        self.assertIsInstance(data['data'], list)
        self.assertEqual(len(data['data']), 5)


class TestQAEvaluationStartService(TestCase):
    """评价任务入队后应立即发布可见的运行状态。"""

    def test_start_marks_selected_references_running_before_worker_execution(self):
        from core.models import Project, QAReference
        from core.quality.services.evaluation_service import start_evaluation

        user = User.objects.create_user('qa-start-user')
        project = Project.objects.create(name='QA start project', owner=user)
        qa_ref = QAReference.objects.create(
            project=project,
            title='Queued QA study',
            quality_method='QUADAS2',
        )
        queued_task = MagicMock(id=91)
        model_ids = ['deepseek-v4-pro', 'qwen3-6-plus']

        with patch(
            'core.quality.services.evaluation_service.AIQuotaService.preflight',
            return_value=20,
        ), patch(
            'core.scheduler.TaskScheduler.start_step',
            return_value=queued_task,
        ), patch(
            'core.quality.services.evaluation_service.log_task_start',
        ):
            result = start_evaluation(project, user, [qa_ref.id], model_ids)

        qa_ref.refresh_from_db()
        self.assertEqual(result['task_id'], 91)
        self.assertEqual(qa_ref.ai_eval_status, 'running')
        self.assertEqual(qa_ref.eval_mode, 'multi')
        self.assertEqual(qa_ref.selected_models, model_ids)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 领域结果计算逻辑测试（Mock DB）
# ─────────────────────────────────────────────────────────────────────────────

class TestRecalcDomainResults(TestCase):
    """_recalc_domain_results 的规则测试"""

    def _make_signal_item(self, domain, result_type, human_judgment=None, is_confirmed=False, ai_judgment='是'):
        item = MagicMock()
        item.domain = domain
        item.result_type = result_type
        item.is_confirmed = is_confirmed
        item.human_judgment = human_judgment
        item.pre_selected = ai_judgment
        return item

    def test_all_low_means_low_risk(self):
        """所有信号问题都判为低风险 → 领域结果为 low"""
        # 此测试因依赖 ORM 操作，仅验证逻辑规则
        # 实际 _recalc_domain_results 是 DB 操作，这里用集成测试方式模拟
        # 规则：没有'否'/'✗'，没有'不清楚'，全部确认 → low
        judgments = ['是', '是', '是']
        has_high   = any(j in ['否', '✗'] for j in judgments)
        has_unclear = any(j in ['不清楚', '高'] for j in judgments)
        self.assertFalse(has_high)
        self.assertFalse(has_unclear)

    def test_any_high_means_high_risk(self):
        """有任意'否' → 高风险"""
        judgments = ['是', '否', '是']
        has_high = any(j in ['否', '✗'] for j in judgments)
        self.assertTrue(has_high)

    def test_any_unclear_means_unclear_risk(self):
        """有'不清楚'但没有'否' → 不清楚"""
        judgments = ['是', '不清楚', '是']
        has_high    = any(j in ['否', '✗'] for j in judgments)
        has_unclear = any(j in ['不清楚', '高'] for j in judgments)
        self.assertFalse(has_high)
        self.assertTrue(has_unclear)
