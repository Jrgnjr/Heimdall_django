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

    def test_le_seuil_d_un_groupe_vaut_pour_tous_ses_exemplaires(self):
        Material.objects.create(name="Cartouche", ordre=20, cat="Consommable",
                                qty=1, seuil=0, affectation="Commun",
                                libelle="Cartouche", numero_serie="A1")
        Material.objects.create(name="Cartouche #2", ordre=21, cat="Consommable",
                                qty=1, seuil=0, affectation="Commun",
                                libelle="Cartouche", numero_serie="A2")
        self.agir("materiel.seuil", libelle="Cartouche", seuil=5)
        self.assertEqual(self.article("Cartouche").seuil, 5)
        self.assertEqual(self.article("Cartouche #2").seuil, 5)

    def test_seuil_d_un_groupe_inconnu_refuse(self):
        self.refus("materiel.seuil", libelle="Fantôme", seuil=5)

    def test_ajuster_le_stock_fixe_la_valeur_et_journalise(self):
        from stock.models import MaterialLog
        avant = self.article("Gants nitrile").qty
        self.agir("materiel.ajuster", nom="Gants nitrile", qty=avant + 7)
        self.assertEqual(self.article("Gants nitrile").qty, avant + 7)
        ligne = MaterialLog.objects.filter(kind="AJUST.").last()
        self.assertEqual(ligne.qty, 7)
        self.assertIn("de %d à %d" % (avant, avant + 7), ligne.commentaire)

    def test_ajuster_sous_ce_qui_est_sorti_refuse(self):
        self.sortir("Gants nitrile", 5)
        message = self.refus("materiel.ajuster", nom="Gants nitrile", qty=4)
        self.assertIn("sorties", message)
        self.agir("materiel.ajuster", nom="Gants nitrile", qty=5)

    def test_ajuster_negatif_refuse(self):
        self.refus("materiel.ajuster", nom="Gants nitrile", qty=-1)

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


class LicenceDesDongles(BaseStock):
    """La fin de licence se saisit à l'entrée d'un dongle."""

    def test_creer_un_dongle_avec_sa_licence(self):
        self.agir("materiel.creer", nom="Dongle CAO", cat="Dongle", qty=1,
                  numeroSerie="D-1", licence="2027-03-12")
        self.assertEqual(self.article("Dongle CAO").licence_fin.isoformat(), "2027-03-12")

    def test_la_licence_est_facultative(self):
        self.agir("materiel.creer", nom="Dongle CAO", cat="Dongle", qty=1)
        self.assertIsNone(self.article("Dongle CAO").licence_fin)

    def test_hors_dongle_la_date_est_ignoree(self):
        self.agir("materiel.creer", nom="Perceuse bis", cat="Outil", qty=1,
                  licence="2027-03-12")
        self.assertIsNone(self.article("Perceuse bis").licence_fin)

    def test_recevoir_un_dongle_renouvele_sa_licence(self):
        self.agir("materiel.creer", nom="Dongle CAO", cat="Dongle", qty=1,
                  licence="2026-12-31")
        self.agir("materiel.reception", nom="Dongle CAO", qty=1, licence="2028-01-15")
        m = self.article("Dongle CAO")
        self.assertEqual((m.qty, m.licence_fin.isoformat()), (2, "2028-01-15"))

    def test_une_reception_sans_date_garde_la_licence(self):
        self.agir("materiel.creer", nom="Dongle CAO", cat="Dongle", qty=1,
                  licence="2026-12-31")
        self.agir("materiel.reception", nom="Dongle CAO", qty=1)
        self.assertEqual(self.article("Dongle CAO").licence_fin.isoformat(), "2026-12-31")

    def test_un_lot_de_dongles_partage_la_licence(self):
        self.agir("materiel.creer.lot", nom="Dongle CAO", cat="Dongle",
                  series=["A", "B"], licence="2027-06-01")
        self.assertEqual(Material.objects.filter(
            libelle="Dongle CAO", licence_fin__isnull=False).count(), 2)

    def test_date_invalide(self):
        self.refus("materiel.creer", nom="Dongle CAO", cat="Dongle", qty=1,
                   licence="demain")

    def test_la_licence_est_envoyee_a_l_interface(self):
        from stock.etat import _materiel_json
        self.agir("materiel.creer", nom="Dongle CAO", cat="Dongle", qty=1,
                  licence="2027-03-12")
        self.assertEqual(_materiel_json(self.article("Dongle CAO"))["licenceFin"], "2027-03-12")


