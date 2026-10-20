# -*- coding: utf-8 -*-
"""L'ordre des statuts d'une mission : on avance, on ne recule pas."""

import datetime
import json

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from comptes.models import Compte
from stock.models import Material, MaterialReservation, Mission
from stock.services import ErreurAction, executer
from stock.services.statuts import figer_statuts, statut_de

MOT_DE_PASSE = "un-mot-de-passe-solide"
PREVUE, EN_COURS, TERMINEE, ANNULEE = "PRÉVUE", "EN COURS", "TERMINÉE", "ANNULÉE"


class Base(TestCase):
    """Alice gère « Chantier » ; Bob est un utilisateur ordinaire ; Admin administre."""

    def setUp(self):
        for nom, admin in (("Alice", False), ("Bob", False), ("Admin", True)):
            Compte.objects.create_user(nom, password=MOT_DE_PASSE,
                                       administrateur=admin, doit_changer=False)
        Material.objects.create(name="Perceuse", libelle="Perceuse", ordre=1,
                                cat="Outil", qty=5, seuil=0, affectation="Commun")
        Mission.objects.create(name="Chantier", ordre=1, is_meta=True,
                               owner="Alice", archived=False)

    def agir(self, _action, _qui, **params):
        return executer(_action, _qui, params, _qui == "Admin")

    def refus(self, _action, _qui, **params):
        with self.assertRaises(ErreurAction) as capture:
            self.agir(_action, _qui, **params)
        return str(capture.exception)

    def poser(self, qui, statut):
        return self.agir("mission.statut", qui, nom="Chantier", statut=statut)

    def statut(self):
        return statut_de("Chantier")

    def mission(self):
        return Mission.objects.get(pk="Chantier")


