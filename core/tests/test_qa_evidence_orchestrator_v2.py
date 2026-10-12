"""End-to-end contracts for the production V2 QA evidence orchestrator."""

import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from core.models import (
    Project,
    QAEvaluationRun,
    QAModelSignalResult,
    QAReference,
    QASignalItem,
    Task,
)
from core.quality.executors.qa_eval import QAEvalHandler


User = get_user_model()


def evidence_package(reference, *, result_type='bias_risk'):
    text = 'Consecutive participants were enrolled at the study hospital.'
    sha = hashlib.sha256(text.encode()).hexdigest()
    chunk_id = 'p0003-p0003-c0001'
    signal_key = 'ps_consecutive' if result_type == 'bias_risk' else 'ps_applicability'
    return {
        'retrieval_version': 'qa-evidence-lexical-v1',
        'method_key': 'QUADAS2',
        'method_config_version': '2026.10-v1',
        'method_variant': '',
        'domain': 'patient_selection',
        'domain_name': '患者选择',
        'reference': {
            'id': reference.id,
            'project_id': reference.project_id,
            'title': reference.title,
            'first_author': '',
            'year': None,
            'abstract': '',
        },
        'signal_items': [{
            'domain': 'patient_selection',
            'result_type': result_type,
            'signal_key': signal_key,
            'signal_question': '是否连续入组？',
            'signal_description': '判断是否连续或随机抽样。',
            'options': ['是', '否', '不清楚'] if result_type == 'bias_risk' else ['低', '高', '不清楚'],
        }],
        'selected_chunks': [{
            'chunk_id': chunk_id,
            'page_start': 3,
            'page_end': 3,
            'section': 'methods',
            'sha256': sha,
            'text': text,
            'evidence_spans': [{
                'span_id': 'p0003-s0001-abcdef12',
                'page_number': 3,
                'section': 'methods',
                'char_count': len(text),
                'sha256': sha,
                'text': text,
            }],
            'selected_for': [signal_key],
        }],
        'signal_coverage': {signal_key: [chunk_id]},
    }


def validated_result(package, judgment='是'):
    span = package['selected_chunks'][0]['evidence_spans'][0]
    return [{
        'signal_key': package['signal_items'][0]['signal_key'],
        'judgment': judgment,
        'reason': '原文明确报告。',
        'evidence_refs': ['E001'],
        'resolved_evidence': [{
            'ref_id': 'E001',
            'span_id': span['span_id'],
            'chunk_id': package['selected_chunks'][0]['chunk_id'],
            'page_number': span['page_number'],
            'section': span['section'],
            'text': span['text'],
            'sha256': span['sha256'],
        }],
        'validation_status': 'validated',
    }]


