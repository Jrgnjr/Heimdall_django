# -*- coding: utf-8 -*-
"""Base commune aux tests : une base réaliste, et un raccourci pour agir.

Chaque test travaille sur une base neuve fournie par Django : aucun risque pour
les données réelles.

Les tests appellent `executer()` directement plutôt que de passer par HTTP. Ce
sont les règles métier qu'ils vérifient ; le contrat HTTP a son propre fichier.
La version n'est donc pas incrémentée ici — c'est `stock.api` qui s'en charge —
et les tests qui en dépendent la posent eux-mêmes.
"""

from django.test import TestCase

from comptes.models import Compte
from stock.models import (Cabinet, Material, Mission, PhoneModel, Variant,
                          Version)
from stock.services import ErreurAction, executer


class BaseStock(TestCase):
    """Une base minimale mais réaliste : une armoire, une référence, deux
    déclinaisons, trois articles de matériel."""

    UTILISATEUR = "42"

    def setUp(self):
        self.compte = Compte.objects.create_user(
            self.UTILISATEUR, password="motdepasse-de-test",
            administrateur=True, doit_changer=False)
        # `update_or_create` : la migration 0002 fournit déjà A1 sur une base
        # neuve, et la recréer violerait sa clé.
        Cabinet.objects.update_or_create(
            id="A1", defaults={"ordre": 1, "shelves": 4, "cols": 5})

        self.ref = PhoneModel.objects.create(
            id="R1", ordre=1, brand="Apple", model="iPhone 15 Pro", mpn="A3102")
        Variant.objects.create(phone=self.ref, idx=0, capa="256 Go",
                               color="Titane naturel", qty=6)
        Variant.objects.create(phone=self.ref, idx=1, capa="512 Go",
                               color="Titane bleu", qty=2)

        for rang, (nom, cat, quantite) in enumerate([
                ("Chargeur USB-C 20 W", "Autre", 12),
                ("Câble Lightning 1 m", "Autre", 12),
                ("Kit outils démontage", "Outil", 3)], start=1):
            Material.objects.create(name=nom, libelle=nom, ordre=rang, cat=cat,
                                    qty=quantite, seuil=0, affectation="Commun")

        Version.poser(1)

    # ------------------------------------------------------------------
    def agir(self, _action, _administrateur=True, **params):
        """Exécute une action au nom du compte de test.

        Le premier paramètre est préfixé : plusieurs actions prennent
        elles-mêmes un paramètre « nom », qui entrerait en collision.
        """
        return executer(_action, self.UTILISATEUR, params, _administrateur)

    def refus(self, _action, **params):
        """Exécute une action en attendant un refus, et retourne son message."""
        with self.assertRaises(ErreurAction) as capture:
            self.agir(_action, **params)
        return str(capture.exception)

    # ------------------------------------------------------------------
    def variante(self, i=0):
        return list(self.ref.variants.all())[i]

    def article(self, nom):
        return Material.objects.get(pk=nom)

    def dispo(self, nom):
        return self.article(nom).disponible()

    def journal(self, genre):
        from stock.models import MaterialLog
        return list(MaterialLog.objects.filter(kind=genre))

    def mission(self, nom="Chantier Nord"):
        return Mission.objects.create(name=nom, ordre=1, is_meta=True,
                                      owner=self.UTILISATEUR, archived=False)
