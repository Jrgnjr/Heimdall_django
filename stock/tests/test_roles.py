# -*- coding: utf-8 -*-
"""Les rôles : effectif, chef de groupe, gestionnaire de mission, admin.

Trois rôles de compte (effectif < chef de groupe < admin) et un quatrième propre à
chaque mission (gestionnaire). Voir `stock/services/droits.py`.

Population de ces tests :

- **Admin** — administrateur ;
- **Chef1** — chef de groupe, avec Eff1 et Eff2 pour effectifs ;
- **Chef2** — chef de groupe, avec Eff3 pour effectif ;
- **Libre** — effectif sans chef ;
- **Gest** — effectif, désigné gestionnaire de « Chantier ».
"""

import json

from django.test import Client, TestCase
from django.urls import reverse

from comptes.models import ActiviteCompte, Compte, Dotation, Groupe
from stock.models import (DemandePret, Equipe, Material, MaterialLog,
                          MaterialReservation, Mission)
from stock.services import ErreurAction, executer
from stock.tests.aide_groupes import faire_groupe
from stock.services.droits import (dans_le_groupe, groupe_de, membres_du_groupe,
                                  peut_representer,
                                   role_de)
from stock.services.prets import etat_prets

MOT_DE_PASSE = "un-mot-de-passe-solide"


class Base(TestCase):

    def setUp(self):
        def compte(nom, admin=False):
            return Compte.objects.create_user(
                nom, password=MOT_DE_PASSE, administrateur=admin, doit_changer=False)

        self.admin = compte("Admin", admin=True)
        self.chef1 = compte("Chef1")
        self.chef2 = compte("Chef2")
        self.eff1 = compte("Eff1")
        self.eff2 = compte("Eff2")
        self.eff3 = compte("Eff3")
        self.libre = compte("Libre")
        self.gest = compte("Gest")
        self.g1 = faire_groupe("G1", chef="Chef1", membres=["Eff1", "Eff2"])
        self.g2 = faire_groupe("G2", chef="Chef2", membres=["Eff3"])

        Material.objects.create(name="Perceuse", libelle="Perceuse", ordre=1, cat="Outil",
                                qty=5, seuil=0, affectation="Commun")
        Material.objects.create(name="Clé USB", libelle="Clé USB", ordre=2, cat="Autre",
                                qty=10, seuil=0, affectation="Commun")
        # Chef1 crée « Chantier » et en confie la gestion à Gest : un chef de groupe
        # n'est pas gestionnaire d'office.
        executer("mission.creer", "Chef1",
                 {"nom": "Chantier", "gestionnaires": ["Gest"]}, False)

    def agir(self, _action, _qui, **params):
        return executer(_action, _qui, params, _qui == "Admin")

    def refus(self, _action, _qui, **params):
        with self.assertRaises(ErreurAction) as capture:
            self.agir(_action, _qui, **params)
        return str(capture.exception)

    def equipe(self, mission="Chantier", nom="Nord", membres=()):
        e = Equipe.objects.create(mission_id=mission, nom=nom)
        for m in membres:
            e.membres.add(Compte.objects.get(pk=m))
        return e

    def sac(self, compte, article="Clé USB", quantite=6):
        return Dotation.objects.create(compte_id=compte, ordre=1, material_id=article,
                                       quantite=quantite)

    def ouvrir(self, nom):
        navigateur = Client()
        self.assertTrue(navigateur.login(identifiant=nom, password=MOT_DE_PASSE))
        return navigateur

    def poster(self, navigateur, action, **params):
        return navigateur.post(reverse("api_action"),
                               data=json.dumps({"action": action, "params": params}),
                               content_type="application/json")


# ============================================================================ rôles

class LesRoles(Base):

    def test_le_role_se_deduit_du_compte(self):
        self.assertEqual(role_de("Admin"), "admin")
        self.assertEqual(role_de("Chef1"), "chef de groupe")
        self.assertEqual(role_de("Eff1"), "effectif")
        self.assertEqual(role_de("Fantôme"), "effectif")

    def test_le_groupe_d_un_chef(self):
        self.assertEqual(groupe_de("Chef1"), {"Eff1", "Eff2"})
        self.assertEqual(groupe_de("Chef2"), {"Eff3"})
        self.assertEqual(groupe_de("Libre"), set())
        self.assertEqual(groupe_de(""), set())

    def test_dans_le_groupe(self):
        self.assertTrue(dans_le_groupe("Chef1", "Eff1"))
        self.assertFalse(dans_le_groupe("Chef1", "Eff3"))
        self.assertFalse(dans_le_groupe("Eff1", "Eff2"))
        self.assertFalse(dans_le_groupe("", "Eff1"))

    def test_supprimer_un_chef_laisse_le_groupe_sans_chef(self):
        self.chef1.delete()
        self.g1.refresh_from_db()
        self.assertIsNone(self.g1.chef_id)
        self.assertEqual(Compte.objects.get(pk="Eff1").membre_de_id, self.g1.pk)
        self.assertEqual(Compte.objects.get(pk="Eff1").chef_id, None)

    def test_supprimer_un_groupe_laisse_ses_membres_sans_groupe(self):
        self.g1.delete()
        self.assertIsNone(Compte.objects.get(pk="Eff1").membre_de_id)
        self.assertEqual(role_de("Chef1"), "effectif")

    def test_le_chef_d_un_groupe_sans_chef_n_existe_pas(self):
        Groupe.objects.filter(pk=self.g1.pk).update(chef=None)
        self.assertEqual(role_de("Chef1"), "effectif")
        self.assertEqual(groupe_de("Chef1"), set())
        self.assertEqual(sorted(membres_du_groupe("Eff1")), ["Chef1", "Eff1", "Eff2"])


