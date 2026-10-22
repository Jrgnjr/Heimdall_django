# -*- coding: utf-8 -*-
"""Pièces détachées de téléphones : fiches, modèles compatibles, entrées et sorties."""

from stock.models import PhoneMovement, PiecePhone

from .socle import BaseStock


class PiecesDetachees(BaseStock):

    def admin(self, action, **p):
        return self.agir(action, _administrateur=True, **p)

    def refus_admin(self, action, **p):
        return self.refus(action, _administrateur=True, **p)

    def creer(self, nom="Écran Galaxy S24", **p):
        self.admin("piece.creer", nom=nom, type="Écran", **p)
        return PiecePhone.objects.get(name=nom)

    def test_creer_une_piece_avec_ses_modeles(self):
        from stock.models import PhoneModel
        refs = [r.pk for r in PhoneModel.objects.all()]
        piece = self.creer(qty=3, mpn="GH82-1", modeles=refs)
        self.assertEqual((piece.qty, piece.mpn, piece.kind), (3, "GH82-1", "Écran"))
        self.assertEqual(sorted(m.pk for m in piece.modeles.all()), sorted(refs))
        self.assertEqual(PhoneMovement.objects.filter(kind="CRÉATION").count(), 1)

    def test_creer_sans_stock_ne_journalise_rien(self):
        self.creer()
        self.assertFalse(PhoneMovement.objects.filter(label__startswith="Pièce").exists())

    def test_deux_pieces_de_meme_nom(self):
        self.creer()
        self.assertIn("s'appelle déjà", self.refus_admin(
            "piece.creer", nom="écran galaxy s24", type="Écran"))

    def test_modele_inconnu(self):
        self.assertIn("n'existe plus", self.refus_admin(
            "piece.creer", nom="X", type="Écran", modeles=["fantome"]))

    def test_reserve_aux_administrateurs(self):
        piece = self.creer()
        for action, p in (("piece.creer", {"nom": "Y"}), ("piece.modifier", {"id": piece.pk, "nom": "Z"}),
                          ("piece.supprimer", {"id": piece.pk}), ("piece.entree", {"id": piece.pk, "qty": 1})):
            self.assertIn("réservée aux administrateurs", self.refus(action, _administrateur=False, **p))

    def test_entree_puis_sortie_par_tout_utilisateur(self):
        piece = self.creer()
        self.admin("piece.entree", id=piece.pk, qty=5)
        self.agir("piece.sortie", _administrateur=False, id=piece.pk, qty=2, motif="Réparation Alice")
        piece.refresh_from_db()
        self.assertEqual(piece.qty, 3)
        genres = list(PhoneMovement.objects.filter(label__startswith="Pièce").values_list("kind", flat=True))
        self.assertEqual(sorted(genres), ["ENTRÉE", "SORTIE"])
        self.assertTrue(PhoneMovement.objects.get(kind="SORTIE").label.endswith("(Réparation Alice)"))

    def test_le_stock_ne_descend_pas_sous_zero(self):
        piece = self.creer(qty=1)
        self.assertIn("1 en stock", self.refus("piece.sortie", id=piece.pk, qty=2))
        piece.refresh_from_db()
        self.assertEqual(piece.qty, 1)

    def test_modifier_change_les_modeles(self):
        from stock.models import PhoneModel
        refs = [r.pk for r in PhoneModel.objects.all()]
        piece = self.creer(modeles=refs)
        self.admin("piece.modifier", id=piece.pk, nom="Écran S24+", type="Écran", mpn="X", modeles=[])
        piece.refresh_from_db()
        self.assertEqual((piece.name, piece.mpn, piece.modeles.count()), ("Écran S24+", "X", 0))

    def test_supprimer_un_modele_retire_le_lien_et_garde_la_piece(self):
        from stock.models import PhoneModel
        ref = PhoneModel.objects.first()
        piece = self.creer(modeles=[ref.pk])
        ref.delete()
        piece.refresh_from_db()
        self.assertEqual(piece.modeles.count(), 0)

    def test_supprimer_une_piece(self):
        piece = self.creer()
        self.admin("piece.supprimer", id=piece.pk)
        self.assertFalse(PiecePhone.objects.exists())

    def test_les_pieces_sont_dans_l_etat(self):
        from stock.etat import charger
        piece = self.creer(qty=2)
        _, etat = charger()
        self.assertEqual([x["name"] for x in etat["pieces"]], ["Écran Galaxy S24"])
        self.assertEqual(etat["pieces"][0]["qty"], 2)
