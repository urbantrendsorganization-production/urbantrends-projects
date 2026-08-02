"""Record that a walk-in was booked shorter than the service, at full price.

Settled 2 August 2026. The collision option "shorten to 12:00" writes the
shortened `duration_snapshot` and leaves `price_snapshot` at the service price.
This column says the two disagree, so the drift is measurable rather than
invisible — see `Appointment.was_shortened` and `scheduling/collisions.py`.

Backfills to False, which is correct rather than merely convenient: nothing
before this migration recorded the distinction, so no existing row can be
truthfully marked either way, and False is the value that means "no claim made".
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0003_hold_expiry_and_release"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="was_shortened",
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
