"""Stage 7: SQL workflow state, private settings and optimistic human review."""
from unittest.mock import patch
from core.models import ProjectStage
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenReviewEvent, RescreenRunItem
from core.rescreening.services.workspace import save_configuration, save_review, workspace_state, reference_query
from core.tests.test_shared_fulltext import SharedFulltextFixture


class RescreenWorkspaceTests(SharedFulltextFixture):
    def setUp(self):
        super().setUp()
        _, refs = self.ready(references=True)
        self.ref = refs[0]
        self.ref.refresh_from_db()

    def config(self, **changes):
        payload = dict(project=self.project, user=self.user, expected_version=0,
                       criteria=['排除动物研究'], model_ids=['deepseek-v4-flash'])
        payload.update(changes)
        return save_configuration(**payload)

    def save(self, **changes):
        state = workspace_state(self.project, self.user)
        row = reference_query(self.project).get(pk=self.ref.pk)
        payload = dict(project=self.project, user=self.user, reference_id=self.ref.pk,
            input_version=self.ref.input_version, expected_version=0,
            criteria_revision_id=state['configuration']['criteria_revision_id'],
            suggestion_id=row.suggestion_id, suggestion_revision=row.suggestion_revision or 0,
            decision='included')
        payload.update(changes)
        return save_review(**payload)

    def test_empty_project_and_persistent_step_gates(self):
        state = workspace_state(self.project, self.user)
        self.assertEqual(state['counts']['total'], 1)
        self.assertFalse(state['steps'][3]['enabled'])
        self.config()
        state = workspace_state(self.project, self.user)
        self.assertTrue(state['steps'][3]['enabled'])
        self.assertFalse(state['steps'][4]['completed'])
        self.save()
        self.assertTrue(workspace_state(self.project, self.user)['steps'][4]['completed'])
        self.assertFalse(workspace_state(self.project, self.user)['steps'][5]['completed'])

    def test_review_save_version_conflict_and_audit(self):
        self.config()
        self.save(note='第一次确认')
        with self.assertRaisesMessage(RescreenError, '另一页面'):
            self.save(decision='excluded', reason='不同意见')
        self.save(expected_version=1, decision='excluded', reason='目标人群不符')
        self.assertEqual(RescreenReviewEvent.objects.count(), 2)
        self.assertEqual(RescreenReviewEvent.objects.first().payload['note'], '第一次确认')
        state = workspace_state(self.project, self.user)
        self.assertEqual(state['counts']['excluded'], 1)
        self.assertEqual(state['counts']['included'], 0)

    def test_manual_review_can_skip_ai_and_no_new_model_calls(self):
        self.save(decision='included')
        state = workspace_state(self.project, self.user)
        self.assertEqual(state['counts']['finalized'], 1)
        self.assertIsNone(state['latest_run_id'])

    def test_criteria_change_requires_reconfirmation_without_destroying_review(self):
        self.config()
        self.save()
        self.config(expected_version=1, criteria=['排除非随机研究'])
        state = workspace_state(self.project, self.user)
        self.assertEqual(state['counts']['remaining'], 1)
        self.assertEqual(state['counts']['needs_reconfirmation'], 1)
        row = reference_query(self.project).get()
        self.assertEqual(row.current_review.decision, 'included')

    def test_excluded_requires_reason_and_existing_pdf_cannot_be_not_retrieved(self):
        with self.assertRaisesMessage(RescreenError, '理由'):
            self.save(decision='excluded')
        with self.assertRaisesMessage(RescreenError, '已存在'):
            self.save(decision='not_retrieved')

    def test_stale_input_and_criteria_cannot_overwrite(self):
        self.config()
        with self.assertRaisesMessage(RescreenError, '已变化'):
            self.save(input_version=99)
        with self.assertRaisesMessage(RescreenError, '已变化'):
            self.save(criteria_revision_id=999)

    def test_private_prompt_is_not_returned_to_regular_user_or_stage_metadata(self):
        self.user.profile.role = 'researcher'
        self.user.profile.save(update_fields=['role'])
        config = self.config(custom_prompt='PRIVATE-PROMPT-MARKER')
        self.assertIn('custom_prompt', config)
        self.user.profile.role = 'user'
        self.user.profile.save(update_fields=['role'])
        state = self.client.get('/api/rescreening/workspace/', {'project_id': self.project.pk})
        self.assertEqual(state.status_code, 200)
        self.assertNotIn('PRIVATE-PROMPT-MARKER', str(state.data))
        self.assertNotIn('protocol_prompt', str(state.data))
        self.assertNotIn('PRIVATE-PROMPT-MARKER', str(list(ProjectStage.objects.filter(project=self.project).values())))
        with self.assertRaisesMessage(RescreenError, '无权修改'):
            self.config(expected_version=1, custom_prompt='try overwrite')

    def test_settings_conflict_and_normal_save_preserves_private_prompt(self):
        self.user.profile.role = 'researcher'
        self.user.profile.save(update_fields=['role'])
        self.config(custom_prompt='private')
        with self.assertRaisesMessage(RescreenError, '其他页面'):
            self.config()
        self.user.profile.role = 'user'
        self.user.profile.save(update_fields=['role'])
        self.config(expected_version=1)
        from core.rescreening.models import RescreenSettings
        self.assertEqual(RescreenSettings.objects.get().custom_prompt, 'private')

    def test_paginated_api_counts_filters_and_permissions(self):
        self.config()
        self.save()
        url = '/api/rescreening/workspace/references/'
        response = self.client.get(url, {'project_id': self.project.pk, 'status': 'included', 'page_size': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['total'], 1)
        self.assertTrue(response.data['data']['items'][0]['review_valid'])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url, {'project_id': self.project.pk}).status_code, 403)
        self.assertEqual(self.client.get(f'/api/rescreening/references/{self.ref.pk}/review/').status_code, 404)

    def test_review_tabs_use_global_counts_and_sql_filters(self):
        self.config()
        suggestion = self.suggestion()
        suggestion.consensus = 'conflict'
        suggestion.save(update_fields=['consensus'])
        self.save(decision='pending')
        state = workspace_state(self.project, self.user)
        self.assertEqual(state['counts']['conflict'], 1)
        self.assertEqual(state['counts']['pending'], 1)
        url = '/api/rescreening/workspace/references/'
        for status in ('conflict', 'pending'):
            response = self.client.get(url, {'project_id': self.project.pk, 'status': status, 'page_size': 1})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['data']['total'], 1)
            self.assertEqual(response.data['data']['items'][0]['source_type'], 'pdf')
        self.config(expected_version=1, criteria=['排除非随机研究'])
        state = workspace_state(self.project, self.user)
        self.assertEqual(state['counts']['pending'], 0)
        self.assertEqual(state['counts']['conflict'], 0)
        self.assertEqual(state['counts']['needs_reconfirmation'], 1)
        for status in ('conflict', 'pending'):
            response = self.client.get(url, {'project_id': self.project.pk, 'status': status})
            self.assertEqual(response.data['data']['total'], 0)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(url, {'project_id': self.project.pk, 'status': 'conflict'}).status_code, 403)

    def test_fulltext_cards_count_all_references_not_current_page(self):
        state = workspace_state(self.project, self.user)
        self.assertEqual((state['counts']['bound'], state['counts']['missing'], state['counts']['fulltext_failed']), (1, 0, 0))
        asset = self.ref.current_binding.asset
        asset.status = 'failed'
        asset.save(update_fields=['status'])
        state = workspace_state(self.project, self.user)
        self.assertEqual((state['counts']['bound'], state['counts']['ready'], state['counts']['fulltext_failed']), (0, 0, 1))
        from core.rescreening.services.fulltext_binding import bind_fulltext
        bind_fulltext(reference=self.ref, asset=None, user=self.user, expected_version=self.ref.input_version)
        state = workspace_state(self.project, self.user)
        self.assertEqual((state['counts']['bound'], state['counts']['missing'], state['counts']['fulltext_failed']), (0, 1, 0))

    def test_save_api_refreshes_stats_and_history(self):
        detail = self.client.get(f'/api/rescreening/references/{self.ref.pk}/review/').data['data']
        response = self.client.post(f'/api/rescreening/references/{self.ref.pk}/review/', {
            'input_version': detail['input_version'], 'expected_version': 0, 'criteria_revision_id': None,
            'suggestion_id': None, 'suggestion_revision': 0, 'decision': 'included', 'note': '已阅读全文',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['data']['review_valid'])
        history = self.client.get(f'/api/rescreening/references/{self.ref.pk}/review/history/').data['data']
        self.assertEqual(history['total'], 1)

    def suggestion(self):
        from core.rescreening.models import RescreenRun, RescreenCriteriaRevision
        from core.bibliography import bibliography_snapshot
        run = RescreenRun.objects.create(corpus=self.ref.corpus, input_revision=self.ref.corpus.revision,
            criteria_revision=RescreenCriteriaRevision.objects.latest('pk'), model_ids=['deepseek-v4-flash'],
            config_snapshot={}, status='completed', total_count=1, processed_count=1)
        return RescreenRunItem.objects.create(run=run, reference=self.ref, input_version=self.ref.input_version,
            raw_metadata_version=self.ref.raw_metadata_versions.get(input_version=self.ref.input_version),
            asset=self.ref.current_binding.asset, bibliography_snapshot=bibliography_snapshot(self.ref),
            status='completed', consensus='included', result_revision=1)

    def test_new_run_or_retry_changes_suggestion_but_preserves_human_history(self):
        self.config()
        first = self.suggestion()
        self.save()
        self.assertEqual(workspace_state(self.project, self.user)['counts']['remaining'], 0)
        first.result_revision += 1
        first.save(update_fields=['result_revision'])
        self.assertEqual(workspace_state(self.project, self.user)['counts']['needs_reconfirmation'], 1)
        with self.assertRaisesMessage(RescreenError, '已变化'):
            self.save(expected_version=1, suggestion_revision=1)
        self.save(expected_version=1)
        second = self.suggestion()
        self.assertEqual(workspace_state(self.project, self.user)['counts']['remaining'], 1)
        self.assertEqual(RescreenReviewEvent.objects.count(), 2)
        self.assertNotEqual(second.pk, first.pk)

    def test_not_retrieved_can_be_finalized_without_any_pdf(self):
        from core.rescreening.services.fulltext_binding import bind_fulltext
        self.ref = bind_fulltext(reference=self.ref, asset=None, user=self.user, expected_version=self.ref.input_version)
        self.save(decision='not_retrieved', note='已尝试获取，作者未回复')
        self.assertEqual(workspace_state(self.project, self.user)['counts']['not_retrieved'], 1)

    def test_prompt_is_frozen_in_actual_estimate_without_any_provider_calls(self):
        from core.rescreening.services.ai_runs import prepare
        self.user.profile.role = 'researcher'
        self.user.profile.save(update_fields=['role'])
        self.config(custom_prompt='私有项目补充要求')
        with patch('core.ai.providers.provider_is_configured', return_value=True):
            prepared = prepare(self.project, [self.ref.pk], ['排除动物研究'], ['deepseek-v4-flash'])
        self.assertIn('私有项目补充要求', prepared['template'])
        self.assertIn('criteria_results', prepared['template'])
        self.assertEqual(prepared['settings_version'], 1)

    def test_noop_settings_save_does_not_invalidate_runs(self):
        self.config()
        unchanged = self.config(expected_version=1)
        self.assertEqual(unchanged['version'], 1)
