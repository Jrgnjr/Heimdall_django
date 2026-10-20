# -*- coding: utf-8 -*-
"""Les réglages suivent le compte, pas le poste."""

import json

from django.test import Client, TestCase
from django.urls import reverse

from comptes.models import Compte

MOT_DE_PASSE = "motdepasse-de-test"


class ReglagesDuCompte(TestCase):

    def setUp(self):
        for nom in ("Alice", "Bob"):
            Compte.objects.create_user(nom, password=MOT_DE_PASSE,
                                       doit_changer=False)

    def ouvrir(self, nom):
        navigateur = Client()
        self.assertTrue(navigateur.login(identifiant=nom, password=MOT_DE_PASSE))
        return navigateur

    def poser(self, navigateur, **reglages):
        return navigateur.post(reverse("api_reglages"),
                               data=json.dumps({"reglages": reglages}),
                               content_type="application/json")

    def lus(self, navigateur):
        return navigateur.get(reverse("api_state")).json()["reglages"]

    def test_un_compte_neuf_n_a_aucun_reglage(self):
        self.assertEqual(self.lus(self.ouvrir("Alice")), {})

    def test_les_reglages_sont_retrouves_a_la_connexion(self):
        self.assertEqual(self.poser(self.ouvrir("Alice"), stockPhonePageSize=50,
                                    showArchived=True).status_code, 200)
        # Une autre session, plus tard : mêmes réglages.
        self.assertEqual(self.lus(self.ouvrir("Alice")),
                         {"stockPhonePageSize": 50, "showArchived": True})

    def test_chaque_compte_a_les_siens(self):
        alice, bob = self.ouvrir("Alice"), self.ouvrir("Bob")
        self.poser(alice, stockMaterialPageSize="all")
        self.poser(bob, stockMaterialPageSize=20)
        self.assertEqual(self.lus(alice), {"stockMaterialPageSize": "all"})
        self.assertEqual(self.lus(bob), {"stockMaterialPageSize": 20})

    def test_un_nouvel_envoi_fusionne_avec_l_existant(self):
        alice = self.ouvrir("Alice")
        self.poser(alice, adminConsoSize=50)
        self.poser(alice, brand="Apple")
        self.assertEqual(self.lus(alice), {"adminConsoSize": 50, "brand": "Apple"})

    def test_un_reglage_inconnu_est_refuse(self):
        reponse = self.poser(self.ouvrir("Alice"), pirate="x")
        self.assertEqual(reponse.status_code, 422)

    def test_une_valeur_illisible_est_refusee(self):
        alice = self.ouvrir("Alice")
        for invalide in ({"stockPhonePageSize": 7}, {"adminPhoneSize": True},
                         {"showArchived": "oui"}, {"brand": "x" * 200},
                         {"stockMaterialPageSize": {"a": 1}}):
            self.assertEqual(self.poser(alice, **invalide).status_code, 422, invalide)
        self.assertEqual(self.lus(alice), {})

    def test_un_refus_n_enregistre_rien_du_tout(self):
        alice = self.ouvrir("Alice")
        self.poser(alice, brand="Apple", pirate="x")
        self.assertEqual(self.lus(alice), {})

    def test_sans_session_c_est_401(self):
        reponse = Client().post(reverse("api_reglages"), data="{}",
                                content_type="application/json")
        self.assertEqual(reponse.status_code, 401)


