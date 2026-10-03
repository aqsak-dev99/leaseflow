import pytest


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    """Keep files created during tests out of the real media folder."""
    settings.MEDIA_ROOT = tmp_path