class AdministrerLesGroupes(Base):

    def groupe(self, nom):
        return Groupe.objects.get(nom=nom)

    def test_reserve_aux_administrateurs(self):
        for action, params in (("groupe.creer", {"nom": "X"}),
                               ("groupe.modifier", {"groupe": 1, "nom": "X"}),
                               ("groupe.supprimer", {"groupe": 1}),
                               ("groupe.membre", {"compte": "Libre", "groupe": 1})):
            for qui in ("Chef1", "Eff1", "Gest"):
                self.assertIn("réservée aux administrateurs",
                              self.refus(action, qui, **params), (action, qui))
        self.assertFalse(Groupe.objects.filter(nom="X").exists())

    # ---- créer
    def test_creer_un_groupe_vide_et_sans_chef(self):
        self.agir("groupe.creer", "Admin", nom="Nouveau")
        g = self.groupe("Nouveau")
        self.assertIsNone(g.chef_id)
        self.assertEqual(g.membres.count(), 0)

    def test_creer_avec_membres_chef_et_materiel(self):
        self.agir("groupe.creer", "Admin", nom="Équipe A", materiel="2",
                  membres=["Libre"], chef="Gest")
        g = self.groupe("Équipe A")
        self.assertEqual(g.chef_id, "Gest")
        self.assertEqual(sorted(g.membres.values_list("identifiant", flat=True)), ["Gest", "Libre"])
        self.assertEqual(g.affectation, "Groupe 2")
        self.assertEqual(role_de("Gest"), "chef de groupe")

    def test_le_nom_est_unique(self):
        self.assertIn("s'appelle déjà", self.refus("groupe.creer", "Admin", nom="g1"))

    def test_un_nom_est_obligatoire(self):
        self.refus("groupe.creer", "Admin", nom="  ")

    def test_materiel_inconnu(self):
        self.assertIn("Matériel inconnu", self.refus("groupe.creer", "Admin", nom="X", materiel="9"))

    def test_un_refus_ne_laisse_pas_de_groupe_a_moitie_fait(self):
        self.refus("groupe.creer", "Admin", nom="X", membres=["Libre", "Eff1"])   # Eff1 est pris
        self.assertFalse(Groupe.objects.filter(nom="X").exists())
        self.assertIsNone(Compte.objects.get(pk="Libre").membre_de_id)

    def test_un_administrateur_n_a_pas_de_groupe(self):
        self.assertIn("administrateur", self.refus("groupe.creer", "Admin", nom="X", membres=["Admin"]))

    def test_un_compte_desactive_n_entre_pas(self):
        Compte.objects.filter(pk="Libre").update(actif=False)
        self.assertIn("désactivé", self.refus("groupe.creer", "Admin", nom="X", membres=["Libre"]))

    def test_un_chef_dirige_un_seul_groupe(self):
        self.assertIn("déjà membre", self.refus("groupe.creer", "Admin", nom="X", chef="Chef1"))

    # ---- modifier
    def test_renommer(self):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, nom="Alpha")
        self.assertEqual(Groupe.objects.get(pk=self.g1.pk).nom, "Alpha")

    def test_renommer_en_un_nom_pris(self):
        self.assertIn("s'appelle déjà", self.refus("groupe.modifier", "Admin", groupe=self.g1.pk, nom="G2"))

    def test_garder_son_propre_nom_n_est_pas_un_conflit(self):
        resume, _ = self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, nom="G1")
        self.assertIn("rien à changer", resume)

    def test_affecter_le_materiel(self):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, materiel="3")
        self.assertEqual(Groupe.objects.get(pk=self.g1.pk).affectation, "Groupe 3")
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, materiel="")
        self.assertEqual(Groupe.objects.get(pk=self.g1.pk).affectation, "")

    def test_nommer_un_chef_parmi_les_membres(self):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, chef="Eff1")
        self.assertEqual(Groupe.objects.get(pk=self.g1.pk).chef_id, "Eff1")
        self.assertEqual(role_de("Chef1"), "effectif")          # l'ancien chef reste membre
        self.assertEqual(role_de("Eff1"), "chef de groupe")

    def test_nommer_un_chef_libre_l_ajoute_au_groupe(self):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, chef="Libre")
        self.assertEqual(Compte.objects.get(pk="Libre").membre_de_id, self.g1.pk)

    def test_retirer_le_chef_le_laisse_membre(self):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, chef="")
        self.assertIsNone(Groupe.objects.get(pk=self.g1.pk).chef_id)
        self.assertEqual(Compte.objects.get(pk="Chef1").membre_de_id, self.g1.pk)

    def test_un_membre_d_un_autre_groupe_ne_devient_pas_chef_ici(self):
        self.assertIn("est membre du groupe", self.refus(
            "groupe.modifier", "Admin", groupe=self.g1.pk, chef="Eff3"))

    def test_un_chef_ne_dirige_pas_deux_groupes(self):
        Groupe.objects.filter(pk=self.g1.pk).update(chef=None)
        self.assertIn("dirige déjà", self.refus(
            "groupe.modifier", "Admin", groupe=self.g1.pk, chef="Chef2"))

    def test_groupe_inconnu(self):
        self.assertIn("n'existe pas", self.refus("groupe.modifier", "Admin", groupe=999, nom="X"))
        self.assertIn("n'existe pas", self.refus("groupe.modifier", "Admin", groupe="abc", nom="X"))

    # ---- supprimer
    def test_supprimer_un_groupe(self):
        resume, _ = self.agir("groupe.supprimer", "Admin", groupe=self.g1.pk)
        self.assertIn("3 membres sans groupe", resume)
        self.assertFalse(Groupe.objects.filter(pk=self.g1.pk).exists())
        self.assertTrue(Compte.objects.filter(pk="Eff1").exists())

    # ---- membres
    def test_ajouter_un_membre(self):
        self.agir("groupe.membre", "Admin", compte="Libre", groupe=self.g1.pk)
        self.assertEqual(groupe_de("Chef1"), {"Eff1", "Eff2", "Libre"})

    def test_changer_un_membre_de_groupe(self):
        self.agir("groupe.membre", "Admin", compte="Eff1", groupe=self.g2.pk)
        self.assertEqual(groupe_de("Chef1"), {"Eff2"})
        self.assertEqual(groupe_de("Chef2"), {"Eff3", "Eff1"})

    def test_retirer_un_membre(self):
        self.agir("groupe.membre", "Admin", compte="Eff1", groupe="")
        self.assertEqual(groupe_de("Chef1"), {"Eff2"})
        self.assertIsNone(Compte.objects.get(pk="Eff1").membre_de_id)

    def test_retirer_ou_deplacer_un_chef_lui_retire_la_direction(self):
        self.agir("groupe.membre", "Admin", compte="Chef1", groupe="")
        self.assertIsNone(Groupe.objects.get(pk=self.g1.pk).chef_id)
        self.agir("groupe.membre", "Admin", compte="Chef2", groupe=self.g1.pk)
        self.assertIsNone(Groupe.objects.get(pk=self.g2.pk).chef_id)
        self.assertEqual(role_de("Chef2"), "effectif")

    def test_deja_dans_le_groupe_ou_sans_groupe(self):
        self.assertIn("déjà dans", self.agir("groupe.membre", "Admin", compte="Eff1", groupe=self.g1.pk)[0])
        self.assertIn("n'avait pas de groupe", self.agir("groupe.membre", "Admin", compte="Libre", groupe="")[0])

    def test_un_administrateur_ne_rejoint_pas_un_groupe(self):
        self.assertIn("administrateur", self.refus("groupe.membre", "Admin", compte="Admin", groupe=self.g1.pk))

    def test_compte_inconnu(self):
        self.assertIn("n'existe pas", self.refus("groupe.membre", "Admin", compte="Fantôme", groupe=self.g1.pk))

    def test_c_est_inscrit_au_registre_des_comptes(self):
        self.agir("groupe.creer", "Admin", nom="Nouveau")
        self.agir("groupe.membre", "Admin", compte="Libre", groupe=self.groupe("Nouveau").pk)
        self.assertTrue(ActiviteCompte.objects.filter(acteur="Admin", action="groupe créé").exists())
        self.assertTrue(ActiviteCompte.objects.filter(
            acteur="Admin", action="groupe : membre ajouté", nouveau_nom="Libre").exists())

    def test_un_groupe_sans_chef_n_ouvre_aucun_droit_de_chef(self):
        """Sans chef, personne ne répond à la place d'un absent : seuls les admins gèrent."""
        Groupe.objects.filter(pk=self.g1.pk).update(chef=None)
        self.sac("Eff1")
        self.refus("compte.dotations", "Eff2", compte="Eff1", materiel=[])
        self.refus("compte.dotations", "Chef1", compte="Eff1", materiel=[])


