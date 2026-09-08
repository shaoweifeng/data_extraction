"""Configuration use cases for criteria and extraction-field screening steps."""

from core.models import ActivityLog, StageStep


class ScreeningConfigurationService:
    @staticmethod
    def save_start_criteria(step, criteria):
        metadata = dict(step.metadata or {})
        metadata['criteria'] = list(criteria)
        step.metadata = metadata
        step.save(update_fields=['metadata'])

    @staticmethod
    def update_step_metadata(step, metadata, user):
        project = step.stage.project
        current = step.metadata or {}

        if step.step_key == 'criteria' and 'criteria' in metadata:
            old_values = set(current.get('criteria', []))
            new_values = set(metadata['criteria'])
            for value in new_values - old_values:
                ActivityLog.objects.create(
                    project=project, operation_type='criteria_add',
                    operation_detail={'criteria': value}, created_by=user,
                )
            for value in old_values - new_values:
                ActivityLog.objects.create(
                    project=project, operation_type='criteria_delete',
                    operation_detail={'criteria': value}, created_by=user,
                )

        if step.step_key == 'field_extraction' and 'fields' in metadata:
            old_values = {
                (field['name'], field['definition']) for field in current.get('fields', [])
            }
            new_values = {
                (field['name'], field['definition']) for field in metadata['fields']
            }
            for name, definition in new_values - old_values:
                ActivityLog.objects.create(
                    project=project, operation_type='field_extraction_add',
                    operation_detail={'field_name': name, 'field_definition': definition},
                    created_by=user,
                )
            for name, definition in old_values - new_values:
                ActivityLog.objects.create(
                    project=project, operation_type='field_extraction_delete',
                    operation_detail={'field_name': name, 'field_definition': definition},
                    created_by=user,
                )

        updated = dict(current)
        updated.update(metadata)
        step.metadata = updated
        step.save(update_fields=['metadata'])
        return step

    @staticmethod
    def extraction_fields(project):
        step = StageStep.objects.filter(
            stage__project=project,
            stage__stage_key='SCREEN_1',
            step_key='field_extraction',
        ).first()
        return (step.metadata or {}).get('fields', []) if step else []
