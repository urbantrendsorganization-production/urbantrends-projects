"""Slice 4. Additive only: two timestamps for what actually happened, and the
offline-retry guard.

No change to the exclusion constraint or to the status set it filters on —
"waiting, not started" ships as `confirmed` with a null `started_at` rather
than as a seventh status, precisely so this migration does not have to touch it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0001_initial'),
        ('orgs', '0003_alter_staffinvite_options_alter_staffinvite_managers'),
        ('scheduling', '0001_initial'),
        ('shops', '0002_scheduling_policy_and_deposit_floor'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='client_request_id',
            field=models.CharField(blank=True, editable=False, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='finished_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='appointment',
            constraint=models.UniqueConstraint(condition=models.Q(('client_request_id__isnull', False)), fields=('shop', 'client_request_id'), name='one_appointment_per_client_request'),
        ),
    ]
