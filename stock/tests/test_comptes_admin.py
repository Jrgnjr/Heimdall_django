# -*- coding: utf-8 -*-
"""Administrer un compte : état, mot de passe provisoire, code de récupération."""

import json

from django.test import Client, TestCase
from django.urls import reverse

from comptes import recuperation
from comptes.models import ActiviteCompte, Compte
from stock.models import Operation
from stock.services import ErreurAction, executer
from stock.tests.aide_groupes import faire_groupe

MOT_DE_PASSE = "un-mot-de-passe-solide"


class Base(TestCase):

    def setUp(self):
        def compte(nom, admin=False):
            return Compte.objects.create_user(
                nom, password=MOT_DE_PASSE, administrateur=admin, doit_changer=False)

        self.admin = compte("Admin", admin=True)
        self.admin2 = compte("Admin2", admin=True)
        self.chef = compte("Chef")
        self.eff = compte("Eff")
        self.libre = compte("Libre")
        self.groupe = faire_groupe("G", chef="Chef", membres=["Eff"])

    def agir(self, _action, _qui, **params):
        return executer(_action, _qui, params, _qui.startswith("Admin"))

    def refus(self, _action, _qui, **params):
        with self.assertRaises(ErreurAction) as capture:
            self.agir(_action, _qui, **params)
        return str(capture.exception)

    def ouvrir(self, nom, mot_de_passe=MOT_DE_PASSE):
        navigateur = Client()
        self.assertTrue(navigateur.login(identifiant=nom, password=mot_de_passe))
        return navigateur

    def poster(self, navigateur, action, **params):
        return navigateur.post(reverse("api_action"),
                               data=json.dumps({"action": action, "params": params}),
                               content_type="application/json")


class ReserveAuxAdministrateurs(Base):

    def test_les_trois_actions_sont_reservees(self):
        for action, params in (("compte.etat", {"actif": False}),
                               ("compte.mot_de_passe", {}),
                               ("compte.recuperation", {})):
            for qui in ("Chef", "Eff", "Libre"):
                self.assertIn("réservée aux administrateurs", self.refus(
                    action, qui, compte="Libre", **params), (action, qui))


class ActiverDesactiver(Base):

    def test_desactiver_un_compte(self):
        self.agir("compte.etat", "Admin", compte="Libre", actif=False)
        self.assertFalse(Compte.objects.get(pk="Libre").actif)

    def test_un_compte_desactive_ne_se_connecte_plus(self):
        self.agir("compte.etat", "Admin", compte="Libre", actif=False)
        self.assertFalse(Client().login(identifiant="Libre", password=MOT_DE_PASSE))

    def test_sa_session_ouverte_cesse_d_etre_reconnue(self):
        libre = self.ouvrir("Libre")
        self.assertEqual(libre.get(reverse("api_state")).status_code, 200)
        self.agir("compte.etat", "Admin", compte="Libre", actif=False)
        self.assertEqual(libre.get(reverse("api_state")).status_code, 401)

    def test_reactiver(self):
        self.agir("compte.etat", "Admin", compte="Libre", actif=False)
        self.agir("compte.etat", "Admin", compte="Libre", actif=True)
        self.assertTrue(Client().login(identifiant="Libre", password=MOT_DE_PASSE))

    def test_on_ne_se_desactive_pas_soi_meme(self):
        self.assertIn("votre propre compte", self.refus(
            "compte.etat", "Admin", compte="Admin", actif=False))
        self.assertTrue(Compte.objects.get(pk="Admin").actif)

    def test_on_ne_desactive_pas_le_dernier_administrateur(self):
        Compte.objects.filter(pk="Admin2").update(actif=False)
        self.assertIn("dernier administrateur actif", self.refus(
            "compte.etat", "Admin2", compte="Admin", actif=False))
        self.assertTrue(Compte.objects.get(pk="Admin").actif)

    def test_un_administrateur_en_desactive_un_autre(self):
        self.agir("compte.etat", "Admin", compte="Admin2", actif=False)

    def test_un_chef_desactive_perd_la_direction_de_son_groupe(self):
        self.agir("compte.etat", "Admin", compte="Chef", actif=False)
        self.groupe.refresh_from_db()
        self.assertIsNone(self.groupe.chef_id)
        self.assertEqual(Compte.objects.get(pk="Eff").membre_de_id, self.groupe.pk)

    def test_rien_a_changer(self):
        resume, _ = self.agir("compte.etat", "Admin", compte="Libre", actif=True)
        self.assertIn("inchangé", resume)

    def test_c_est_inscrit_au_registre(self):
        self.agir("compte.etat", "Admin", compte="Libre", actif=False)
        self.agir("compte.etat", "Admin", compte="Libre", actif=True)
        actions = list(ActiviteCompte.objects.filter(nouveau_nom="Libre")
                       .order_by("pk").values_list("action", flat=True))
        self.assertEqual(actions, ["compte désactivé", "compte réactivé"])

    def test_les_emprunts_et_le_sac_restent(self):
        from stock.models import Material, MaterialReservation
        Material.objects.create(name="Perceuse", libelle="Perceuse", ordre=1, cat="Outil",
                                qty=2, seuil=0, affectation="Commun")
        self.agir("materiel.emprunt", "Libre", nom="Perceuse", qty=1)
        self.agir("compte.etat", "Admin", compte="Libre", actif=False)
        self.assertEqual(MaterialReservation.objects.get().taken_by, "Libre")


