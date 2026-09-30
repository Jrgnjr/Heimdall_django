# -*- coding: utf-8 -*-
"""Une première armoire sur une base neuve.

Sans elle, l'écran « Plan de l'armoire » n'aurait rien à afficher et le
placement automatique n'aurait nulle part à placer : la première réception
n'aboutirait qu'à « NON PLACÉ », ce qui ressemble à une panne.

Reprise du comportement de `_amorcer()` dans l'application Qt, à l'identique :
4 étagères de 5 casiers. Sans effet si une armoire existe déjà — c'est le cas
après une reprise de `donnees.db`, qui apporte les siennes.
"""

from django.db import migrations


def creer(apps, schema_editor):
    Cabinet = apps.get_model("stock", "Cabinet")
    if not Cabinet.objects.exists():
        Cabinet.objects.create(id="A1", ordre=1, shelves=4, cols=5)


def retirer(apps, schema_editor):
    # Seule une armoire restée aux dimensions d'origine repart : si elle a été
    # redimensionnée, c'est qu'on s'en sert.
    Cabinet = apps.get_model("stock", "Cabinet")
    Cabinet.objects.filter(id="A1", shelves=4, cols=5).delete()


class Migration(migrations.Migration):

    dependencies = [("stock", "0001_initial")]

    operations = [migrations.RunPython(creer, retirer)]
