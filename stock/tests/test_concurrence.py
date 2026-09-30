# -*- coding: utf-8 -*-
"""Plusieurs personnes qui écrivent en même temps.

`TransactionTestCase` et pas `TestCase` : ce dernier enveloppe chaque test dans
une transaction annulée à la fin, et des fils qui partagent cette transaction ne
verraient jamais les écritures les uns des autres — le test passerait pour la
mauvaise raison.

Ce que ces tests attrapent, mesuré avant le verrou de `stock.api` : dix
emprunts simultanés de deux unités sur un stock de dix donnaient quatre
acceptations, aucun refus, et **six erreurs 500** — la contrainte d'unicité de
`stock_operation.version` violée par deux requêtes ayant lu la même version.
"""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from django.db import connection, connections
from django.test import Client, TransactionTestCase
from django.urls import reverse

from comptes.models import Compte
from stock.models import (Cabinet, Material, MaterialReservation, Operation,
                          PhoneModel, Variant, Version)

MOT_DE_PASSE = "un-mot-de-passe-solide"
PARALLELES = 10


@unittest.skipUnless(
    connection.vendor == "postgresql",
    "SQLite ne sait pas écrire à plusieurs — c'est précisément pourquoi le "
    "déploiement vise PostgreSQL. Ces tests s'exécutent donc sur Postgres : "
    "docker compose exec web python manage.py test stock.tests.test_concurrence")
class EcrituresSimultanees(TransactionTestCase):

    # Les migrations posent l'armoire A1 et la ligne de version ; sans cela,
    # `TransactionTestCase` vide les tables entre les tests et les reprend.
    serialized_rollback = True

    def setUp(self):
        Compte.objects.create_user("Admin", password=MOT_DE_PASSE,
                                   administrateur=True, doit_changer=False)
        Cabinet.objects.update_or_create(
            id="A1", defaults={"ordre": 1, "shelves": 4, "cols": 5})
        ref = PhoneModel.objects.create(id="R1", ordre=1, brand="Apple",
                                        model="iPhone 15 Pro", mpn="A3102")
        Variant.objects.create(phone=ref, idx=0, capa="256 Go", color="Noir",
                               qty=60)
        Material.objects.create(name="Gants", libelle="Gants", ordre=1,
                                cat="Consommable", qty=10, seuil=0,
                                affectation="Commun")
        Version.poser(1)

    # ------------------------------------------------------------------
    def _client(self):
        c = Client()
        self.assertTrue(c.login(identifiant="Admin", password=MOT_DE_PASSE))
        return c

    def _en_parallele(self, fabrique_requete):
        """Lance PARALLELES requêtes au même instant et retourne leurs codes.

        Une barrière plutôt qu'un simple `map` : sans elle, les fils démarrent
        en file indienne et la course ne se produit pas.

        Chaque fil ferme sa connexion en partant : Django en ouvre une par fil,
        et les laisser ouvertes empêcherait la destruction de la base de test.
        """
        barriere = threading.Barrier(PARALLELES)
        resultats = []
        verrou = threading.Lock()

        def travail(i):
            try:
                client, envoyer = fabrique_requete(i)
                barriere.wait(timeout=30)
                reponse = envoyer(client)
                with verrou:
                    resultats.append(reponse.status_code)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=PARALLELES) as pool:
            list(pool.map(travail, range(PARALLELES)))
        return resultats

    def _poster(self, client, _action, **params):
        # Deuxième paramètre préfixé : plusieurs actions prennent elles-mêmes
        # un paramètre « nom », qui entrerait en collision avec celui du helper.
        import json
        return client.post(reverse("api_action"),
                           data=json.dumps({"action": _action, "params": params}),
                           content_type="application/json")

    # ------------------------------------------------------------------
    def test_aucune_ecriture_simultanee_ne_provoque_d_erreur_serveur(self):
        """Le symptôme d'origine : 500 au lieu d'un refus ou d'un succès.

        C'est le test qui échouait avant le verrou.
        """
        clients = [self._client() for _ in range(PARALLELES)]

        def fabrique(i):
            return clients[i], lambda c: self._poster(
                c, "telephone.reception", refId="R1", variantIdx=0, qty=1)

        codes = self._en_parallele(fabrique)
        cinq_cents = [c for c in codes if c >= 500]
        self.assertEqual(cinq_cents, [],
                         "écritures simultanées : %s" % sorted(codes))
        self.assertEqual(len(codes), PARALLELES)

    def test_les_versions_restent_contigues(self):
        """Le différentiel en dépend : une version manquante fait renvoyer
        l'état complet à toutes les sessions ouvertes."""
        clients = [self._client() for _ in range(PARALLELES)]

        def fabrique(i):
            return clients[i], lambda c: self._poster(
                c, "telephone.reception", refId="R1", variantIdx=0, qty=1)

        codes = self._en_parallele(fabrique)
        reussies = sum(1 for c in codes if c == 200)

        versions = sorted(Operation.objects.values_list("version", flat=True))
        self.assertEqual(len(versions), len(set(versions)),
                         "deux opérations portent la même version")
        self.assertEqual(versions, list(range(2, 2 + reussies)),
                         "la suite des versions a un trou ou un doublon")
        self.assertEqual(Version.courante(), 1 + reussies)

    def test_le_stock_ne_part_pas_en_survente(self):
        """Dix emprunts de deux unités sur un stock de dix : cinq au maximum
        peuvent aboutir, et les autres doivent être refusés proprement."""
        clients = [self._client() for _ in range(PARALLELES)]

        def fabrique(i):
            return clients[i], lambda c: self._poster(
                c, "materiel.emprunt", nom="Gants", qty=2)

        codes = self._en_parallele(fabrique)
        acceptes = sum(1 for c in codes if c == 200)
        refuses = sum(1 for c in codes if c == 422)

        self.assertEqual(acceptes + refuses, PARALLELES,
                         "toutes les requêtes doivent trancher : %s" % sorted(codes))
        self.assertLessEqual(acceptes, 5,
                             "plus d'emprunts acceptés que le stock ne permet")

        sortis = sum(r.qty for r in MaterialReservation.objects.all() if r.ouvert)
        self.assertLessEqual(sortis, 10,
                             "%d unités sorties d'un stock de 10" % sortis)
        self.assertEqual(Material.objects.get(pk="Gants").disponible(),
                         10 - sortis)

    def test_les_identifiants_de_reference_ne_se_marchent_pas_dessus(self):
        """`prochain_id()` lit tous les identifiants puis choisit le suivant :
        deux créations simultanées pourraient viser le même."""
        clients = [self._client() for _ in range(PARALLELES)]

        def fabrique(i):
            return clients[i], lambda c, i=i: self._poster(
                c, "telephone.creer", brand="Marque %d" % i,
                model="Modèle %d" % i, qty=1)

        codes = self._en_parallele(fabrique)
        self.assertEqual([c for c in codes if c >= 500], [],
                         "codes : %s" % sorted(codes))
        identifiants = list(PhoneModel.objects.values_list("id", flat=True))
        self.assertEqual(len(identifiants), len(set(identifiants)),
                         "deux références partagent un identifiant")
        # R1 existait déjà ; les créations réussies ajoutent les suivantes.
        reussies = sum(1 for c in codes if c == 200)
        self.assertEqual(len(identifiants), 1 + reussies)
