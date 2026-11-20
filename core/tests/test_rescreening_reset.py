"""Exclusive import modes, explicit reset, and independent QA preservation."""
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Project, ProjectStage, Task, QAReference, StageStep
from core.fulltext.models import FulltextAsset
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus, RescreenReference, RescreenExport, RescreenRun, RescreenReview
from core.rescreening.services.reset import reset_corpus
from core.rescreening.services.exports import fingerprint
from core.rescreening.services.import_mode import select_import_mode
from core.rescreening.services.imports import start_import
from core.rescreening.services.workspace import save_configuration, workspace_state
from core.rescreening.services.qa_handoff import preview, handoff
from core.tests.test_rescreening_delivery import RescreenDeliveryFixture
from core.tests import test_rescreening_workspace as workspace_tests
from core.tests.test_screening_imports import ris_file
from core.fulltext.services import create_assets
from core.tests.test_qa_fulltext import make_pdf


class RescreenResetTests(RescreenDeliveryFixture):
    def reset(self, **changes):
        state = workspace_state(self.project, self.user)
        return reset_corpus(project=self.project, user=self.user, **(dict(expected_revision=state['revision'],
            expected_mode=state['import_mode'], expected_fingerprint=state['fingerprint']) | changes))

    def test_mode_is_persistent_and_all_import_paths_enforce_it(self):
        self.assertEqual(workspace_state(self.project, self.user)['import_mode'], 'pdf')
        with self.assertRaisesMessage(RescreenError, '导入模式'):
            select_import_mode(self.project, self.user, 'bibliography')
        with self.assertRaisesMessage(RescreenError, '导入模式'):
            start_import(project=self.project, user=self.user, idempotency_key='different-mode', uploads=[ris_file()])
        self.assertEqual(select_import_mode(self.project, self.user, 'pdf'), 'pdf')
        self.assertEqual(RescreenReference.objects.count(), 1)

    def test_reset_deletes_complete_rescreen_graph_and_unused_private_files(self):
        save_configuration(project=self.project, user=self.user, expected_version=0,
            criteria=['排除非人类研究'], model_ids=['deepseek-v4-flash'])
        workspace_tests.RescreenWorkspaceTests.suggestion(self)
        self.review()
        job = self.generate()
        old_workspace = self.root / 'workspaces' / f'project_{self.project.pk}' / f'rescreen_export_task_{job.task_id}_20260101_000000'
        old_workspace.mkdir(parents=True)
        (old_workspace / 'log.txt').write_text('旧复筛任务日志')
        qa_workspace = old_workspace.parent / 'qa_eval_task_999_20260101_000000'
        qa_workspace.mkdir()
        storage, name = self.asset.raw_file.storage, self.asset.raw_file.name
        initial = StageStep.objects.get(stage__project=self.project, stage__stage_key='SCREEN_1', step_key='criteria')
        initial.metadata = {'criteria': ['初筛标准保留']}
        initial.save()
        before = workspace_state(self.project, self.user)['revision']
        with self.captureOnCommitCallbacks(execute=True):
            self.reset()
        state = workspace_state(self.project, self.user)
        self.assertEqual((state['counts']['total'], state['import_mode'], state['revision']), (0, '', before+1))
        self.assertEqual(state['configuration']['criteria'], [])
        for model in (RescreenReference, RescreenExport, RescreenRun, RescreenReview, FulltextAsset):
            self.assertEqual(model.objects.count(), 0, model.__name__)
        self.assertFalse(storage.exists(name))
        self.assertFalse(old_workspace.exists())
        self.assertTrue(qa_workspace.exists())
        self.assertFalse(Task.objects.filter(project=self.project, task_type__startswith='rescreen_').exists())
        initial.refresh_from_db()
        self.assertEqual(initial.metadata['criteria'], ['初筛标准保留'])
        self.assertTrue(all(not step['completed'] for step in state['steps']))
        self.assertEqual(select_import_mode(self.project, self.user, 'bibliography'), 'bibliography')

    def test_reset_preserves_qa_snapshots_fulltext_and_prevents_duplicate_handoff(self):
        self.review()
        self.transfer()
        qa = QAReference.objects.get()
        qa.ai_eval_status = 'completed'
        qa.save(update_fields=['ai_eval_status'])
        saved_bibliography = qa.rescreen_source_snapshot.bibliography
        with self.captureOnCommitCallbacks(execute=True):
            result = self.reset()
        self.assertEqual(result['retained_qa'], 1)
        qa.refresh_from_db()
        self.assertIsNone(qa.source_rescreen_reference_id)
        self.assertIsNone(qa.source_rescreen_review_id)
        self.assertEqual(qa.ai_eval_status, 'completed')
        self.assertEqual(qa.rescreen_source_snapshot.bibliography, saved_bibliography)
        self.assertTrue(qa.shared_fulltext_asset.raw_file.storage.exists(qa.shared_fulltext_asset.raw_file.name))
        with self.asset.raw_file.open('rb') as stream:
            body = stream.read()
        _, refs = create_assets(project=self.project, user=self.user, create_references=True, schedule=False,
            files=[SimpleUploadedFile('again.pdf', body, content_type='application/pdf')])
        self.ref = refs[0]
        self.review()
        current = preview(self.project)
        self.assertEqual((current['counts']['new'], current['counts']['existing']), (0, 1))
        with self.assertRaisesMessage(RescreenError, '来源差异'):
            self.transfer()
        self.assertEqual(self.transfer(acknowledge_differences=True)['imported'], 0)
        self.assertEqual(QAReference.objects.count(), 1)

    def test_reset_refuses_stale_request_and_active_tasks(self):
        with self.assertRaisesMessage(RescreenError, '数据已变化'):
            self.reset(expected_revision=100)
        self.assertEqual(RescreenReference.objects.count(), 1)
        Task.objects.create(project=self.project, task_type='rescreen_pdf', status='running')
        with self.assertRaisesMessage(RescreenError, '活动任务'):
            self.reset()
        self.assertEqual(RescreenReference.objects.count(), 1)

    def test_reset_requires_explicit_confirmation_and_owner_permission(self):
        url = '/api/rescreening/workspace/reset/'
        response = self.client.post(url, {'project_id': self.project.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(url, {'project_id': self.project.pk, 'confirm': True}, format='json').status_code, 403)
        self.assertEqual(RescreenReference.objects.count(), 1)

    def test_reset_preserves_credit_audit_and_refuses_unsettled_holds(self):
        from core.models_billing import CreditAccount, CreditReservation, CreditTransaction
        account, _ = CreditAccount.objects.get_or_create(user=self.user)
        task = Task.objects.create(project=self.project, task_type='rescreen_ai', status='failed')
        reservation = CreditReservation.objects.create(account=account, task=task, idempotency_key='reset-test-hold',
            pricing_version='test', status='reserved', estimated_credits=10, reserved_credits=10)
        with self.assertRaisesMessage(RescreenError, '积分尚未结算'):
            self.reset()
        reservation.status = 'released'
        reservation.save(update_fields=['status'])
        transaction = CreditTransaction.objects.create(account=account, task=task, txn_type='consume',
            amount=-10, balance_after=account.balance, note='保留结算记录')
        balance = account.balance
        self.reset()
        transaction.refresh_from_db()
        reservation.refresh_from_db()
        account.refresh_from_db()
        self.assertIsNone(transaction.task_id)
        self.assertIsNone(reservation.task_id)
        self.assertEqual(account.balance, balance)

    def test_reset_and_mode_selection_reject_stale_epochs(self):
        state = workspace_state(self.project, self.user)
        self.reset()
        with self.assertRaisesMessage(RescreenError, '数据已变化'):
            reset_corpus(project=self.project, user=self.user, expected_revision=state['revision'],
                expected_mode=state['import_mode'], expected_fingerprint=state['fingerprint'])
        with self.assertRaisesMessage(RescreenError, '文献已变化'):
            select_import_mode(self.project, self.user, 'pdf', state['revision'])
        from core.fulltext.errors import FulltextError
        with self.assertRaisesMessage(FulltextError, '文献已变化'):
            create_assets(project=self.project, user=self.user, create_references=False, schedule=False,
                expected_revision=state['revision'], files=[SimpleUploadedFile('late.pdf', make_pdf(), content_type='application/pdf')])

    def test_mode_api_requires_revision_and_survives_reload(self):
        self.reset()
        state = workspace_state(self.project,self.user)
        response = self.client.post('/api/rescreening/workspace/import-mode/', {'project_id': self.project.pk,
            'mode': 'bibliography', 'expected_revision': state['revision']}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/rescreening/workspace/', {'project_id':self.project.pk}).data['data']['import_mode'], 'bibliography')
        response = self.client.post('/api/fulltext/assets/upload/', {'project_id':self.project.pk,
            'create_references':'true', 'files':SimpleUploadedFile('wrong.pdf', make_pdf(), content_type='application/pdf')}, format='multipart')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'import_mode_locked')

    def test_migration_recognizes_historical_mixed_modes_without_deleting_data(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        from core.rescreening.models import RescreenImportBatch
        populate = import_module('core.migrations.0057_rescreencorpus_import_mode').populate_modes
        populate(apps, SimpleNamespace(connection=connection))
        self.assertEqual(RescreenCorpus.objects.get(project=self.project).import_mode, 'pdf')
        corpus = RescreenCorpus.objects.get(project=self.project)
        RescreenImportBatch.objects.create(project=self.project, corpus=corpus, source_type='bibliography',
            status='failed', base_revision=corpus.revision, target_revision=corpus.revision+1,
            idempotency_key='historical-mixed', request_hash='test', limits_snapshot={})
        populate(apps, SimpleNamespace(connection=connection))
        self.assertEqual(RescreenCorpus.objects.get(project=self.project).import_mode, 'mixed')
        self.assertEqual(RescreenReference.objects.count(), 1)
        self.assertEqual(FulltextAsset.objects.count(), 1)

    def test_criteria_can_delete_last_row_and_initial_criteria_is_project_scoped(self):
        config = save_configuration(project=self.project, user=self.user, expected_version=0,
            criteria=['排除动物'], model_ids=[])
        result = save_configuration(project=self.project, user=self.user, expected_version=config['version'], criteria=[], model_ids=[])
        self.assertEqual(result['criteria'], [])
        self.assertFalse(workspace_state(self.project,self.user)['steps'][2]['completed'])
        url = '/api/rescreening/initial-criteria/'
        data = self.client.get(url, {'project_id': self.project.pk}).data['data']
        self.assertFalse(data['performed'])
        step = StageStep.objects.get(stage__project=self.project, stage__stage_key='SCREEN_1', step_key='criteria')
        step.metadata = {'criteria': ['年龄不足18岁']}
        step.save()
        data = self.client.get(url, {'project_id': self.project.pk}).data['data']
        self.assertEqual(data, {'performed': True, 'criteria': ['年龄不足18岁']})
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url, {'project_id': self.project.pk}).status_code, 403)
