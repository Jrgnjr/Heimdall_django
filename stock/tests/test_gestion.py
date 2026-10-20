# -*- coding: utf-8 -*-
"""Gestion d'une mission : gestionnaires, effectif, prêts forcés."""

import json

from django.test import Client, TestCase
from django.urls import reverse

from comptes.models import Compte, Dotation
from stock.models import (Equipe, GestionMission, Material, MaterialLog,
                          MaterialReservation, Mission)
from stock.services import ErreurAction, executer
from stock.services.gestion import (effectifs_de, gestion_par_mission,
                                    gestionnaires_de, peut_gerer)
from stock.services.prets import etat_prets

MOT_DE_PASSE = "un-mot-de-passe-solide"


class Base(TestCase):
    """Alice crée « Chantier » ; Bob, Carole, Dave sont des comptes ordinaires."""

    def setUp(self):
        for nom, admin in (("Alice", False), ("Bob", False), ("Carole", False),
                           ("Dave", False), ("Admin", True)):
            Compte.objects.create_user(nom, password=MOT_DE_PASSE,
                                       administrateur=admin, doit_changer=False)
        Material.objects.create(name="Perceuse", libelle="Perceuse", ordre=1,
                                cat="Outil", qty=5, seuil=0, affectation="Commun")
        Material.objects.create(name="Clé USB", libelle="Clé USB", ordre=2,
                                cat="Autre", qty=10, seuil=0, affectation="Commun")

    def agir(self, _action, _qui, **params):
        return executer(_action, _qui, params, _qui == "Admin")

    def refus(self, _action, _qui, **params):
        with self.assertRaises(ErreurAction) as capture:
            self.agir(_action, _qui, **params)
        return str(capture.exception)

    def creer(self, qui="Alice", nom="Chantier", **plus):
        return self.agir("mission.creer", qui, nom=nom, **plus)

    def equipe(self, mission="Chantier", nom="Nord", membres=()):
        e = Equipe.objects.create(mission_id=mission, nom=nom)
        for m in membres:
            e.membres.add(Compte.objects.get(pk=m))
        return e


class DesignerLaGestion(Base):

    def test_le_createur_gere_par_defaut(self):
        self.creer()
        self.assertEqual(gestionnaires_de("Chantier"), ["Alice"])

    def test_le_createur_designe_la_gestion(self):
        self.creer(gestionnaires=["Bob", "Carole"])
        self.assertEqual(gestionnaires_de("Chantier"), ["Bob", "Carole"])

    def test_le_createur_peut_se_compter_parmi_les_gestionnaires(self):
        self.creer(gestionnaires=["Alice", "Bob"])
        self.assertEqual(gestionnaires_de("Chantier"), ["Alice", "Bob"])

    def test_sans_designation_c_est_le_createur(self):
        self.creer(gestionnaires=[])
        self.assertEqual(gestionnaires_de("Chantier"), ["Alice"])

    def test_un_compte_inconnu_est_refuse(self):
        self.assertIn("n'existe pas", self.refus(
            "mission.creer", "Alice", nom="Chantier", gestionnaires=["Fantôme"]))
        self.assertFalse(Mission.objects.filter(pk="Chantier").exists())

    def test_un_doublon_est_refuse(self):
        self.assertIn("deux fois", self.refus(
            "mission.creer", "Alice", nom="Chantier", gestionnaires=["Bob", "Bob"]))

    def test_un_compte_desactive_est_refuse(self):
        Compte.objects.filter(pk="Bob").update(actif=False)
        self.refus("mission.creer", "Alice", nom="Chantier", gestionnaires=["Bob"])

    def test_une_mission_ancienne_a_son_createur_pour_gestionnaire(self):
        """Une mission d'avant cette règle n'a aucune ligne de gestion."""
        Mission.objects.create(name="Ancienne", ordre=1, is_meta=True, owner="Bob",
                               archived=False)
        self.assertEqual(GestionMission.objects.count(), 0)
        self.assertEqual(gestionnaires_de("Ancienne"), ["Bob"])
        self.assertTrue(peut_gerer("Ancienne", "Bob", False))
        self.assertFalse(peut_gerer("Ancienne", "Alice", False))

    def test_un_administrateur_gere_toutes_les_missions(self):
        self.creer()
        self.assertTrue(peut_gerer("Chantier", "Admin", True))
        self.assertFalse(peut_gerer("Chantier", "Bob", False))

    def test_la_gestion_de_toutes_les_missions_est_exposee(self):
        self.creer(gestionnaires=["Bob"])
        Mission.objects.create(name="Ancienne", ordre=2, is_meta=True, owner="Carole",
                               archived=False)
        self.assertEqual(gestion_par_mission(),
                         {"Chantier": ["Bob"], "Ancienne": ["Carole"]})


