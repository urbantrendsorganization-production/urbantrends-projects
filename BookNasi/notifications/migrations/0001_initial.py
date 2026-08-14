"""Slice 6. One row per message we tried to send.

Reviewed by hand — CLAUDE.md §11.

`one_shot_message_per_appointment` is the last line of defence against
double-messaging: a duplicate callback that somehow got past the payment
dedupe still cannot send a client two confirmations. It is partial because
slice 8's reminders are *not* one-shot — the same appointment gets a T-24h and
a T-2h message — and a blanket unique constraint would make that slice a
migration instead of a task.

The rendered body is deliberately not a column. It is reconstructible from the
template id and the variables, and a second durable copy of a client's name,
time and number exists only for convenience — CLAUDE.md §9.
"""

import django.db.models.deletion
import django.db.models.manager
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('orgs', '0003_alter_staffinvite_options_alter_staffinvite_managers'),
        ('scheduling', '0004_appointment_was_shortened'),
    ]

    operations = [
        migrations.CreateModel(
            name='Message',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('template', models.CharField(choices=[('booking_confirmed', 'Booking confirmed'), ('hold_released', 'Hold released'), ('slot_lost', 'Paid but the slot was taken')], max_length=32)),
                ('to', models.CharField(max_length=16)),
                ('variables', models.JSONField(default=dict)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('sent', 'Handed to the provider'), ('failed', 'Provider refused it')], db_index=True, default='queued', max_length=8)),
                ('provider', models.CharField(blank=True, max_length=24)),
                ('provider_message_id', models.CharField(blank=True, max_length=64)),
                ('error_detail', models.CharField(blank=True, max_length=255)),
                ('cost_kes', models.PositiveIntegerField(blank=True, null=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('appointment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='scheduling.appointment')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='orgs.organization')),
            ],
            options={
                'db_table': 'messages',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['status', 'created_at'], name='msg_status_created_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('template__in', ['booking_confirmed', 'hold_released', 'slot_lost'])), fields=('appointment', 'template'), name='one_shot_message_per_appointment')],
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
    ]
