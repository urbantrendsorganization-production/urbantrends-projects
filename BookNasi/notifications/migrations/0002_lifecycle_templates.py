"""Slice 7: four more templates, and the one-shot constraint widened.

Reviewed by hand (CLAUDE.md §11). The constraint condition is rebuilt from
`templates.ONE_SHOT`, which is a tuple rather than a set for the reason that
module states: set ordering is randomised per process and would make
`makemigrations --check` report a phantom change on every run.

`rescheduled` is deliberately outside it — a booking may be moved up to
`MAX_RESCHEDULES` times and each move is a different time the client has to
be told about.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
        ('orgs', '0003_alter_staffinvite_options_alter_staffinvite_managers'),
        ('scheduling', '0005_lifecycle_columns'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='message',
            name='one_shot_message_per_appointment',
        ),
        migrations.AlterField(
            model_name='message',
            name='template',
            field=models.CharField(choices=[('booking_confirmed', 'Booking confirmed'), ('hold_released', 'Hold released'), ('slot_lost', 'Paid but the slot was taken'), ('cancelled_refund', 'Cancelled, deposit refunded'), ('cancelled_credit', 'Cancelled, deposit became credit'), ('cancelled_plain', 'Cancelled, nothing had been taken'), ('rescheduled', 'Booking moved')], max_length=32),
        ),
        migrations.AddConstraint(
            model_name='message',
            constraint=models.UniqueConstraint(condition=models.Q(('template__in', ['booking_confirmed', 'hold_released', 'slot_lost', 'cancelled_refund', 'cancelled_credit', 'cancelled_plain'])), fields=('appointment', 'template'), name='one_shot_message_per_appointment'),
        ),
    ]
