import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import DataFile, Project


class LegacyScreeningArtifactCleanupTests(TestCase):
    def test_command_is_dry_run_by_default_and_deletes_file_when_executed(self):
        user = get_user_model().objects.create_user('cleanup-user', password='pw')
        project = Project.objects.create(name='Cleanup project', owner=user)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            artifact = DataFile.objects.create(
                project=project,
                filename='reference_1.xml',
                data_category='intermediate',
                source='tool_generated',
                metadata={'artifact_type': 'screening_parsed_reference_xml'},
                created_by=user,
            )
            artifact.file.save('reference_1.xml', ContentFile(b'<reference/>'))
            storage = artifact.file.storage
            stored_name = artifact.file.name

            preview = StringIO()
            call_command(
                'cleanup_legacy_screening_artifacts',
                project_id=project.id,
                stdout=preview,
            )
            self.assertTrue(DataFile.objects.filter(pk=artifact.pk).exists())
            self.assertTrue(storage.exists(stored_name))
            self.assertIn('[预览]', preview.getvalue())

            call_command(
                'cleanup_legacy_screening_artifacts',
                project_id=project.id,
                execute=True,
                stdout=StringIO(),
            )
            self.assertFalse(DataFile.objects.filter(pk=artifact.pk).exists())
            self.assertFalse(storage.exists(stored_name))
