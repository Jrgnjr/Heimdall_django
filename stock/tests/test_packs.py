# -*- coding: utf-8 -*-
"""Packs : une malette prise d'un seul geste, et le panier mixte."""

from stock.models import Material, MaterialReservation, Pack, PackItem

from .socle import BaseStock


class Packs(BaseStock):

    CONTENU = [
        {"id": "Chargeur USB-C 20 W", "qty": 2},
        {"id": "Kit outils démontage", "qty": 1},
    ]

    def creer_malette(self, nom="Malette terrain A", **extra):
        params = {"nom": nom, "lignes": self.CONTENU}
        params.update(extra)
        return self.agir("pack.creer", **params)

    def ouverts(self, pack="Malette terrain A"):
        return list(MaterialReservation.objects.filter(pack=pack,
                                                      returned_by__isnull=True))

    # -- composition --------------------------------------------------

    def test_creation_enregistre_le_contenu_dans_l_ordre(self):
        self.creer_malette(etiquette="PELI-01")
        pack = Pack.objects.get(pk="Malette terrain A")
        self.assertEqual(pack.etiquette, "PELI-01")
        self.assertEqual([i.material_id for i in pack.items.all()],
                         [l["id"] for l in self.CONTENU])

    def test_composer_un_pack_ne_reserve_rien(self):
        """Le choix de conception : un pack promet un contenu, pas une
        exclusivité dessus."""
        avant = self.dispo("Chargeur USB-C 20 W")
        self.creer_malette()
        self.assertEqual(self.dispo("Chargeur USB-C 20 W"), avant)

    def test_n_importe_quel_compte_peut_creer_un_pack(self):
        from stock.services import executer
        executer("pack.creer", self.UTILISATEUR,
                 {"nom": "Malette", "lignes": self.CONTENU}, False)
        self.assertTrue(Pack.objects.filter(pk="Malette").exists())

    def test_deux_packs_de_meme_nom_refuses(self):
        self.creer_malette()
        self.assertIn("existe déjà", self.refus("pack.creer", nom="Malette terrain A",
                                               lignes=self.CONTENU))

    def test_pack_vide_refuse(self):
        self.assertIn("au moins un article",
                      self.refus("pack.creer", nom="Vide", lignes=[]))

    def test_article_en_double_refuse(self):
        message = self.refus("pack.creer", nom="Doublon", lignes=[
            {"id": "Chargeur USB-C 20 W", "qty": 1},
            {"id": "Chargeur USB-C 20 W", "qty": 2}])
        self.assertIn("deux fois", message)

    def test_modification_remplace_le_contenu(self):
        self.creer_malette()
        self.agir("pack.modifier", nom="Malette terrain A",
                  lignes=[{"id": "Câble Lightning 1 m", "qty": 3}])
        pack = Pack.objects.get(pk="Malette terrain A")
        self.assertEqual([(i.material_id, i.qty) for i in pack.items.all()],
                         [("Câble Lightning 1 m", 3)])

    def test_renommage_suit_les_emprunts_en_cours(self):
        """Sans quoi la malette renommée ne se rendrait plus d'un geste."""
        self.creer_malette()
        self.agir("pack.emprunt", pack="Malette terrain A")
        self.agir("pack.modifier", nom="Malette terrain A",
                  nouveauNom="Malette terrain B", lignes=self.CONTENU)
        self.assertEqual(len(self.ouverts("Malette terrain B")), 2)
        self.assertEqual(PackItem.objects.filter(pack_id="Malette terrain B").count(), 2)

    # -- emprunt ------------------------------------------------------

    def test_emprunt_sort_tout_le_contenu(self):
        self.creer_malette()
        avant = self.dispo("Chargeur USB-C 20 W")
        self.agir("pack.emprunt", pack="Malette terrain A")
        self.assertEqual(len(self.ouverts()), 2)
        self.assertEqual(self.dispo("Chargeur USB-C 20 W"), avant - 2)

    def test_chaque_emprunt_porte_le_nom_du_pack(self):
        self.creer_malette()
        self.agir("pack.emprunt", pack="Malette terrain A")
        self.assertTrue(all(r.pack == "Malette terrain A" for r in self.ouverts()))

    def test_le_journal_dit_de_quelle_malette_l_article_sort(self):
        self.creer_malette()
        self.agir("pack.emprunt", pack="Malette terrain A",
                  commentaire="Chargé dans le camion")
        recent = self.journal("SORTIE")[0]
        self.assertIn("Pack « Malette terrain A »", recent.commentaire)
        self.assertIn("Chargé dans le camion", recent.commentaire)

    def test_emprunt_partiel(self):
        self.creer_malette()
        self.agir("pack.emprunt", pack="Malette terrain A",
                  lignes=[{"nom": "Kit outils démontage", "qty": 1}])
        self.assertEqual([r.material_id for r in self.ouverts()],
                         ["Kit outils démontage"])

    def test_reprendre_une_malette_entamee_refuse(self):
        """Elle serait incomplète, et on la croirait complète."""
        self.creer_malette()
        self.agir("pack.emprunt", pack="Malette terrain A",
                  lignes=[{"nom": "Kit outils démontage", "qty": 1}])
        self.assertIn("déjà sorti", self.refus("pack.emprunt",
                                              pack="Malette terrain A"))

    def test_emprunt_refuse_si_stock_insuffisant_et_rien_n_est_ecrit(self):
        self.creer_malette()
        self.agir("materiel.emprunt", nom="Kit outils démontage", qty=3)
        message = self.refus("pack.emprunt", pack="Malette terrain A")
        self.assertIn("insuffisant", message)
        self.assertEqual(self.ouverts(), [])

    def test_article_hors_pack_refuse(self):
        self.creer_malette()
        message = self.refus("pack.emprunt", pack="Malette terrain A",
                             lignes=[{"nom": "Câble Lightning 1 m", "qty": 1}])
        self.assertIn("ne fait pas partie", message)

    def test_plus_que_ce_que_le_pack_contient_refuse(self):
        self.creer_malette()
        message = self.refus("pack.emprunt", pack="Malette terrain A",
                             lignes=[{"nom": "Kit outils démontage", "qty": 5}])
        self.assertIn("ne contient que", message)

    # -- retour -------------------------------------------------------

    def test_retour_rend_tout_d_un_geste(self):
        self.creer_malette()
        avant = self.dispo("Chargeur USB-C 20 W")
        self.agir("pack.emprunt", pack="Malette terrain A")
        self.agir("pack.retour", pack="Malette terrain A")
        self.assertEqual(self.ouverts(), [])
        self.assertEqual(self.dispo("Chargeur USB-C 20 W"), avant)

    def test_retour_sans_rien_dehors_refuse(self):
        self.creer_malette()
        self.assertIn("Aucun article à rendre",
                      self.refus("pack.retour", pack="Malette terrain A"))

    def test_un_article_se_rend_seul(self):
        """« Entière par défaut, article par article possible »."""
        self.creer_malette()
        self.agir("pack.emprunt", pack="Malette terrain A")
        self.agir("materiel.emprunt.retour", nom="Kit outils démontage", index=0)
        self.assertEqual(len(self.ouverts()), 1)

    # -- suppression --------------------------------------------------

    def test_suppression_refusee_tant_que_dehors(self):
        self.creer_malette()
        self.agir("pack.emprunt", pack="Malette terrain A")
        self.assertIn("encore dehors", self.refus("pack.supprimer",
                                                 nom="Malette terrain A"))

    def test_suppression_emporte_le_contenu_mais_pas_les_articles(self):
        self.creer_malette()
        self.agir("pack.supprimer", nom="Malette terrain A")
        self.assertFalse(Pack.objects.filter(pk="Malette terrain A").exists())
        self.assertEqual(PackItem.objects.count(), 0)
        self.assertTrue(Material.objects.filter(pk="Chargeur USB-C 20 W").exists())