class OrdreDesStatuts(Base):
    """Alice gère « Chantier » ; Bob n'a aucun rôle sur cette mission."""

    # -- qui peut changer un statut ---------------------------------------

    def test_seul_le_gestionnaire_change_le_statut(self):
        message = self.refus("mission.statut", "Bob", nom="Chantier", statut=EN_COURS)
        self.assertIn("réservé aux gestionnaires", message)
        self.assertIn("(Alice)", message)
        self.assertEqual(self.statut(), PREVUE)
        self.poser("Alice", EN_COURS)
        self.assertEqual(self.statut(), EN_COURS)

    def test_un_administrateur_change_tous_les_statuts(self):
        self.poser("Admin", TERMINEE)
        self.assertEqual(self.statut(), TERMINEE)

    def test_le_gestionnaire_d_une_autre_mission_n_a_pas_la_main(self):
        Mission.objects.create(name="Autre", ordre=2, is_meta=True, owner="Bob",
                               archived=False)
        self.agir("mission.statut", "Bob", nom="Autre", statut=TERMINEE)
        self.refus("mission.statut", "Alice", nom="Autre", statut=EN_COURS)

    # -- avancer ----------------------------------------------------------

    def test_on_avance_dans_l_ordre(self):
        self.poser("Alice", EN_COURS)
        self.assertEqual(self.statut(), EN_COURS)
        self.poser("Alice", TERMINEE)
        self.assertEqual(self.statut(), TERMINEE)

    def test_on_peut_sauter_une_etape_en_avancant(self):
        self.poser("Alice", TERMINEE)
        self.assertEqual(self.statut(), TERMINEE)

    # -- reculer ----------------------------------------------------------

    def test_le_gestionnaire_peut_reculer(self):
        self.poser("Alice", TERMINEE)
        self.poser("Alice", EN_COURS)
        self.assertEqual(self.statut(), EN_COURS)
        self.poser("Alice", PREVUE)
        self.assertEqual(self.statut(), PREVUE)

    def test_un_administrateur_peut_reculer(self):
        self.poser("Alice", TERMINEE)
        self.poser("Admin", PREVUE)
        self.assertEqual(self.statut(), PREVUE)

    def test_un_tiers_ne_recule_pas(self):
        for depart, arrivee in ((EN_COURS, PREVUE), (TERMINEE, EN_COURS), (TERMINEE, PREVUE)):
            self.poser("Alice", depart)
            message = self.refus("mission.statut", "Bob", nom="Chantier", statut=arrivee)
            self.assertIn("réservé aux gestionnaires", message, (depart, arrivee))
            self.assertEqual(self.statut(), depart)

    def test_reculer_abaisse_le_plancher(self):
        """Sinon le calcul remonterait aussitôt la mission à son ancien niveau."""
        self.poser("Alice", TERMINEE)
        self.poser("Alice", PREVUE)
        self.assertEqual(self.mission().status_max, PREVUE)
        self.assertEqual(self.statut(), PREVUE)

    def test_rester_au_meme_statut_est_toujours_permis(self):
        self.poser("Alice", EN_COURS)
        self.poser("Alice", EN_COURS)

    # -- annulée, à part --------------------------------------------------

    def test_le_gestionnaire_annule_une_mission_prevue_ou_en_cours(self):
        self.poser("Alice", ANNULEE)
        self.assertEqual(self.statut(), ANNULEE)
        self.poser("Alice", PREVUE)
        self.poser("Alice", EN_COURS)
        self.poser("Alice", ANNULEE)
        self.assertEqual(self.statut(), ANNULEE)

    def test_un_tiers_n_annule_pas(self):
        self.refus("mission.statut", "Bob", nom="Chantier", statut=ANNULEE)
        self.assertEqual(self.statut(), PREVUE)

    def test_le_gestionnaire_annule_meme_une_mission_terminee(self):
        self.poser("Alice", TERMINEE)
        self.poser("Alice", ANNULEE)
        self.assertEqual(self.statut(), ANNULEE)

    def test_un_tiers_ne_rouvre_pas_une_mission_annulee(self):
        self.poser("Alice", ANNULEE)
        for cible in (PREVUE, EN_COURS, TERMINEE):
            self.refus("mission.statut", "Bob", nom="Chantier", statut=cible)
        self.poser("Alice", EN_COURS)
        self.assertEqual(self.statut(), EN_COURS)

    def test_un_administrateur_rouvre_une_mission_annulee(self):
        self.poser("Alice", ANNULEE)
        self.poser("Admin", PREVUE)
        self.assertEqual(self.statut(), PREVUE)

    def test_annuler_ne_change_pas_le_plancher(self):
        self.poser("Alice", EN_COURS)
        self.poser("Alice", ANNULEE)
        self.assertEqual(self.mission().status_max, EN_COURS)

    # -- mission sans ligne propre ----------------------------------------

    def test_une_mission_implicite_n_a_que_les_administrateurs_pour_gestionnaires(self):
        """Elle n'a pas de créateur : seul un administrateur peut la matérialiser."""
        self.refus("mission.statut", "Bob", nom="Venue d'un emprunt", statut=EN_COURS)
        self.agir("mission.statut", "Admin", nom="Venue d'un emprunt", statut=EN_COURS)
        m = Mission.objects.get(pk="Venue d'un emprunt")
        self.assertEqual((m.is_meta, m.status_override), (False, EN_COURS))

    # -- pas de falsification ---------------------------------------------

    def test_le_client_ne_peut_pas_s_attribuer_le_droit_administrateur(self):
        message = self.refus("mission.statut", "Bob", nom="Chantier", statut=TERMINEE,
                             _administrateur=True)
        self.assertIn("réservé aux gestionnaires", message)

    def test_le_client_ne_peut_pas_se_faire_passer_pour_un_autre_acteur(self):
        message = self.refus("mission.statut", "Bob", nom="Chantier", statut=TERMINEE,
                             _acteur="Alice")
        self.assertIn("réservé aux gestionnaires", message)


