"""Slice 7: the manage token, the refund-window latch and the move counter.

Reviewed by hand (CLAUDE.md §11). Purely additive — five nullable or
defaulted columns on `appointments`, no constraint changes, and nothing that
rewrites an existing row.

`manage_token` is unique but nullable: walk-ins never get one, and a
cancelled booking has its revoked. Postgres treats NULLs as distinct in a
unique index, so any number of rows may have none.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0004_appointment_was_shortened'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='entered_refund_window_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='manage_expires_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='manage_token',
            field=models.CharField(blank=True, editable=False, max_length=32, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='reschedule_count',
            field=models.PositiveSmallIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name='appointment',
            name='token_version',
            field=models.PositiveIntegerField(default=1, editable=False),
        ),
    ]
