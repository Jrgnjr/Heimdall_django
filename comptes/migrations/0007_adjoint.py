import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('comptes', '0006_groupes'),
    ]

    operations = [
        migrations.AddField(
            model_name='groupe',
            name='adjoint',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='groupe_adjoint', to=settings.AUTH_USER_MODEL, verbose_name='adjoint'),
        ),
    ]