class EvidenceV2OrchestratorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('v2-owner', password='pw')
        self.project = Project.objects.create(name='V2 project', owner=self.user)
        self.reference = QAReference.objects.create(
            project=self.project,
            title='V2 diagnostic study',
            quality_method='QUADAS2',
            ai_eval_status='running',
        )
        self.task = Task.objects.create(
            project=self.project,
            task_type='qa_eval',
            created_by=self.user,
        )
        self.package = evidence_package(self.reference)

    def handler(self, models=None, *, stop_checker=None):
        handler = QAEvalHandler(
            self.project.id,
            [self.reference.id],
            'single',
            models or ['model-a'],
            user_id=self.user.id,
            stop_checker=stop_checker,
        )
        handler.task_obj = self.task
        return handler

    @patch('core.quality.services.evidence_orchestrator_v2.get_model_config', return_value={'name': 'Model A'})
    @patch('core.quality.services.evidence_orchestrator_v2.build_reference_evidence_packages')
    @patch('core.quality.services.evidence_orchestrator_v2.call_model_v2')
    def test_valid_result_is_independently_persisted_and_task_retry_is_idempotent(
        self, call_model, build_packages, _model_config,
    ):
        build_packages.return_value = [self.package]
        call_model.return_value = (
            validated_result(self.package),
            {'prompt': 100, 'completion': 20, 'total': 120},
            [],
            'a' * 64,
        )
        first = self.handler()
        stats = first._eval_one_ref_with_evidence_v2(self.reference)
        first._v2_orchestrator.finalize()
        self.assertEqual(stats['total'], 120)
        self.assertEqual(call_model.call_count, 1)
        run = QAEvaluationRun.objects.get()
        row = QAModelSignalResult.objects.get()
        item = QASignalItem.objects.get()
        self.assertEqual(run.status, 'completed')
        self.assertEqual(run.validated_count, 1)
        self.assertEqual(row.status, 'validated')
        self.assertEqual(item.ai_judgment, '是')
        self.assertEqual(item.model_results[0]['evidence_span_ids'], ['p0003-s0001-abcdef12'])
        item.human_judgment = '否'
        item.is_confirmed = True
        item.confirmed_by = self.user
        item.save(update_fields=['human_judgment', 'is_confirmed', 'confirmed_by'])

        second = self.handler()
        self.reference.refresh_from_db()
        second._eval_one_ref_with_evidence_v2(self.reference)
        second._v2_orchestrator.finalize()
        self.assertEqual(call_model.call_count, 1)
        self.assertEqual(QAEvaluationRun.objects.count(), 1)
        self.assertEqual(QAModelSignalResult.objects.count(), 1)
        item.refresh_from_db()
        self.assertTrue(item.is_confirmed)
        self.assertEqual(item.human_judgment, '否')

    @patch('core.quality.services.evidence_orchestrator_v2.get_model_config', return_value={'name': 'Model A'})
    @patch('core.quality.services.evidence_orchestrator_v2.build_reference_evidence_packages')
    @patch('core.quality.services.evidence_orchestrator_v2.call_model_v2')
    def test_protocol_violation_becomes_manual_review_without_ai_recommendation(
        self, call_model, build_packages, _model_config,
    ):
        build_packages.return_value = [self.package]
        call_model.return_value = ([], {'total': 10}, [{
            'code': 'evidence_ref_not_allowed',
            'signal_key': 'ps_consecutive',
            'returned_refs': ['E999'],
            'allowed_refs': ['E001'],
        }], 'b' * 64)
        handler = self.handler()
        handler._eval_one_ref_with_evidence_v2(self.reference)
        handler._v2_orchestrator.finalize()
        row = QAModelSignalResult.objects.get()
        item = QASignalItem.objects.get()
        self.reference.refresh_from_db()
        self.assertEqual(row.status, 'needs_review')
        self.assertEqual(row.evidence_refs, ['E999'])
        self.assertEqual(row.resolved_evidence, [])
        self.assertEqual(item.ai_judgment, '')
        self.assertEqual(item.pre_selected, '')
        self.assertEqual(item.model_results[0]['validation_status'], 'needs_review')
        self.assertEqual(self.reference.ai_eval_status, 'completed')
        self.assertEqual(QAEvaluationRun.objects.get().status, 'completed')

    @patch('core.quality.services.evidence_orchestrator_v2.get_model_config', side_effect=lambda model: {'name': model})
    @patch('core.quality.services.evidence_orchestrator_v2.build_reference_evidence_packages')
    @patch('core.quality.services.evidence_orchestrator_v2.call_model_v2')
    def test_partial_multi_model_result_uses_only_trusted_model(
        self, call_model, build_packages, _model_config,
    ):
        build_packages.return_value = [self.package]

        def response(model_id, *_args):
            if model_id == 'model-a':
                return validated_result(self.package), {'total': 12}, [], 'a' * 64
            return [], None, [{'code': 'provider_failed', 'error': 'TimeoutError'}], ''

        call_model.side_effect = response
        handler = self.handler(['model-a', 'model-b'])
        handler._eval_one_ref_with_evidence_v2(self.reference)
        handler._v2_orchestrator.finalize()
        item = QASignalItem.objects.get()
        self.reference.refresh_from_db()
        self.assertEqual(item.ai_judgment, '是')
        self.assertEqual(item.consistency, 'partial')
        self.assertEqual(
            set(QAModelSignalResult.objects.values_list('status', flat=True)),
            {'validated', 'provider_failed'},
        )
        self.assertEqual(self.reference.ai_eval_status, 'completed')
        self.assertEqual(QAEvaluationRun.objects.get().status, 'partial')

    @patch('core.quality.services.evidence_orchestrator_v2.build_reference_evidence_packages')
    @patch('core.quality.services.evidence_orchestrator_v2.call_model_v2')
    def test_retryable_failure_is_bounded_to_two_attempts(
        self, call_model, build_packages,
    ):
        build_packages.return_value = [self.package]
        call_model.return_value = (
            [], None, [{'code': 'provider_failed', 'error': 'TimeoutError'}], '',
        )
        for _ in range(3):
            handler = self.handler()
            self.reference.refresh_from_db()
            handler._eval_one_ref_with_evidence_v2(self.reference)
            handler._v2_orchestrator.finalize()
        self.assertEqual(call_model.call_count, 2)
        self.assertEqual(QAModelSignalResult.objects.get().attempt_count, 2)
        self.reference.refresh_from_db()
        self.assertEqual(self.reference.ai_eval_status, 'failed')

    @patch('core.quality.services.evidence_orchestrator_v2.build_reference_evidence_packages')
    @patch('core.quality.services.evidence_orchestrator_v2.call_model_v2')
    def test_stop_before_domain_makes_run_and_reference_resumable(
        self, call_model, build_packages,
    ):
        build_packages.return_value = [self.package]
        handler = self.handler(stop_checker=lambda: True)
        self.assertIsNone(handler._eval_one_ref_with_evidence_v2(self.reference))
        handler._v2_orchestrator.finalize(stopped=True)
        self.reference.refresh_from_db()
        self.assertTrue(handler.was_stopped)
        self.assertEqual(self.reference.ai_eval_status, 'pending')
        self.assertEqual(QAEvaluationRun.objects.get().status, 'stopped')
        call_model.assert_not_called()

    def test_project_delete_cascades_v2_audit_rows(self):
        run = QAEvaluationRun.objects.create(
            project=self.project,
            task=self.task,
            protocol_version='qa-evidence-protocol-v2',
            retrieval_version='qa-evidence-lexical-v1',
            chunking_version='qa-chunks-v2-spans',
        )
        QAModelSignalResult.objects.create(
            evaluation_run=run,
            qa_reference=self.reference,
            signal_key='ps_consecutive',
            model_id='model-a',
        )
        self.project.delete()
        self.assertFalse(QAEvaluationRun.objects.exists())
        self.assertFalse(QAModelSignalResult.objects.exists())


class QAReviewContextApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('context-owner', password='pw')
        self.outsider = User.objects.create_user('context-outsider', password='pw')
        self.project = Project.objects.create(name='Context project', owner=self.owner)
        self.client = Client()
        self.client.force_login(self.owner)
        self.url = '/api/qa/review-context/'

    def test_owner_can_upsert_and_read_context_but_outsider_cannot(self):
        response = self.client.put(
            self.url,
            data={
                'project_id': self.project.id,
                'quality_method': 'QUADAS2',
                'method_variant': '',
                'target_population': '成年患者',
                'index_test': 'CT',
                'target_condition': '肺癌',
                'reference_standard': '病理学',
                'intended_use': '初筛',
                'review_objective': '评价诊断准确性',
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['target_population'], '成年患者')
        listing = self.client.get(self.url, {'project_id': self.project.id})
        self.assertEqual(len(listing.json()['data']), 1)

        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(self.url, {'project_id': self.project.id}).status_code,
            404,
        )
        self.assertEqual(
            self.client.put(
                self.url,
                data={
                    'project_id': self.project.id,
                    'quality_method': 'QUADAS2',
                },
                content_type='application/json',
            ).status_code,
            404,
        )
