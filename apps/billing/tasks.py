from celery import shared_task

from . import services


@shared_task
def generate_monthly_invoices():
    return services.generate_invoices()


@shared_task
def mark_overdue_invoices():
    return len(services.mark_overdue())
