# -*- coding: utf-8 -*-
"""Matériel : catalogue, emprunts, consommables, exemplaires sériés."""

from stock.models import Material, MaterialReservation

from .socle import BaseStock


class Catalogue(BaseStock):

    def test_creation_d_un_article(self):
        self.agir("materiel.creer", nom="Testeur de batterie", cat="Outil", qty=2)
        m = self.article("Testeur de batterie")
        self.assertEqual((m.cat, m.qty, m.affectation), ("Outil", 2, "Commun"))

    def test_un_article_identique_est_un_reapprovisionnement(self):
        self.agir("materiel.creer", nom="Chargeur USB-C 20 W", cat="Autre", qty=5)
        self.assertEqual(self.article("Chargeur USB-C 20 W").qty, 17)
        self.assertEqual(Material.objects.filter(libelle="Chargeur USB-C 20 W").count(), 1)

    def test_une_etiquette_differente_fait_un_autre_exemplaire(self):
        self.agir("materiel.creer", nom="Chargeur USB-C 20 W", cat="Autre",
                  qty=1, etiquette="Bac B2")
        self.assertEqual(Material.objects.filter(libelle="Chargeur USB-C 20 W").count(), 2)

    def test_les_cles_se_suffixent(self):
        self.agir("materiel.creer", nom="Chargeur USB-C 20 W", qty=1,
                  numeroSerie="X1")
        self.assertTrue(Material.objects.filter(pk="Chargeur USB-C 20 W #2").exists())

    def test_affectation_dans_une_liste_fermee(self):
        message = self.refus("materiel.affectation", nom="Chargeur USB-C 20 W",
                             affectation="Groupe 9")
        self.assertIn("Affectation inconnue", message)

    def test_suppression_refusee_si_emprunte(self):
        self.agir("materiel.emprunt", nom="Kit outils démontage", qty=1)
        message = self.refus("materiel.supprimer", nom="Kit outils démontage")
        self.assertIn("encore emprunté", message)


class Emprunts(BaseStock):

    def test_emprunter_ne_touche_pas_la_quantite(self):
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=4)
        self.assertEqual(self.article("Chargeur USB-C 20 W").qty, 12)
        self.assertEqual(self.dispo("Chargeur USB-C 20 W"), 8)

    def test_emprunt_refuse_au_dela_du_disponible(self):
        self.agir("materiel.emprunt", nom="Kit outils démontage", qty=3)
        message = self.refus("materiel.emprunt", nom="Kit outils démontage", qty=1)
        self.assertIn("Stock insuffisant", message)

    def test_retour_libere_le_disponible(self):
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=4)
        self.agir("materiel.emprunt.retour", nom="Chargeur USB-C 20 W", index=0)
        self.assertEqual(self.dispo("Chargeur USB-C 20 W"), 12)

    def test_emprunt_pour_une_mission_inexistante_refuse(self):
        message = self.refus("materiel.emprunt", nom="Chargeur USB-C 20 W",
                             qty=1, mission="Jamais créée")
        self.assertIn("n'existe pas", message)

    def test_emprunt_groupe_est_tout_ou_rien(self):
        message = self.refus("materiel.emprunt.groupe", lignes=[
            {"nom": "Chargeur USB-C 20 W", "qty": 2},
            {"nom": "Kit outils démontage", "qty": 99}])
        self.assertIn("Aucun emprunt n'a été enregistré", message)
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_emprunt_groupe_sans_selection_refuse(self):
        message = self.refus("materiel.emprunt.groupe", lignes=[], packs=[])
        self.assertIn("Aucun article sélectionné", message)

    def test_la_demande_est_cumulee_sur_un_meme_article(self):
        """Chaque ligne prise isolément passerait ; ensemble, non."""
        message = self.refus("materiel.emprunt.groupe", lignes=[
            {"nom": "Kit outils démontage", "qty": 2},
            {"nom": "Kit outils démontage", "qty": 2}])
        self.assertIn("Stock insuffisant", message)
        self.assertEqual(MaterialReservation.objects.count(), 0)