class ModifierLaGestion(Base):

    def setUp(self):
        super().setUp()
        self.creer(gestionnaires=["Alice"])

    def test_un_gestionnaire_peut_ajouter_un_autre_gestionnaire(self):
        self.agir("mission.gestion", "Alice", mission="Chantier",
                  gestionnaires=["Alice", "Bob"])
        self.assertEqual(gestionnaires_de("Chantier"), ["Alice", "Bob"])

    def test_un_gestionnaire_peut_passer_la_main(self):
        self.agir("mission.gestion", "Alice", mission="Chantier", gestionnaires=["Bob"])
        self.assertEqual(gestionnaires_de("Chantier"), ["Bob"])
        self.refus("mission.gestion", "Alice", mission="Chantier", gestionnaires=["Alice"])

    def test_un_tiers_ne_peut_pas_modifier_la_gestion(self):
        self.assertIn("Réservé aux gestionnaires", self.refus(
            "mission.gestion", "Carole", mission="Chantier", gestionnaires=["Carole"]))
        self.assertEqual(gestionnaires_de("Chantier"), ["Alice"])

    def test_un_administrateur_peut_modifier_la_gestion(self):
        self.agir("mission.gestion", "Admin", mission="Chantier", gestionnaires=["Dave"])
        self.assertEqual(gestionnaires_de("Chantier"), ["Dave"])

    def test_on_ne_peut_pas_retirer_tous_les_gestionnaires(self):
        self.assertIn("au moins un gestionnaire", self.refus(
            "mission.gestion", "Alice", mission="Chantier", gestionnaires=[]))

    def test_mission_inconnue(self):
        self.refus("mission.gestion", "Admin", mission="Fantôme", gestionnaires=["Bob"])

    def test_le_client_ne_peut_pas_se_dire_administrateur(self):
        self.refus("mission.gestion", "Carole", mission="Chantier",
                   gestionnaires=["Carole"], _administrateur=True)


