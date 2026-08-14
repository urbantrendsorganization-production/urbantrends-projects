"""Slice 8: scheduled reminders, and four more templates.

Reviewed by hand (CLAUDE.md §11).

`Reminder` is a schedule, not a message. One row per (appointment, kind),
moved by a reschedule rather than duplicated — which is why uniqueness lives
here and reminders stay outside `ONE_SHOT`, exactly as `0001_initial` said
they would.

`no_show` and `refund_sent` *are* one-shot and join that tuple, so the
constraint's condition is rebuilt. You can only miss an appointment once,
and a shop refunding twice is a bug to fix rather than to announce again.
"""

import django.db.models.deletion
import django.db.models.manager
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_lifecycle_templates'),
        ('orgs', '0003_alter_staffinvite_options_alter_staffinvite_managers'),
        ('scheduling', '0005_lifecycle_columns'),
    ]

    operations = [
        migrations.CreateModel(
            name='Reminder',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('kind', models.CharField(choices=[('t24', '24 hours before'), ('t2', '2 hours before')], max_length=8)),
                ('send_at', models.DateTimeField()),
                ('task_id', models.CharField(blank=True, max_length=64)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'reminders',
                'ordering': ['send_at'],
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.RemoveConstraint(
            model_name='message',
            name='one_shot_message_per_appointment',
        ),
        migrations.AlterField(
            model_name='message',
            name='template',
            field=models.CharField(choices=[('booking_confirmed', 'Booking confirmed'), ('hold_released', 'Hold released'), ('slot_lost', 'Paid but the slot was taken'), ('cancelled_refund', 'Cancelled, deposit refunded'), ('cancelled_credit', 'Cancelled, deposit became credit'), ('cancelled_plain', 'Cancelled, nothing had been taken'), ('rescheduled', 'Booking moved'), ('reminder_24h', 'Reminder, 24 hours before'), ('reminder_2h', 'Reminder, 2 hours before'), ('no_show', 'Missed appointment, deposit kept'), ('refund_sent', 'Refund sent by the shop')], max_length=32),
        ),
        migrations.AddConstraint(
            model_name='message',
            constraint=models.UniqueConstraint(condition=models.Q(('template__in', ['booking_confirmed', 'hold_released', 'slot_lost', 'cancelled_refund', 'cancelled_credit', 'cancelled_plain', 'no_show', 'refund_sent'])), fields=('appointment', 'template'), name='one_shot_message_per_appointment'),
        ),
        migrations.AddField(
            model_name='reminder',
            name='appointment',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reminders', to='scheduling.appointment'),
        ),
        migrations.AddField(
            model_name='reminder',
            name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='orgs.organization'),
        ),
        migrations.AddIndex(
            model_name='reminder',
            index=models.Index(fields=['sent_at', 'send_at'], name='reminder_due_idx'),
        ),
        migrations.AddConstraint(
            model_name='reminder',
            constraint=models.UniqueConstraint(fields=('appointment', 'kind'), name='one_reminder_of_each_kind'),
        ),
    ]