# ================================================================== créer une mission

class CreerUneMission(Base):

    def creer(self, qui, nom="Autre"):
        return self.agir("mission.creer", qui, nom=nom)

    def test_un_effectif_ne_cree_pas_de_mission(self):
        for qui in ("Eff1", "Libre", "Gest"):
            self.assertIn("réservé aux chefs de groupe et aux administrateurs",
                          self.refus("mission.creer", qui, nom="Autre"))
        self.assertFalse(Mission.objects.filter(pk="Autre").exists())

    def test_un_chef_de_groupe_cree_une_mission(self):
        self.creer("Chef2")
        self.assertEqual(Mission.objects.get(pk="Autre").owner, "Chef2")

    def test_un_administrateur_cree_une_mission(self):
        self.creer("Admin")
        self.assertTrue(Mission.objects.filter(pk="Autre").exists())

    def test_un_chef_cree_pour_d_autres_gestionnaires_sans_l_etre(self):
        from stock.services.gestion import gestionnaires_de
        self.assertEqual(gestionnaires_de("Chantier"), ["Gest"])

    def test_par_l_api(self):
        self.assertEqual(self.poster(self.ouvrir("Eff1"), "mission.creer",
                                     nom="Autre").status_code, 422)
        self.assertEqual(self.poster(self.ouvrir("Chef1"), "mission.creer",
                                     nom="Autre").status_code, 200)

    def test_le_client_ne_peut_pas_se_dire_chef_ni_administrateur(self):
        reponse = self.poster(self.ouvrir("Eff1"), "mission.creer", nom="Autre",
                              _administrateur=True, _acteur="Chef1")
        self.assertEqual(reponse.status_code, 422)
        self.assertFalse(Mission.objects.filter(pk="Autre").exists())


# ========================================================== date, archivage, statut

class GererUneMission(Base):

    def test_la_date_exige_la_gestion(self):
        for qui in ("Eff1", "Chef1", "Chef2", "Libre"):
            self.assertIn("aux gestionnaires de la mission", self.refus(
                "mission.date", qui, nom="Chantier", date="2099-01-01"))
        self.agir("mission.date", "Gest", nom="Chantier", date="2099-01-01")
        self.agir("mission.date", "Admin", nom="Chantier", date="2099-02-01")

    def test_l_archivage_exige_la_gestion(self):
        self.refus("mission.archiver", "Chef1", nom="Chantier", archive=True)
        self.agir("mission.archiver", "Gest", nom="Chantier", archive=True)
        self.assertTrue(Mission.objects.get(pk="Chantier").archived)

    def test_le_statut_exige_la_gestion(self):
        self.refus("mission.statut", "Chef1", nom="Chantier", statut="EN COURS")
        self.agir("mission.statut", "Gest", nom="Chantier", statut="EN COURS")

    def test_la_suppression_reste_aux_administrateurs(self):
        self.assertIn("réservée aux administrateurs", self.refus(
            "mission.supprimer", "Gest", nom="Chantier"))

    def test_un_chef_de_groupe_n_est_pas_gestionnaire_d_office(self):
        self.refus("mission.gestion", "Chef1", mission="Chantier", gestionnaires=["Chef1"])


# ====================================================================== équipes

class ComposerLesEquipes(Base):

    def setUp(self):
        super().setUp()
        self.equipe(membres=[])

    def membres(self, qui, membres):
        return self.agir("mission.equipe.membres", qui, mission="Chantier", nom="Nord",
                         membres=membres)

    def test_le_gestionnaire_compose_comme_il_l_entend(self):
        self.membres("Gest", ["Eff1", "Eff3", "Libre"])
        self.assertEqual(set(Equipe.objects.get().membres.values_list("identifiant", flat=True)),
                         {"Eff1", "Eff3", "Libre"})

    def test_un_chef_place_ses_effectifs(self):
        self.membres("Chef1", ["Eff1", "Eff2"])
        self.assertEqual(set(Equipe.objects.get().membres.values_list("identifiant", flat=True)),
                         {"Eff1", "Eff2"})

    def test_un_chef_ne_place_pas_les_effectifs_d_un_autre(self):
        message = self.refus("mission.equipe.membres", "Chef1", mission="Chantier",
                             nom="Nord", membres=["Eff1", "Eff3"])
        self.assertIn("Eff3", message)
        self.assertIn("ne place dans une équipe que ses propres effectifs", message)
        self.assertEqual(Equipe.objects.get().membres.count(), 0)

    def test_un_chef_ne_se_place_pas_lui_meme_ni_un_libre(self):
        self.refus("mission.equipe.membres", "Chef1", mission="Chantier", nom="Nord",
                   membres=["Chef1"])
        self.refus("mission.equipe.membres", "Chef1", mission="Chantier", nom="Nord",
                   membres=["Libre"])

    def test_un_chef_retire_aussi_ses_effectifs(self):
        self.membres("Gest", ["Eff1", "Eff3"])
        self.membres("Chef1", ["Eff3"])             # retire Eff1, laisse Eff3 (pas à lui)
        self.assertEqual(set(Equipe.objects.get().membres.values_list("identifiant", flat=True)),
                         {"Eff3"})

    def test_un_chef_ne_retire_pas_l_effectif_d_un_autre(self):
        self.membres("Gest", ["Eff1", "Eff3"])
        self.refus("mission.equipe.membres", "Chef1", mission="Chantier", nom="Nord",
                   membres=["Eff1"])

    def test_un_effectif_ne_compose_pas(self):
        self.assertIn("aux gestionnaires de la mission", self.refus(
            "mission.equipe.membres", "Eff1", mission="Chantier", nom="Nord", membres=["Eff1"]))

    def test_un_chef_ne_cree_ni_ne_renomme_ni_ne_supprime_une_equipe(self):
        for action, params in (("mission.equipe.creer", {"nom": "Est"}),
                               ("mission.equipe.renommer", {"nom": "Nord", "nouveauNom": "Ouest"}),
                               ("mission.equipe.supprimer", {"nom": "Nord"})):
            self.assertIn("aux gestionnaires de la mission",
                          self.refus(action, "Chef1", mission="Chantier", **params))

    def test_un_gestionnaire_peut_etre_place_dans_une_equipe(self):
        self.agir("mission.equipe.membres", "Admin", mission="Chantier", nom="Nord",
                  membres=["Gest"])
        self.assertIn("Gest", {m for e in Equipe.objects.filter(mission_id="Chantier")
                               for m in e.membres.values_list("identifiant", flat=True)})


