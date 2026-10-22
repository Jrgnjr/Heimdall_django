# -*- coding: utf-8 -*-
"""Missions et templates de mission."""

from stock.models import (Material, MaterialReservation, Mission,
                          MissionTemplate, MissionTemplateItem)

from .socle import BaseStock


class Missions(BaseStock):

    def test_creation(self):
        self.agir("mission.creer", nom="Chantier Nord", date="2026-11-03")
        m = Mission.objects.get(pk="Chantier Nord")
        self.assertTrue(m.is_meta)
        self.assertEqual(m.planned_date.isoformat(), "2026-11-03")

    def test_deux_missions_de_meme_nom_refusees(self):
        self.agir("mission.creer", nom="Chantier Nord")
        self.assertIn("existe déjà", self.refus("mission.creer", nom="Chantier Nord"))

    def test_une_date_invalide_est_refusee(self):
        message = self.refus("mission.creer", nom="Chantier", date="03/11/2026")
        self.assertIn("Date invalide", message)

    def test_un_statut_inconnu_est_refuse(self):
        self.agir("mission.creer", nom="Chantier Nord")
        self.assertIn("Statut inconnu", self.refus("mission.statut",
                                                  nom="Chantier Nord",
                                                  statut="PRESQUE"))

    def test_un_statut_materialise_une_mission_implicite(self):
        """Il faut une ligne pour ranger un statut."""
        self.agir("mission.statut", nom="Venue d'un emprunt", statut="EN COURS")
        m = Mission.objects.get(pk="Venue d'un emprunt")
        self.assertFalse(m.is_meta, "elle reste implicite")
        self.assertEqual(m.status_override, "EN COURS")

    def test_archiver_et_desarchiver(self):
        self.agir("mission.creer", nom="Chantier Nord")
        self.agir("mission.archiver", nom="Chantier Nord", archive=True)
        self.assertTrue(Mission.objects.get(pk="Chantier Nord").archived)
        self.agir("mission.archiver", nom="Chantier Nord", archive=False)
        self.assertFalse(Mission.objects.get(pk="Chantier Nord").archived)

    def test_suppression_refusee_si_du_materiel_y_est_rattache(self):
        self.agir("mission.creer", nom="Chantier Nord")
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=1,
                  mission="Chantier Nord")
        message = self.refus("mission.supprimer", nom="Chantier Nord")
        self.assertIn("encore du matériel affecté", message)

    def test_suppression_possible_une_fois_vide(self):
        self.agir("mission.creer", nom="Chantier Nord")
        self.agir("mission.supprimer", nom="Chantier Nord")
        self.assertFalse(Mission.objects.filter(pk="Chantier Nord").exists())

    def test_restitution_ferme_les_lignes(self):
        self.agir("mission.creer", nom="Chantier Nord")
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=4,
                  mission="Chantier Nord")
        self.agir("materiel.mission.restituer", mission="Chantier Nord")
        self.assertFalse(MaterialReservation.objects
                         .filter(mission="Chantier Nord",
                                 returned_by__isnull=True).exists())
        self.assertEqual(self.dispo("Chargeur USB-C 20 W"), 12)

    def test_restituer_sans_rien_dehors_refuse(self):
        self.agir("mission.creer", nom="Chantier Nord")
        self.assertIn("Aucun matériel à restituer",
                      self.refus("materiel.mission.restituer", mission="Chantier Nord"))


