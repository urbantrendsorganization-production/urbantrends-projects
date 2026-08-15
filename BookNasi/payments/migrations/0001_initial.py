"""Slice 6. The payment row, the raw callback log, and the move audit trail.

Reviewed by hand — CLAUDE.md §11. Two of the constraints below are load-bearing
and neither may become a check in Python:

`one_payment_per_checkout_request` is CLAUDE.md §5's "unique constraint on the
checkout request ID". Partial, because a payment has no id between the row being
written and Safaricom accepting the push, and that window exists on purpose —
see `payments/stk.py`.

`one_open_payment_per_appointment` is what stops two live STK pushes against one
booking, which is how a client pays twice. Partial on the non-terminal states,
so a resend is possible once the previous push has been superseded and a
finished payment never blocks a retry.

`PaymentMove` ships empty. Slice 7's `slotLost` remedy re-points a succeeded
payment at another slot, and the table exists now so that slice adds an endpoint
rather than a migration against live money records.
"""

import django.db.models.deletion
import django.db.models.manager
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('orgs', '0003_alter_staffinvite_options_alter_staffinvite_managers'),
        ('scheduling', '0004_appointment_was_shortened'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('state', models.CharField(choices=[('initiated', 'Initiated'), ('pushed', 'Prompt sent'), ('push_failed', 'Could not send the prompt'), ('succeeded', 'Paid'), ('failed', 'Failed'), ('cancelled_by_user', 'Cancelled on the phone'), ('unknown', 'Unresolved'), ('superseded', 'Superseded by a new prompt'), ('orphaned', 'Paid, no booking')], db_index=True, default='initiated', max_length=20)),
                ('amount', models.PositiveIntegerField()),
                ('phone', models.CharField(max_length=16)),
                ('merchant_request_id', models.CharField(blank=True, max_length=64)),
                ('checkout_request_id', models.CharField(blank=True, max_length=64, null=True)),
                ('result_code', models.IntegerField(blank=True, null=True)),
                ('result_desc', models.CharField(blank=True, max_length=255)),
                ('mpesa_receipt', models.CharField(blank=True, max_length=32)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('pushed_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('query_attempts', models.PositiveSmallIntegerField(default=0)),
                ('last_queried_at', models.DateTimeField(blank=True, null=True)),
                ('discrepancy_count', models.PositiveSmallIntegerField(default=0)),
                ('orphan_reason', models.CharField(blank=True, choices=[('slot_lost', 'Slot was taken while the payment was in flight'), ('booking_cancelled', 'Booking was cancelled'), ('already_paid', 'Deposit was already paid'), ('booking_moved_on', 'Booking had already run')], max_length=24)),
                ('support_code', models.CharField(max_length=16, unique=True)),
                ('appointment', models.ForeignKey(help_text='Reassignable. Every change writes a PaymentMove.', on_delete=django.db.models.deletion.PROTECT, related_name='payments', to='scheduling.appointment')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='orgs.organization')),
            ],
            options={
                'db_table': 'payments',
                'ordering': ['-created_at'],
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name='MpesaCallback',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('checkout_request_id', models.CharField(blank=True, db_index=True, max_length=64)),
                ('merchant_request_id', models.CharField(blank=True, max_length=64)),
                ('result_code', models.IntegerField(blank=True, null=True)),
                ('result_desc', models.CharField(blank=True, max_length=255)),
                ('payload', models.JSONField(default=dict)),
                ('outcome', models.CharField(choices=[('applied', 'Applied'), ('duplicate', 'Duplicate, ignored'), ('discrepancy', 'Conflicting duplicate, recorded not applied'), ('unmatched', 'No matching payment'), ('malformed', 'Unparseable')], max_length=16)),
                ('previous_result_code', models.IntegerField(blank=True, null=True)),
                ('payment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='callbacks', to='payments.payment')),
            ],
            options={
                'db_table': 'mpesa_callbacks',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PaymentMove',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('reason', models.CharField(max_length=32)),
                ('from_appointment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='payments_moved_out', to='scheduling.appointment')),
                ('moved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='orgs.organization')),
                ('payment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='moves', to='payments.payment')),
                ('to_appointment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='payments_moved_in', to='scheduling.appointment')),
            ],
            options={
                'db_table': 'payment_moves',
                'ordering': ['-created_at'],
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['state', 'created_at'], name='pay_state_created_idx'),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['state', 'pushed_at'], name='pay_state_pushed_idx'),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.UniqueConstraint(condition=models.Q(('checkout_request_id__isnull', False)), fields=('checkout_request_id',), name='one_payment_per_checkout_request'),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.UniqueConstraint(condition=models.Q(('state__in', ('initiated', 'pushed', 'unknown'))), fields=('appointment',), name='one_open_payment_per_appointment'),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('state', 'succeeded'), _negated=True), models.Q(('mpesa_receipt', ''), _negated=True), _connector='OR'), name='succeeded_payment_has_a_receipt'),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('state', 'orphaned'), _negated=True), models.Q(('orphan_reason', ''), _negated=True), _connector='OR'), name='orphaned_payment_has_a_reason'),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.CheckConstraint(condition=models.Q(('amount__gte', 1)), name='payment_amount_positive'),
        ),
    ]
