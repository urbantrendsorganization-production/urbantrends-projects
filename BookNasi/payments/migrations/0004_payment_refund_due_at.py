"""Slice 7: record a refund the shop owes back.

Reviewed by hand (CLAUDE.md §11). One nullable timestamp, no constraint
changes. Stamped by `scheduling.lifecycle.cancel` on a REFUND outcome and
read by the exception queue — we are not the merchant, so the deposit sits
in the shop's paybill and all this side can do is put it in front of a
human.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_queue_resolution'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='refund_due_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