# ======================================================================== emprunts

class EmprunterPourUneMission(Base):

    def emprunter(self, qui, **plus):
        return self.agir("materiel.emprunt", qui, nom="Perceuse", qty=1,
                         mission="Chantier", **plus)

    def test_sans_mission_c_est_libre(self):
        for qui in ("Eff1", "Libre", "Chef1", "Gest"):
            self.agir("materiel.emprunt", qui, nom="Perceuse", qty=1)
        self.assertEqual(MaterialReservation.objects.count(), 4)

    def test_un_effectif_etranger_a_la_mission_est_refuse(self):
        for qui in ("Eff1", "Libre"):
            self.assertIn("On n'emprunte pour la mission", self.refus(
                "materiel.emprunt", qui, nom="Perceuse", qty=1, mission="Chantier"))
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_un_equipier_peut_emprunter_pour_sa_mission(self):
        self.equipe(membres=["Eff1"])
        self.emprunter("Eff1")
        self.assertEqual(MaterialReservation.objects.get().taken_by, "Eff1")

    def test_le_gestionnaire_et_l_administrateur_le_peuvent(self):
        self.emprunter("Gest")
        self.emprunter("Admin")
        self.assertEqual(MaterialReservation.objects.count(), 2)

    def test_un_chef_dont_un_effectif_est_equipier_le_peut(self):
        self.equipe(membres=["Eff2"])
        self.emprunter("Chef1")
        self.assertEqual(MaterialReservation.objects.get().taken_by, "Chef1")

    def test_un_chef_sans_lien_avec_la_mission_ne_le_peut_pas(self):
        self.equipe(membres=["Eff2"])                  # un effectif de Chef1, pas de Chef2
        self.refus("materiel.emprunt", "Chef2", nom="Perceuse", qty=1, mission="Chantier")

    def test_le_message_nomme_les_gestionnaires(self):
        self.assertIn("Gest", self.refus("materiel.emprunt", "Eff1", nom="Perceuse",
                                         qty=1, mission="Chantier"))

    def test_le_panier_suit_la_meme_regle(self):
        self.refus("materiel.emprunt.groupe", "Eff1", mission="Chantier",
                   lignes=[{"nom": "Perceuse", "qty": 1}])
        self.equipe(membres=["Eff1"])
        self.agir("materiel.emprunt.groupe", "Eff1", mission="Chantier",
                  lignes=[{"nom": "Perceuse", "qty": 1}])
        self.assertEqual(MaterialReservation.objects.count(), 1)

    def test_par_l_api(self):
        self.assertEqual(self.poster(self.ouvrir("Eff1"), "materiel.emprunt", nom="Perceuse",
                                     qty=1, mission="Chantier").status_code, 422)
        self.assertEqual(self.poster(self.ouvrir("Gest"), "materiel.emprunt", nom="Perceuse",
                                     qty=1, mission="Chantier").status_code, 200)


# ==================================================================== rendre

class RendreEtRestituer(Base):

    def setUp(self):
        super().setUp()
        self.equipe(membres=["Eff1"])
        self.agir("materiel.emprunt", "Eff1", nom="Perceuse", qty=2, mission="Chantier")

    def retour(self, qui):
        return self.agir("materiel.emprunt.retour", qui, nom="Perceuse", index=0)

    def test_l_emprunteur_rend_sa_ligne(self):
        self.retour("Eff1")
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_le_gestionnaire_de_la_mission_peut_la_rendre(self):
        self.retour("Gest")
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_le_chef_de_l_emprunteur_peut_la_rendre(self):
        self.retour("Chef1")
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_un_administrateur_peut_la_rendre(self):
        self.retour("Admin")

    def test_un_autre_effectif_ne_le_peut_pas(self):
        for qui in ("Eff2", "Libre", "Chef2", "Eff3"):
            self.assertIn("Seul l'emprunteur (Eff1)", self.refus(
                "materiel.emprunt.retour", qui, nom="Perceuse", index=0))
        self.assertEqual(MaterialReservation.objects.count(), 1)

    def test_le_preteur_peut_reprendre_son_materiel(self):
        MaterialReservation.objects.all().delete()
        self.sac("Eff2", "Perceuse", 3)
        self.agir("pret.forcer", "Gest", mission="Chantier", proprietaire="Eff2",
                  article="Perceuse", qty=1)
        self.agir("materiel.emprunt.retour", "Eff2", nom="Perceuse", index=0)
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_restituer_toute_la_mission_est_reserve_a_la_gestion(self):
        for qui in ("Eff1", "Chef1", "Libre"):
            self.assertIn("aux gestionnaires de la mission", self.refus(
                "materiel.mission.restituer", qui, mission="Chantier"))
        self.agir("materiel.mission.restituer", "Gest", mission="Chantier")
        self.assertTrue(all(not r.ouvert for r in MaterialReservation.objects.all()))

    def test_restituer_une_ligne_suit_la_regle_du_retour(self):
        self.refus("materiel.mission.restituer_ligne", "Eff2", nom="Perceuse", index=0)
        self.agir("materiel.mission.restituer_ligne", "Eff1", nom="Perceuse", index=0)

    def test_repartir_le_materiel_entre_equipes_est_reserve_a_la_gestion(self):
        for qui in ("Eff1", "Chef1"):
            self.assertIn("aux gestionnaires de la mission", self.refus(
                "materiel.equipe.affecter", qui, nom="Perceuse", index=0, equipe="Nord"))
        self.agir("materiel.equipe.affecter", "Gest", nom="Perceuse", index=0, equipe="Nord")

    def test_desassigner_est_reserve_a_la_gestion(self):
        Mission.objects.filter(pk="Chantier").update(planned_date="2099-01-01")
        self.refus("materiel.mission.desassigner", "Eff1", nom="Perceuse", index=0)
        self.refus("materiel.mission.desassigner", "Chef1", nom="Perceuse", index=0)
        self.agir("materiel.mission.desassigner", "Gest", nom="Perceuse", index=0)


