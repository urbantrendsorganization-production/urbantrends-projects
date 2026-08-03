import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_model_changes_are_missing_a_migration():
    """CLAUDE.md §11: migrations are reviewed by hand. That only works if they
    exist — a model edited without one shows up as a schema drift on deploy,
    long after the review."""
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