class ReinitialiserLeMotDePasse(Base):

    def reinitialiser(self):
        reponse = self.poster(self.ouvrir("Admin"), "compte.mot_de_passe", compte="Libre")
        self.assertEqual(reponse.status_code, 200, reponse.content)
        return reponse.json()["secret"]

    def test_un_mot_de_passe_provisoire_est_rendu_une_fois(self):
        secret = self.reinitialiser()
        self.assertEqual(len(secret), 12)
        self.assertRegex(secret, r"^[a-zA-Z2-9]+$")
        self.assertNotRegex(secret, r"[0O1Il]")

    def test_il_remplace_l_ancien_et_oblige_a_le_changer(self):
        secret = self.reinitialiser()
        libre = Compte.objects.get(pk="Libre")
        self.assertTrue(libre.check_password(secret))
        self.assertFalse(libre.check_password(MOT_DE_PASSE))
        self.assertTrue(libre.doit_changer)
        navigateur = self.ouvrir("Libre", secret)
        self.assertEqual(navigateur.get(reverse("api_state")).status_code, 403)   # à renouveler

    def test_deux_reinitialisations_donnent_deux_mots_de_passe(self):
        self.assertNotEqual(self.reinitialiser(), self.reinitialiser())

    def test_les_sessions_ouvertes_se_ferment(self):
        libre = self.ouvrir("Libre")
        self.reinitialiser()
        self.assertEqual(libre.get(reverse("api_state")).status_code, 401)

    def test_le_secret_n_entre_ni_dans_l_historique_ni_dans_le_resume(self):
        secret = self.reinitialiser()
        for operation in Operation.objects.all():
            self.assertNotIn(secret, operation.parametres)
            self.assertNotIn(secret, operation.resume)
            self.assertNotIn("_secret", operation.parametres)

    def test_le_secret_n_est_pas_dans_la_reponse_des_autres_actions(self):
        reponse = self.poster(self.ouvrir("Admin"), "compte.etat", compte="Libre", actif=True)
        self.assertNotIn("secret", reponse.json())

    def test_on_ne_se_reinitialise_pas_soi_meme(self):
        self.assertIn("votre propre mot de passe", self.refus(
            "compte.mot_de_passe", "Admin", compte="Admin"))

    def test_compte_inconnu(self):
        self.assertIn("n'existe pas", self.refus(
            "compte.mot_de_passe", "Admin", compte="Fantôme"))

    def test_c_est_inscrit_au_registre_sans_le_mot_de_passe(self):
        secret = self.reinitialiser()
        ligne = ActiviteCompte.objects.get(nouveau_nom="Libre")
        self.assertEqual(ligne.acteur, "Admin")
        self.assertIn("réinitialisé", ligne.action)
        self.assertNotIn(secret, ligne.action + ligne.ancien_nom)

    def test_un_client_ne_peut_pas_injecter_un_secret(self):
        reponse = self.poster(self.ouvrir("Admin"), "compte.etat", compte="Libre",
                              actif=True, _secret="injecte")
        self.assertNotIn("secret", reponse.json())


class RetirerLeCodeDeRecuperation(Base):

    def test_le_code_cesse_de_fonctionner(self):
        code = recuperation.definir(self.libre)
        self.agir("compte.recuperation", "Admin", compte="Libre")
        self.libre.refresh_from_db()
        self.assertEqual(self.libre.code_recuperation, "")
        self.assertFalse(recuperation.verifier(self.libre, code, __import__("django.utils.timezone", fromlist=["now"]).now()))

    def test_sans_code_rien_a_faire(self):
        resume, _ = self.agir("compte.recuperation", "Admin", compte="Libre")
        self.assertIn("n'avait pas de code", resume)

    def test_c_est_inscrit_au_registre(self):
        recuperation.definir(self.libre)
        self.agir("compte.recuperation", "Admin", compte="Libre")
        self.assertTrue(ActiviteCompte.objects.filter(
            nouveau_nom="Libre", action__contains="retiré par un administrateur").exists())


class ExpositionAuxAdministrateurs(Base):

    def etat(self, qui):
        return self.ouvrir(qui).get(reverse("api_state")).json()

    def test_l_administrateur_voit_aussi_les_comptes_desactives(self):
        Compte.objects.filter(pk="Libre").update(actif=False)
        roles = self.etat("Admin")["comptesRoles"]
        self.assertFalse(roles["Libre"]["actif"])
        self.assertTrue(roles["Eff"]["actif"])

    def test_la_derniere_visite_est_exposee(self):
        from django.utils import timezone
        Compte.objects.filter(pk="Eff").update(derniere_visite=timezone.now())
        roles = self.etat("Admin")["comptesRoles"]
        self.assertIsNotNone(roles["Eff"]["visite"])
        self.assertIsNone(roles["Libre"]["visite"])

    def test_un_non_administrateur_ne_recoit_pas_ces_informations(self):
        for qui in ("Chef", "Eff", "Libre"):
            self.assertEqual(self.etat(qui)["comptesRoles"], {})

    def test_l_annuaire_ne_contient_que_les_comptes_actifs(self):
        Compte.objects.filter(pk="Libre").update(actif=False)
        annuaire = self.etat("Admin")["annuaire"]
        self.assertNotIn("Libre", annuaire)
        self.assertIn("Eff", annuaire)
