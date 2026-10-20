# -*- coding: utf-8 -*-
"""Mot de passe oublié : le code de récupération."""

import re
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from comptes import recuperation
from comptes.models import ActiviteCompte, Compte

ANCIEN = "ancien-mot-de-passe-9x"
NOUVEAU = "nouveau-mot-de-passe-7k"


class CodeDeRecuperation(TestCase):

    def setUp(self):
        self.alice = Compte.objects.create_user("Alice", password=ANCIEN,
                                                doit_changer=False)
        self.client = Client()
        self.client.login(identifiant="Alice", password=ANCIEN)

    # -- générer ---------------------------------------------------------

    def generer(self, motdepasse=ANCIEN, client=None):
        return (client or self.client).post(reverse("code_recuperation"), {
            "motdepasse": motdepasse, "action": "generer"})

    def code_affiche(self, reponse):
        trouve = re.search(r"\b([A-Z2-9]{4}(?:-[A-Z2-9]{4}){4})\b",
                           reponse.content.decode())
        return trouve.group(1) if trouve else None

    def test_la_page_exige_une_session(self):
        reponse = Client().get(reverse("code_recuperation"))
        self.assertEqual(reponse.status_code, 302)

    def test_generer_demande_le_mot_de_passe_actuel(self):
        reponse = self.generer(motdepasse="faux")
        self.assertIsNone(self.code_affiche(reponse))
        self.assertContains(reponse, "Mot de passe actuel incorrect")
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.code_recuperation, "")

    def test_le_code_est_affiche_et_forme_correctement(self):
        code = self.code_affiche(self.generer())
        self.assertIsNotNone(code)
        self.assertRegex(code, r"^[A-Z2-9]{4}(-[A-Z2-9]{4}){4}$")

    def test_le_code_n_est_jamais_stocke_en_clair(self):
        code = self.code_affiche(self.generer())
        self.alice.refresh_from_db()
        brut = recuperation.normaliser(code)
        self.assertNotIn(brut, self.alice.code_recuperation)
        self.assertNotIn(code, self.alice.code_recuperation)
        self.assertTrue(self.alice.code_recuperation)

    def test_la_page_ne_remontre_jamais_le_code(self):
        self.generer()
        reponse = self.client.get(reverse("code_recuperation"))
        self.assertIsNone(self.code_affiche(reponse))
        self.assertContains(reponse, "Un code de récupération est défini")

    def test_deux_codes_sont_differents(self):
        self.assertNotEqual(recuperation.generer(), recuperation.generer())

    def test_regenerer_invalide_l_ancien_code(self):
        premier = self.code_affiche(self.generer())
        second = self.code_affiche(self.generer())
        self.assertNotEqual(premier, second)
        self.assertEqual(self.recuperer("Alice", premier).status_code, 200)  # refusé
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(ANCIEN))

    def test_supprimer_le_code(self):
        self.generer()
        self.client.post(reverse("code_recuperation"),
                         {"motdepasse": ANCIEN, "action": "supprimer"})
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.code_recuperation, "")

    # -- récupérer -------------------------------------------------------

    def recuperer(self, identifiant, code, mdp=NOUVEAU, confirmation=None):
        return Client().post(reverse("mot_de_passe_oublie"), {
            "identifiant": identifiant, "code": code, "password1": mdp,
            "password2": mdp if confirmation is None else confirmation})

    def test_le_formulaire_est_accessible_sans_session(self):
        self.assertEqual(Client().get(reverse("mot_de_passe_oublie")).status_code, 200)

    def test_la_page_de_connexion_propose_le_lien(self):
        self.assertContains(Client().get(reverse("connexion")), "Mot de passe oublié")

    def test_recuperation_reussie(self):
        code = self.code_affiche(self.generer())
        reponse = self.recuperer("Alice", code)
        self.assertRedirects(reponse, reverse("connexion"))
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(NOUVEAU))
        self.assertFalse(self.alice.check_password(ANCIEN))
        self.assertTrue(Client().login(identifiant="Alice", password=NOUVEAU))

    def test_le_code_est_a_usage_unique(self):
        code = self.code_affiche(self.generer())
        self.recuperer("Alice", code)
        autre = "encore-un-autre-mdp-4z"
        self.recuperer("Alice", code, mdp=autre)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(NOUVEAU))
        self.assertEqual(self.alice.code_recuperation, "")

    def test_le_code_se_saisit_comme_on_veut(self):
        code = self.code_affiche(self.generer())
        saisie = code.lower().replace("-", " ")
        self.recuperer("Alice", "  " + saisie + "  ")
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(NOUVEAU))

    def test_les_sessions_ouvertes_sont_fermees(self):
        code = self.code_affiche(self.generer())
        self.recuperer("Alice", code)
        self.assertEqual(self.client.get(reverse("api_state")).status_code, 401)

    def test_le_renouvellement_impose_est_leve(self):
        self.alice.doit_changer = True
        self.alice.save(update_fields=["doit_changer"])
        self.alice.code_recuperation = ""  # un administrateur a réinitialisé
        code = recuperation.definir(self.alice)
        self.recuperer("Alice", code)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.doit_changer)

    def test_la_recuperation_est_inscrite_au_registre(self):
        code = self.code_affiche(self.generer())
        self.recuperer("Alice", code)
        self.assertTrue(ActiviteCompte.objects.filter(
            acteur="Alice", action__contains="réinitialisé").exists())

    # -- refus -----------------------------------------------------------

    def test_un_faux_code_est_refuse(self):
        self.generer()
        reponse = self.recuperer("Alice", "AAAA-BBBB-CCCC-DDDD-EEEE")
        self.assertContains(reponse, "incorrect")
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(ANCIEN))

    def test_les_messages_ne_disent_pas_si_le_compte_existe(self):
        self.generer()
        inconnu = self.recuperer("Fantôme", "AAAA-BBBB-CCCC-DDDD-EEEE").content
        faux = self.recuperer("Alice", "AAAA-BBBB-CCCC-DDDD-EEEE").content
        message = re.compile(rb'class="erreurs">.*?</ul>', re.S)
        self.assertEqual(message.search(inconnu).group(0), message.search(faux).group(0))

    def test_un_compte_sans_code_ne_peut_pas_recuperer(self):
        reponse = self.recuperer("Alice", "AAAA-BBBB-CCCC-DDDD-EEEE")
        self.assertContains(reponse, "incorrect")

    def test_un_compte_desactive_ne_peut_pas_recuperer(self):
        code = self.code_affiche(self.generer())
        self.alice.actif = False
        self.alice.save(update_fields=["actif"])
        self.recuperer("Alice", code)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(ANCIEN))

    def test_un_mot_de_passe_faible_est_refuse_sans_consommer_le_code(self):
        code = self.code_affiche(self.generer())
        reponse = self.recuperer("Alice", code, mdp="12345678")
        self.assertEqual(reponse.status_code, 200)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(ANCIEN))
        self.assertTrue(self.alice.code_recuperation)   # toujours valable
        self.recuperer("Alice", code)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(NOUVEAU))

    def test_deux_mots_de_passe_differents_sont_refuses(self):
        code = self.code_affiche(self.generer())
        reponse = self.recuperer("Alice", code, confirmation="autre-chose-2m")
        self.assertContains(reponse, "ne correspondent pas")
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(ANCIEN))

    # -- verrouillage ----------------------------------------------------

    def test_cinq_erreurs_verrouillent_la_recuperation(self):
        code = self.code_affiche(self.generer())
        for _ in range(recuperation.ECHECS_MAX):
            self.recuperer("Alice", "AAAA-BBBB-CCCC-DDDD-EEEE")
        self.alice.refresh_from_db()
        self.assertTrue(recuperation.est_bloque(self.alice, timezone.now()))
        # Même le bon code est refusé pendant le verrouillage.
        self.recuperer("Alice", code)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(ANCIEN))

    def test_le_verrou_ne_ferme_pas_la_connexion_normale(self):
        self.generer()
        for _ in range(recuperation.ECHECS_MAX):
            self.recuperer("Alice", "AAAA-BBBB-CCCC-DDDD-EEEE")
        self.assertTrue(Client().login(identifiant="Alice", password=ANCIEN))

    def test_le_verrou_se_leve_avec_le_temps(self):
        code = self.code_affiche(self.generer())
        for _ in range(recuperation.ECHECS_MAX):
            self.recuperer("Alice", "AAAA-BBBB-CCCC-DDDD-EEEE")
        self.alice.refresh_from_db()
        self.alice.recuperation_bloque_jusqu = timezone.now() - timedelta(seconds=1)
        self.alice.save(update_fields=["recuperation_bloque_jusqu"])
        self.recuperer("Alice", code)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(NOUVEAU))

    def test_les_echecs_sont_comptes_par_compte(self):
        Compte.objects.create_user("Bob", password=ANCIEN, doit_changer=False)
        for _ in range(recuperation.ECHECS_MAX):
            self.recuperer("Bob", "AAAA-BBBB-CCCC-DDDD-EEEE")
        self.generer()
        self.alice.refresh_from_db()
        self.assertFalse(recuperation.est_bloque(self.alice, timezone.now()))