class Templates(BaseStock):

    def setUp(self):
        super().setUp()
        # Trois perceuses, pour éprouver les lignes « type » et la désignation.
        for i in range(1, 4):
            Material.objects.create(
                name="Perceuse" if i == 1 else "Perceuse #%d" % i,
                libelle="Perceuse", ordre=10 + i, cat="Outil", qty=1, seuil=0,
                affectation="Commun", etiquette="A-1%d" % i)

    def creer(self, nom="Intervention type", lignes=None):
        return self.agir("mission.template.creer", nom=nom, lignes=lignes or [
            {"genre": "type", "libelle": "Perceuse", "qty": 2}])

    def test_creation_sans_verifier_le_stock(self):
        """Un article emprunté a sa place dans un template."""
        self.agir("materiel.emprunt", nom="Perceuse", qty=1)
        self.creer()
        self.assertEqual(MissionTemplate.objects.count(), 1)

    def test_un_libelle_inconnu_est_refuse(self):
        message = self.refus("mission.template.creer", nom="T", lignes=[
            {"genre": "type", "libelle": "Marteau-piqueur", "qty": 1}])
        self.assertIn("Aucun article ne porte le nom", message)

    def test_un_genre_inconnu_est_refuse(self):
        message = self.refus("mission.template.creer", nom="T", lignes=[
            {"genre": "peut-etre", "libelle": "Perceuse", "qty": 1}])
        self.assertIn("Genre de ligne inconnu", message)

    def test_template_vide_refuse(self):
        self.assertIn("au moins un article",
                      self.refus("mission.template.creer", nom="T", lignes=[]))

    def test_ligne_en_double_refusee(self):
        message = self.refus("mission.template.creer", nom="T", lignes=[
            {"genre": "type", "libelle": "Perceuse", "qty": 1},
            {"genre": "type", "libelle": "perceuse", "qty": 2}])
        self.assertIn("figure deux fois", message)

    def test_emploi_sert_les_exemplaires_dans_l_ordre(self):
        self.creer()
        self.agir("mission.creer", nom="Chantier Nord", template="Intervention type")
        ouverts = MaterialReservation.objects.filter(mission="Chantier Nord")
        self.assertEqual(sorted(r.material_id for r in ouverts),
                         ["Perceuse", "Perceuse #2"])

    def test_un_exemplaire_peut_etre_designe(self):
        self.creer()
        ligne = MissionTemplateItem.objects.get()
        self.agir("mission.creer", nom="Chantier Nord",
                  template="Intervention type",
                  choix={str(ligne.id): {"Perceuse #3": 1}})
        ouverts = MaterialReservation.objects.filter(mission="Chantier Nord")
        self.assertIn("Perceuse #3", [r.material_id for r in ouverts])

    def test_designer_plus_que_demande_refuse(self):
        self.creer()
        ligne = MissionTemplateItem.objects.get()
        message = self.refus("mission.creer", nom="Chantier Nord",
                             template="Intervention type",
                             choix={str(ligne.id): {"Perceuse": 1, "Perceuse #2": 1,
                                                    "Perceuse #3": 1}})
        self.assertIn("qui n'en demande que", message)

    def test_stock_insuffisant_annule_la_mission(self):
        """Mieux vaut pas de mission qu'une mission incomplète."""
        self.creer(lignes=[{"genre": "type", "libelle": "Perceuse", "qty": 3}])
        self.agir("materiel.emprunt", nom="Perceuse", qty=1)
        message = self.refus("mission.creer", nom="Chantier Nord",
                             template="Intervention type")
        self.assertIn("La mission n'a pas été créée", message)
        self.assertFalse(Mission.objects.filter(pk="Chantier Nord").exists())
        self.assertEqual(
            MaterialReservation.objects.filter(mission="Chantier Nord").count(), 0)

    def test_une_ligne_exemplaire_disparue_bloque_l_emploi(self):
        self.creer(lignes=[{"genre": "exemplaire", "id": "Perceuse #3", "qty": 1}])
        Material.objects.filter(pk="Perceuse #3").delete()
        message = self.refus("mission.creer", nom="Chantier Nord",
                             template="Intervention type")
        self.assertIn("n'existe plus", message)

    def test_renommage_garde_la_composition(self):
        self.creer()
        self.agir("mission.template.modifier", nom="Intervention type",
                  nouveauNom="Intervention rapide",
                  lignes=[{"genre": "type", "libelle": "Perceuse", "qty": 1}])
        self.assertFalse(MissionTemplate.objects.filter(pk="Intervention type").exists())
        cible = MissionTemplate.objects.get(pk="Intervention rapide")
        self.assertEqual([(i.kind, i.qty) for i in cible.items.all()], [("type", 1)])

    def test_suppression(self):
        self.creer()
        self.agir("mission.template.supprimer", nom="Intervention type")
        self.assertEqual(MissionTemplate.objects.count(), 0)
        self.assertEqual(MissionTemplateItem.objects.count(), 0)


