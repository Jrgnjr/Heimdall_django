# -*- coding: utf-8 -*-
"""Le contrat HTTP avec l'interface.

C'est le fichier qui protège ce que `index.html` attend : les codes de retour
qu'elle interprète elle-même, la forme des réponses, et le différentiel. Un champ
renommé côté serveur casse un écran en silence ; ces tests le font parler.
"""

import json

from django.test import Client, TestCase
from django.urls import reverse

from comptes.models import Compte
from stock.models import (Cabinet, Material, Operation, PhoneModel, Variant,
                          Version)


class ContratAPI(TestCase):

    MOT_DE_PASSE = "un-mot-de-passe-solide"

    def setUp(self):
        self.compte = Compte.objects.create_user(
            "Admin", password=self.MOT_DE_PASSE, administrateur=True,
            doit_changer=False)
        # `update_or_create` : la migration 0002 fournit déjà A1 sur une base
        # neuve, et la recréer violerait sa clé.
        Cabinet.objects.update_or_create(
            id="A1", defaults={"ordre": 1, "shelves": 4, "cols": 5})
        ref = PhoneModel.objects.create(id="R1", ordre=1, brand="Apple",
                                        model="iPhone 15 Pro", mpn="A3102")
        Variant.objects.create(phone=ref, idx=0, capa="256 Go", color="Noir", qty=6)
        Material.objects.create(name="Chargeur USB-C 20 W",
                                libelle="Chargeur USB-C 20 W", ordre=1,
                                cat="Autre", qty=12, seuil=0, affectation="Commun")
        Version.poser(1)
        self.client = Client()

    def connecter(self):
        self.assertTrue(self.client.login(identifiant="Admin",
                                         password=self.MOT_DE_PASSE))

    def poster(self, _action, **params):
        # Premier paramètre préfixé : plusieurs actions prennent elles-mêmes un
        # paramètre « nom », qui entrerait en collision avec celui du helper.
        return self.client.post(
            reverse("api_action"),
            data=json.dumps({"action": _action, "params": params}),
            content_type="application/json")

    # -- garde ---------------------------------------------------------

    def test_sans_session_l_api_repond_401(self):
        """401 : l'interface se redirige elle-même vers la connexion."""
        self.assertEqual(self.client.get(reverse("api_state")).status_code, 401)
        self.assertEqual(self.poster("telephone.sortie").status_code, 401)

    def test_un_mot_de_passe_a_changer_repond_403(self):
        """403 : l'interface se redirige vers le renouvellement. Confondre les
        deux codes enverrait l'utilisateur sur le mauvais écran."""
        self.compte.doit_changer = True
        self.compte.save(update_fields=["doit_changer"])
        self.connecter()
        self.assertEqual(self.client.get(reverse("api_state")).status_code, 403)
        self.assertEqual(self.poster("telephone.sortie").status_code, 403)

    def test_la_page_redirige_vers_le_renouvellement(self):
        self.compte.doit_changer = True
        self.compte.save(update_fields=["doit_changer"])
        self.connecter()
        reponse = self.client.get(reverse("accueil"))
        self.assertRedirects(reponse, reverse("mot_de_passe"))

    def test_la_page_exige_une_session(self):
        reponse = self.client.get(reverse("accueil"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("connexion"), reponse["Location"])

    def test_le_jeton_csrf_est_depose_par_le_premier_appel(self):
        self.connecter()
        self.client.get(reverse("api_state"))
        self.assertIn("csrftoken", self.client.cookies)

    # -- lecture -------------------------------------------------------

    def test_etat_complet(self):
        self.connecter()
        d = self.client.get(reverse("api_state")).json()
        self.assertEqual(d["version"], 1)
        self.assertEqual(d["user"], "Admin")
        self.assertTrue(d["admin"])
        attendues = {"refs", "cabinets", "assignments", "movements", "materiel",
                     "matRes", "matLog", "missions", "missionStatus",
                     "templates", "packs", "equipes"}
        self.assertEqual(set(d["state"]), attendues)

    def test_rien_n_a_change(self):
        """L'égalité stricte est voulue : elle fait échouer ce test dès qu'un
        champ apparaît dans l'enveloppe, et c'est ainsi qu'on s'aperçoit d'un
        ajout au contrat plutôt que de le découvrir à l'écran.

        `dotations` y figure depuis le portage du sac de dotation : l'interface
        le relit à chaque interrogation, comme `comptes`.
        """
        self.connecter()
        d = self.client.get(reverse("api_state"), {"since": 1}).json()
        self.assertEqual(d, {"changed": False, "version": 1, "user": "Admin",
                             "admin": True, "comptes": ["Admin"],
                             "dotations": {}})

    def test_un_retard_trop_grand_renvoie_l_etat_complet(self):
        """Sans les opérations intermédiaires, un différentiel mentirait."""
        self.connecter()
        Version.poser(50)
        d = self.client.get(reverse("api_state"), {"since": 1}).json()
        self.assertTrue(d["changed"])
        self.assertIn("state", d)
        self.assertNotIn("delta", d)

    def test_la_liste_des_comptes_reste_aux_administrateurs(self):
        Compte.objects.create_user("Simple", password=self.MOT_DE_PASSE,
                                   administrateur=False, doit_changer=False)
        self.client.login(identifiant="Simple", password=self.MOT_DE_PASSE)
        d = self.client.get(reverse("api_state")).json()
        self.assertEqual(d["comptes"], [])
        self.assertFalse(d["admin"])

    # -- écriture ------------------------------------------------------

    def test_une_action_avance_la_version_et_renvoie_le_delta(self):
        self.connecter()
        d = self.poster("telephone.sortie", refId="R1", variantIdx=0, qty=2).json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["version"], 2)
        self.assertIn("Sortie de 2", d["resume"])
        self.assertIn("refs", d["delta"])
        self.assertEqual(Variant.objects.get().qty, 4)

    def test_un_refus_metier_est_un_422_et_n_ecrit_rien(self):
        self.connecter()
        reponse = self.poster("telephone.sortie", refId="R1", variantIdx=0, qty=99)
        self.assertEqual(reponse.status_code, 422)
        self.assertIn("insuffisant", reponse.json()["error"])
        self.assertEqual(Variant.objects.get().qty, 6)
        self.assertEqual(Version.courante(), 1, "la version ne doit pas avancer")
        self.assertEqual(Operation.objects.count(), 0)

    def test_une_action_inconnue_est_un_422(self):
        self.connecter()
        reponse = self.poster("telephone.teleporter")
        self.assertEqual(reponse.status_code, 422)
        self.assertIn("Action inconnue", reponse.json()["error"])

    def test_un_corps_illisible_est_un_400(self):
        self.connecter()
        reponse = self.client.post(reverse("api_action"), data="{pas du json",
                                   content_type="application/json")
        self.assertEqual(reponse.status_code, 400)

    def test_l_api_refuse_le_get_en_ecriture(self):
        self.connecter()
        self.assertEqual(self.client.get(reverse("api_action")).status_code, 405)

    def test_une_action_reservee_est_refusee_a_un_non_administrateur(self):
        Compte.objects.create_user("Simple", password=self.MOT_DE_PASSE,
                                   administrateur=False, doit_changer=False)
        self.client.login(identifiant="Simple", password=self.MOT_DE_PASSE)
        reponse = self.poster("telephone.reception", refId="R1", variantIdx=0, qty=1)
        self.assertEqual(reponse.status_code, 422)
        self.assertIn("réservée aux administrateurs", reponse.json()["error"])

    def test_l_operation_retient_qui_a_agi(self):
        self.connecter()
        self.poster("telephone.sortie", refId="R1", variantIdx=0, qty=1)
        op = Operation.objects.get()
        self.assertEqual((op.version, op.auteur, op.type),
                         (2, "Admin", "telephone.sortie"))

    def test_agir_au_nom_d_un_autre_est_reserve_aux_administrateurs(self):
        Compte.objects.create_user("Simple", password=self.MOT_DE_PASSE,
                                   administrateur=False, doit_changer=False)
        self.client.login(identifiant="Simple", password=self.MOT_DE_PASSE)
        reponse = self.poster("materiel.emprunt", nom="Chargeur USB-C 20 W",
                              qty=1, auteur="Admin")
        self.assertEqual(reponse.status_code, 422)
        self.assertIn("au nom d'un autre", reponse.json()["error"])

    def test_un_administrateur_peut_agir_au_nom_d_un_autre(self):
        Compte.objects.create_user("Simple", password=self.MOT_DE_PASSE,
                                   administrateur=False, doit_changer=False)
        self.connecter()
        d = self.poster("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=1,
                        auteur="Simple").json()
        self.assertTrue(d["ok"])
        from stock.models import MaterialReservation
        self.assertEqual(MaterialReservation.objects.get().taken_by, "Simple")
        # L'historique porte le compte réellement connecté, jamais l'emprunté.
        self.assertEqual(Operation.objects.get().auteur, "Admin")

    def test_un_auteur_invente_est_refuse(self):
        self.connecter()
        reponse = self.poster("materiel.emprunt", nom="Chargeur USB-C 20 W",
                              qty=1, auteur="Personne")
        self.assertEqual(reponse.status_code, 422)
        self.assertIn("n'existe pas", reponse.json()["error"])

    def test_le_contenu_du_classeur_ne_va_pas_dans_l_historique(self):
        """Quelques centaines de kilo-octets en base64, illisibles."""
        self.connecter()
        import base64
        import io
        from openpyxl import Workbook
        classeur = Workbook()
        f = classeur.active
        f.append(("Fabricant", "Modèle", "Nom commercial", "Quantité"))
        f.append(("Nokia", "TA-1471", "Nokia XR21", 5))
        tampon = io.BytesIO()
        classeur.save(tampon)
        encode = base64.b64encode(tampon.getvalue()).decode()

        d = self.poster("telephone.importer_xlsx", xlsxBase64=encode).json()
        self.assertTrue(d["ok"])
        self.assertNotIn(encode[:64], Operation.objects.get().parametres)
        self.assertIn("[fichier importé]", Operation.objects.get().parametres)


