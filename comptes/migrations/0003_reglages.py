# -*- coding: utf-8 -*-
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0002_dotation"),
    ]

    operations = [
        migrations.AddField(
            model_name="compte",
            name="reglages",
            field=models.JSONField(blank=True, default=dict, verbose_name="réglages"),
        ),
    ]