class PlancherDuStatutCalcule(Base):
    """Le statut qui avance seul ne doit pas reculer non plus."""

    def ouvrir(self, nom):
        navigateur = Client()
        navigateur.login(identifiant=nom, password=MOT_DE_PASSE)
        return navigateur

    def poster(self, navigateur, action, **params):
        return navigateur.post(reverse("api_action"),
                               data=json.dumps({"action": action, "params": params}),
                               content_type="application/json")

    def aujourdhui(self):
        return timezone.localdate()

    def test_repousser_la_date_ne_fait_pas_reculer(self):
        Mission.objects.filter(pk="Chantier").update(planned_date=self.aujourdhui())
        self.assertEqual(self.statut(), EN_COURS)
        alice = self.ouvrir("Alice")
        futur = (self.aujourdhui() + datetime.timedelta(days=30)).isoformat()
        self.assertEqual(self.poster(alice, "mission.date", nom="Chantier",
                                     date=futur).status_code, 200)
        self.assertEqual(self.statut(), EN_COURS)

    def test_rendre_le_dernier_emprunt_ne_fait_pas_reculer(self):
        """Une mission sans date est « en cours » tant qu'elle détient du matériel ;
        l'emprunt rendu par suppression de sa ligne la ramenait à « prévue »."""
        alice = self.ouvrir("Alice")
        self.poster(alice, "materiel.emprunt", nom="Perceuse", qty=1, mission="Chantier")
        self.assertEqual(self.statut(), EN_COURS)
        self.poster(alice, "materiel.emprunt.retour", nom="Perceuse", index=0)
        self.assertEqual(MaterialReservation.objects.count(), 0)
        self.assertEqual(self.statut(), EN_COURS)

    def test_du_materiel_affecte_apres_la_fin_ne_la_rouvre_pas(self):
        alice = self.ouvrir("Alice")
        self.poster(alice, "materiel.emprunt", nom="Perceuse", qty=1, mission="Chantier")
        self.poster(alice, "materiel.mission.restituer", mission="Chantier")
        self.assertEqual(self.statut(), TERMINEE)
        self.poster(alice, "materiel.emprunt", nom="Perceuse", qty=1, mission="Chantier")
        self.assertEqual(self.statut(), TERMINEE)

    def test_le_statut_calcule_n_est_pas_fige_a_tort(self):
        """Prévue reste prévue tant que rien ne l'a fait avancer."""
        alice = self.ouvrir("Alice")
        self.poster(alice, "mission.date", nom="Chantier",
                    date=(self.aujourdhui() + datetime.timedelta(days=30)).isoformat())
        self.assertEqual(self.statut(), PREVUE)
        self.assertIn(self.mission().status_max, (None, "", PREVUE))

    def test_figer_retient_le_plus_haut_niveau_atteint(self):
        Mission.objects.filter(pk="Chantier").update(planned_date=self.aujourdhui())
        figer_statuts()
        self.assertEqual(self.mission().status_max, EN_COURS)
        figer_statuts(self.aujourdhui() - datetime.timedelta(days=1))   # jamais à la baisse
        self.assertEqual(self.mission().status_max, EN_COURS)

    def test_l_api_expose_le_plancher_de_chaque_mission(self):
        Mission.objects.filter(pk="Chantier").update(planned_date=self.aujourdhui())
        alice = self.ouvrir("Alice")
        self.poster(alice, "mission.date", nom="Chantier", date=self.aujourdhui().isoformat())
        etat = alice.get(reverse("api_state")).json()
        self.assertEqual(etat["plancherMissions"], {"Chantier": EN_COURS})

    def test_un_changement_de_statut_par_l_api_exige_la_gestion(self):
        alice, bob = self.ouvrir("Alice"), self.ouvrir("Bob")
        refus = self.poster(bob, "mission.statut", nom="Chantier", statut=TERMINEE)
        self.assertEqual(refus.status_code, 422)
        self.assertIn("gestionnaire", refus.json()["error"])
        self.assertEqual(self.statut(), PREVUE)
        self.assertEqual(self.poster(alice, "mission.statut", nom="Chantier",
                                     statut=TERMINEE).status_code, 200)
        self.assertEqual(self.poster(alice, "mission.statut", nom="Chantier",
                                     statut=PREVUE).status_code, 200)
        self.assertEqual(self.statut(), PREVUE)

    def test_le_client_ne_peut_pas_se_declarer_administrateur_par_l_api(self):
        self.poster(self.ouvrir("Alice"), "mission.statut", nom="Chantier", statut=TERMINEE)
        refus = self.poster(self.ouvrir("Bob"), "mission.statut", nom="Chantier",
                            statut=PREVUE, _administrateur=True, _acteur="Alice")
        self.assertEqual(refus.status_code, 422)
        self.assertEqual(self.statut(), TERMINEE)

    def test_l_historique_ne_garde_pas_la_cle_de_droit(self):
        from stock.models import Operation
        alice = self.ouvrir("Alice")
        self.poster(alice, "mission.statut", nom="Chantier", statut=EN_COURS)
        self.assertNotIn("_administrateur", Operation.objects.last().parametres)


