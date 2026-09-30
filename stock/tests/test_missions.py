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