class Consommables(BaseStock):
    """Ce qui se consomme ne revient pas."""

    def setUp(self):
        super().setUp()
        Material.objects.create(name="Gants nitrile", libelle="Gants nitrile",
                                ordre=10, cat="Consommable", qty=100, seuil=0,
                                affectation="Commun")
        Material.objects.create(name="Collier de serrage",
                                libelle="Collier de serrage", ordre=11,
                                cat="Consommable", qty=50, seuil=0,
                                affectation="Commun")
        self.mission()

    def sortir(self, nom, qty, mission="Chantier Nord"):
        self.agir("materiel.emprunt", nom=nom, qty=qty, mission=mission)

    def test_la_categorie_est_connue_du_modele(self):
        self.assertIn("Consommable", Material.CATEGORIES)

    def test_le_seuil_se_pose_et_se_retire(self):
        self.agir("materiel.seuil", nom="Gants nitrile", seuil=20)
        self.assertEqual(self.article("Gants nitrile").seuil, 20)
        self.agir("materiel.seuil", nom="Gants nitrile", seuil=0)
        self.assertEqual(self.article("Gants nitrile").seuil, 0)

    def test_un_seuil_negatif_refuse(self):
        self.refus("materiel.seuil", nom="Gants nitrile", seuil=-1)

    def test_ce_qui_est_consomme_ne_revient_pas(self):
        self.sortir("Gants nitrile", 10)
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  consommes={"Gants nitrile": 6})
        self.assertEqual(self.article("Gants nitrile").qty, 94)
        self.assertEqual(self.dispo("Gants nitrile"), 94)

    def test_le_journal_porte_les_deux_lignes(self):
        """CONSOMMÉ et RETOUR : une seule mentirait sur ce qui rentre."""
        self.sortir("Gants nitrile", 10)
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  consommes={"Gants nitrile": 6})
        self.assertEqual([(e.item, e.qty, e.mission) for e in self.journal("CONSOMMÉ")],
                         [("Gants nitrile", 6, "Chantier Nord")])
        self.assertEqual([(e.item, e.qty) for e in self.journal("RETOUR")],
                         [("Gants nitrile", 4)])

    def test_tout_consomme_n_inscrit_aucun_retour(self):
        self.sortir("Gants nitrile", 10)
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  consommes={"Gants nitrile": 10})
        self.assertEqual(self.journal("RETOUR"), [])
        self.assertEqual(len(self.journal("CONSOMMÉ")), 1)

    def test_la_ligne_d_emprunt_se_ferme_quand_meme(self):
        self.sortir("Gants nitrile", 10)
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  consommes={"Gants nitrile": 10})
        self.assertFalse(MaterialReservation.objects
                         .filter(mission="Chantier Nord",
                                 returned_by__isnull=True).exists())

    def test_la_consommation_se_repartit_sur_plusieurs_sorties(self):
        self.sortir("Gants nitrile", 6)
        self.sortir("Gants nitrile", 4)
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  consommes={"Gants nitrile": 8})
        self.assertEqual(self.article("Gants nitrile").qty, 92)
        self.assertEqual(sorted(e.qty for e in self.journal("CONSOMMÉ")), [2, 6])

    def test_un_non_consommable_ne_se_declare_pas_utilise(self):
        self.sortir("Kit outils démontage", 2)
        message = self.refus("materiel.mission.restituer", mission="Chantier Nord",
                             consommes={"Kit outils démontage": 1})
        self.assertIn("n'est pas un consommable", message)
        self.assertEqual(self.article("Kit outils démontage").qty, 3)

    def test_consommer_plus_que_sorti_refuse(self):
        self.sortir("Gants nitrile", 10)
        message = self.refus("materiel.mission.restituer", mission="Chantier Nord",
                             consommes={"Gants nitrile": 11})
        self.assertIn("seulement étaient sortis", message)

    def test_consommer_un_article_absent_refuse(self):
        self.sortir("Gants nitrile", 10)
        message = self.refus("materiel.mission.restituer", mission="Chantier Nord",
                             consommes={"Collier de serrage": 1})
        self.assertIn("ne fait pas partie", message)

    def test_une_quantite_nulle_est_ignoree(self):
        self.sortir("Gants nitrile", 10)
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  consommes={"Gants nitrile": 0})
        self.assertEqual(self.article("Gants nitrile").qty, 100)
        self.assertEqual(self.journal("CONSOMMÉ"), [])

    def test_restitution_sans_consommation_se_comporte_comme_avant(self):
        self.sortir("Kit outils démontage", 2)
        self.agir("materiel.mission.restituer", mission="Chantier Nord")
        self.assertEqual(self.article("Kit outils démontage").qty, 3)
        self.assertEqual(self.journal("CONSOMMÉ"), [])