class GestionnaireOuEffectif(Base):
    """Soit en gestion, soit en effectif : jamais les deux sur une même mission."""

    def setUp(self):
        super().setUp()
        self.creer(gestionnaires=["Alice"])

    def test_nommer_gestionnaire_quelqu_un_de_l_effectif_est_refuse(self):
        self.equipe(membres=["Bob"])
        message = self.refus("mission.gestion", "Alice", mission="Chantier",
                             gestionnaires=["Alice", "Bob"])
        self.assertIn("soit en gestion, soit en effectif", message)
        self.assertEqual(gestionnaires_de("Chantier"), ["Alice"])

    def test_mettre_un_gestionnaire_dans_une_equipe_est_refuse(self):
        self.equipe()
        message = self.refus("mission.equipe.membres", "Alice", mission="Chantier",
                             nom="Nord", membres=["Alice"])
        self.assertIn("soit en gestion, soit en effectif", message)
        self.assertEqual(effectifs_de("Chantier"), set())

    def test_un_effectif_ordinaire_peut_etre_ajoute(self):
        self.equipe()
        self.agir("mission.equipe.membres", "Alice", mission="Chantier", nom="Nord",
                  membres=["Bob", "Carole"])
        self.assertEqual(effectifs_de("Chantier"), {"Bob", "Carole"})

    def test_on_peut_changer_de_role_en_quittant_d_abord_l_autre(self):
        self.equipe(membres=["Bob"])
        self.agir("mission.equipe.membres", "Alice", mission="Chantier", nom="Nord",
                  membres=[])
        self.agir("mission.gestion", "Alice", mission="Chantier",
                  gestionnaires=["Alice", "Bob"])
        self.assertEqual(gestionnaires_de("Chantier"), ["Alice", "Bob"])

    def test_le_meme_compte_peut_gerer_une_mission_et_etre_effectif_d_une_autre(self):
        self.creer(qui="Carole", nom="Autre", gestionnaires=["Carole"])
        self.equipe(mission="Autre", nom="Sud")
        self.agir("mission.equipe.membres", "Carole", mission="Autre", nom="Sud",
                  membres=["Bob"])
        self.agir("mission.gestion", "Alice", mission="Chantier",
                  gestionnaires=["Alice", "Bob"])     # Bob gère Chantier, travaille sur Autre
        self.assertEqual(gestionnaires_de("Chantier"), ["Alice", "Bob"])
        self.assertEqual(effectifs_de("Autre"), {"Bob"})

    def test_un_etat_anterieur_n_est_pas_refuse_retroactivement(self):
        """Quelqu'un déjà dans l'équipe et déjà gestionnaire (avant la règle) peut
        y rester quand on modifie le reste."""
        GestionMission.objects.create(mission_id="Chantier", compte="Bob")
        e = self.equipe(membres=["Bob"])
        self.agir("mission.equipe.membres", "Alice", mission="Chantier", nom="Nord",
                  membres=["Bob", "Carole"])
        self.assertEqual(set(e.membres.values_list("identifiant", flat=True)),
                         {"Bob", "Carole"})

    def test_l_ancien_createur_implicite_ne_peut_pas_rejoindre_l_effectif(self):
        Mission.objects.create(name="Ancienne", ordre=5, is_meta=True, owner="Carole",
                               archived=False)
        self.equipe(mission="Ancienne", nom="Est")
        self.assertIn("gère la mission", self.refus(
            "mission.equipe.membres", "Carole", mission="Ancienne", nom="Est",
            membres=["Carole"]))


class DroitsSurLesEquipes(Base):

    def setUp(self):
        super().setUp()
        self.creer(gestionnaires=["Alice", "Bob"])

    def test_chaque_gestionnaire_compose_les_equipes(self):
        self.agir("mission.equipe.creer", "Alice", mission="Chantier", nom="Nord")
        self.agir("mission.equipe.renommer", "Bob", mission="Chantier", nom="Nord",
                  nouveauNom="Sud")
        self.agir("mission.equipe.supprimer", "Bob", mission="Chantier", nom="Sud")
        self.assertEqual(Equipe.objects.count(), 0)

    def test_un_tiers_ne_compose_pas_les_equipes(self):
        self.agir("mission.equipe.creer", "Alice", mission="Chantier", nom="Nord")
        for action, params in (
                ("mission.equipe.creer", {"nom": "Est"}),
                ("mission.equipe.renommer", {"nom": "Nord", "nouveauNom": "Ouest"}),
                ("mission.equipe.membres", {"nom": "Nord", "membres": ["Carole"]}),
                ("mission.equipe.supprimer", {"nom": "Nord"})):
            self.assertIn("Réservé aux gestionnaires",
                          self.refus(action, "Carole", mission="Chantier", **params))
        self.assertEqual(Equipe.objects.get().nom, "Nord")

    def test_un_administrateur_les_compose_partout(self):
        self.agir("mission.equipe.creer", "Admin", mission="Chantier", nom="Nord")
        self.assertEqual(Equipe.objects.count(), 1)

    def test_les_droits_s_arretent_a_la_mission(self):
        self.creer(qui="Carole", nom="Autre", gestionnaires=["Carole"])
        self.refus("mission.equipe.creer", "Alice", mission="Autre", nom="Nord")


