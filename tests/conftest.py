import pytest
from django.core.management import call_command


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Create the demo data once for the whole test session.

    Each test runs inside a transaction that is rolled back afterwards, so tests
    can change this data freely without affecting each other.
    """
    with django_db_blocker.unblock():
        call_command("seed_demo")


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    """Give every test its own empty folder for uploaded files."""
    settings.MEDIA_ROOT = tmp_path