class ExemplairesSeries(BaseStock):
    """Savoir lequel a servi."""

    SERIES = ["CAL-1", "CAL-2", "CAL-3"]

    def lot(self, nom="Cartouche de calibration", series=None):
        return self.agir("materiel.creer.lot", nom=nom, cat="Consommable",
                         series=list(series or self.SERIES))

    def exemplaire(self, serie, libelle="Cartouche de calibration"):
        for m in Material.objects.filter(numero_serie=serie):
            if (m.libelle or m.name).casefold() == libelle.casefold():
                return m
        return None

    def test_un_lot_donne_une_ligne_par_serie(self):
        self.lot()
        lignes = Material.objects.filter(libelle="Cartouche de calibration")
        self.assertEqual(sorted(m.numero_serie for m in lignes), self.SERIES)
        self.assertEqual([m.qty for m in lignes], [1, 1, 1])

    def test_une_serie_repetee_refuse_tout_le_lot(self):
        message = self.refus("materiel.creer.lot", nom="Cartouche",
                             cat="Consommable", series=["A", "B", "A"])
        self.assertIn("deux fois", message)
        self.assertEqual(Material.objects.filter(libelle="Cartouche").count(), 0)

    def test_une_serie_deja_prise_refuse_tout_le_lot(self):
        self.lot(series=["CAL-1"])
        message = self.refus("materiel.creer.lot", nom="Cartouche de calibration",
                             cat="Consommable", series=["CAL-2", "CAL-1"])
        self.assertIn("déjà porté", message)
        self.assertEqual(
            Material.objects.filter(libelle="Cartouche de calibration").count(), 1)

    def test_deux_familles_numerotent_a_partir_de_un(self):
        self.lot(nom="Cartouche de calibration", series=["0001"])
        self.lot(nom="Filtre à air", series=["0001"])
        self.assertIsNotNone(self.exemplaire("0001", "Filtre à air"))

    def test_une_serie_se_corrige(self):
        self.lot(series=["CAL-1"])
        cle = self.exemplaire("CAL-1").name
        self.agir("materiel.identifiants", nom=cle, numeroSerie="CAL-9",
                  etiquette="Bac A3")
        m = self.article(cle)
        self.assertEqual((m.numero_serie, m.etiquette), ("CAL-9", "Bac A3"))

    def test_corriger_vers_une_serie_prise_refuse(self):
        self.lot(series=["CAL-1", "CAL-2"])
        cle = self.exemplaire("CAL-1").name
        message = self.refus("materiel.identifiants", nom=cle, numeroSerie="CAL-2")
        self.assertIn("déjà porté", message)
        self.assertEqual(self.article(cle).numero_serie, "CAL-1")

    def test_reecrire_la_meme_serie_est_accepte(self):
        """Le contrôle de doublon trouverait l'exemplaire lui-même."""
        self.lot(series=["CAL-1"])
        cle = self.exemplaire("CAL-1").name
        self.agir("materiel.identifiants", nom=cle, numeroSerie="CAL-1",
                  etiquette="Bac B1")
        self.assertEqual(self.article(cle).etiquette, "Bac B1")

    def test_corriger_ne_touche_pas_la_cle(self):
        """Les emprunts et les lignes de pack citent la clé."""
        self.lot(series=["CAL-1"])
        cle = self.exemplaire("CAL-1").name
        self.agir("materiel.identifiants", nom=cle, numeroSerie="CAL-9")
        self.assertTrue(Material.objects.filter(pk=cle).exists())

    def test_le_journal_dit_quel_exemplaire_a_ete_consomme(self):
        self.mission()
        self.lot()
        prise = self.exemplaire("CAL-2")
        self.agir("materiel.emprunt", nom=prise.name, qty=1,
                  mission="Chantier Nord")
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  consommes={prise.name: 1})
        self.assertEqual(
            [(e.item, e.identite, e.mission) for e in self.journal("CONSOMMÉ")],
            [("Cartouche de calibration", "série CAL-2", "Chantier Nord")])

    def test_le_journal_garde_l_ancien_numero_apres_correction(self):
        """`identite` est recopiée au mouvement, pas relue à l'affichage."""
        self.mission()
        self.lot(series=["CAL-1"])
        cle = self.exemplaire("CAL-1").name
        self.agir("materiel.emprunt", nom=cle, qty=1, mission="Chantier Nord")
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  consommes={cle: 1})
        self.agir("materiel.identifiants", nom=cle, numeroSerie="CAL-9")
        self.assertEqual(self.journal("CONSOMMÉ")[0].identite, "série CAL-1")