class DroitsSurLesStatuts(Base):

    def setUp(self):
        super().setUp()
        self.creer(gestionnaires=["Alice", "Bob"])
        self.equipe(membres=["Dave"])
        self.agir("mission.statut", "Carole", nom="Chantier", statut="TERMINÉE")

    def test_chaque_gestionnaire_peut_reculer(self):
        self.agir("mission.statut", "Bob", nom="Chantier", statut="EN COURS")
        self.agir("mission.statut", "Alice", nom="Chantier", statut="PRÉVUE")

    def test_l_effectif_ne_recule_pas(self):
        message = self.refus("mission.statut", "Dave", nom="Chantier", statut="PRÉVUE")
        self.assertIn("Alice, Bob", message)

    def test_un_tiers_ne_recule_pas(self):
        self.refus("mission.statut", "Carole", nom="Chantier", statut="EN COURS")


class ForcerUnPret(Base):
    """Un gestionnaire peut prendre dans le sac d'une personne absente."""

    def setUp(self):
        super().setUp()
        self.creer(gestionnaires=["Alice"])
        Dotation.objects.create(compte_id="Carole", ordre=1, material_id="Clé USB",
                                quantite=6)

    def forcer(self, qui="Alice", qty=2, **plus):
        return self.agir("pret.forcer", qui, mission="Chantier", proprietaire="Carole",
                         article="Clé USB", qty=qty, **plus)

    def test_le_pret_est_accorde_sans_reponse_du_proprietaire(self):
        self.forcer()
        r = MaterialReservation.objects.get()
        self.assertEqual((r.material_id, r.qty, r.taken_by, r.mission),
                         ("Clé USB", 2, "Alice", "Chantier"))
        self.assertEqual((r.sac_de, r.force_par), ("Carole", "Alice"))
        self.assertTrue(r.ouvert)

    def test_aucune_demande_n_est_creee(self):
        from stock.models import DemandePret
        self.forcer()
        self.assertEqual(DemandePret.objects.count(), 0)

    def test_c_est_marque_force_et_visible_du_proprietaire(self):
        self.forcer()
        pret = etat_prets("Carole")["prets"][0]
        self.assertEqual((pret["a"], pret["quantite"], pret["forcePar"]),
                         ("Alice", 2, "Alice"))

    def test_c_est_journalise(self):
        self.forcer()
        ligne = MaterialLog.objects.get(kind="SORTIE")
        self.assertEqual((ligne.who, ligne.mission, ligne.qty), ("Alice", "Chantier", 2))
        self.assertIn("Prêt forcé par Alice depuis le sac de Carole", ligne.commentaire)

    def test_le_sac_prete_moins_ensuite(self):
        self.forcer(qty=4)
        self.assertEqual(etat_prets("Alice")["sacs"]["Carole"][0]["disponible"], 2)

    def test_on_ne_depasse_pas_ce_que_le_sac_peut_preter(self):
        self.assertIn("6", self.refus("pret.forcer", "Alice", mission="Chantier",
                                      proprietaire="Carole", article="Clé USB", qty=7))
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_un_article_absent_du_sac_est_refuse(self):
        self.refus("pret.forcer", "Alice", mission="Chantier", proprietaire="Carole",
                   article="Perceuse", qty=1)

    def test_seuls_les_gestionnaires_et_les_administrateurs_peuvent_forcer(self):
        for qui in ("Bob", "Dave"):
            self.assertIn("Réservé aux gestionnaires", self.refus(
                "pret.forcer", qui, mission="Chantier", proprietaire="Carole",
                article="Clé USB", qty=1))
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_un_administrateur_force_sur_toutes_les_missions(self):
        self.forcer(qui="Admin")
        r = MaterialReservation.objects.get()
        self.assertEqual((r.taken_by, r.force_par), ("Admin", "Admin"))

    def test_le_client_ne_peut_pas_se_dire_administrateur(self):
        self.refus("pret.forcer", "Bob", mission="Chantier", proprietaire="Carole",
                   article="Clé USB", qty=1, _administrateur=True)

    def test_on_ne_force_pas_un_membre_de_l_effectif(self):
        """Il emporte déjà son sac."""
        self.equipe(membres=["Carole"])
        self.assertIn("emporte déjà son sac", self.refus(
            "pret.forcer", "Alice", mission="Chantier", proprietaire="Carole",
            article="Clé USB", qty=1))

    def test_on_ne_se_force_pas_son_propre_sac(self):
        Dotation.objects.create(compte_id="Alice", ordre=1, material_id="Perceuse",
                                quantite=1)
        self.assertIn("déjà à lui", self.refus(
            "pret.forcer", "Alice", mission="Chantier", proprietaire="Alice",
            article="Perceuse", qty=1))

    def test_pour_designe_l_emprunteur(self):
        self.forcer(pour="Dave")
        r = MaterialReservation.objects.get()
        self.assertEqual((r.taken_by, r.force_par), ("Dave", "Alice"))

    def test_pour_un_compte_inconnu_est_refuse(self):
        self.refus("pret.forcer", "Alice", mission="Chantier", proprietaire="Carole",
                   article="Clé USB", qty=1, pour="Fantôme")

    def test_une_mission_archivee_est_refusee(self):
        Mission.objects.filter(pk="Chantier").update(archived=True)
        self.assertIn("archivée", self.refus("pret.forcer", "Alice", mission="Chantier",
                                             proprietaire="Carole", article="Clé USB", qty=1))

    def test_une_mission_inconnue_est_refusee(self):
        self.refus("pret.forcer", "Admin", mission="Fantôme", proprietaire="Carole",
                   article="Clé USB", qty=1)

    def test_le_pret_force_se_rend_comme_les_autres(self):
        self.forcer(qty=3)
        self.agir("materiel.emprunt.retour", "Alice", nom="Clé USB", index=0)
        self.assertEqual(MaterialReservation.objects.count(), 0)
        self.assertEqual(etat_prets("Alice")["sacs"]["Carole"][0]["disponible"], 6)