class PanierMixte(BaseStock):
    """Malettes et articles réservés d'un seul coup."""

    def setUp(self):
        super().setUp()
        self.agir("pack.creer", nom="Malette chantier",
                  lignes=[{"id": "Chargeur USB-C 20 W", "qty": 2}])

    def test_un_panier_mele_malettes_et_articles(self):
        self.agir("materiel.emprunt.groupe",
                  packs=["Malette chantier"],
                  lignes=[{"nom": "Câble Lightning 1 m", "qty": 2}])
        self.assertEqual(
            MaterialReservation.objects.filter(pack="Malette chantier").count(), 1)
        pris = MaterialReservation.objects.filter(material_id="Câble Lightning 1 m")
        self.assertEqual([(r.qty, r.pack) for r in pris], [(2, "")])

    def test_seuls_les_emprunts_venus_de_la_malette_la_portent(self):
        self.agir("materiel.emprunt.groupe",
                  packs=["Malette chantier"],
                  lignes=[{"nom": "Chargeur USB-C 20 W", "qty": 3}])
        self.agir("pack.retour", pack="Malette chantier")
        restants = [r for r in
                    MaterialReservation.objects.filter(material_id="Chargeur USB-C 20 W")
                    if r.ouvert]
        self.assertEqual([r.qty for r in restants], [3],
                         "la ligne prise à l'unité reste dehors")

    def test_la_demande_est_cumulee_entre_la_malette_et_l_unite(self):
        """Chaque ligne prise isolément passerait ; ensemble, non."""
        Material.objects.create(name="Trépied", libelle="Trépied", ordre=20,
                                cat="Outil", qty=2, seuil=0, affectation="Commun")
        self.agir("pack.creer", nom="Malette photo",
                  lignes=[{"id": "Trépied", "qty": 2}])
        message = self.refus("materiel.emprunt.groupe", packs=["Malette photo"],
                             lignes=[{"nom": "Trépied", "qty": 1}])
        self.assertIn("insuffisant", message)
        self.assertEqual(self.dispo("Trépied"), 2, "rien ne doit être sorti")

    def test_une_malette_entamee_refuse_le_panier(self):
        self.agir("pack.emprunt", pack="Malette chantier")
        self.assertIn("déjà sorti", self.refus("materiel.emprunt.groupe",
                                              packs=["Malette chantier"]))

    def test_la_meme_malette_deux_fois_refusee(self):
        message = self.refus("materiel.emprunt.groupe",
                             packs=["Malette chantier", "Malette chantier"])
        self.assertIn("deux fois", message)

    def test_le_resume_annonce_les_deux_natures(self):
        resume, _ = self.agir("materiel.emprunt.groupe",
                              packs=["Malette chantier"],
                              lignes=[{"nom": "Câble Lightning 1 m", "qty": 1}])
        self.assertIn("1 article(s) et 1 malette(s) empruntés", resume)

    def test_le_panier_se_rattache_a_une_mission(self):
        self.mission()
        self.agir("materiel.emprunt.groupe", mission="Chantier Nord",
                  packs=["Malette chantier"],
                  lignes=[{"nom": "Câble Lightning 1 m", "qty": 1}])
        self.assertEqual(
            MaterialReservation.objects.filter(mission="Chantier Nord").count(), 2)