class Connexion(TestCase):

    MOT_DE_PASSE = "un-mot-de-passe-solide"

    def setUp(self):
        self.compte = Compte.objects.create_user(
            "Admin", password=self.MOT_DE_PASSE, administrateur=True,
            doit_changer=True)
        self.client = Client()

    def test_la_connexion_horodate_la_visite(self):
        self.assertIsNone(self.compte.derniere_visite)
        self.client.post(reverse("connexion"),
                         {"username": "Admin", "password": self.MOT_DE_PASSE})
        self.compte.refresh_from_db()
        self.assertIsNotNone(self.compte.derniere_visite)

    def test_un_mot_de_passe_impose_mene_au_renouvellement(self):
        reponse = self.client.post(
            reverse("connexion"),
            {"username": "Admin", "password": self.MOT_DE_PASSE})
        self.assertRedirects(reponse, reverse("mot_de_passe"))

    def test_le_message_d_echec_ne_dit_pas_si_le_compte_existe(self):
        r1 = self.client.post(reverse("connexion"),
                              {"username": "Admin", "password": "faux"})
        r2 = self.client.post(reverse("connexion"),
                              {"username": "Inconnu", "password": "faux"})
        self.assertContains(r1, "Identifiant ou mot de passe incorrect")
        self.assertContains(r2, "Identifiant ou mot de passe incorrect")

    def test_un_compte_inactif_ne_se_connecte_pas(self):
        self.compte.actif = False
        self.compte.save(update_fields=["actif"])
        self.assertFalse(self.client.login(identifiant="Admin",
                                          password=self.MOT_DE_PASSE))

    def test_changer_de_mot_de_passe_leve_le_drapeau_et_garde_la_session(self):
        self.client.login(identifiant="Admin", password=self.MOT_DE_PASSE)
        reponse = self.client.post(reverse("mot_de_passe"), {
            "new_password1": "un-autre-mot-de-passe",
            "new_password2": "un-autre-mot-de-passe"})
        self.assertRedirects(reponse, reverse("accueil"))
        self.compte.refresh_from_db()
        self.assertFalse(self.compte.doit_changer)
        # Sans `update_session_auth_hash`, le changement déconnecterait.
        self.assertEqual(self.client.get(reverse("api_state")).status_code, 200)

    def test_la_deconnexion_exige_un_post(self):
        self.client.login(identifiant="Admin", password=self.MOT_DE_PASSE)
        self.assertEqual(self.client.get(reverse("deconnexion")).status_code, 405)
        self.assertEqual(self.client.post(reverse("deconnexion")).status_code, 302)
        self.assertEqual(self.client.get(reverse("api_state")).status_code, 401)