class DesassignerSeulementSiPrevue(Base):

    def setUp(self):
        super().setUp()
        Mission.objects.filter(pk="Chantier").update(
            planned_date=timezone.localdate() + datetime.timedelta(days=10))
        self.agir("materiel.emprunt", "Alice", nom="Perceuse", qty=1, mission="Chantier")

    def desassigner(self, qui="Alice"):
        return self.agir("materiel.mission.desassigner", qui, nom="Perceuse", index=0)

    def test_possible_tant_que_la_mission_est_prevue(self):
        self.assertEqual(self.statut(), PREVUE)
        self.desassigner()
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_le_refus_oriente_vers_la_restitution(self):
        self.poser("Alice", EN_COURS)
        self.assertIn("Restituez-le", self.refus(
            "materiel.mission.desassigner", "Alice", nom="Perceuse", index=0))

    def test_refuse_quand_la_mission_est_en_cours(self):
        self.poser("Alice", EN_COURS)
        self.assertIn("est en cours", self.refus(
            "materiel.mission.desassigner", "Alice", nom="Perceuse", index=0))
        self.assertEqual(MaterialReservation.objects.get().mission, "Chantier")

    def test_refuse_quand_la_mission_est_terminee(self):
        self.poser("Alice", TERMINEE)
        self.assertIn("est terminée", self.refus(
            "materiel.mission.desassigner", "Alice", nom="Perceuse", index=0))

    def test_refuse_quand_la_mission_est_annulee(self):
        self.poser("Alice", ANNULEE)
        self.assertIn("est annulée", self.refus(
            "materiel.mission.desassigner", "Alice", nom="Perceuse", index=0))

    def test_refuse_quand_la_date_est_arrivee(self):
        Mission.objects.filter(pk="Chantier").update(planned_date=timezone.localdate())
        self.assertIn("est en cours", self.refus(
            "materiel.mission.desassigner", "Alice", nom="Perceuse", index=0))

    def test_pas_d_exception_pour_les_administrateurs(self):
        self.poser("Alice", EN_COURS)
        self.refus("materiel.mission.desassigner", "Admin", nom="Perceuse", index=0)

    def test_redevenue_prevue_par_son_gestionnaire_elle_redevient_possible(self):
        self.poser("Alice", EN_COURS)
        self.poser("Alice", PREVUE)
        self.desassigner()
        self.assertEqual(MaterialReservation.objects.count(), 0)


