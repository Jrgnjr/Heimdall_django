# -*- coding: utf-8 -*-
"""Prêts de matériel personnel : demander, accepter, refuser, rendre."""

import json

from django.test import Client, TestCase
from django.urls import reverse

from comptes.models import Compte, Dotation
from stock.models import (DemandePret, Equipe, Material, MaterialLog,
                          MaterialReservation, Mission)
from stock.services import ErreurAction, executer
from stock.services.prets import etat_prets

MOT_DE_PASSE = "un-mot-de-passe-solide"


class PretsDeSac(TestCase):
    """Alice demande à Bob, qui détient un portable et dix clés USB dans son sac."""

    def setUp(self):
        for nom, admin in (("Alice", False), ("Bob", False), ("Carole", False),
                           ("Admin", True)):
            Compte.objects.create_user(nom, password=MOT_DE_PASSE,
                                       administrateur=admin, doit_changer=False)
        Material.objects.create(name="Portable", libelle="Portable", ordre=1,
                                cat="Ordinateur", qty=1, seuil=0, affectation="Commun",
                                etiquette="PC-1", numero_serie="S1")
        Material.objects.create(name="Clé USB", libelle="Clé USB", ordre=2,
                                cat="Autre", qty=10, seuil=0, affectation="Commun")
        Dotation.objects.create(compte_id="Bob", ordre=1, material_id="Portable", quantite=1)
        Dotation.objects.create(compte_id="Bob", ordre=2, material_id="Clé USB",
                                quantite=6, detail="boîte bleue")
        Mission.objects.create(name="Chantier", ordre=1, is_meta=True,
                               owner="Alice", archived=False)

    def agir(self, _action, _qui, **params):
        return executer(_action, _qui, params, _qui == "Admin")

    def refus(self, _action, _qui, **params):
        with self.assertRaises(ErreurAction) as capture:
            self.agir(_action, _qui, **params)
        return str(capture.exception)

    def demander(self, qui="Alice", a="Bob", article="Clé USB", qty=2, **plus):
        return self.agir("pret.demander", qui, proprietaire=a, article=article,
                         qty=qty, **plus)

    def demande(self):
        return DemandePret.objects.get()

    # -- demander ---------------------------------------------------------

    def test_une_demande_est_envoyee_en_attente(self):
        self.demander(mission="Chantier", motif="Pour le relevé")
        d = self.demande()
        self.assertEqual((d.demandeur, d.proprietaire, d.material_id, d.quantite),
                         ("Alice", "Bob", "Clé USB", 2))
        self.assertEqual((d.mission, d.motif, d.statut),
                         ("Chantier", "Pour le relevé", DemandePret.EN_ATTENTE))

    def test_une_demande_peut_se_faire_sans_mission(self):
        self.demander()
        self.assertEqual(self.demande().mission, "—")

    def test_demander_ne_sort_rien_encore(self):
        self.demander()
        self.assertEqual(MaterialReservation.objects.count(), 0)
        self.assertEqual(Material.objects.get(pk="Clé USB").disponible(), 10)

    def test_on_ne_demande_pas_a_soi_meme(self):
        self.assertIn("déjà à vous", self.refus("pret.demander", "Bob", proprietaire="Bob",
                                                article="Clé USB", qty=1))

    def test_le_sac_doit_contenir_l_article(self):
        self.assertIn("plus cet article", self.refus(
            "pret.demander", "Alice", proprietaire="Carole", article="Clé USB", qty=1))

    def test_un_compte_inconnu_est_refuse(self):
        self.assertIn("n'existe pas", self.refus(
            "pret.demander", "Alice", proprietaire="Fantôme", article="Clé USB", qty=1))

    def test_on_ne_depasse_pas_la_quantite_du_sac(self):
        message = self.refus("pret.demander", "Alice", proprietaire="Bob",
                             article="Clé USB", qty=7)
        self.assertIn("6", message)

    def test_une_quantite_nulle_est_refusee(self):
        self.refus("pret.demander", "Alice", proprietaire="Bob", article="Clé USB", qty=0)

    def test_une_mission_inconnue_est_refusee(self):
        self.refus("pret.demander", "Alice", proprietaire="Bob", article="Clé USB",
                   qty=1, mission="Fantôme")

    def test_une_mission_archivee_est_refusee(self):
        Mission.objects.filter(pk="Chantier").update(archived=True)
        self.assertIn("archivée", self.refus("pret.demander", "Alice", proprietaire="Bob",
                                             article="Clé USB", qty=1, mission="Chantier"))

    def test_un_membre_de_la_mission_n_a_pas_a_etre_sollicite(self):
        """Chaque personne de la mission emporte déjà son sac."""
        equipe = Equipe.objects.create(mission_id="Chantier", nom="Nord")
        equipe.membres.add(Compte.objects.get(pk="Bob"))
        self.assertIn("emporte déjà son sac", self.refus(
            "pret.demander", "Alice", proprietaire="Bob", article="Clé USB", qty=1,
            mission="Chantier"))

    def test_un_membre_reste_sollicitable_pour_une_autre_mission_ou_sans(self):
        equipe = Equipe.objects.create(mission_id="Chantier", nom="Nord")
        equipe.membres.add(Compte.objects.get(pk="Bob"))
        self.demander()                       # sans mission : permis
        self.assertEqual(DemandePret.objects.count(), 1)

    def test_pas_deux_fois_la_meme_demande(self):
        self.demander()
        self.assertIn("déjà fait cette demande", self.refus(
            "pret.demander", "Alice", proprietaire="Bob", article="Clé USB", qty=2))

    def test_une_demande_differente_est_permise(self):
        self.demander()
        self.demander(article="Portable", qty=1)
        self.assertEqual(DemandePret.objects.count(), 2)

    # -- accepter ---------------------------------------------------------

    def test_accepter_fait_sortir_le_materiel_a_l_emprunteur(self):
        self.demander(mission="Chantier")
        self.agir("pret.accepter", "Bob", id=self.demande().pk)
        r = MaterialReservation.objects.get()
        self.assertEqual((r.material_id, r.qty, r.taken_by, r.mission, r.sac_de),
                         ("Clé USB", 2, "Alice", "Chantier", "Bob"))
        self.assertIsNone(r.returned_by)
        self.assertEqual(self.demande().statut, DemandePret.ACCEPTEE)

    def test_accepter_est_journalise(self):
        self.demander(mission="Chantier")
        self.agir("pret.accepter", "Bob", id=self.demande().pk)
        ligne = MaterialLog.objects.get(kind="SORTIE")
        self.assertEqual((ligne.who, ligne.mission, ligne.qty), ("Alice", "Chantier", 2))
        self.assertIn("Prêté par Bob", ligne.commentaire)

    def test_le_pret_reduit_ce_que_le_sac_peut_encore_preter(self):
        self.demander(qty=4)
        self.agir("pret.accepter", "Bob", id=self.demande().pk)
        self.assertEqual(etat_prets("Alice")["sacs"]["Bob"][1]["disponible"], 2)
        self.assertIn("2", self.refus("pret.demander", "Carole", proprietaire="Bob",
                                      article="Clé USB", qty=3))

    def test_seul_le_sollicite_peut_accepter(self):
        self.demander()
        for autre in ("Alice", "Carole"):
            self.assertIn("ne vous est pas adressée",
                          self.refus("pret.accepter", autre, id=self.demande().pk))
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_une_demande_ne_se_traite_qu_une_fois(self):
        self.demander()
        pk = self.demande().pk
        self.agir("pret.accepter", "Bob", id=pk)
        self.assertIn("déjà reçu une réponse", self.refus("pret.accepter", "Bob", id=pk))
        self.assertIn("déjà reçu une réponse", self.refus("pret.refuser", "Bob", id=pk))
        self.assertEqual(MaterialReservation.objects.count(), 1)

    def test_l_acceptation_reverifie_la_disponibilite(self):
        """Entre la demande et la réponse, le sac a pu prêter ailleurs."""
        self.demander(qty=5)
        self.demander(qty=5, a="Bob", article="Clé USB", mission="Chantier")
        premiere, seconde = DemandePret.objects.order_by("pk")
        self.agir("pret.accepter", "Bob", id=premiere.pk)
        self.assertIn("ne reste que 1", self.refus("pret.accepter", "Bob", id=seconde.pk))
        self.assertEqual(MaterialReservation.objects.count(), 1)

    def test_accepter_refuse_si_la_mission_a_disparu(self):
        self.demander(mission="Chantier")
        Mission.objects.filter(pk="Chantier").delete()
        self.refus("pret.accepter", "Bob", id=self.demande().pk)
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_le_materiel_pris_dans_le_sac_apparait_dans_la_mission(self):
        self.demander(mission="Chantier")
        self.agir("pret.accepter", "Bob", id=self.demande().pk)
        self.assertEqual(MaterialReservation.objects.filter(mission="Chantier").count(), 1)

    # -- refuser ----------------------------------------------------------

    def test_refuser_avec_une_raison(self):
        self.demander()
        self.agir("pret.refuser", "Bob", id=self.demande().pk, raison="J'en ai besoin")
        d = self.demande()
        self.assertEqual((d.statut, d.raison_refus), (DemandePret.REFUSEE, "J'en ai besoin"))
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_refuser_sans_raison_est_permis(self):
        self.demander()
        self.agir("pret.refuser", "Bob", id=self.demande().pk)
        self.assertEqual(self.demande().raison_refus, "")

    def test_une_raison_trop_longue_est_refusee(self):
        self.demander()
        self.refus("pret.refuser", "Bob", id=self.demande().pk, raison="x" * 400)

    def test_seul_le_sollicite_peut_refuser(self):
        self.demander()
        self.refus("pret.refuser", "Alice", id=self.demande().pk)
        self.assertEqual(self.demande().statut, DemandePret.EN_ATTENTE)

    def test_apres_un_refus_on_peut_redemander(self):
        self.demander()
        self.agir("pret.refuser", "Bob", id=self.demande().pk)
        self.demander()
        self.assertEqual(DemandePret.objects.count(), 2)

    # -- annuler ----------------------------------------------------------

    def test_le_demandeur_peut_annuler(self):
        self.demander()
        self.agir("pret.annuler", "Alice", id=self.demande().pk)
        self.assertEqual(self.demande().statut, DemandePret.ANNULEE)

    def test_le_sollicite_ne_peut_pas_annuler_a_la_place_du_demandeur(self):
        self.demander()
        self.refus("pret.annuler", "Bob", id=self.demande().pk)

    def test_une_demande_acceptee_ne_s_annule_plus(self):
        self.demander()
        pk = self.demande().pk
        self.agir("pret.accepter", "Bob", id=pk)
        self.refus("pret.annuler", "Alice", id=pk)

    # -- rendre -----------------------------------------------------------

    def preter(self, qty=2):
        self.demander(qty=qty)
        self.agir("pret.accepter", "Bob", id=self.demande().pk)
        return MaterialReservation.objects.get()

    def test_l_emprunteur_rend_par_le_retour_ordinaire(self):
        """Le prêt est un emprunt comme un autre : il se rend comme les autres, et
        le matériel regagne le sac, qui n'a jamais été vidé."""
        self.preter(qty=4)
        self.assertEqual(etat_prets("Alice")["sacs"]["Bob"][1]["disponible"], 2)
        self.agir("materiel.emprunt.retour", "Alice", nom="Clé USB", index=0)
        self.assertEqual(MaterialReservation.objects.count(), 0)
        self.assertEqual(etat_prets("Alice")["sacs"]["Bob"][1]["disponible"], 6)
        self.assertEqual(etat_prets("Bob")["prets"], [])

    def test_le_pret_suit_la_restitution_de_mission(self):
        self.demander(qty=2, mission="Chantier")
        self.agir("pret.accepter", "Bob", id=self.demande().pk)
        self.agir("materiel.mission.restituer", "Alice", mission="Chantier")
        self.assertEqual(etat_prets("Bob")["prets"], [])
        self.assertEqual(etat_prets("Alice")["sacs"]["Bob"][1]["disponible"], 6)

    def test_le_preteur_constate_le_retour(self):
        r = self.preter()
        self.agir("pret.rendu", "Bob", id=r.pk)
        self.assertEqual(MaterialReservation.objects.count(), 0)
        self.assertEqual(etat_prets("Bob")["prets"], [])
        self.assertEqual(MaterialLog.objects.filter(kind="RETOUR").count(), 1)

    def test_seul_le_preteur_constate_le_retour(self):
        r = self.preter()
        self.refus("pret.rendu", "Alice", id=r.pk)
        self.refus("pret.rendu", "Carole", id=r.pk)
        self.assertEqual(MaterialReservation.objects.count(), 1)

    def test_un_emprunt_ordinaire_n_est_pas_un_pret(self):
        self.agir("materiel.emprunt", "Alice", nom="Clé USB", qty=1)
        self.assertEqual(etat_prets("Bob")["prets"], [])

    # -- ce que voit chacun ----------------------------------------------

    def test_le_sollicite_voit_la_demande_dans_ses_notifications(self):
        self.demander(mission="Chantier", motif="Pour le relevé")
        recue = etat_prets("Bob")["recues"][0]
        self.assertEqual((recue["de"], recue["libelle"], recue["quantite"],
                          recue["mission"], recue["motif"]),
                         ("Alice", "Clé USB", 2, "Chantier", "Pour le relevé"))

    def test_le_demandeur_voit_la_reponse_et_la_raison(self):
        self.demander()
        self.agir("pret.refuser", "Bob", id=self.demande().pk, raison="Indisponible")
        emise = etat_prets("Alice")["emises"][0]
        self.assertEqual((emise["statut"], emise["raison"]), ("REFUSÉE", "Indisponible"))

    def test_les_tiers_ne_voient_pas_la_demande(self):
        self.demander()
        self.assertEqual(etat_prets("Carole")["recues"], [])
        self.assertEqual(etat_prets("Carole")["emises"], [])
        self.assertEqual(etat_prets("Admin")["recues"], [])

    def test_le_preteur_voit_ses_prets_en_cours(self):
        self.preter()
        pret = etat_prets("Bob")["prets"][0]
        self.assertEqual((pret["libelle"], pret["quantite"], pret["a"]), ("Clé USB", 2, "Alice"))

    def test_tout_le_monde_voit_le_contenu_des_autres_sacs_mais_pas_le_sien(self):
        self.assertEqual(sorted(etat_prets("Alice")["sacs"]), ["Bob"])
        self.assertEqual(etat_prets("Bob")["sacs"], {})
        ligne = etat_prets("Alice")["sacs"]["Bob"][0]
        self.assertEqual((ligne["libelle"], ligne["disponible"]), ("Portable", 1))
        self.assertIn("série S1", ligne["detail"])

    def test_les_sacs_des_comptes_desactives_sont_masques(self):
        Compte.objects.filter(pk="Bob").update(actif=False)
        self.assertEqual(etat_prets("Alice")["sacs"], {})

    def test_le_responsable_de_la_mission_voit_les_demandes_qui_la_visent(self):
        """Carole demande à Bob pour « Chantier », dont Alice est responsable :
        Alice la voit sur la carte de la mission, sans pouvoir y répondre."""
        self.demander(qui="Carole", mission="Chantier")
        vue = etat_prets("Alice")["missions"]
        self.assertEqual(len(vue), 1)
        self.assertEqual((vue[0]["de"], vue[0]["a"], vue[0]["libelle"], vue[0]["mission"]),
                         ("Carole", "Bob", "Clé USB", "Chantier"))
        self.assertEqual(etat_prets("Alice")["recues"], [])

    def test_une_demande_repondue_quitte_la_carte_de_la_mission(self):
        self.demander(qui="Carole", mission="Chantier")
        self.agir("pret.refuser", "Bob", id=self.demande().pk)
        self.assertEqual(etat_prets("Alice")["missions"], [])

    def test_les_tiers_ne_voient_pas_les_demandes_d_une_mission_qui_n_est_pas_la_leur(self):
        self.demander(qui="Carole", mission="Chantier")
        self.assertEqual(etat_prets("Admin")["missions"], [])
        # Le sollicité et le demandeur ont leur propre vue, pas celle-ci.
        self.assertEqual(etat_prets("Bob")["missions"], [])
        self.assertEqual(etat_prets("Carole")["missions"], [])

    def test_une_demande_sans_mission_n_apparait_sur_aucune_carte(self):
        self.demander(qui="Carole")
        self.assertEqual(etat_prets("Alice")["missions"], [])

    # -- par l'API --------------------------------------------------------

    def ouvrir(self, nom):
        navigateur = Client()
        navigateur.login(identifiant=nom, password=MOT_DE_PASSE)
        return navigateur

    def poster(self, navigateur, action, **params):
        return navigateur.post(reverse("api_action"),
                               data=json.dumps({"action": action, "params": params}),
                               content_type="application/json")

    def test_un_non_administrateur_peut_demander_et_repondre(self):
        alice, bob = self.ouvrir("Alice"), self.ouvrir("Bob")
        self.assertEqual(self.poster(alice, "pret.demander", proprietaire="Bob",
                                     article="Clé USB", qty=1).status_code, 200)
        notifs = bob.get(reverse("api_state")).json()["pret"]["recues"]
        self.assertEqual(len(notifs), 1)
        reponse = self.poster(bob, "pret.accepter", id=notifs[0]["id"])
        self.assertEqual(reponse.status_code, 200, reponse.content)
        self.assertEqual(reponse.json()["pret"]["prets"][0]["a"], "Alice")

    def test_l_api_n_expose_pas_les_demandes_des_autres(self):
        self.demander()
        carole = self.ouvrir("Carole")
        etat = carole.get(reverse("api_state")).json()["pret"]
        self.assertEqual((etat["recues"], etat["emises"]), ([], []))