class MotsDePasseRepris(TestCase):
    """Une empreinte écrite par l'application Qt doit rester valide.

    C'est ce qui évite de faire changer de mot de passe à toute l'équipe au
    passage à Django. Le format est reproduit ici plutôt qu'importé de l'ancien
    projet : ce test doit tenir sans lui.
    """

    def test_une_empreinte_au_format_qt_est_acceptee(self):
        import hashlib
        sel = "0123456789abcdef0123456789abcdef"
        brut = hashlib.scrypt(b"MonMotDePasse2026", salt=sel.encode("ascii"),
                              n=2 ** 14, r=8, p=1, dklen=32,
                              maxmem=64 * 1024 * 1024)
        empreinte = "scrypt$16384$8$1$%s$%s" % (sel, brut.hex())

        compte = Compte(identifiant="Repris")
        compte.password = empreinte
        compte.save()

        self.assertTrue(compte.check_password("MonMotDePasse2026"))
        self.assertFalse(compte.check_password("autre"))

    def test_le_hasher_maison_est_celui_qui_ecrit(self):
        from django.contrib.auth.hashers import identify_hasher
        compte = Compte.objects.create_user("Neuf", password="un-mot-de-passe")
        self.assertEqual(type(identify_hasher(compte.password)).__name__,
                         "ScryptHeimdall")
        self.assertTrue(compte.password.startswith("scrypt$16384$8$1$"))