class ThemeDuCompte(TestCase):
    """Le thème est un réglage du compte, appliqué dès le chargement de la page."""

    def setUp(self):
        Compte.objects.create_user("Alice", password=MOT_DE_PASSE, doit_changer=False)
        self.navigateur = Client()
        self.navigateur.login(identifiant="Alice", password=MOT_DE_PASSE)

    def choisir(self, theme):
        return self.navigateur.post(
            reverse("api_reglages"),
            data=json.dumps({"reglages": {"theme": theme}}),
            content_type="application/json")

    def test_les_trois_themes_sont_acceptes(self):
        for theme in ("sombre", "clair", "auto"):
            self.assertEqual(self.choisir(theme).status_code, 200, theme)

    def test_un_theme_inconnu_est_refuse(self):
        self.assertEqual(self.choisir("fluo").status_code, 422)

    def test_par_defaut_la_page_est_sombre(self):
        self.assertContains(self.navigateur.get("/"), 'data-theme="dark"')

    def test_le_theme_clair_est_pose_dans_la_page(self):
        self.choisir("clair")
        self.assertContains(self.navigateur.get("/"), 'data-theme="light"')

    def test_le_theme_automatique_est_resolu_par_la_page(self):
        self.choisir("auto")
        self.assertContains(self.navigateur.get("/"), 'data-theme="auto"')

    def test_la_page_de_mission_suit_le_theme_du_compte(self):
        from stock.models import Mission
        Mission.objects.create(name="Chantier")
        self.choisir("clair")
        self.assertContains(self.navigateur.get("/missions/Chantier/"),
                            'data-theme="light"')

    def test_chaque_compte_a_son_theme(self):
        Compte.objects.create_user("Bob", password=MOT_DE_PASSE, doit_changer=False)
        bob = Client()
        bob.login(identifiant="Bob", password=MOT_DE_PASSE)
        self.choisir("clair")
        self.assertContains(bob.get("/"), 'data-theme="dark"')


class DispositionDuProfil(TestCase):
    """Chaque compte compose son profil avec les cartes qu'il veut."""

    def setUp(self):
        Compte.objects.create_user("Alice", password=MOT_DE_PASSE, doit_changer=False)
        Compte.objects.create_user("Bob", password=MOT_DE_PASSE, doit_changer=False)
        self.alice, self.bob = Client(), Client()
        self.alice.login(identifiant="Alice", password=MOT_DE_PASSE)
        self.bob.login(identifiant="Bob", password=MOT_DE_PASSE)

    def poser(self, navigateur, disposition):
        return navigateur.post(
            reverse("api_reglages"),
            data=json.dumps({"reglages": {"profilWidgets": disposition}}),
            content_type="application/json")

    def test_une_disposition_valide_est_enregistree_et_relue(self):
        disposition = [{"id": "sac", "taille": "l"}, {"id": "equipes", "taille": "s"}]
        self.assertEqual(self.poser(self.alice, disposition).status_code, 200)
        lu = self.alice.get(reverse("api_state")).json()["reglages"]
        self.assertEqual(lu["profilWidgets"], disposition)

    def test_chaque_compte_a_la_sienne(self):
        self.poser(self.alice, [{"id": "sac", "taille": "s"}])
        self.poser(self.bob, [{"id": "retard", "taille": "l"}])
        self.assertEqual(
            self.alice.get(reverse("api_state")).json()["reglages"]["profilWidgets"],
            [{"id": "sac", "taille": "s"}])
        self.assertEqual(
            self.bob.get(reverse("api_state")).json()["reglages"]["profilWidgets"],
            [{"id": "retard", "taille": "l"}])

    def test_une_disposition_vide_est_permise(self):
        """Masquer toutes les cartes est un choix."""
        self.assertEqual(self.poser(self.alice, []).status_code, 200)

    def test_les_dispositions_invalides_sont_refusees(self):
        for invalide in (
                [{"id": "inconnu", "taille": "s"}],
                [{"id": "sac", "taille": "xl"}],
                [{"id": "sac", "taille": "s"}, {"id": "sac", "taille": "l"}],
                [{"id": "sac"}],
                [{"id": "sac", "taille": "s", "extra": 1}],
                ["sac"],
                "sac",
                {"id": "sac", "taille": "s"},
                [{"id": "sac", "taille": "s"}] * 20):
            self.assertEqual(self.poser(self.alice, invalide).status_code, 422, invalide)
