# -*- coding: utf-8 -*-
"""Ce dont le déploiement conteneurisé dépend.

Docker et les répartiteurs de charge interrogent `/sante/` ; l'entrypoint du
conteneur appelle `amorcer_admin` à chaque démarrage. Si l'un des deux change de
comportement, le conteneur se déclare sain à tort ou n'a plus de porte d'entrée
— deux pannes qui ne se voient qu'en production. D'où ce fichier.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from comptes.models import ActiviteCompte, Compte


class PointDeSante(TestCase):

    def test_repond_sans_session(self):
        """C'est Docker qui interroge, et il n'a pas de compte."""
        reponse = self.client.get(reverse("sante"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json(), {"ok": True})

    def test_refuse_le_post(self):
        self.assertEqual(self.client.post(reverse("sante")).status_code, 405)

    def test_signale_une_base_injoignable(self):
        """Un processus qui répond alors que la base est tombée ne doit pas être
        déclaré sain : il continuerait de recevoir du trafic."""
        from unittest.mock import patch
        with patch("stock.views.connection.cursor",
                   side_effect=RuntimeError("connexion refusée")):
            reponse = self.client.get(reverse("sante"))
        self.assertEqual(reponse.status_code, 503)
        self.assertFalse(reponse.json()["ok"])
        self.assertIn("connexion refusée", reponse.json()["base"])


class AmorcageAdmin(TestCase):

    def amorcer(self, **options):
        sortie = StringIO()
        call_command("amorcer_admin", stdout=sortie, **options)
        return sortie.getvalue()

    def test_cree_le_premier_administrateur(self):
        sortie = self.amorcer()
        compte = Compte.objects.get(identifiant="Admin")
        self.assertTrue(compte.administrateur)
        self.assertTrue(compte.actif)
        self.assertIn("Mot de passe provisoire", sortie)

    def test_le_mot_de_passe_tire_au_hasard_doit_etre_change(self):
        """Il a transité par un journal : il ne peut pas rester en place."""
        self.amorcer()
        self.assertTrue(Compte.objects.get(identifiant="Admin").doit_changer)

    def test_le_mot_de_passe_tire_au_hasard_fonctionne(self):
        sortie = self.amorcer()
        ligne = [l for l in sortie.splitlines() if "Mot de passe provisoire" in l][0]
        mot_de_passe = ligne.split(":", 1)[1].strip()
        self.assertTrue(
            Compte.objects.get(identifiant="Admin").check_password(mot_de_passe))

    def test_un_mot_de_passe_choisi_n_est_pas_impose_a_changer(self):
        """Il appartient déjà à quelqu'un : pas la peine de le remplacer."""
        sortie = self.amorcer(mot_de_passe="un-mot-de-passe-choisi")
        compte = Compte.objects.get(identifiant="Admin")
        self.assertFalse(compte.doit_changer)
        self.assertTrue(compte.check_password("un-mot-de-passe-choisi"))
        self.assertNotIn("Mot de passe provisoire", sortie,
                         "un mot de passe fourni n'a pas à être réaffiché")

    def test_est_idempotente(self):
        """L'entrypoint l'appelle à chaque démarrage du conteneur."""
        self.amorcer()
        empreinte = Compte.objects.get(identifiant="Admin").password
        sortie = self.amorcer()
        self.assertIn("existe déjà", sortie)
        self.assertEqual(Compte.objects.count(), 1)
        self.assertEqual(Compte.objects.get(identifiant="Admin").password,
                         empreinte, "le mot de passe ne doit pas être réécrit")

    def test_ne_fait_rien_si_un_autre_administrateur_existe(self):
        Compte.objects.create_user("Chef", "un-mot-de-passe", administrateur=True)
        self.amorcer()
        self.assertFalse(Compte.objects.filter(identifiant="Admin").exists())

    def test_refuse_d_elever_un_compte_existant_non_administrateur(self):
        """Promouvoir en silence un compte ordinaire serait une surprise."""
        Compte.objects.create_user("Admin", "un-mot-de-passe", administrateur=False)
        sortie = self.amorcer()
        self.assertIn("n'est pas administrateur", sortie)
        self.assertFalse(Compte.objects.get(identifiant="Admin").administrateur)

    def test_n_ouvre_pas_l_administration_django_par_defaut(self):
        """`/admin/` écrit sans passer par les règles métier : l'ouvrir est une
        décision à prendre, pas un effet de bord de l'amorçage."""
        self.amorcer()
        self.assertFalse(Compte.objects.get(identifiant="Admin").is_staff)
        Compte.objects.all().delete()
        self.amorcer(staff=True)
        self.assertTrue(Compte.objects.get(identifiant="Admin").is_staff)

    def test_laisse_une_trace(self):
        self.amorcer()
        self.assertTrue(ActiviteCompte.objects
                        .filter(action="compte administrateur créé").exists())

    def test_un_identifiant_choisi_est_respecte(self):
        self.amorcer(identifiant="Patron")
        self.assertTrue(Compte.objects.get(identifiant="Patron").administrateur)


class IconeDeLOnglet(TestCase):
    """Le navigateur doit trouver l'icône, avec ou sans balise."""

    def test_favicon_redirige_vers_le_fichier_statique(self):
        reponse = self.client.get("/favicon.ico")
        self.assertEqual(reponse.status_code, 301)
        self.assertIn("heimdall", reponse["Location"])

    def test_favicon_n_est_pas_pris_pour_une_page_d_onglet(self):
        from django.test import override_settings
        with override_settings(ONGLETS_ISOLES=True):
            reponse = self.client.get("/favicon.ico")
        self.assertNotRegex(reponse["Location"], r"/s-[0-9a-f]{12}/")

    def test_la_page_principale_declare_son_icone(self):
        from comptes.models import Compte
        Compte.objects.create_user("Alice", password="motdepasse-de-test",
                                   doit_changer=False)
        self.client.login(identifiant="Alice", password="motdepasse-de-test")
        page = self.client.get("/").content.decode()
        self.assertIn('rel="icon"', page)
        self.assertIn("heimdall.ico", page)
