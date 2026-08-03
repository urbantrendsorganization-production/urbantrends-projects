"""Enable btree_gist in the foundation slice, not in slice 3.

The availability engine's exclusion constraint on `appointments` needs this
extension, and creating an extension needs elevated database privileges.
Discovering that against a locked-down production Postgres while shipping the
riskiest module in the repo is a bad afternoon. It costs nothing here, and
/health/ reports whether it took.

CLAUDE.md §4.
"""

from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [BtreeGistExtension()]