# ====================================================================== prêts

class PretsEtChefDeGroupe(Base):
    """Eff1 (groupe de Chef1) a un sac ; Libre lui demande de la Clé USB."""

    def setUp(self):
        super().setUp()
        self.sac("Eff1")

    def demander(self, qty=2, **plus):
        self.agir("pret.demander", "Libre", proprietaire="Eff1", article="Clé USB",
                  qty=qty, **plus)
        return DemandePret.objects.latest("pk")

    # -- répondre à la place d'un absent ----------------------------------

    def test_le_chef_accepte_a_la_place_d_un_effectif_absent(self):
        d = self.demander()
        self.agir("pret.accepter", "Chef1", id=d.pk)
        r = MaterialReservation.objects.get()
        self.assertEqual((r.sac_de, r.taken_by, r.qty), ("Eff1", "Libre", 2))
        self.assertEqual(DemandePret.objects.get().statut, DemandePret.ACCEPTEE)

    def test_le_pret_porte_le_nom_du_sac_et_non_de_celui_qui_a_accepte(self):
        d = self.demander()
        self.agir("pret.accepter", "Chef1", id=d.pk)
        self.assertEqual(etat_prets("Eff1")["prets"][0]["a"], "Libre")
        self.assertEqual(etat_prets("Chef1")["prets"], [])

    def test_le_journal_dit_qui_a_accepte(self):
        d = self.demander()
        self.agir("pret.accepter", "Chef1", id=d.pk)
        note = MaterialLog.objects.get(kind="SORTIE").commentaire
        self.assertIn("Prêté par Eff1", note)
        self.assertIn("accepté par Chef1", note)

    def test_le_proprietaire_accepte_lui_meme(self):
        d = self.demander()
        self.agir("pret.accepter", "Eff1", id=d.pk)
        self.assertNotIn("accepté par", MaterialLog.objects.get(kind="SORTIE").commentaire)

    def test_le_chef_refuse_aussi_avec_une_raison(self):
        d = self.demander()
        self.agir("pret.refuser", "Chef1", id=d.pk, raison="Il est en congé")
        refusee = DemandePret.objects.get()
        self.assertEqual((refusee.statut, refusee.raison_refus),
                         (DemandePret.REFUSEE, "Il est en congé"))

    def test_un_administrateur_repond_aussi(self):
        d = self.demander()
        self.agir("pret.accepter", "Admin", id=d.pk)
        self.assertEqual(MaterialReservation.objects.get().sac_de, "Eff1")

    def test_le_chef_d_un_autre_groupe_ne_repond_pas(self):
        d = self.demander()
        for qui in ("Chef2", "Eff2", "Eff3", "Gest"):
            self.assertIn("ne vous est pas adressée", self.refus("pret.accepter", qui, id=d.pk))
            self.refus("pret.refuser", qui, id=d.pk)
        self.assertEqual(DemandePret.objects.get().statut, DemandePret.EN_ATTENTE)

    def test_un_effectif_sans_chef_n_a_que_lui_pour_repondre(self):
        self.sac("Libre", "Perceuse", 1)
        self.agir("pret.demander", "Eff2", proprietaire="Libre", article="Perceuse", qty=1)
        d = DemandePret.objects.latest("pk")
        self.refus("pret.accepter", "Chef1", id=d.pk)
        self.agir("pret.accepter", "Libre", id=d.pk)

    def test_l_acceptation_par_le_chef_reverifie_le_sac_de_l_effectif(self):
        d = self.demander(qty=5)
        self.agir("pret.demander", "Eff2", proprietaire="Eff1", article="Clé USB", qty=5)
        autre = DemandePret.objects.latest("pk")
        self.agir("pret.accepter", "Chef1", id=d.pk)
        self.assertIn("ne reste que 1", self.refus("pret.accepter", "Chef1", id=autre.pk))

    def test_le_chef_constate_le_retour_pour_son_effectif(self):
        d = self.demander()
        self.agir("pret.accepter", "Eff1", id=d.pk)
        pret = etat_prets("Eff1")["prets"][0]
        self.agir("pret.rendu", "Chef1", id=pret["id"])
        self.assertEqual(MaterialReservation.objects.count(), 0)
        self.agir("pret.demander", "Libre", proprietaire="Eff1", article="Clé USB", qty=1)
        self.agir("pret.accepter", "Eff1", id=DemandePret.objects.latest("pk").pk)
        self.refus("pret.rendu", "Chef2", id=etat_prets("Eff1")["prets"][0]["id"])

    # -- ce que voit le chef ------------------------------------------------

    def test_le_chef_voit_les_demandes_de_son_groupe(self):
        self.demander()
        groupe = etat_prets("Chef1")["recuesGroupe"]
        self.assertEqual(len(groupe), 1)
        self.assertEqual((groupe[0]["pour"], groupe[0]["de"], groupe[0]["libelle"],
                          groupe[0]["quantite"]), ("Eff1", "Libre", "Clé USB", 2))
        self.assertEqual(len(etat_prets("Eff1")["recues"]), 1)

    def test_les_autres_ne_voient_pas_les_demandes_d_un_groupe(self):
        self.demander()
        for qui in ("Chef2", "Eff2", "Libre", "Admin", "Gest"):
            self.assertEqual(etat_prets(qui)["recuesGroupe"], [], qui)

    def test_une_demande_repondue_quitte_la_liste_du_chef(self):
        d = self.demander()
        self.agir("pret.refuser", "Eff1", id=d.pk)
        self.assertEqual(etat_prets("Chef1")["recuesGroupe"], [])

    # -- forcer ------------------------------------------------------------

    def test_un_chef_force_dans_le_sac_d_un_effectif_de_son_groupe(self):
        self.agir("pret.forcer", "Chef1", mission="Chantier", proprietaire="Eff1",
                  article="Clé USB", qty=2)
        r = MaterialReservation.objects.get()
        self.assertEqual((r.sac_de, r.force_par, r.taken_by), ("Eff1", "Chef1", "Chef1"))

    def test_un_chef_ne_force_pas_hors_de_son_groupe(self):
        self.sac("Eff3", "Perceuse", 1)
        self.assertIn("aux gestionnaires de la mission", self.refus(
            "pret.forcer", "Chef1", mission="Chantier", proprietaire="Eff3",
            article="Perceuse", qty=1))

    def test_un_effectif_ne_force_pas(self):
        self.refus("pret.forcer", "Eff2", mission="Chantier", proprietaire="Eff1",
                   article="Clé USB", qty=1)

    def test_le_gestionnaire_force_partout(self):
        self.agir("pret.forcer", "Gest", mission="Chantier", proprietaire="Eff1",
                  article="Clé USB", qty=1)

    def test_demander_reste_ouvert_a_tous(self):
        for qui in ("Eff2", "Eff3", "Chef2", "Gest", "Admin"):
            self.agir("pret.demander", qui, proprietaire="Eff1", article="Clé USB", qty=1)
        self.assertEqual(DemandePret.objects.count(), 5)


