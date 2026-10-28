"""Stages 5–6: deterministic provider boundaries, durable calls, ledger and isolation.

All providers are patched in tests. No PDF or request is sent to a real model.
"""
import json
from unittest.mock import Mock, patch
from django.conf import settings
from django.test import override_settings
from core.ai.usage_schema import normalize_provider_usage
from core.models import Task
from core.models_billing import CreditAccount, CreditReservation, CreditTransaction, ModelBillingRate, TokenUsageLog
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCall, RescreenRun, RescreenModelResult
from core.rescreening.services import ai_protocol as protocol
from core.rescreening.services.ai_execution import process_run
from core.rescreening.services.ai_runs import start_run, retry_run, finish_task, prepare
from core.services.credit_ledger_service import grant_batch_credits, extend_reservation
from core.services.ai_models_config import get_model_config
from core.tests.test_shared_fulltext import SharedFulltextFixture

MODELS = ['deepseek-v4-flash', 'qwen3-7-flash']


@override_settings(MODEL_WEIGHTED_BILLING_ENABLED=True, CREDIT_BATCH_LEDGER_ENABLED=True,
                  BILLING_RESERVATION_ENABLED=True, MODEL_WEIGHTED_BILLING_ALLOW_DRAFT=False)
class RescreenAITests(SharedFulltextFixture):
    def setUp(self):
        super().setUp()
        self.configured = patch('core.ai.providers.provider_is_configured', return_value=True)
        self.configured.start()
        self.addCleanup(self.configured.stop)
        self.executor_configured = patch('core.rescreening.services.ai_execution.provider_is_configured', return_value=True)
        self.executor_configured.start()
        self.addCleanup(self.executor_configured.stop)
        self.slots = patch('core.services.concurrency_service.refresh_task_slots', return_value=1)
        self.slots.start()
        self.addCleanup(self.slots.stop)
        self.asset, self.refs = self.ready(references=True)
        self.ref = self.refs[0]
        self.ref.refresh_from_db()
        self.corpus = self.ref.corpus
        self.criteria = ['排除动物研究']
        grant_batch_credits(self.user, 100000, batch_type='manual', batch_key='rescreen-test-funds')
        self.account = CreditAccount.objects.get(user=self.user)
        self.initial_balance = self.account.balance

    def start(self, models=None, key='run-1'):
        self.corpus.refresh_from_db()
        return start_run(project=self.project, user=self.user, ids=[self.ref.pk], criteria=self.criteria,
            model_ids=models or MODELS, expected_revision=self.corpus.revision, idempotency_key=key)

    def response(self, prompt, *, decision='included', invalid=False, usage=True, model=MODELS[0]):
        data = json.loads(prompt.split('\n')[-1])
        ids = [data['evidence'][0]['id']]
        body = {'decision': decision, 'reason': '根据全文判断', 'criteria_results': [
            {'criterion_id': row['id'], 'judgment': 'violated' if decision == 'excluded' else 'satisfied',
             'reason': '可核验的全文证据', 'evidence_ids': ['unknown-id'] if invalid else ids}
            for row in data['criteria']]}
        config = get_model_config(model)
        stats = normalize_provider_usage({'prompt_tokens': 1000, 'completion_tokens': 100},
            provider=config['provider'], model_id=config['id'], provider_model=config['model'],
            region=config.get('region', ''), service_tier=config.get('service_tier', 'standard'))
        return json.dumps(body, ensure_ascii=False), stats if usage else None

    def execute(self, run, factory=None, stop=lambda: False):
        def default_factory(model, config):
            return Mock(generate_text=lambda prompt: self.response(prompt, model=model))
        with patch('core.rescreening.services.ai_execution.get_provider', side_effect=factory or default_factory) as provider:
            result = process_run(run.pk, expected_task_id=run.task_id, check_stop=stop)
        return result, provider

    def terminal_task(self, run):
        Task.objects.filter(pk=run.task_id).update(status='completed')

    def test_real_pdf_snapshot_and_double_model_consensus(self):
        run = self.start()
        self.assertEqual(CreditReservation.objects.get(task=run.task).status, 'reserved')
        item = run.items.get()
        self.assertEqual(item.evidence_package['asset_sha256'], self.asset.sha256)
        self.assertEqual(item.raw_metadata_version.input_version, self.ref.input_version)
        finished, provider = self.execute(run)
        self.assertEqual(finished.status, 'completed')
        item.refresh_from_db()
        self.assertEqual(item.consensus, 'included')
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(RescreenCall.objects.filter(status='completed').count(), 2)
        self.assertEqual(CreditReservation.objects.get(task=run.task).status, 'settled')
        log = TokenUsageLog.objects.get(task=run.task)
        self.assertEqual(log.total_tokens, 2200)
        self.assertIn('AI全文复筛', log.transaction.note)
        self.assertNotIn('tokens', log.transaction.note)

    def test_idempotency_and_duplicate_delivery_never_repeat_calls(self):
        run = self.start()
        self.assertEqual(self.start().pk, run.pk)
        self.execute(run)
        repeated, provider = self.execute(run)
        self.assertEqual(provider.call_count, 0)
        self.assertEqual(CreditTransaction.objects.filter(task=run.task, txn_type='consume').count(), 1)

    def test_conflicting_idempotency_key_is_rejected(self):
        self.start()
        with self.assertRaisesMessage(RescreenError, '幂等键'):
            self.start(models=[MODELS[0]])

    def test_invalid_citation_is_not_a_result_and_platform_bears_usage(self):
        run = self.start(models=[MODELS[0]])
        result, _ = self.execute(run, lambda model, config: Mock(generate_text=lambda p: self.response(p, invalid=True, model=model)))
        self.assertEqual(result.status, 'failed')
        row = run.items.get().model_results.get()
        self.assertEqual(row.error_code, 'invalid_evidence')
        self.assertEqual(row.decision, '')
        self.assertEqual(TokenUsageLog.objects.get(task=run.task).credits_consumed, 0)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, self.initial_balance)

    def test_malformed_json_preserves_usage_for_audit(self):
        run = self.start(models=[MODELS[0]])
        def factory(model, config):
            return Mock(generate_text=lambda prompt: ('not json', self.response(prompt, model=model)[1]))
        self.execute(run, factory)
        self.assertEqual(RescreenCall.objects.get().error_code, 'invalid_json')
        self.assertEqual(TokenUsageLog.objects.get().total_tokens, 1100)

    def test_partial_failure_retry_only_unfinished_model(self):
        run = self.start()
        def factory(model, config):
            return Mock(generate_text=lambda prompt: self.response(prompt, model=model, invalid=model == MODELS[1]))
        done, _ = self.execute(run, factory)
        self.assertEqual(done.status, 'partial')
        self.assertEqual(done.items.get().consensus, 'pending')
        self.terminal_task(run)
        resumed = retry_run(run_id=run.pk, user=self.user)
        new_task_id = resumed.task_id
        self.assertNotEqual(new_task_id, run.task_id)
        done, provider = self.execute(resumed)
        self.assertEqual(done.status, 'completed')
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.call_args.args[0], MODELS[1])
        self.assertEqual(RescreenCall.objects.count(), 3)

    def test_disagreement_requires_manual_confirmation(self):
        run = self.start()
        def factory(model, config):
            return Mock(generate_text=lambda p: self.response(p, model=model,
                decision='included' if model == MODELS[0] else 'excluded'))
        done, _ = self.execute(run, factory)
        self.assertEqual(done.status, 'completed')
        self.assertEqual(done.items.get().consensus, 'pending')

    def test_missing_usage_requires_explicit_ack_before_retry(self):
        run = self.start(models=[MODELS[0]])
        self.execute(run, lambda model, config: Mock(generate_text=lambda p: self.response(p, model=model, usage=False)))
        self.terminal_task(run)
        with self.assertRaisesMessage(RescreenError, '未知'):
            retry_run(run_id=run.pk, user=self.user)
        resumed = retry_run(run_id=run.pk, user=self.user, acknowledge_unknown=True)
        self.assertEqual(RescreenCall.objects.get().status, 'acknowledged_unknown')
        self.assertEqual(self.execute(resumed)[0].status, 'completed')

    def test_stop_before_calls_releases_full_hold(self):
        run = self.start()
        done, provider = self.execute(run, stop=lambda: True)
        self.assertEqual(done.status, 'paused')
        provider.assert_not_called()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, self.initial_balance)

    def test_stop_between_models_settles_only_known_calls(self):
        run = self.start()
        done, provider = self.execute(run, stop=lambda: RescreenCall.objects.filter(status='completed').exists())
        self.assertEqual(done.status, 'paused')
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(TokenUsageLog.objects.get(task=run.task).total_tokens, 1100)
        self.terminal_task(run)
        resumed = retry_run(run_id=run.pk, user=self.user)
        self.assertEqual(self.execute(resumed)[1].call_count, 1)

    def test_changed_corpus_cannot_resume_old_input(self):
        run = self.start()
        self.execute(run, stop=lambda: True)
        self.terminal_task(run)
        self.corpus.revision += 1
        self.corpus.save(update_fields=['revision'])
        with self.assertRaisesMessage(RescreenError, '已变化'):
            retry_run(run_id=run.pk, user=self.user)

    def test_input_mutations_block_while_ai_active(self):
        self.start()
        from core.rescreening.services.fulltext_binding import bind_fulltext
        with self.assertRaisesMessage(RescreenError, '活动任务'):
            bind_fulltext(reference=self.ref, asset=None, user=self.user, expected_version=self.ref.input_version)

    def test_incomplete_fulltext_rejected_without_reserving(self):
        self.asset.extraction_truncated = True
        self.asset.save(update_fields=['extraction_truncated'])
        with self.assertRaisesMessage(RescreenError, '未完整提取'):
            self.start()
        self.assertEqual(RescreenRun.objects.count(), 0)
        self.assertFalse(CreditReservation.objects.exists())

    def test_unconfigured_provider_is_rejected_without_fake_result(self):
        with patch('core.ai.providers.provider_is_configured', return_value=False):
            with self.assertRaisesMessage(RescreenError, '凭据'):
                self.start()

    def test_zero_balance_rolls_back_run_and_task_creation(self):
        # Both balances are deliberately drained by reserving all available funds.
        from core.services.credit_ledger_service import reserve_credits
        hold_task = Task.objects.create(project=self.project, task_type='qa_eval', created_by=self.user, status='completed')
        reserve_credits(self.user, self.initial_balance, task=hold_task, idempotency_key='drain',
                        pricing_version=settings.MODEL_WEIGHTED_BILLING_PRICING_VERSION)
        with self.assertRaisesMessage(RescreenError, '积分不足'):
            self.start()
        self.assertEqual(RescreenRun.objects.count(), 0)
        self.assertFalse(Task.objects.filter(task_type='rescreen_ai').exists())

    def test_extend_hold_then_repeated_settlement_is_idempotent(self):
        run = self.start(models=[MODELS[0]])
        reservation = CreditReservation.objects.get(task=run.task)
        old_amount = reservation.reserved_credits
        extended = extend_reservation(reservation, old_amount+10)
        self.assertEqual(extended.reserved_credits, old_amount+10)
        self.execute(run)
        from core.rescreening.services.ai_billing import settle_task
        self.account.refresh_from_db()
        balance = self.account.balance
        settle_task(run.task)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, balance)
        self.assertEqual(TokenUsageLog.objects.filter(task=run.task).count(), 1)

    def test_billing_failure_retains_hold_and_blocks_new_input_until_recovered(self):
        run = self.start(models=[MODELS[0]])
        with patch('core.rescreening.services.ai_billing.settle_task', side_effect=RuntimeError('database unavailable')):
            with self.assertRaises(RuntimeError):
                self.execute(run)
        run.refresh_from_db()
        self.assertEqual(run.status, 'settlement_pending')
        self.assertEqual(CreditReservation.objects.get(task=run.task).status, 'reserved')
        finish_task(run.task)
        self.assertEqual(CreditReservation.objects.get(task=run.task).status, 'settled')

    def test_frozen_rate_version_survives_default_version_change(self):
        run = self.start(models=[MODELS[0]])
        with override_settings(MODEL_WEIGHTED_BILLING_PRICING_VERSION='not-a-real-new-version'):
            self.execute(run)
        self.assertEqual(TokenUsageLog.objects.get(task=run.task).pricing_version, run.pricing_version)

    def test_estimate_is_based_on_actual_package_and_models(self):
        first = prepare(self.project, [self.ref.pk], self.criteria, [MODELS[0]])
        second = prepare(self.project, [self.ref.pk], self.criteria, MODELS)
        self.assertEqual(first['estimate']['call_count'], 1)
        self.assertEqual(second['estimate']['call_count'], 2)
        self.assertGreater(second['estimate']['reserve_credits'], first['estimate']['reserve_credits'])

    def test_api_visibility_pagination_and_prompt_restriction(self):
        run = self.start()
        self.execute(run)
        url = f'/api/rescreening/ai/runs/{run.pk}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('prompt_version', response.data['data'])
        self.assertEqual(self.client.get('/api/rescreening/ai/prompt/', {'project_id': self.project.pk}).status_code, 403)
        self.assertEqual(self.client.get(url+'items/?page_size=1').data['data']['total'], 1)
        result = self.client.get(f'/api/rescreening/ai/items/{run.items.get().pk}/').data['data']
        self.assertNotIn('usage', result['models'][0])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_researcher_can_read_prompt_but_not_other_project(self):
        self.user.profile.role = 'researcher'
        self.user.profile.save(update_fields=['role'])
        response = self.client.get('/api/rescreening/ai/prompt/', {'project_id': self.project.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn('prompt', response.data['data'])

    def test_admin_has_no_hold_but_has_real_weighted_usage_log(self):
        self.user.profile.role = 'admin'
        self.user.profile.save(update_fields=['role'])
        self.project.name = '长项目名称' * 45
        self.project.save(update_fields=['name'])
        run = self.start(models=[MODELS[0]])
        self.assertFalse(CreditReservation.objects.filter(task=run.task).exists())
        self.execute(run)
        self.assertEqual(TokenUsageLog.objects.get(task=run.task).transaction.txn_type, 'admin_usage')
        self.assertLessEqual(len(TokenUsageLog.objects.get(task=run.task).transaction.note), 255)

    def test_wrong_task_cannot_claim_run(self):
        run = self.start()
        with self.assertRaises(RescreenRun.DoesNotExist):
            process_run(run.pk, expected_task_id=run.task_id+100)

    def test_call_budget_and_criteria_are_bounded(self):
        limits = protocol.limits_snapshot()
        with self.assertRaises(RescreenError):
            protocol.normalize_criteria(['x'] * 51, limits)
        with self.assertRaises(RescreenError):
            protocol.call_budget('x'*99001, MODELS[0], limits)
        with self.assertRaises(RescreenError):
            prepare(self.project, [True], self.criteria, MODELS)

    def test_missing_evidence_downgrades_to_pending_not_excluded(self):
        package = protocol.build_package(self.asset, [{'id': 'C1', 'text': '排除动物'}], protocol.limits_snapshot())
        body = json.dumps({'decision': 'excluded', 'reason': 'unknown', 'criteria_results': [
            {'criterion_id': 'C1', 'judgment': 'violated', 'reason': 'no data', 'evidence_ids': []}]})
        result = protocol.parse_result(body, package, [{'id': 'C1', 'text': '排除动物'}])
        self.assertEqual(result['decision'], 'pending')

    def test_redis_unavailable_does_not_fail_open_for_rescreen(self):
        from core.services.concurrency_service import try_acquire, slots_for_task
        run = self.start()
        self.assertEqual(slots_for_task(run.task, 16), 1)
        with patch('core.services.concurrency_service._get_redis', side_effect=RuntimeError('offline')):
            with self.assertRaisesMessage(RuntimeError, '并发服务不可用'):
                try_acquire(run.task_id, 1, user_id=self.user.pk, user_limit=4, strict=True)

    def test_many_criteria_batches_resume_without_repeating_successful_batch(self):
        self.criteria = ['排除动物研究'] * 9
        run = self.start(models=[MODELS[0]])
        self.assertEqual(len(run.items.get().evidence_package['batches']), 2)
        def factory(model, config):
            def generate(prompt):
                data = json.loads(prompt.split('\n')[-1])
                return self.response(prompt, model=model, invalid=data['criteria'][0]['id'] == 'C9')
            return Mock(generate_text=generate)
        done, provider = self.execute(run, factory)
        self.assertEqual(done.status, 'failed')
        self.assertEqual(provider.call_count, 2)
        self.terminal_task(run)
        resumed = retry_run(run_id=run.pk, user=self.user)
        done, provider = self.execute(resumed)
        self.assertEqual(provider.call_count, 1)
        result = done.items.get().model_results.get()
        self.assertEqual(result.status, 'completed')
        self.assertEqual(len(result.criteria_results), 9)
        self.assertEqual(RescreenCall.objects.count(), 3)

    def test_long_document_retrieves_tail_evidence_instead_of_first_characters(self):
        import fitz
        with fitz.open() as document:
            for number in range(20):
                page = document.new_page()
                page.insert_textbox(fitz.Rect(50, 50, 540, 780),
                    ('Unrelated background facts about earlier experiments. ' * 55) if number < 19 else
                    ('Methods\nParticipants were adult humans randomized in a placebo controlled trial. ' * 40))
            body = document.tobytes()
        asset, refs = self.ready(body, name='long-study.pdf', references=True)
        subset = [{'id': 'C1', 'text': 'Exclude non-randomized animal studies; inspect adult humans placebo controlled trial'}]
        limits = {**protocol.limits_snapshot(), 'short_chars': 1000, 'criterion_chars': 6000, 'body_chars': 8000}
        package = protocol.build_batches(asset, {'title': 'Long study'}, subset, [MODELS[0]], limits)
        self.assertEqual(package['strategy'], 'retrieved')
        self.assertTrue(any(row['page'] == 20 for batch in package['batches'] for row in batch['evidence']))
        self.assertTrue(package['source_complete'])
        self.assertLess(package['selected_spans'], package['total_spans'])

    def test_provider_receives_output_cap_and_no_truncation_option(self):
        run = self.start(models=[MODELS[0]])
        done, provider = self.execute(run)
        config = provider.call_args.kwargs['config']
        self.assertTrue(config['reject_prompt_truncation'])
        self.assertEqual(config['max_output_tokens'], 4096)

    def test_broker_failure_releases_hold_and_keeps_a_failed_run(self):
        with patch('core.rescreening.services.ai_runs.dispatch_step_task', side_effect=RuntimeError('broker down')):
            with self.captureOnCommitCallbacks(execute=True):
                run = self.start(models=[MODELS[0]])
        run.refresh_from_db()
        self.assertEqual(run.status, 'failed')
        self.assertEqual(CreditReservation.objects.get(task=run.task).status, 'released')

    def test_api_start_and_estimate_return_run_and_frozen_revision(self):
        payload = {'project_id': self.project.pk, 'ids': [self.ref.pk], 'criteria': self.criteria,
                   'model_ids': [MODELS[0]], 'expected_revision': self.corpus.revision}
        estimate = self.client.post('/api/rescreening/ai/estimate/', payload, format='json')
        self.assertEqual(estimate.status_code, 200)
        self.assertGreater(estimate.data['data']['reserve_credits'], 0)
        response = self.client.post('/api/rescreening/ai/start/', payload, format='json', HTTP_IDEMPOTENCY_KEY='http-once')
        self.assertEqual(response.status_code, 202)
        repeated = self.client.post('/api/rescreening/ai/start/', payload, format='json', HTTP_IDEMPOTENCY_KEY='http-once')
        self.assertEqual(repeated.data['data']['id'], response.data['data']['id'])

    def test_api_cancel_pending_run_and_retry_only_after_ack(self):
        run = self.start()
        response = self.client.post(f'/api/rescreening/ai/runs/{run.pk}/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['status'], 'paused')
        response = self.client.post(f'/api/rescreening/ai/runs/{run.pk}/retry/', {}, format='json')
        self.assertEqual(response.status_code, 202)

    def test_maintenance_pauses_rescreen_and_does_not_resume_against_changed_input(self):
        from core.operations.services import pause_long_running_tasks, resume_maintenance_tasks
        run = self.start()
        result = pause_long_running_tasks()
        self.assertIn(run.task_id, result['paused'])
        resumed = resume_maintenance_tasks()
        self.assertEqual(len(resumed['resumed']), 1)

    def test_full_worker_handler_lifecycle_uses_shared_slots_and_settles(self):
        run = self.start(models=[MODELS[0]])
        from core.executors.celery_tasks import execute_async_step
        def factory(model, config):
            return Mock(generate_text=lambda p: self.response(p, model=model))
        with patch('core.services.concurrency_service.try_acquire', return_value=True) as acquire, \
                patch('core.services.concurrency_service.release') as release, \
                patch('core.rescreening.services.ai_execution.get_provider', side_effect=factory):
            self.assertTrue(execute_async_step.run(run.task_id, 'rescreen_ai', self.project.pk))
            acquire.assert_called_once()
            self.assertTrue(acquire.call_args.kwargs['strict'])
            release.assert_called_once()
        run.task.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(run.task.status, 'completed')
        self.assertEqual(run.status, 'completed')
        self.assertEqual(CreditReservation.objects.get(task=run.task).status, 'settled')

    def test_topup_failure_preserves_original_hold(self):
        from core.rescreening.services import ai_billing
        from core.services.credit_ledger_service import reserve_credits
        run = self.start(models=[MODELS[0]])
        hold = CreditReservation.objects.get(task=run.task)
        self.account.refresh_from_db()
        other = Task.objects.create(project=self.project, task_type='qa_eval', created_by=self.user, status='completed')
        reserve_credits(self.user, self.account.balance, task=other, idempotency_key='reserve-remainder',
                        pricing_version=run.pricing_version)
        with self.assertRaisesMessage(RescreenError, '预占不足'):
            ai_billing.before_call(run.task, run, ai_billing.estimated_call(MODELS[0], 1000, 1000000))
        hold.refresh_from_db()
        self.assertEqual(hold.status, 'reserved')

    def test_finish_recovery_failure_marker_is_not_rolled_back(self):
        run = self.start()
        with patch('core.rescreening.services.ai_billing.settle_task', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                finish_task(run.task)
        run.refresh_from_db()
        self.assertEqual(run.status, 'settlement_pending')

    def test_late_provider_response_after_recovery_never_publishes_or_charges(self):
        run = self.start(models=[MODELS[0]])
        def factory(model, config):
            def generate(prompt):
                # Represents an old worker returning after interruption recovery.
                finish_task(run.task, cancelled=True)
                return self.response(prompt, model=model)
            return Mock(generate_text=generate)
        done, _ = self.execute(run, factory)
        self.assertNotEqual(done.items.get().model_results.get().status, 'completed')
        self.assertEqual(RescreenCall.objects.get().status, 'late_received')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, self.initial_balance)
        self.assertEqual(TokenUsageLog.objects.get(task=run.task).credits_consumed, 0)

    def test_known_usage_before_billing_expiry_cannot_be_refunded_as_unused(self):
        from datetime import timedelta
        from io import StringIO
        from django.core.management import call_command
        from django.utils import timezone
        run = self.start(models=[MODELS[0]])
        CreditReservation.objects.filter(task=run.task).update(expires_at=timezone.now()-timedelta(seconds=1))
        # A live/queued task is not expired out from under the worker.
        call_command('process_credit_expirations', apply=True, stdout=StringIO())
        self.assertEqual(CreditReservation.objects.get(task=run.task).status, 'reserved')
