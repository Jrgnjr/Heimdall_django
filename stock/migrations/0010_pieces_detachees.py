import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0009_licence_des_dongles'),
    ]

    operations = [
        migrations.CreateModel(
            name='PiecePhone',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True, verbose_name='nom')),
                ('kind', models.CharField(default='Autre', max_length=80, verbose_name='type')),
                ('mpn', models.CharField(blank=True, default='', max_length=120, verbose_name='référence fabricant')),
                ('qty', models.IntegerField(default=0, verbose_name='quantité')),
                ('notes', models.CharField(blank=True, default='', max_length=300)),
                ('cree_le', models.DateTimeField(default=django.utils.timezone.now)),
                ('modeles', models.ManyToManyField(blank=True, db_table='stock_piece_modele', related_name='pieces', to='stock.phonemodel')),
            ],
            options={
                'verbose_name': 'pièce détachée',
                'verbose_name_plural': 'pièces détachées',
                'db_table': 'stock_piece_phone',
                'ordering': ['kind', 'name'],
            },
        ),
    ]
