"""Slice 7: let a shop mark an exception-queue row as dealt with.

Reviewed by hand (CLAUDE.md §11). Three nullable/blank columns on
`payments`, no constraint changes, no rewrite of existing rows.

Deliberately not a payment *state*: the state machine describes what
happened to the money, and "somebody rang the client" is not a money fact.
Prefixed `queue_` because `resolved_at` already exists and means the
payment reached a terminal state, which is a different question.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_credit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='queue_note',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='payment',
            name='queue_resolved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='queue_resolved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
    ]
