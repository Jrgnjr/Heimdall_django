# -*- coding: utf-8 -*-
"""Les prêts à une personne sans compte : déclarés, rendus, signalés en retard."""

from datetime import timedelta

from django.utils import timezone

from stock.models import PretExterne
from stock.services.prets_externes import etat_externes
from stock.tests.test_roles import Base


class PretsExternes(Base):
    def declarer(self, qui="Eff1", **p):
        params = {"article": "Perceuse", "qty": 1, "emprunteur": "Marc Dupont"}
        params.update(p)
        return self.agir("pret.externe.declarer", qui, **params)

    def en_retard(self, qui="Eff1"):
        self.declarer(qui, commentaire="Voisin")
        p = PretExterne.objects.filter(preteur=qui).latest("pk")
        PretExterne.objects.filter(pk=p.pk).update(
            echeance=timezone.localdate() - timedelta(days=3))
        return p

    def ids(self, compte, admin=False):
        return [x["id"] for x in etat_externes(compte, admin)]

    # -- déclarer --------------------------------------------------------------

    def test_declarer_un_pret_avec_commentaire_et_echeance(self):
        demain = (timezone.localdate() + timedelta(days=2)).isoformat()
        self.declarer(commentaire="Rendez-vous lundi", echeance=demain,
                      mission="Chantier")
        p = PretExterne.objects.get()
        self.assertEqual((p.preteur, p.emprunteur, p.quantite, p.mission),
                         ("Eff1", "Marc Dupont", 1, "Chantier"))
        self.assertEqual(p.commentaire, "Rendez-vous lundi")
        self.assertEqual(p.echeance.isoformat(), demain)

    def test_sans_mission_ni_echeance(self):
        self.declarer()
        p = PretExterne.objects.get()
        self.assertEqual(p.mission, "—")
        self.assertIsNone(p.echeance)

    def test_une_echeance_passee_est_refusee(self):
        hier = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.assertIn("passé", self.refus(
            "pret.externe.declarer", "Eff1", article="Perceuse", qty=1,
            emprunteur="Marc", echeance=hier))

    def test_quelqu_un_qui_a_un_compte_passe_par_une_demande(self):
        self.assertIn("a un compte", self.refus(
            "pret.externe.declarer", "Eff1", article="Perceuse", qty=1,
            emprunteur="eff2"))

    def test_article_inconnu_et_mission_inconnue(self):
        self.refus("pret.externe.declarer", "Eff1", article="Fantôme", qty=1,
                   emprunteur="Marc")
        self.refus("pret.externe.declarer", "Eff1", article="Perceuse", qty=1,
                   emprunteur="Marc", mission="Inexistante")

    # -- le retard ---------------------------------------------------------------

    def test_le_retard_se_calcule(self):
        self.en_retard()
        self.assertTrue(etat_externes("Eff1", False)[0]["enRetard"])

    def test_pas_de_retard_sans_echeance_ni_apres_le_retour(self):
        self.declarer()
        self.assertFalse(etat_externes("Eff1", False)[0]["enRetard"])
        p = self.en_retard("Eff2")  # un second prêt, d'un autre
        self.agir("pret.externe.rendre", "Eff2", id=p.pk)
        self.assertFalse([x for x in etat_externes("Eff2", False) if x["id"] == p.pk][0]["enRetard"])

    # -- qui est alerté ------------------------------------------------------------

    def test_le_preteur_son_chef_son_adjoint_et_les_administrateurs_voient_le_retard(self):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, adjoint="Eff2")
        p = self.en_retard("Eff1")
        for compte in ("Eff1", "Chef1", "Eff2"):
            self.assertIn(p.pk, self.ids(compte), compte)
        self.assertIn(p.pk, self.ids("Admin", True))

    def test_les_autres_ne_voient_rien(self):
        p = self.en_retard("Eff1")
        for compte in ("Eff3", "Chef2", "Libre", "Gest"):
            self.assertNotIn(p.pk, self.ids(compte), compte)

    def test_un_effectif_ne_voit_pas_les_prets_d_un_pair(self):
        p = self.en_retard("Eff1")
        self.assertNotIn(p.pk, self.ids("Eff2"))

    def test_le_chef_et_l_adjoint_se_voient_l_un_l_autre(self):
        self.agir("groupe.modifier", "Admin", groupe=self.g1.pk, adjoint="Eff2")
        p = self.en_retard("Chef1")
        self.assertIn(p.pk, self.ids("Eff2"))
        q = self.en_retard("Eff2")
        self.assertIn(q.pk, self.ids("Chef1"))

    # -- rendre / retirer ------------------------------------------------------------

    def test_rendre_par_le_preteur_le_chef_ou_un_admin(self):
        for qui in ("Eff1", "Chef1", "Admin"):
            PretExterne.objects.all().delete()
            self.declarer()
            self.agir("pret.externe.rendre", qui, id=PretExterne.objects.get().pk)
            p = PretExterne.objects.get()
            self.assertIsNotNone(p.rendu_le)
            self.assertEqual(p.rendu_par, qui)

    def test_un_pair_ou_un_etranger_ne_rend_pas(self):
        self.declarer()
        pk = PretExterne.objects.get().pk
        for qui in ("Eff2", "Eff3", "Chef2"):
            self.assertIn("Seuls son prêteur", self.refus("pret.externe.rendre", qui, id=pk))

    def test_rendre_deux_fois(self):
        self.declarer()
        pk = PretExterne.objects.get().pk
        self.agir("pret.externe.rendre", "Eff1", id=pk)
        self.assertIn("déjà rendu", self.refus("pret.externe.rendre", "Eff1", id=pk))

    def test_retirer_une_declaration(self):
        self.declarer()
        pk = PretExterne.objects.get().pk
        self.refus("pret.externe.supprimer", "Chef1", id=pk)
        self.agir("pret.externe.supprimer", "Eff1", id=pk)
        self.assertFalse(PretExterne.objects.exists())