class ModifierUnArticle(BaseStock):
    """Nom et catégorie suivent la famille ; le reste est propre à l'exemplaire."""

    def deux_exemplaires(self):
        self.agir("materiel.creer.lot", nom="Cartouche", cat="Outil", series=["A1", "A2"])
        return self.article("Cartouche"), self.article("Cartouche #2")

    def test_changer_le_nom_et_la_categorie_touche_toute_la_famille(self):
        a, b = self.deux_exemplaires()
        self.agir("materiel.modifier", nom=a.name, libelle="Cartouche encre", cat="Consommable",
                  numeroSerie="A1", etiquette="", affectation="Commun")
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.nom_affiche, b.nom_affiche), ("Cartouche encre", "Cartouche encre"))
        self.assertEqual((a.cat, b.cat), ("Consommable", "Consommable"))
        self.assertEqual((a.name, b.name), ("Cartouche", "Cartouche #2"))   # les clés ne bougent pas

    def test_serie_etiquette_et_affectation_sont_propres_a_l_exemplaire(self):
        a, b = self.deux_exemplaires()
        self.agir("materiel.modifier", nom=a.name, numeroSerie="Z9", etiquette="Bac 3",
                  affectation="Groupe 1")
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.numero_serie, a.etiquette, a.affectation), ("Z9", "Bac 3", "Groupe 1"))
        self.assertEqual((b.numero_serie, b.etiquette, b.affectation), ("A2", "", "Commun"))

    def test_une_serie_deja_prise_est_refusee(self):
        a, b = self.deux_exemplaires()
        self.assertIn("déjà porté", self.refus("materiel.modifier", nom=a.name, numeroSerie="A2"))
        a.refresh_from_db()
        self.assertEqual(a.numero_serie, "A1")

    def test_renommer_vers_un_nom_qui_creerait_un_sosie_est_refuse(self):
        self.agir("materiel.creer", nom="Chargeur", cat="Autre", qty=1)
        self.agir("materiel.creer", nom="Cable", cat="Autre", qty=1)
        self.assertIn("identique", self.refus("materiel.modifier", nom="Cable", libelle="Chargeur"))
        self.assertEqual(self.article("Cable").nom_affiche, "Cable")

    def test_la_licence_d_un_dongle_se_corrige_et_s_efface_hors_dongle(self):
        self.agir("materiel.creer", nom="Dongle CAO", cat="Dongle", qty=1, numeroSerie="D1",
                  licence="2027-01-01")
        d = self.article("Dongle CAO")
        self.agir("materiel.modifier", nom=d.name, numeroSerie="D1", licence="2028-05-05")
        d.refresh_from_db()
        self.assertEqual(d.licence_fin.isoformat(), "2028-05-05")
        self.agir("materiel.modifier", nom=d.name, numeroSerie="D1", cat="Outil")
        d.refresh_from_db()
        self.assertIsNone(d.licence_fin)

    def test_les_modeles_de_mission_par_type_suivent_le_renommage(self):
        from stock.models import MissionTemplate, MissionTemplateItem
        a, _ = self.deux_exemplaires()
        from django.utils import timezone
        t = MissionTemplate.objects.create(name="Kit", owner="x", created_at=timezone.now())
        MissionTemplateItem.objects.create(template=t, ordre=1, kind="type", libelle="Cartouche", qty=1)
        self.agir("materiel.modifier", nom=a.name, libelle="Cartouche encre", numeroSerie="A1")
        self.assertEqual(MissionTemplateItem.objects.get(template=t).libelle, "Cartouche encre")

    def test_reserve_aux_administrateurs(self):
        a, _ = self.deux_exemplaires()
        self.assertIn("réservée aux administrateurs", self.refus(
            "materiel.modifier", _administrateur=False, nom=a.name, libelle="X"))
