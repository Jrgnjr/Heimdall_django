# -*- coding: utf-8 -*-
"""Une session par onglet : deux personnes, deux onglets, un navigateur."""

import re

from django.test import Client, TestCase, override_settings

from comptes.models import Compte

MOT_DE_PASSE = "motdepasse-de-test"
ANONYME_1 = "/s-aaaaaaaaaaaa"
ANONYME_2 = "/s-bbbbbbbbbbbb"


@override_settings(ONGLETS_ISOLES=True)
class OngletsIndependants(TestCase):
    """Le client de test garde un seul pot de cookies, comme un navigateur."""

    def setUp(self):
        for nom, admin in (("Alice", True), ("Bob", False), ("Zoé", False)):
            Compte.objects.create_user(nom, password=MOT_DE_PASSE,
                                       administrateur=admin, doit_changer=False)
        self.navigateur = Client()

    def connecter(self, onglet, identifiant):
        return self.navigateur.post(onglet + "/connexion/", {
            "username": identifiant, "password": MOT_DE_PASSE})

    def utilisateur(self, onglet):
        reponse = self.navigateur.get(onglet + "/api/state")
        return reponse.json().get("user") if reponse.status_code == 200 else None

    # -- entrée -------------------------------------------------------------

    def test_une_page_sans_onglet_en_recoit_un(self):
        reponse = self.navigateur.get("/")
        self.assertEqual(reponse.status_code, 302)
        self.assertRegex(reponse["Location"], r"^/s-[0-9a-f]{12}/$")

    def test_chaque_visite_donne_un_onglet_different(self):
        a = self.navigateur.get("/")["Location"]
        b = self.navigateur.get("/")["Location"]
        self.assertNotEqual(a, b)

    def test_le_chemin_et_la_requete_sont_conserves(self):
        reponse = self.navigateur.get("/connexion/?next=/missions/X/")
        self.assertRegex(reponse["Location"],
                         r"^/s-[0-9a-f]{12}/connexion/\?next=/missions/X/$")

    def test_la_sonde_de_sante_n_a_pas_d_onglet(self):
        self.assertEqual(self.navigateur.get("/sante/").status_code, 200)

    # -- l'adresse porte le nom du compte -----------------------------------

    def test_la_connexion_renvoie_vers_l_adresse_du_compte(self):
        reponse = self.connecter(ANONYME_1, "Alice")
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(reponse["Location"], "/u/Alice/")

    def test_un_nom_accentue_est_encode_dans_l_adresse(self):
        reponse = self.connecter(ANONYME_1, "Zoé")
        self.assertEqual(reponse["Location"], "/u/Zo%C3%A9/")
        self.assertEqual(self.navigateur.get("/u/Zo%C3%A9/api/state").json()["user"], "Zoé")

    def test_la_page_du_compte_est_servie(self):
        self.connecter(ANONYME_1, "Alice")
        self.assertEqual(self.navigateur.get("/u/Alice/").status_code, 200)

    def test_la_fiche_d_une_mission_s_ouvre_dans_l_onglet_sans_reconnexion(self):
        """Le bouton « Tableau » ouvre `/u/<compte>/missions/…` : le cookie de
        l'onglet suit, et la page est servie directement."""
        from stock.models import Mission
        Mission.objects.create(name="Chantier Nord")
        self.connecter(ANONYME_1, "Alice")
        reponse = self.navigateur.get("/u/Alice/missions/Chantier%20Nord/")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Chantier Nord")

    def test_le_lien_partage_sans_onglet_passe_par_la_connexion(self):
        """Une adresse neutre (`/missions/…`) ne porte aucun cookie : elle reçoit
        un onglet neuf, puis la connexion, puis retrouve sa page."""
        from stock.models import Mission
        Mission.objects.create(name="Chantier Nord")
        reponse = self.navigateur.get("/missions/Chantier%20Nord/")
        self.assertRegex(reponse["Location"], r"^/s-[0-9a-f]{12}/missions/Chantier%20Nord/$")
        reponse = self.navigateur.get(reponse["Location"])
        self.assertRegex(reponse["Location"],
                         r"^/s-[0-9a-f]{12}/connexion/\?next=/s-[0-9a-f]{12}/missions/")
        reponse = self.navigateur.post(
            reponse["Location"], {"username": "Alice", "password": MOT_DE_PASSE})
        self.assertEqual(reponse["Location"], "/u/Alice/missions/Chantier%20Nord/")

    def test_les_cookies_sont_attaches_a_l_adresse_du_compte(self):
        self.connecter(ANONYME_1, "Alice")
        nom = "sessionid_u-" + "Alice".encode().hex()
        self.assertEqual(self.navigateur.cookies[nom]["path"], "/u/Alice/")
        self.assertNotIn("sessionid", self.navigateur.cookies)

    def test_la_destination_demandee_est_conservee(self):
        reponse = self.navigateur.post(
            ANONYME_1 + "/connexion/?next=" + ANONYME_1 + "/missions/Chantier/",
            {"username": "Alice", "password": MOT_DE_PASSE})
        self.assertEqual(reponse["Location"], "/u/Alice/missions/Chantier/")

    def test_une_destination_exterieure_est_ecartee(self):
        reponse = self.navigateur.post(
            ANONYME_1 + "/connexion/?next=https://autre.exemple/",
            {"username": "Alice", "password": MOT_DE_PASSE})
        self.assertEqual(reponse["Location"], "/u/Alice/")

    # -- l'isolement --------------------------------------------------------

    def test_deux_onglets_deux_utilisateurs(self):
        self.connecter(ANONYME_1, "Alice")
        self.connecter(ANONYME_2, "Bob")
        self.assertEqual(self.utilisateur("/u/Alice"), "Alice")
        self.assertEqual(self.utilisateur("/u/Bob"), "Bob")

    def test_les_droits_suivent_l_onglet(self):
        self.connecter(ANONYME_1, "Alice")
        self.connecter(ANONYME_2, "Bob")
        self.assertTrue(self.navigateur.get("/u/Alice/api/state").json()["admin"])
        self.assertFalse(self.navigateur.get("/u/Bob/api/state").json()["admin"])

    def test_l_adresse_d_un_autre_compte_n_ouvre_pas_sa_session(self):
        """Taper /u/Bob/ avec la session d'Alice ne fait pas d'Alice un Bob."""
        self.connecter(ANONYME_1, "Alice")
        self.assertEqual(self.navigateur.get("/u/Bob/api/state").status_code, 401)
        reponse = self.navigateur.get("/u/Bob/")
        self.assertRegex(reponse["Location"], r"^/s-[0-9a-f]{12}/connexion/\?next=/$")

    def test_il_n_y_a_pas_de_page_de_connexion_au_nom_d_un_compte(self):
        """/u/Compte-001/connexion/?next=/u/Admin ne doit pas exister."""
        reponse = self.navigateur.get("/u/Compte-001/connexion/?next=/u/Admin")
        self.assertEqual(reponse.status_code, 302)
        self.assertRegex(reponse["Location"], r"^/s-[0-9a-f]{12}/connexion/$")

    def test_on_ne_se_connecte_pas_depuis_l_adresse_d_un_compte(self):
        reponse = self.connecter("/u/Bob", "Alice")
        self.assertRegex(reponse["Location"], r"^/s-[0-9a-f]{12}/connexion/$")
        self.assertEqual(self.utilisateur("/u/Alice"), None)
        self.assertEqual(self.utilisateur("/u/Bob"), None)

    def test_apres_la_deconnexion_on_revient_sur_une_adresse_neutre(self):
        self.connecter(ANONYME_1, "Alice")
        self.navigateur.post("/u/Alice/deconnexion/")
        reponse = self.navigateur.get("/u/Alice/connexion/")
        self.assertRegex(reponse["Location"], r"^/s-[0-9a-f]{12}/connexion/$")

    def test_une_page_demandee_sans_session_est_retenue_pour_apres(self):
        reponse = self.navigateur.get("/u/Alice/missions/Chantier/")
        self.assertRegex(reponse["Location"],
                         r"^/s-[0-9a-f]{12}/connexion/\?next=/missions/Chantier/$")
        suite = reponse["Location"]
        reponse = self.navigateur.post(
            suite, {"username": "Alice", "password": MOT_DE_PASSE})
        self.assertEqual(reponse["Location"], "/u/Alice/missions/Chantier/")

    def test_une_destination_vers_un_autre_compte_est_ramenee_a_soi(self):
        reponse = self.navigateur.post(
            ANONYME_1 + "/connexion/?next=/u/Bob/missions/X/",
            {"username": "Alice", "password": MOT_DE_PASSE})
        self.assertEqual(reponse["Location"], "/u/Alice/missions/X/")
        reponse = self.navigateur.post(
            ANONYME_2 + "/connexion/?next=/u/Admin",
            {"username": "Bob", "password": MOT_DE_PASSE})
        self.assertEqual(reponse["Location"], "/u/Bob/")

    def test_la_racine_ne_partage_pas_la_session_d_un_onglet(self):
        """Un cookie posé hors onglet ne doit pas authentifier un onglet."""
        self.connecter(ANONYME_1, "Alice")
        self.assertEqual(self.navigateur.get("/api/state").status_code, 401)

    def test_se_deconnecter_dans_un_onglet_garde_l_autre(self):
        self.connecter(ANONYME_1, "Alice")
        self.connecter(ANONYME_2, "Bob")
        reponse = self.navigateur.post("/u/Alice/deconnexion/")
        self.assertEqual(reponse["Location"], "/u/Alice/connexion/")
        self.assertEqual(self.utilisateur("/u/Alice"), None)
        self.assertEqual(self.utilisateur("/u/Bob"), "Bob")

    def test_deux_onglets_du_meme_compte_partagent_la_session(self):
        """Choix assumé : même adresse, mêmes cookies, même session."""
        self.connecter(ANONYME_1, "Alice")
        self.assertEqual(self.utilisateur("/u/Alice"), "Alice")
        self.navigateur.post("/u/Alice/deconnexion/")
        self.assertEqual(self.utilisateur("/u/Alice"), None)

    def test_changer_de_compte_dans_un_onglet_ne_touche_pas_l_autre(self):
        self.connecter(ANONYME_1, "Alice")
        self.connecter(ANONYME_2, "Bob")
        self.navigateur.post("/u/Alice/deconnexion/")
        self.connecter(ANONYME_1, "Zoé")
        self.assertEqual(self.utilisateur("/u/Zo%C3%A9"), "Zoé")
        self.assertEqual(self.utilisateur("/u/Bob"), "Bob")

    def test_un_onglet_connecte_ne_change_pas_de_compte_sans_se_deconnecter(self):
        """Il n'existe aucun passage d'un compte à l'autre : il faut fermer le
        premier, puis rouvrir avec un mot de passe."""
        self.connecter(ANONYME_1, "Alice")
        self.connecter(ANONYME_2, "Bob")
        reponse = self.navigateur.get("/u/Alice/connexion/")
        self.assertEqual(self.utilisateur("/u/Alice"), "Alice")

    def test_un_onglet_jamais_connecte_ne_voit_rien(self):
        self.connecter(ANONYME_1, "Alice")
        self.assertEqual(self.navigateur.get(ANONYME_2 + "/api/state").status_code, 401)

    # -- jeton CSRF ---------------------------------------------------------

    def _jeton(self, navigateur, adresse):
        page = navigateur.get(adresse).content.decode()
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)

    def test_la_connexion_passe_avec_les_controles_csrf(self):
        navigateur = Client(enforce_csrf_checks=True)
        jeton = self._jeton(navigateur, ANONYME_1 + "/connexion/")
        reponse = navigateur.post(ANONYME_1 + "/connexion/", {
            "username": "Alice", "password": MOT_DE_PASSE,
            "csrfmiddlewaretoken": jeton})
        self.assertEqual(reponse.status_code, 302)

    def test_une_action_passe_avec_le_jeton_de_l_onglet_du_compte(self):
        """Après la connexion, le jeton CSRF doit suivre vers l'adresse du compte."""
        navigateur = Client(enforce_csrf_checks=True)
        jeton = self._jeton(navigateur, ANONYME_1 + "/connexion/")
        navigateur.post(ANONYME_1 + "/connexion/", {
            "username": "Alice", "password": MOT_DE_PASSE,
            "csrfmiddlewaretoken": jeton})
        nom = "csrftoken_u-" + "Alice".encode().hex()
        reponse = navigateur.post(
            "/u/Alice/api/action",
            data='{"action": "mission.creer", "params": {"nom": "Chantier"}}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=navigateur.cookies[nom].value)
        self.assertEqual(reponse.status_code, 200, reponse.content)

    def test_un_jeton_d_un_onglet_ne_vaut_pas_pour_un_autre(self):
        navigateur = Client(enforce_csrf_checks=True)
        jeton = self._jeton(navigateur, ANONYME_1 + "/connexion/")
        navigateur.get(ANONYME_2 + "/connexion/")
        reponse = navigateur.post(ANONYME_2 + "/connexion/", {
            "username": "Alice", "password": MOT_DE_PASSE,
            "csrfmiddlewaretoken": jeton})
        self.assertEqual(reponse.status_code, 403)
