# Les groupes deviennent une entité à part entière : ils existent sans chef.
#
# L'ancien système portait le rôle sur le compte (`chef_de_groupe`, `chef`). On crée un
# groupe par chef existant — « Groupe de <chef> » —, dont il est chef et membre, et où
# l'on place ses effectifs ; puis les deux anciens champs disparaissent.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def vers_groupes(apps, schema_editor):
    Compte = apps.get_model("comptes", "Compte")
    Groupe = apps.get_model("comptes", "Groupe")
    for chef in Compte.objects.filter(chef_de_groupe=True):
        materiel = chef.groupe if chef.groupe in ("1", "2", "3") else ""
        g = Groupe.objects.create(nom="Groupe de %s" % chef.identifiant,
                                  materiel=materiel, chef=chef)
        Compte.objects.filter(pk=chef.pk).update(membre_de=g)
        Compte.objects.filter(chef_id=chef.pk).update(membre_de=g)


def vers_comptes(apps, schema_editor):
    Compte = apps.get_model("comptes", "Compte")
    Groupe = apps.get_model("comptes", "Groupe")
    for g in Groupe.objects.exclude(chef=None):
        Compte.objects.filter(pk=g.chef_id).update(chef_de_groupe=True)
        Compte.objects.filter(membre_de=g).exclude(pk=g.chef_id).update(chef=g.chef_id)


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0005_roles"),
    ]

    operations = [
        migrations.CreateModel(
            name="Groupe",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=80, unique=True, verbose_name="nom")),
                ("materiel", models.CharField(blank=True, choices=[("1", "Groupe 1"), ("2", "Groupe 2"), ("3", "Groupe 3")], default="", help_text="L'étiquette « Groupe n » du stock de matériel qui désigne celui de ce groupe.", max_length=1, verbose_name="matériel affecté")),
                ("cree_le", models.DateTimeField(default=django.utils.timezone.now, verbose_name="créé le")),
                ("chef", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="groupe_dirige", to=settings.AUTH_USER_MODEL, verbose_name="chef de groupe")),
            ],
            options={"verbose_name": "groupe", "verbose_name_plural": "groupes", "db_table": "groupes", "ordering": ["nom"]},
        ),
        migrations.AddField(
            model_name="compte",
            name="membre_de",
            field=models.ForeignKey(blank=True, help_text="Le groupe dont ce compte est membre.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="membres", to="comptes.groupe", verbose_name="groupe"),
        ),
        migrations.RunPython(vers_groupes, vers_comptes),
        migrations.RemoveField(model_name="compte", name="chef"),
        migrations.RemoveField(model_name="compte", name="chef_de_groupe"),
    ]