# ====================================================================== sacs

class SacsEtGroupe(Base):

    def setUp(self):
        super().setUp()
        self.sac("Eff1")

    def test_un_chef_compose_le_sac_de_ses_effectifs(self):
        self.agir("compte.dotations", "Chef1", compte="Eff1",
                  materiel=[["Perceuse", 2, "du groupe"]])
        self.assertEqual(Dotation.objects.get(compte_id="Eff1").material_id, "Perceuse")

    def test_un_chef_ne_compose_pas_le_sac_d_un_autre_groupe(self):
        self.assertIn("réservé aux administrateurs et à son chef de groupe", self.refus(
            "compte.dotations", "Chef2", compte="Eff1", materiel=[]))
        self.refus("compte.dotations", "Chef1", compte="Libre", materiel=[])
        self.refus("compte.dotations", "Chef1", compte="Chef2", materiel=[])

    def test_un_effectif_ne_compose_aucun_sac_pas_meme_le_sien(self):
        self.refus("compte.dotations", "Eff1", compte="Eff1", materiel=[])

    def test_un_administrateur_compose_tous_les_sacs(self):
        self.agir("compte.dotations", "Admin", compte="Libre", materiel=[["Perceuse", 1, ""]])

    def test_le_chef_recoit_les_sacs_de_son_groupe_dans_l_etat(self):
        self.sac("Eff3", "Perceuse", 1)
        self.sac("Chef1", "Perceuse", 1)
        etat = self.ouvrir("Chef1").get(reverse("api_state")).json()["dotations"]
        self.assertEqual(sorted(etat), ["Chef1", "Eff1"])

    def test_un_effectif_recoit_les_sacs_de_son_groupe_et_de_lui_seul(self):
        """Tout le groupe voit tout : le sien et ceux de ses pairs et de son chef."""
        self.sac("Eff3", "Perceuse", 1)       # un autre groupe
        self.sac("Chef1", "Perceuse", 1)
        etat = self.ouvrir("Eff2").get(reverse("api_state")).json()["dotations"]
        self.assertEqual(sorted(etat), ["Chef1", "Eff1"])
        self.sac("Eff2", "Perceuse", 1)
        etat = self.ouvrir("Eff2").get(reverse("api_state")).json()["dotations"]
        self.assertEqual(sorted(etat), ["Chef1", "Eff1", "Eff2"])

    def test_un_effectif_sans_groupe_ne_recoit_que_le_sien(self):
        self.sac("Libre", "Perceuse", 1)
        etat = self.ouvrir("Libre").get(reverse("api_state")).json()["dotations"]
        self.assertEqual(sorted(etat), ["Libre"])

    def test_un_administrateur_les_recoit_tous(self):
        self.sac("Eff3", "Perceuse", 1)
        etat = self.ouvrir("Admin").get(reverse("api_state")).json()["dotations"]
        self.assertEqual(sorted(etat), ["Eff1", "Eff3"])


# ============================================================= agir au nom de

class AgirAuNomDe(Base):

    def test_un_chef_agit_au_nom_d_un_effectif_de_son_groupe(self):
        reponse = self.poster(self.ouvrir("Chef1"), "materiel.emprunt", nom="Perceuse",
                              qty=1, auteur="Eff1")
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual(MaterialReservation.objects.get().taken_by, "Eff1")

    def test_un_chef_n_agit_pas_au_nom_d_un_autre_groupe(self):
        for cible in ("Eff3", "Libre", "Chef2", "Admin"):
            reponse = self.poster(self.ouvrir("Chef1"), "materiel.emprunt", nom="Perceuse",
                                  qty=1, auteur=cible)
            self.assertEqual(reponse.status_code, 422, cible)
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_un_effectif_n_agit_qu_en_son_nom(self):
        reponse = self.poster(self.ouvrir("Eff1"), "materiel.emprunt", nom="Perceuse",
                              qty=1, auteur="Eff2")
        self.assertEqual(reponse.status_code, 422)
        self.assertIn("au nom d'un autre", reponse.json()["error"])

    def test_un_administrateur_agit_au_nom_de_n_importe_qui(self):
        reponse = self.poster(self.ouvrir("Admin"), "materiel.emprunt", nom="Perceuse",
                              qty=1, auteur="Eff3")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(MaterialReservation.objects.get().taken_by, "Eff3")

    def test_la_liste_proposee_depend_du_role(self):
        etat = lambda qui: self.ouvrir(qui).get(reverse("api_state")).json()["comptes"]
        self.assertEqual(sorted(etat("Chef1")), ["Eff1", "Eff2"])
        self.assertEqual(etat("Eff1"), [])
        self.assertIn("Chef1", etat("Admin"))

    def test_les_droits_se_jugent_sur_l_acteur_pas_sur_l_auteur(self):
        """Un administrateur qui agit au nom d'un effectif garde ses droits."""
        reponse = self.poster(self.ouvrir("Admin"), "mission.date", nom="Chantier",
                              date="2099-01-01", auteur="Eff1")
        self.assertEqual(reponse.status_code, 200, reponse.content)

    def test_un_chef_qui_agit_au_nom_d_un_effectif_n_en_acquiert_pas_les_droits_de_gestion(self):
        reponse = self.poster(self.ouvrir("Chef1"), "mission.date", nom="Chantier",
                              date="2099-01-01", auteur="Eff1")
        self.assertEqual(reponse.status_code, 422)

    def test_un_chef_garde_son_autorite_en_representant_son_effectif(self):
        """Il force un prêt de son groupe, même en agissant au nom d'un effectif."""
        self.sac("Eff2", "Perceuse", 2)
        reponse = self.poster(self.ouvrir("Chef1"), "pret.forcer", mission="Chantier",
                              proprietaire="Eff2", article="Perceuse", qty=1, auteur="Eff1")
        self.assertEqual(reponse.status_code, 200, reponse.content)
        r = MaterialReservation.objects.get()
        self.assertEqual((r.taken_by, r.force_par), ("Eff1", "Eff1"))

    def test_peut_representer(self):
        self.assertTrue(peut_representer("Eff1", "Chef1", {}))
        self.assertFalse(peut_representer("Eff3", "Chef1", {}))
        self.assertTrue(peut_representer("Eff3", "Admin", {"_administrateur": True}))