class TableauDeMission(BaseStock):
    """La page de lien partagé : une fiche en lecture seule, derrière la session."""

    def _url(self, nom):
        from django.urls import reverse
        return reverse("mission_tableau", args=[nom])

    def test_exige_une_session(self):
        self.agir("mission.creer", nom="Chantier Nord")
        reponse = self.client.get(self._url("Chantier Nord"))
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(reponse["Location"].startswith("/connexion/"))

    def test_affiche_la_mission(self):
        self.agir("mission.creer", nom="Chantier Nord")
        self.client.force_login(self.compte)
        reponse = self.client.get(self._url("Chantier Nord"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Chantier Nord")
        self.assertContains(reponse, "PRÉVUE")

    def test_mission_inconnue(self):
        self.client.force_login(self.compte)
        self.assertEqual(self.client.get(self._url("Fantôme")).status_code, 404)

    def test_nom_avec_barre_oblique(self):
        self.agir("mission.creer", nom="Nord/Sud")
        self.client.force_login(self.compte)
        self.assertEqual(self.client.get(self._url("Nord/Sud")).status_code, 200)


class StatutSelonLaDate(BaseStock):
    """Le statut avance seul : la date prévue, puis les emprunts."""

    def setUp(self):
        super().setUp()
        import datetime
        self.jour = datetime.date(2026, 10, 20)
        self.veille = self.jour - datetime.timedelta(days=1)

    def _mission(self, **champs):
        return Mission(name="M", **champs)

    def test_prevue_tant_que_la_date_n_est_pas_arrivee(self):
        m = self._mission(planned_date=self.jour)
        self.assertEqual(m.statut([], self.veille), Mission.PREVUE)

    def test_en_cours_le_jour_venu(self):
        m = self._mission(planned_date=self.jour)
        self.assertEqual(m.statut([], self.jour), Mission.EN_COURS)

    def test_sans_date_elle_reste_prevue(self):
        self.assertEqual(self._mission().statut([], self.jour), Mission.PREVUE)

    def test_du_materiel_reserve_ne_devance_pas_la_date(self):
        class Ligne:
            ouvert = True
        m = self._mission(planned_date=self.jour)
        self.assertEqual(m.statut([Ligne()], self.veille), Mission.PREVUE)
        self.assertEqual(m.statut([Ligne()], self.jour), Mission.EN_COURS)

    def test_tout_rendu_termine_la_mission(self):
        class Ligne:
            ouvert = False
        m = self._mission(planned_date=self.jour)
        self.assertEqual(m.statut([Ligne()], self.jour), Mission.TERMINEE)

    def test_un_statut_impose_l_emporte(self):
        m = self._mission(planned_date=self.jour, status_override=Mission.PREVUE)
        self.assertEqual(m.statut([], self.jour), Mission.PREVUE)


class DesassignerDuMateriel(BaseStock):
    """Désassigner, dans une mission prévue, c'est rendre le matériel."""

    def setUp(self):
        super().setUp()
        import datetime
        # Prévue : sa date est dans le futur. C'est le seul état où l'on peut
        # encore désassigner du matériel.
        self.mission().planned_date = None
        Mission.objects.filter(pk="Chantier Nord").update(
            planned_date=datetime.date.today() + datetime.timedelta(days=10))
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=2,
                  mission="Chantier Nord")

    def lignes(self):
        return MaterialReservation.objects.filter(material_id="Chargeur USB-C 20 W")

    def desassigner(self, **plus):
        return self.agir("materiel.mission.desassigner",
                         nom="Chargeur USB-C 20 W", index=0, **plus)

    def test_le_materiel_est_rendu_au_stock(self):
        sorti = self.dispo("Chargeur USB-C 20 W")
        self.desassigner()
        self.assertEqual(self.dispo("Chargeur USB-C 20 W"), sorti + 2)

    def test_la_ligne_disparait_de_la_mission(self):
        from stock.services.materiel import emprunts_ouverts_de_mission
        self.desassigner()
        self.assertEqual(self.lignes().count(), 0)
        self.assertEqual(emprunts_ouverts_de_mission("Chantier Nord"), [])

    def test_la_mission_videe_reste_prevue_meme_le_jour_de_sa_date(self):
        """Une ligne fermée aurait fait calculer « terminée » une mission vide."""
        from stock.services.statuts import statut_de
        import datetime
        self.desassigner()
        Mission.objects.filter(pk="Chantier Nord").update(
            planned_date=datetime.date.today())
        self.assertEqual(statut_de("Chantier Nord"), "EN COURS")   # pas « terminée »

    def test_c_est_journalise_comme_un_retour(self):
        from stock.models import MaterialLog
        self.desassigner()
        ligne = MaterialLog.objects.filter(kind="RETOUR").last()
        self.assertEqual((ligne.mission, ligne.qty), ("Chantier Nord", 2))
        self.assertIn("Désassigné", ligne.commentaire)

    def test_une_ligne_sans_mission_est_refusee(self):
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=1)
        self.assertIn("aucune mission", self.refus(
            "materiel.mission.desassigner", nom="Chargeur USB-C 20 W", index=1))

    def test_une_ligne_rendue_est_refusee(self):
        from django.utils import timezone
        MaterialReservation.objects.filter(material_id="Chargeur USB-C 20 W").update(
            returned_by="42", returned_at=timezone.now())
        self.assertIn("déjà rendue", self.refus(
            "materiel.mission.desassigner", nom="Chargeur USB-C 20 W", index=0))

    def test_une_ligne_modifiee_entre_temps_est_refusee(self):
        self.assertIn("modifiée par quelqu'un d'autre", self.refus(
            "materiel.mission.desassigner", nom="Chargeur USB-C 20 W", index=0,
            empreinte="99|Autre|Quelqu'un"))
        self.assertEqual(self.lignes().count(), 1)

    def test_l_empreinte_juste_est_acceptee(self):
        self.desassigner(empreinte="2|Chantier Nord|%s" % self.UTILISATEUR)
        self.assertEqual(self.lignes().count(), 0)

    def test_tout_utilisateur_peut_desassigner(self):
        self.agir("materiel.mission.desassigner", _administrateur=False,
                  nom="Chargeur USB-C 20 W", index=0)
        self.assertEqual(self.lignes().count(), 0)

    def test_un_pret_de_sac_regagne_le_sac(self):
        from comptes.models import Compte, Dotation
        from stock.models import DemandePret
        from stock.services import executer
        from stock.services.prets import etat_prets
        Compte.objects.create_user("Bob", password="x" * 10, doit_changer=False)
        Dotation.objects.create(compte_id="Bob", ordre=1,
                                material_id="Kit outils démontage", quantite=2)
        executer("pret.demander", self.UTILISATEUR, {
            "proprietaire": "Bob", "article": "Kit outils démontage", "qty": 1,
            "mission": "Chantier Nord"}, True)
        executer("pret.accepter", "Bob", {"id": DemandePret.objects.get().pk}, False)
        self.assertEqual(len(etat_prets("Bob")["prets"]), 1)
        index = MaterialReservation.objects.filter(
            material_id="Kit outils démontage").first()
        self.agir("materiel.mission.desassigner", nom="Kit outils démontage", index=0)
        self.assertEqual(etat_prets("Bob")["prets"], [])
        self.assertEqual(etat_prets(self.UTILISATEUR)["sacs"]["Bob"][0]["disponible"], 2)