class RestituerUneLigne(Base):
    """Une fois la mission en cours, le matériel ne se désassigne plus : il se rend."""

    def setUp(self):
        super().setUp()
        self.agir("materiel.emprunt", "Alice", nom="Perceuse", qty=2, mission="Chantier")
        self.poser("Alice", EN_COURS)

    def ligne(self):
        return MaterialReservation.objects.get()

    def restituer(self, qui="Alice", **plus):
        return self.agir("materiel.mission.restituer_ligne", qui, nom="Perceuse",
                         index=0, **plus)

    def test_la_ligne_se_ferme_et_reste_dans_la_mission(self):
        self.restituer()
        r = self.ligne()
        self.assertFalse(r.ouvert)
        self.assertEqual((r.mission, r.returned_by), ("Chantier", "Alice"))

    def test_le_materiel_revient_au_stock(self):
        avant = Material.objects.get(pk="Perceuse").disponible()
        self.restituer()
        self.assertEqual(Material.objects.get(pk="Perceuse").disponible(), avant + 2)

    def test_c_est_journalise_comme_un_retour(self):
        from stock.models import MaterialLog
        self.restituer()
        ligne = MaterialLog.objects.filter(kind="RETOUR").last()
        self.assertEqual((ligne.qty, ligne.mission, ligne.who), (2, "Chantier", "Alice"))

    def test_les_autres_lignes_ne_bougent_pas(self):
        self.agir("materiel.emprunt", "Alice", nom="Perceuse", qty=1, mission="Chantier")
        self.restituer()
        ouvertes = [r for r in MaterialReservation.objects.all() if r.ouvert]
        self.assertEqual([r.qty for r in ouvertes], [1])

    def test_une_ligne_deja_rendue_est_refusee(self):
        self.restituer()
        self.assertIn("déjà rendue", self.refus(
            "materiel.mission.restituer_ligne", "Alice", nom="Perceuse", index=0))

    def test_une_ligne_sans_mission_est_refusee(self):
        self.agir("materiel.emprunt", "Alice", nom="Perceuse", qty=1)
        self.assertIn("aucune mission", self.refus(
            "materiel.mission.restituer_ligne", "Alice", nom="Perceuse", index=1))

    def test_une_ligne_modifiee_entre_temps_est_refusee(self):
        self.refus("materiel.mission.restituer_ligne", "Alice", nom="Perceuse", index=0,
                   empreinte="99|Autre|Quelqu'un")
        self.assertTrue(self.ligne().ouvert)

    def test_un_tiers_ne_peut_pas_restituer(self):
        self.assertIn("Seul l'emprunteur", self.refus(
            "materiel.mission.restituer_ligne", "Bob", nom="Perceuse", index=0))
        self.assertTrue(self.ligne().ouvert)

    def test_le_gestionnaire_de_la_mission_peut_restituer(self):
        self.restituer("Admin")
        self.assertFalse(self.ligne().ouvert)

    def test_la_derniere_ligne_rendue_termine_la_mission_calculee(self):
        """La ligne reste dans la mission, fermée : le statut calculé la voit."""
        self.poser("Alice", PREVUE)
        Mission.objects.filter(pk="Chantier").update(status_override=None,
                                                     status_max=None)
        self.assertEqual(self.statut(), EN_COURS)
        self.restituer()
        self.assertEqual(self.statut(), TERMINEE)

    def test_un_pret_de_sac_regagne_le_sac(self):
        from comptes.models import Dotation
        from stock.services.prets import etat_prets
        Dotation.objects.create(compte_id="Bob", ordre=1, material_id="Perceuse", quantite=3)
        MaterialReservation.objects.all().delete()
        self.agir("pret.demander", "Alice", proprietaire="Bob", article="Perceuse",
                  qty=2, mission="Chantier")
        from stock.models import DemandePret
        self.agir("pret.accepter", "Bob", id=DemandePret.objects.get().pk)
        self.assertEqual(etat_prets("Bob")["prets"][0]["quantite"], 2)
        self.restituer()
        self.assertEqual(etat_prets("Bob")["prets"], [])