class ExpositionParLApi(Base):

    def ouvrir(self, nom):
        navigateur = Client()
        navigateur.login(identifiant=nom, password=MOT_DE_PASSE)
        return navigateur

    def poster(self, navigateur, action, **params):
        return navigateur.post(reverse("api_action"),
                               data=json.dumps({"action": action, "params": params}),
                               content_type="application/json")

    def test_tout_le_monde_voit_qui_gere_les_missions(self):
        self.creer(gestionnaires=["Bob"])
        etat = self.ouvrir("Dave").get(reverse("api_state")).json()
        self.assertEqual(etat["gestionMissions"], {"Chantier": ["Bob"]})

    def test_tout_le_monde_recoit_l_annuaire_des_comptes_actifs(self):
        Compte.objects.filter(pk="Dave").update(actif=False)
        etat = self.ouvrir("Bob").get(reverse("api_state")).json()
        self.assertEqual(sorted(etat["annuaire"]), ["Admin", "Alice", "Bob", "Carole"])
        self.assertEqual(etat["comptes"], [])          # la liste d'agir « au nom de » reste réservée

    def test_un_gestionnaire_non_administrateur_agit_par_l_api(self):
        self.creer(gestionnaires=["Alice"])
        Dotation.objects.create(compte_id="Carole", ordre=1, material_id="Clé USB",
                                quantite=3)
        alice = self.ouvrir("Alice")
        reponse = self.poster(alice, "pret.forcer", mission="Chantier",
                              proprietaire="Carole", article="Clé USB", qty=2)
        self.assertEqual(reponse.status_code, 200, reponse.content)
        refus = self.poster(self.ouvrir("Bob"), "pret.forcer", mission="Chantier",
                            proprietaire="Carole", article="Clé USB", qty=1)
        self.assertEqual(refus.status_code, 422)


class TableauDeMission(Base):
    """La page tableau de bord nomme la gestion, plus un « responsable »."""

    def test_la_page_affiche_les_gestionnaires(self):
        self.creer(gestionnaires=["Bob", "Carole"])
        client = Client()
        client.login(identifiant="Dave", password=MOT_DE_PASSE)
        page = client.get("/missions/Chantier/")
        self.assertContains(page, "Gestion : Bob, Carole")
        self.assertNotContains(page, "Responsable")