class EquipesALaCreation(BaseStock):
    """Les équipes se créent avec la mission, vérifiées avant toute écriture."""

    def creer(self, **p):
        return self.agir("mission.creer", nom="Chantier Nord", **p)

    def test_creer_la_mission_avec_ses_equipes_et_leurs_membres(self):
        from comptes.models import Compte
        Compte.objects.create_user("Alice", password="x", doit_changer=False)
        Compte.objects.create_user("Bob", password="x", doit_changer=False)
        self.creer(equipes=[{"nom": "Terrain", "membres": ["Alice", "Bob"]},
                            {"nom": "Base", "membres": []}])
        m = Mission.objects.get(pk="Chantier Nord")
        self.assertEqual([e.nom for e in m.equipes.order_by("ordre")], ["Terrain", "Base"])
        self.assertEqual(sorted(m.equipes.get(nom="Terrain").membres.values_list(
            "identifiant", flat=True)), ["Alice", "Bob"])

    def test_sans_equipe_rien_ne_change(self):
        self.creer()
        self.assertFalse(Mission.objects.get(pk="Chantier Nord").equipes.exists())

    def test_deux_equipes_de_meme_nom(self):
        self.assertIn("existe déjà", self.refus(
            "mission.creer", nom="Chantier Nord",
            equipes=[{"nom": "Terrain"}, {"nom": "terrain"}]))
        self.assertFalse(Mission.objects.filter(pk="Chantier Nord").exists())

    def test_un_gestionnaire_peut_etre_membre_d_une_equipe(self):
        self.creer(gestionnaires=[self.UTILISATEUR],
                   equipes=[{"nom": "Terrain", "membres": [self.UTILISATEUR]}])
        e = Mission.objects.get(pk="Chantier Nord").equipes.get(nom="Terrain")
        self.assertEqual(list(e.membres.values_list("identifiant", flat=True)),
                         [self.UTILISATEUR])

    def test_membre_inconnu_ou_en_double(self):
        self.assertIn("n'existe pas", self.refus(
            "mission.creer", nom="Chantier Nord",
            equipes=[{"nom": "Terrain", "membres": ["Fantôme"]}]))