# ================================================================ exposition

class ExpositionDesRoles(Base):

    def etat(self, qui):
        return self.ouvrir(qui).get(reverse("api_state")).json()

    def test_chacun_connait_son_role(self):
        groupe = {"id": self.g1.pk, "nom": "G1", "chef": "Chef1",
                  "adjoint": "", "membres": ["Chef1", "Eff1", "Eff2"], "affectation": ""}
        self.assertEqual(self.etat("Eff1")["moi"],
                         {"role": "effectif", "chef": "Chef1", "effectifs": [], "groupe": groupe})
        self.assertEqual(self.etat("Libre")["moi"],
                         {"role": "effectif", "chef": "", "effectifs": [], "groupe": None})
        self.assertEqual(self.etat("Chef1")["moi"],
                         {"role": "chef de groupe", "chef": "",
                          "effectifs": ["Eff1", "Eff2"], "groupe": groupe})
        self.assertEqual(self.etat("Admin")["moi"]["role"], "admin")

    def test_seul_l_administrateur_recoit_tous_les_roles(self):
        self.assertEqual(self.etat("Eff1")["comptesRoles"], {})
        self.assertEqual(self.etat("Chef1")["comptesRoles"], {})
        roles = self.etat("Admin")["comptesRoles"]
        self.assertEqual(roles["Eff1"], {"role": "effectif", "chef": "Chef1", "adjoint": False,
                                         "groupe": self.g1.pk, "actif": True, "visite": None})
        self.assertEqual(roles["Chef2"]["role"], "chef de groupe")

    def test_les_demandes_du_groupe_arrivent_au_chef(self):
        self.sac("Eff1")
        self.agir("pret.demander", "Libre", proprietaire="Eff1", article="Clé USB", qty=1)
        self.assertEqual(len(self.etat("Chef1")["pret"]["recuesGroupe"]), 1)
        self.assertEqual(self.etat("Chef2")["pret"]["recuesGroupe"], [])

    def test_creer_un_groupe_par_l_api(self):
        self.assertEqual(self.poster(self.ouvrir("Chef1"), "groupe.creer", nom="X").status_code, 422)
        self.assertEqual(self.poster(self.ouvrir("Admin"), "groupe.creer", nom="X",
                                     chef="Libre").status_code, 200)
        self.assertEqual(self.etat("Libre")["moi"]["role"], "chef de groupe")

    def test_l_administrateur_recoit_la_liste_des_groupes(self):
        groupes = self.etat("Admin")["groupes"]
        self.assertEqual([g["nom"] for g in groupes], ["G1", "G2"])
        self.assertEqual(groupes[0]["chef"], "Chef1")
        self.assertEqual(groupes[0]["membres"], ["Chef1", "Eff1", "Eff2"])

    def test_un_groupe_vide_et_sans_chef_est_visible_de_l_administrateur(self):
        self.agir("groupe.creer", "Admin", nom="Vide")
        vide = [g for g in self.etat("Admin")["groupes"] if g["nom"] == "Vide"][0]
        self.assertEqual((vide["chef"], vide["membres"]), ("", []))

    def test_les_autres_ne_recoivent_pas_la_liste_des_groupes(self):
        for qui in ("Chef1", "Eff1", "Libre"):
            self.assertEqual(self.etat(qui)["groupes"], [])


class WidgetMonGroupe(Base):
    """Le catalogue du profil connaît « Mon groupe »."""

    def test_la_disposition_peut_contenir_le_widget_groupe(self):
        reponse = self.ouvrir("Chef1").post(
            reverse("api_reglages"),
            data=json.dumps({"reglages": {"profilWidgets": [
                {"id": "groupe", "taille": "s"}, {"id": "sac", "taille": "l"}]}}),
            content_type="application/json")
        self.assertEqual(reponse.status_code, 200, reponse.content)


class MonGroupe(Base):
    """Le groupe tel que ses membres le voient, avec ou sans chef."""

    def etat(self, qui):
        return self.ouvrir(qui).get(reverse("api_state")).json()

    def test_l_affectation_vient_du_groupe(self):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, materiel="2")
        for qui in ("Eff1", "Chef1"):
            self.assertEqual(self.etat(qui)["moi"]["groupe"]["affectation"], "Groupe 2")
        self.assertEqual(self.etat("Eff3")["moi"]["groupe"]["affectation"], "")

    def test_un_groupe_sans_materiel_n_a_pas_d_affectation(self):
        self.assertEqual(self.etat("Eff1")["moi"]["groupe"]["affectation"], "")

    def test_les_membres_sont_le_chef_et_les_effectifs(self):
        self.assertEqual(self.etat("Eff2")["moi"]["groupe"]["membres"], ["Chef1", "Eff1", "Eff2"])

    def test_un_membre_desactive_n_est_plus_dans_le_groupe(self):
        Compte.objects.filter(pk="Eff2").update(actif=False)
        self.assertEqual(self.etat("Eff1")["moi"]["groupe"]["membres"], ["Chef1", "Eff1"])

    def test_un_groupe_sans_chef_se_voit_quand_meme(self):
        Groupe.objects.filter(pk=self.g1.pk).update(chef=None)
        groupe = self.etat("Eff1")["moi"]["groupe"]
        self.assertEqual(groupe["chef"], "")
        self.assertEqual(groupe["membres"], ["Chef1", "Eff1", "Eff2"])
        self.assertEqual(self.etat("Eff1")["moi"]["role"], "effectif")

    def test_les_membres_d_un_groupe_sans_chef_voient_leurs_sacs(self):
        Groupe.objects.filter(pk=self.g1.pk).update(chef=None)
        self.sac("Eff2")
        etat = self.ouvrir("Eff1").get(reverse("api_state")).json()["dotations"]
        self.assertEqual(sorted(etat), ["Eff2"])

    def test_sans_groupe_pas_de_groupe(self):
        self.assertIsNone(self.etat("Libre")["moi"]["groupe"])
        self.assertIsNone(self.etat("Admin")["moi"]["groupe"])


# ============================================================================ adjoint

