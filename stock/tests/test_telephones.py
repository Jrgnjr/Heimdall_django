# -*- coding: utf-8 -*-
"""Téléphones, armoires et casiers."""

from stock.models import Cabinet, PhoneModel, PhoneMovement, SlotAssignment
from stock.services.emplacements import emplacement_de

from .socle import BaseStock


class Telephones(BaseStock):

    def test_reception_augmente_le_stock(self):
        self.agir("telephone.reception", refId="R1", variantIdx=0, qty=3)
        self.assertEqual(self.variante().qty, 9)

    def test_sortie_diminue_le_stock_et_laisse_une_trace(self):
        self.agir("telephone.sortie", refId="R1", variantIdx=0, qty=2)
        self.assertEqual(self.variante().qty, 4)
        sorties = list(self.ref.outs.all())
        self.assertEqual(len(sorties), 1)
        self.assertEqual(sorties[0].who, self.UTILISATEUR)

    def test_sortie_refusee_si_stock_insuffisant(self):
        message = self.refus("telephone.sortie", refId="R1", variantIdx=0, qty=99)
        self.assertIn("insuffisant", message)
        self.assertEqual(self.variante().qty, 6, "le stock ne doit pas bouger")

    def test_reservation_ne_sort_pas_du_stock(self):
        self.agir("telephone.reservation", refId="R1", variantIdx=0, qty=2)
        self.assertEqual(self.variante().qty, 6)
        self.assertEqual(len(list(self.ref.reservations.all())), 1)

    def test_reservation_puis_vente(self):
        self.agir("telephone.reservation", refId="R1", variantIdx=0, qty=2)
        self.agir("telephone.reservation.vendre", refId="R1", index=0)
        self.assertEqual(self.variante().qty, 4, "la vente sort du stock")
        self.assertEqual(len(list(self.ref.reservations.all())), 0)
        self.assertEqual(len(list(self.ref.outs.all())), 1)

    def test_reservation_annulee_ne_touche_pas_le_stock(self):
        self.agir("telephone.reservation", refId="R1", variantIdx=0, qty=2)
        self.agir("telephone.reservation.annuler", refId="R1", index=0)
        self.assertEqual(self.variante().qty, 6)
        self.assertEqual(len(list(self.ref.reservations.all())), 0)

    def test_on_ne_reserve_pas_plus_que_le_stock(self):
        self.agir("telephone.reservation", refId="R1", variantIdx=0, qty=5)
        message = self.refus("telephone.reservation", refId="R1", variantIdx=0, qty=2)
        self.assertIn("réservable", message)

    def test_retour_d_une_sortie_reincremente(self):
        self.agir("telephone.sortie", refId="R1", variantIdx=0, qty=2)
        self.agir("telephone.sortie.retour", refId="R1", index=0)
        self.assertEqual(self.variante().qty, 6)
        self.assertEqual(len(list(self.ref.outs.all())), 0)

    def test_une_empreinte_perimee_est_refusee(self):
        """Le rang seul ne suffit pas : si la ligne a changé, il désigne autre
        chose."""
        self.agir("telephone.reservation", refId="R1", variantIdx=0, qty=2)
        message = self.refus("telephone.reservation.annuler", refId="R1",
                             index=0, empreinte="1|2|3|4")
        self.assertIn("modifiée par quelqu'un d'autre", message)

    def test_creation_regroupe_sur_la_reference_existante(self):
        self.agir("telephone.creer", brand="Apple", model="iPhone 15 Pro",
                  capa="256 Go", color="Titane naturel", qty=4)
        self.assertEqual(PhoneModel.objects.count(), 1)
        self.assertEqual(self.variante().qty, 10)

    def test_creation_d_une_nouvelle_reference(self):
        self.agir("telephone.creer", brand="Samsung", model="Galaxy S24",
                  mpn="SM-S921B", capa="256 Go", color="Noir", qty=4)
        self.assertEqual(PhoneModel.objects.count(), 2)
        nouvelle = PhoneModel.objects.get(brand="Samsung")
        self.assertEqual(nouvelle.id, "R2", "les identifiants se suivent")

    def test_suppression_refusee_si_reservations(self):
        self.agir("telephone.reservation", refId="R1", variantIdx=0, qty=1)
        message = self.refus("telephone.supprimer", refId="R1")
        self.assertIn("réservations ou des sorties", message)
        self.assertTrue(PhoneModel.objects.filter(pk="R1").exists())

    def test_suppression_emporte_les_declinaisons(self):
        self.agir("telephone.supprimer", refId="R1")
        self.assertFalse(PhoneModel.objects.filter(pk="R1").exists())
        from stock.models import Variant
        self.assertEqual(Variant.objects.count(), 0)

    def test_une_action_reservee_est_refusee_a_un_non_administrateur(self):
        message = self.refus_non_admin("telephone.reception", refId="R1",
                                       variantIdx=0, qty=1)
        self.assertIn("réservée aux administrateurs", message)

    def refus_non_admin(self, _action, **params):
        from stock.services import ErreurAction, executer
        with self.assertRaises(ErreurAction) as capture:
            executer(_action, self.UTILISATEUR, params, False)
        return str(capture.exception)