class RepartitionAuDepart(BaseStock):
    """Chaque ligne du panier peut partir dans son équipe."""

    def setUp(self):
        super().setUp()
        self.agir("mission.creer", nom="Chantier Nord",
                  equipes=[{"nom": "Terrain"}, {"nom": "Base"}])
        self.nom1, self.nom2 = [m.name for m in Material.objects.all()[:2]]

    def equipe_de(self, nom):
        return MaterialReservation.objects.get(material_id=nom, returned_at__isnull=True,
                                               returned_by__isnull=True).equipe

    def test_chaque_ligne_va_dans_son_equipe(self):
        self.agir("materiel.emprunt.groupe", mission="Chantier Nord", packs=[],
                  lignes=[{"nom": self.nom1, "qty": 1, "equipe": "Terrain"},
                          {"nom": self.nom2, "qty": 1, "equipe": "Base"}])
        self.assertEqual((self.equipe_de(self.nom1), self.equipe_de(self.nom2)),
                         ("Terrain", "Base"))

    def test_une_ligne_sans_equipe_reste_au_niveau_de_la_mission(self):
        self.agir("materiel.emprunt.groupe", mission="Chantier Nord", packs=[],
                  lignes=[{"nom": self.nom1, "qty": 1, "equipe": ""}])
        self.assertEqual(self.equipe_de(self.nom1), "")

    def test_l_equipe_du_panier_sert_de_defaut(self):
        self.agir("materiel.emprunt.groupe", mission="Chantier Nord", packs=[],
                  equipe="Base", lignes=[{"nom": self.nom1, "qty": 1}])
        self.assertEqual(self.equipe_de(self.nom1), "Base")

    def test_equipe_inconnue_refusee_sans_rien_enregistrer(self):
        self.refus("materiel.emprunt.groupe", mission="Chantier Nord", packs=[],
                   lignes=[{"nom": self.nom1, "qty": 1, "equipe": "Fantôme"}])
        self.assertFalse(MaterialReservation.objects.exists())
