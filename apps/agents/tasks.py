from celery import shared_task

from .triggers import run_overdue_check


@shared_task
def overdue_check():
    """Runs every morning. The pause keeps us inside the free model's rate limit."""
    return len(run_overdue_check(pause=3))