class Emplacements(BaseStock):

    def test_une_reference_est_placee_automatiquement(self):
        self.assertEqual(emplacement_de("R1"), "A1·E1·C1")

    def test_un_casier_choisi_a_la_main_l_emporte(self):
        self.agir("armoire.affecter", refId="R1", loc="A1·E2·C3")
        self.assertEqual(emplacement_de("R1"), "A1·E2·C3")
        self.assertTrue(SlotAssignment.objects.filter(phone_id="R1").exists())

    def test_un_casier_inexistant_est_refuse(self):
        message = self.refus("armoire.affecter", refId="R1", loc="A9·E1·C1")
        self.assertIn("n'existe pas", message)

    def test_liberer_rend_au_placement_automatique(self):
        self.agir("armoire.affecter", refId="R1", loc="A1·E2·C3")
        self.agir("armoire.liberer", refId="R1")
        self.assertFalse(SlotAssignment.objects.filter(phone_id="R1").exists())
        self.assertEqual(emplacement_de("R1"), "A1·E1·C1")

    def test_un_transfert_est_inscrit_au_journal(self):
        self.agir("armoire.affecter", refId="R1", loc="A1·E2·C3")
        transferts = PhoneMovement.objects.filter(kind="TRANSF.")
        self.assertEqual(len(transferts), 1)
        self.assertIn("A1·E2·C3", transferts[0].label)

    def test_retrecir_une_armoire_nettoie_les_casiers_perimes(self):
        """Un casier fixé qui n'existe plus promettrait un emplacement faux."""
        self.agir("armoire.affecter", refId="R1", loc="A1·E4·C5")
        self.agir("armoire.dimension", cabId="A1", champ="shelves", delta=-1)
        self.assertFalse(SlotAssignment.objects.filter(phone_id="R1").exists())

    def test_les_dimensions_sont_bornees(self):
        for _ in range(12):
            self.agir("armoire.dimension", cabId="A1", champ="cols", delta=1)
        self.assertEqual(Cabinet.objects.get(pk="A1").cols, 10)
        for _ in range(12):
            self.agir("armoire.dimension", cabId="A1", champ="cols", delta=-1)
        self.assertEqual(Cabinet.objects.get(pk="A1").cols, 1)

    def test_il_doit_rester_une_armoire(self):
        message = self.refus("armoire.supprimer", cabId="A1")
        self.assertIn("au moins une armoire", message)

    def test_supprimer_une_armoire_emporte_ses_casiers_fixes(self):
        self.agir("armoire.ajouter")
        self.agir("armoire.affecter", refId="R1", loc="A1·E1·C1")
        self.agir("armoire.supprimer", cabId="A1")
        self.assertFalse(SlotAssignment.objects.filter(loc__startswith="A1·").exists())

    def test_les_armoires_ajoutees_se_numerotent(self):
        self.agir("armoire.ajouter")
        self.assertEqual(sorted(Cabinet.objects.values_list("id", flat=True)),
                         ["A1", "A2"])
