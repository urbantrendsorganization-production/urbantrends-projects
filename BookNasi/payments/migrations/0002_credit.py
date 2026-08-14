"""Slice 7: shop credit, and the redemptions that spend it.

Reviewed by hand, as CLAUDE.md §11 requires. Two new tables and no changes
to existing ones. `Credit.remaining_kes` carries a CHECK against
`amount_kes` and `CreditRedemption` a unique on (credit, appointment), so a
retried request cannot spend the same credit twice against one booking — the
same reasoning as `one_appointment_per_client_request`.
"""

import django.db.models.deletion
import django.db.models.manager
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0001_initial'),
        ('orgs', '0003_alter_staffinvite_options_alter_staffinvite_managers'),
        ('payments', '0001_initial'),
        ('scheduling', '0005_lifecycle_columns'),
        ('shops', '0003_refund_policy'),
    ]

    operations = [
        migrations.CreateModel(
            name='Credit',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('amount_kes', models.PositiveIntegerField()),
                ('remaining_kes', models.PositiveIntegerField()),
                ('state', models.CharField(choices=[('open', 'Open'), ('spent', 'Fully redeemed'), ('expired', 'Expired unused'), ('cancelled', 'Voided by the shop')], default='open', max_length=16)),
                ('source', models.CharField(choices=[('late_cancellation', 'Cancelled inside the refund window'), ('shop_goodwill', 'Issued by the shop')], default='late_cancellation', max_length=24)),
                ('expires_at', models.DateTimeField()),
                ('reference', models.CharField(max_length=16, unique=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='credits', to='clients.client')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='orgs.organization')),
                ('shop', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='credits', to='shops.shop')),
                ('source_appointment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='credits_issued', to='scheduling.appointment')),
                ('source_payment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='credits_issued', to='payments.payment')),
            ],
            options={
                'db_table': 'credits',
                'ordering': ['expires_at', 'created_at'],
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name='CreditRedemption',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('amount_kes', models.PositiveIntegerField()),
                ('appointment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='credit_redemptions', to='scheduling.appointment')),
                ('credit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='redemptions', to='payments.credit')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='orgs.organization')),
            ],
            options={
                'db_table': 'credit_redemptions',
                'ordering': ['-created_at'],
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddIndex(
            model_name='credit',
            index=models.Index(fields=['client', 'shop', 'state'], name='credit_client_shop_idx'),
        ),
        migrations.AddIndex(
            model_name='credit',
            index=models.Index(fields=['state', 'expires_at'], name='credit_expiry_idx'),
        ),
        migrations.AddConstraint(
            model_name='credit',
            constraint=models.CheckConstraint(condition=models.Q(('remaining_kes__lte', models.F('amount_kes'))), name='credit_remaining_within_amount'),
        ),
        migrations.AddConstraint(
            model_name='credit',
            constraint=models.CheckConstraint(condition=models.Q(('amount_kes__gte', 1)), name='credit_amount_positive'),
        ),
        migrations.AddConstraint(
            model_name='credit',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('state', 'spent'), _negated=True), ('remaining_kes', 0), _connector='OR'), name='credit_spent_is_empty'),
        ),
        migrations.AddConstraint(
            model_name='creditredemption',
            constraint=models.CheckConstraint(condition=models.Q(('amount_kes__gte', 1)), name='redemption_amount_positive'),
        ),
        migrations.AddConstraint(
            model_name='creditredemption',
            constraint=models.UniqueConstraint(fields=('credit', 'appointment'), name='one_redemption_per_credit_per_appointment'),
        ),
    ]
