# -*- coding: utf-8 -*-
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0003_reglages"),
    ]

    operations = [
        migrations.AddField(
            model_name="compte",
            name="code_recuperation",
            field=models.CharField(blank=True, default="", max_length=300,
                                   verbose_name="empreinte du code de récupération"),
        ),
        migrations.AddField(
            model_name="compte",
            name="recuperation_echecs",
            field=models.PositiveSmallIntegerField(
                default=0, verbose_name="essais de récupération ratés"),
        ),
        migrations.AddField(
            model_name="compte",
            name="recuperation_bloque_jusqu",
            field=models.DateTimeField(blank=True, null=True,
                                       verbose_name="récupération verrouillée jusqu'à"),
        ),
    ]
