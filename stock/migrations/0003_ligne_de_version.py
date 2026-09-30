# -*- coding: utf-8 -*-
"""La ligne de version existe toujours.

C'est elle que chaque action d'écriture verrouille pour se sérialiser
(`stock.api._verrou_ecriture`). Un verrou de ligne ne verrouille rien si la
ligne n'existe pas : sur une base neuve, les deux premières écritures
simultanées passeraient donc à travers, et c'est précisément le cas qu'on veut
couvrir.

La créer ici plutôt qu'à la première écriture évite d'avoir à gérer la course
sur sa création — qui serait le même problème, déplacé d'un cran.
"""

from django.db import migrations


def creer(apps, schema_editor):
    Version = apps.get_model("stock", "Version")
    # `valeur=0` signifie « base vierge » : l'interface affiche alors une
    # application vide, que les premières saisies rempliront.
    Version.objects.get_or_create(pk=1, defaults={"valeur": 0})


def retirer(apps, schema_editor):
    # Seule une ligne restée à zéro repart : si le compteur a avancé, des
    # opérations y font référence.
    Version = apps.get_model("stock", "Version")
    Version.objects.filter(pk=1, valeur=0).delete()


class Migration(migrations.Migration):

    dependencies = [("stock", "0002_armoire_initiale")]

    operations = [migrations.RunPython(creer, retirer)]
