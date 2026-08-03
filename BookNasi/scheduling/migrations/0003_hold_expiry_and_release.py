"""Slice 5. Three nullable columns on the hold.

Additive, and again nothing touching the exclusion constraint: a hold is a
`pending_payment` appointment, which was already one of the statuses the
constraint filters on. All slice 5 adds is when it stops holding, which task
will release it, and whether it was released by expiry or by a client who
cancelled — the last of which is what `scheduling/abuse.py` throttles on.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0002_walk_in_lifecycle_and_offline_retry'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='hold_expires_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='hold_release_task_id',
            field=models.CharField(blank=True, editable=False, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='hold_released_at',
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
