import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0007_gestion_des_missions'),
    ]

    operations = [
        migrations.CreateModel(
            name='PretExterne',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('preteur', models.CharField(db_index=True, max_length=150, verbose_name='prêteur')),
                ('emprunteur', models.CharField(max_length=120, verbose_name='prêté à')),
                ('material_id', models.CharField(blank=True, default='', max_length=200, verbose_name='exemplaire')),
                ('article', models.CharField(max_length=200)),
                ('quantite', models.IntegerField(default=1, verbose_name='quantité')),
                ('mission', models.CharField(default='—', max_length=200)),
                ('commentaire', models.CharField(blank=True, default='', max_length=300)),
                ('echeance', models.DateField(blank=True, null=True, verbose_name='à rendre avant le')),
                ('cree_le', models.DateTimeField(default=django.utils.timezone.now)),
                ('rendu_le', models.DateTimeField(blank=True, null=True, verbose_name='rendu le')),
                ('rendu_par', models.CharField(blank=True, default='', max_length=150, verbose_name='rendu enregistré par')),
            ],
            options={
                'verbose_name': 'prêt à une personne sans compte',
                'verbose_name_plural': 'prêts à des personnes sans compte',
                'db_table': 'stock_pret_externe',
                'ordering': ['-cree_le', '-id'],
            },
        ),
    ]
