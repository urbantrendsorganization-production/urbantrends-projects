"""Erasure state on the client, and a constraint that survives it.

Reviewed by hand (CLAUDE.md §11). The generated version was correct; what it
could not carry is why the constraint is dropped and rebuilt rather than left
alone, and the ordering that makes that safe.

`one_client_per_phone_per_org` gains two exclusions, both of them rows with no
number to deduplicate on:

- **Scrubbed rows.** A scrub blanks the phone, so the second erasure in an
  organization would collide with the first — turning "this person asked to be
  forgotten" into a 500 whose cause is a unique index.
- **Blank phones.** A walk-in can be recorded with a name and no number at all.
  Two unnamed people at the chair on a Tuesday are two people, and the old
  total constraint would have merged their visit histories. That path raised
  before this slice for a different reason (`normalize_phone` refuses a blank),
  so it has never run in production and there is no existing data to reconcile.

The order is load-bearing: the constraint has to go before the columns arrive,
because the new one references `scrubbed_at` and cannot be created against a
table that does not have it yet.

Reversible. Going back rebuilds the total constraint, which will fail if two
scrubbed rows exist by then — correctly, because there would be no way to tell
those people apart again.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0001_initial"),
        ("orgs", "0003_alter_staffinvite_options_alter_staffinvite_managers"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="client",
            name="one_client_per_phone_per_org",
        ),
        migrations.AddField(
            model_name="client",
            name="scrubbed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="scrub_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("requested", "The client asked"),
                    ("retention", "Retention period elapsed"),
                    ("shop", "Erased by the shop"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="erasure_requested_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="client",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("scrubbed_at__isnull", True),
                    models.Q(("phone", ""), _negated=True),
                ),
                fields=("organization", "phone"),
                name="one_client_per_phone_per_org",
            ),
        ),
    ]
