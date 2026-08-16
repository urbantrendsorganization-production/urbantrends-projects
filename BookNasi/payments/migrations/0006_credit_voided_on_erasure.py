"""A credit voided because the client was erased.

Reviewed by hand (CLAUDE.md §11). One new `CreditState` and nothing else.

An earlier draft of this migration also relaxed `Credit.client` from `PROTECT`
to `SET_NULL`, on the reasoning that a client holding an unspent balance could
otherwise never be erased. That reasoning was wrong and the test suite caught
it: erasure is a *soft* delete, the client row is never removed, so `PROTECT`
never fires and was never in the way. Relaxing it would have given up a real
guard — an admin hard-deleting a client out from under money that references
them — in exchange for nothing.

`VOIDED_ON_ERASURE` is distinct from `CANCELLED` because `CANCELLED` means the
shop decided. The shop did not decide this and should not appear on its own
books to have.

No data migration. Nothing is voided retroactively; existing credits keep their
state.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0002_client_erasure"),
        ("payments", "0005_alter_credit_source"),
    ]

    operations = [
        migrations.AlterField(
            model_name="credit",
            name="state",
            field=models.CharField(
                choices=[
                    ("open", "Open"),
                    ("spent", "Fully redeemed"),
                    ("expired", "Expired unused"),
                    ("cancelled", "Voided by the shop"),
                    ("erased", "Voided when the client was erased"),
                ],
                default="open",
                max_length=16,
            ),
        ),
    ]