class UnAdjointAuGroupe(Base):
    """Un groupe a un chef et, s'il le veut, un adjoint aux mêmes droits."""

    def nommer(self, **p):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, **p)

    def test_nommer_un_adjoint_parmi_les_membres(self):
        self.nommer(adjoint="Eff1")
        g = Groupe.objects.get(pk=self.g1.pk)
        self.assertEqual((g.chef_id, g.adjoint_id), ("Chef1", "Eff1"))
        self.assertEqual(role_de("Eff1"), "chef de groupe")     # mêmes droits qu'un chef

    def test_l_adjoint_a_la_main_sur_les_effectifs_pas_sur_le_chef(self):
        self.nommer(adjoint="Eff1")
        self.assertEqual(groupe_de("Eff1"), {"Eff2"})
        self.assertTrue(dans_le_groupe("Eff1", "Eff2"))
        self.assertFalse(dans_le_groupe("Eff1", "Chef1"))
        self.assertTrue(dans_le_groupe("Chef1", "Eff1"))
        self.assertTrue(peut_representer("Eff2", "Eff1", {}))

    def test_l_adjoint_cree_une_mission(self):
        self.nommer(adjoint="Eff1")
        self.agir("mission.creer", "Eff1", nom="Mission adjoint")
        self.assertTrue(Mission.objects.filter(name="Mission adjoint").exists())

    def test_le_chef_et_l_adjoint_sont_deux_personnes(self):
        self.assertIn("déjà le chef", self.refus(
            "groupe.modifier", "Admin", groupe=self.g1.pk, adjoint="Chef1"))
        self.nommer(adjoint="Eff1")
        self.assertIn("adjoint de ce groupe", self.refus(
            "groupe.modifier", "Admin", groupe=self.g1.pk, chef="Eff1"))

    def test_un_adjoint_d_ailleurs_ne_peut_pas_l_etre_ici(self):
        self.assertIn("est membre du groupe", self.refus(
            "groupe.modifier", "Admin", groupe=self.g1.pk, adjoint="Eff3"))

    def test_retirer_l_adjoint_le_laisse_membre(self):
        self.nommer(adjoint="Eff1")
        self.nommer(adjoint="")
        self.assertIsNone(Groupe.objects.get(pk=self.g1.pk).adjoint_id)
        self.assertEqual(role_de("Eff1"), "effectif")
        self.assertEqual(Compte.objects.get(pk="Eff1").membre_de_id, self.g1.pk)

    def test_deplacer_ou_desactiver_l_adjoint_lui_retire_la_fonction(self):
        self.nommer(adjoint="Eff1")
        self.agir("groupe.membre", "Admin", compte="Eff1", groupe=self.g2.pk)
        self.assertIsNone(Groupe.objects.get(pk=self.g1.pk).adjoint_id)
        self.nommer(adjoint="Eff2")
        self.agir("compte.etat", "Admin", compte="Eff2", actif=False)
        self.assertIsNone(Groupe.objects.get(pk=self.g1.pk).adjoint_id)

    def test_creer_un_groupe_avec_chef_et_adjoint(self):
        self.agir("groupe.creer", "Admin", nom="G3", chef="Libre", adjoint="Gest")
        g = Groupe.objects.get(nom="G3")
        self.assertEqual((g.chef_id, g.adjoint_id), ("Libre", "Gest"))
        self.assertIn("deux personnes différentes", self.refus(
            "groupe.creer", "Admin", nom="G4", chef="Eff1", adjoint="Eff1"))

    def test_l_adjoint_est_dans_l_enveloppe(self):
        self.nommer(adjoint="Eff1")
        navigateur = self.ouvrir("Eff1")
        d = navigateur.get(reverse("api_state")).json()
        self.assertEqual(d["moi"]["groupe"]["adjoint"], "Eff1")
        self.assertEqual(d["moi"]["effectifs"], ["Eff2"])


# ============================================================================ créer un compte

class CreerUnCompte(Base):

    def creer(self, **p):
        params = dict(p)
        resume, _ = executer("compte.creer", "Admin", params, True)
        return resume, params

    def test_un_administrateur_cree_un_compte_avec_mot_de_passe_provisoire(self):
        _, params = self.creer(compte="Nouveau")
        c = Compte.objects.get(pk="Nouveau")
        self.assertTrue(c.actif and c.doit_changer and not c.administrateur)
        self.assertEqual(c.role, "effectif")
        provisoire = params.get("_secret")
        self.assertEqual(len(provisoire), 12)
        self.assertTrue(c.check_password(provisoire))
        self.assertTrue(ActiviteCompte.objects.filter(action="compte créé", nouveau_nom="Nouveau").exists())

    def test_le_nouveau_compte_peut_se_connecter_puis_doit_changer_son_mot_de_passe(self):
        _, params = self.creer(compte="Nouveau")
        navigateur = Client()
        self.assertTrue(navigateur.login(identifiant="Nouveau", password=params["_secret"]))
        self.assertTrue(Compte.objects.get(pk="Nouveau").doit_changer)

    def test_creer_dans_un_groupe(self):
        self.creer(compte="Nouveau", groupe=self.g1.pk)
        self.assertEqual(Compte.objects.get(pk="Nouveau").membre_de_id, self.g1.pk)

    def test_groupe_inconnu(self):
        self.refus("compte.creer", "Admin", compte="Nouveau", groupe=999999)
        self.assertFalse(Compte.objects.filter(pk="Nouveau").exists())

    def test_un_identifiant_existant_est_refuse_sans_tenir_compte_de_la_casse(self):
        self.assertIn("existe déjà", self.refus("compte.creer", "Admin", compte="eff1"))

    def test_identifiants_invalides(self):
        for mauvais in ("Jean Dupont", "a/b", "x?y", "  "):
            self.refus("compte.creer", "Admin", compte=mauvais)
        self.assertFalse(Compte.objects.filter(pk="Jean Dupont").exists())

    def test_reserve_aux_administrateurs(self):
        for qui in ("Chef1", "Eff1"):
            with self.assertRaises(ErreurAction) as capture:
                executer("compte.creer", qui, {"compte": "Pirate"}, False)
            self.assertIn("réservée aux administrateurs", str(capture.exception))
        self.assertFalse(Compte.objects.filter(pk="Pirate").exists())

    def test_le_mot_de_passe_n_entre_pas_dans_l_historique(self):
        navigateur = self.ouvrir("Admin")
        reponse = self.poster(navigateur, "compte.creer", compte="Nouveau")
        self.assertEqual(reponse.status_code, 200)
        secret = reponse.json()["secret"]
        from stock.models import Operation
        historique = "".join(str(o.parametres) + o.resume for o in Operation.objects.all())
        self.assertNotIn(secret, historique)
