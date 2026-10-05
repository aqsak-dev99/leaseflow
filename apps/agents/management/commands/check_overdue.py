from django.core.management.base import BaseCommand

from apps.agents.triggers import run_overdue_check


class Command(BaseCommand):
    help = "Mark overdue invoices and draft reminders for the landlord to approve."

    def handle(self, *args, **options):
        drafted = run_overdue_check(pause=3)
        for request in drafted:
            self.stdout.write(f"Drafted: {request.subject} ({request.organization.name})")
        self.stdout.write(self.style.SUCCESS(f"{len(drafted)} reminder(s) waiting for approval."))
