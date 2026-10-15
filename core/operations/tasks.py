"""Periodic operations tasks that do not belong to a feature module."""

from celery import shared_task


@shared_task(name='core.operations.process_due_plan_periods')
def process_due_plan_periods_task():
    from core.services.entitlement_service import process_due_plan_periods

    return process_due_plan_periods()
