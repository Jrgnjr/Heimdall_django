from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0008_prets_externes'),
    ]

    operations = [
        migrations.AddField(
            model_name='material',
            name='licence_fin',
            field=models.DateField(blank=True, null=True, verbose_name='fin de licence'),
        ),
    ]
