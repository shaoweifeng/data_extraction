"""Constraints and revision semantics for the database-backed screening corpus."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import DataFile, Project
from core.screening.models import (
    DedupRun,
    ReferenceDuplicateGroup,
    ReferenceDuplicateMember,
    ReferenceImportBatch,
    ReferenceImportFile,
    ReferenceImportIssue,
    ScreeningCorpus,
    ScreeningReference,
    ScreeningResult,
    ScreeningRun,
)


class ScreeningStorageModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('screening-storage-user')
        self.project = Project.objects.create(name='Database screening', owner=self.user)
        self.corpus = ScreeningCorpus.objects.create(project=self.project)
        self.batch = ReferenceImportBatch.objects.create(
            project=self.project,
            corpus=self.corpus,
            created_by=self.user,
            operation=ReferenceImportBatch.Operation.ADD,
            base_revision=0,
            target_revision=1,
        )
        self.data_file = DataFile.objects.create(
            project=self.project,
            filename='source.ris',
            file='regression/source.ris',
            file_size=128,
            file_type='ris',
            created_by=self.user,
        )
        self.import_file = ReferenceImportFile.objects.create(
            import_batch=self.batch,
            source_file=self.data_file,
            original_filename='source.ris',
            sha256='a' * 64,
            source_format='ris',
            introduced_revision=1,
        )

    def create_reference(self, position, *, introduced_revision=1, removed_revision=None):
        return ScreeningReference.objects.create(
            project=self.project,
            corpus=self.corpus,
            import_batch=self.batch,
            import_file=self.import_file,
            source_file=self.data_file,
            source_record_index=position,
            introduced_revision=introduced_revision,
            removed_revision=removed_revision,
            title=f'Reference {position}',
            normalized_title_hash=f'{position:064x}',
            record_hash=f'{position + 100:064x}',
        )

    def test_source_position_is_unique_within_import_file(self):
        self.create_reference(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_reference(1)

    def test_revision_visibility_and_atomic_publish(self):
        first = self.create_reference(1, introduced_revision=1, removed_revision=2)
        second = self.create_reference(2, introduced_revision=2)

        self.assertQuerySetEqual(
            ScreeningReference.objects.active_at(1), [first], transform=lambda item: item,
        )
        self.corpus.publish_revision(
            expected_revision=0,
            target_revision=1,
            active_reference_count=1,
            active_source_file_count=1,
            last_import_batch=self.batch,
        )
        self.assertQuerySetEqual(
            ScreeningReference.objects.current(), [first], transform=lambda item: item,
        )
        self.corpus.publish_revision(
            expected_revision=1,
            target_revision=2,
            active_reference_count=1,
            active_source_file_count=1,
        )
        self.assertQuerySetEqual(
            ScreeningReference.objects.current(), [second], transform=lambda item: item,
        )

        with self.assertRaisesMessage(ValidationError, '文献集修订号已变化'):
            self.corpus.publish_revision(
                expected_revision=1,
                target_revision=2,
                active_reference_count=1,
                active_source_file_count=1,
            )
        with self.assertRaisesMessage(ValidationError, '下一版'):
            self.corpus.publish_revision(
                expected_revision=2,
                target_revision=4,
                active_reference_count=1,
                active_source_file_count=1,
            )
        self.corpus.revision = 1
        with self.assertRaisesMessage(ValidationError, '文献集修订号不能回退'):
            self.corpus.save()

    def test_reference_can_only_be_member_once_per_dedup_run(self):
        reference = self.create_reference(1)
        run = DedupRun.objects.create(
            project=self.project,
            corpus=self.corpus,
            corpus_revision=0,
            created_by=self.user,
            rule_version='v1.5.0-title',
        )
        first_group = ReferenceDuplicateGroup.objects.create(
            dedup_run=run,
            sequence=1,
            representative_reference=reference,
            match_type='normalized_title',
            match_key_hash='b' * 64,
        )
        second_group = ReferenceDuplicateGroup.objects.create(
            dedup_run=run,
            sequence=2,
            representative_reference=reference,
            match_type='normalized_title',
            match_key_hash='c' * 64,
        )
        ReferenceDuplicateMember.objects.create(
            dedup_run=run,
            group=first_group,
            reference=reference,
            role=ReferenceDuplicateMember.Role.KEPT,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReferenceDuplicateMember.objects.create(
                dedup_run=run,
                group=second_group,
                reference=reference,
                role=ReferenceDuplicateMember.Role.DUPLICATE,
            )

    def test_screening_result_is_idempotent_per_run_and_reference(self):
        reference = self.create_reference(1)
        run = ScreeningRun.objects.create(
            project=self.project,
            corpus=self.corpus,
            corpus_revision=0,
            created_by=self.user,
        )
        ScreeningResult.objects.create(screening_run=run, reference=reference)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ScreeningResult.objects.create(screening_run=run, reference=reference)

    def test_operational_models_are_registered_in_admin(self):
        for model in (
            ScreeningCorpus,
            ReferenceImportBatch,
            ReferenceImportFile,
            ReferenceImportIssue,
            ScreeningReference,
            DedupRun,
            ReferenceDuplicateGroup,
            ReferenceDuplicateMember,
            ScreeningRun,
            ScreeningResult,
        ):
            with self.subTest(model=model.__name__):
                self.assertTrue(admin.site.is_registered(model))
