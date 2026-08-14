"""The refund policy, decided 14 August 2026. CLAUDE.md §12.

Reviewed by hand, as §11 requires. Purely additive: one new column with a
default, one help-text correction, one CHECK constraint. Existing shops get
60-day credit without being asked, which is the policy applying to them rather
than a migration deciding something on their behalf — the terms are a product
decision recorded in §12, not a per-shop setting.
"""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orgs', '0003_alter_staffinvite_options_alter_staffinvite_managers'),
        ('shops', '0002_scheduling_policy_and_deposit_floor'),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='deposit_credit_days',
            field=models.PositiveSmallIntegerField(default=60, help_text='Cancel later than the refund window and the deposit becomes credit at this shop for this many days, against any service. CLAUDE.md §12.', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(365)]),
        ),
        migrations.AlterField(
            model_name='shop',
            name='refund_window_hours',
            field=models.PositiveSmallIntegerField(default=24, help_text='Cancel earlier than this and the deposit is refunded. CLAUDE.md §12.', validators=[django.core.validators.MaxValueValidator(168)]),
        ),
        migrations.AddConstraint(
            model_name='shop',
            constraint=models.CheckConstraint(condition=models.Q(('deposit_credit_days__gte', 1), ('deposit_credit_days__lte', 365)), name='shop_deposit_credit_days_sane'),
        ),
    ]
