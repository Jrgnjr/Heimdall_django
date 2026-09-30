# -*- coding: utf-8 -*-
"""Le sac de dotation : ce qui a été remis à quelqu'un et reste chez lui.

Ce que ces tests protègent avant tout : une ligne de sac désigne un
**exemplaire précis**, et son étiquette et son numéro de série remontent
jusqu'à l'écran. Sans cela, « Dell Latitude 5450 » ne dit pas lequel des trois
est dans le sac — et c'était toute la raison de la demande.
"""

import json

from django.test import TestCase
from django.urls import reverse

from comptes.models import ActiviteCompte, Compte, Dotation
from stock.models import Material
from stock.services import ErreurAction, executer
from stock.services.dotations import sacs


class SacDeDotation(TestCase):

    MOT_DE_PASSE = "un-mot-de-passe-solide"

    def setUp(self):
        self.admin = Compte.objects.create_user(
            "Admin", password=self.MOT_DE_PASSE, administrateur=True,
            doit_changer=False)
        self.simple = Compte.objects.create_user(
            "Compte-001", password=self.MOT_DE_PASSE, administrateur=False,
            doit_changer=False)
        # Trois portables identiques : c'est le cas qui exige l'exemplaire.
        for i, serie in enumerate(("8KJ2LQ3", "8KJ2MR4", "8KJ2NS5"), start=1):
            Material.objects.create(
                name="Dell Latitude 5450" if i == 1 else "Dell Latitude 5450 #%d" % i,
                libelle="Dell Latitude 5450", ordre=i, cat="Ordinateur",
                qty=1, seuil=0, affectation="Commun",
                etiquette="PC-00%d" % i, numero_serie=serie)
        Material.objects.create(name="Câble USB-C", libelle="Câble USB-C",
                                ordre=9, cat="Autre", qty=40, seuil=0,
                                affectation="Commun")

    def agir(self, _action, _utilisateur="Admin", _administrateur=True, **params):
        return executer(_action, _utilisateur, params, _administrateur)

    def refus(self, **params):
        with self.assertRaises(ErreurAction) as capture:
            self.agir("compte.dotations", **params)
        return str(capture.exception)

    def poser(self, compte="Compte-001", materiel=None):
        return self.agir("compte.dotations", compte=compte,
                         materiel=materiel if materiel is not None
                         else [["Dell Latitude 5450 #3", 1, "portable de terrain"]])

    # -- composition ------------------------------------------------------

    def test_le_sac_retient_l_exemplaire_et_pas_le_libelle(self):
        self.poser()
        ligne = Dotation.objects.get()
        self.assertEqual(ligne.material_id, "Dell Latitude 5450 #3")
        self.assertEqual(ligne.compte_id, "Compte-001")

    def test_l_etiquette_et_la_serie_remontent_a_l_ecran(self):
        """Le cœur de la demande."""
        self.poser()
        ligne = sacs("Admin", True)["Compte-001"][0]
        self.assertEqual(ligne["libelle"], "Dell Latitude 5450")
        self.assertEqual(ligne["etiquette"], "PC-003")
        self.assertEqual(ligne["numeroSerie"], "8KJ2NS5")
        self.assertFalse(ligne["manquant"])

    def test_deux_exemplaires_du_meme_modele_se_distinguent(self):
        self.poser(materiel=[["Dell Latitude 5450", 1, ""],
                             ["Dell Latitude 5450 #2", 1, ""]])
        lignes = sacs("Admin", True)["Compte-001"]
        self.assertEqual(sorted(l["numeroSerie"] for l in lignes),
                         ["8KJ2LQ3", "8KJ2MR4"])
        self.assertEqual({l["libelle"] for l in lignes}, {"Dell Latitude 5450"})

    def test_un_article_sans_identifiant_ne_gene_pas(self):
        self.poser(materiel=[["Câble USB-C", 3, ""]])
        ligne = sacs("Admin", True)["Compte-001"][0]
        self.assertEqual((ligne["etiquette"], ligne["numeroSerie"]), ("", ""))
        self.assertEqual(ligne["quantite"], 3)

    def test_le_detail_saisi_est_conserve(self):
        self.poser()
        self.assertEqual(sacs("Admin", True)["Compte-001"][0]["detail"],
                         "portable de terrain")

    def test_poser_remplace_le_sac_entier(self):
        """Une quantité nulle retirée de l'écran doit disparaître du sac."""
        self.poser(materiel=[["Dell Latitude 5450", 1, ""],
                             ["Câble USB-C", 2, ""]])
        self.poser(materiel=[["Câble USB-C", 5, ""]])
        lignes = Dotation.objects.all()
        self.assertEqual([(l.material_id, l.quantite) for l in lignes],
                         [("Câble USB-C", 5)])

    def test_un_sac_vide_est_accepte(self):
        self.poser()
        self.poser(materiel=[])
        self.assertEqual(Dotation.objects.count(), 0)

    def test_l_ordre_de_saisie_est_conserve(self):
        self.poser(materiel=[["Câble USB-C", 1, ""],
                             ["Dell Latitude 5450", 1, ""]])
        self.assertEqual([l.material_id for l in Dotation.objects.all()],
                         ["Câble USB-C", "Dell Latitude 5450"])

    def test_une_trace_est_laissee(self):
        self.poser()
        self.assertTrue(ActiviteCompte.objects
                        .filter(nouveau_nom="Compte-001",
                                action__startswith="sac modifié").exists())

    # -- les refus --------------------------------------------------------

    def test_un_compte_inconnu_refuse(self):
        self.assertIn("n'existe plus", self.refus(compte="Personne",
                                                 materiel=[["Câble USB-C", 1, ""]]))

    def test_un_article_hors_catalogue_refuse(self):
        message = self.refus(compte="Compte-001",
                             materiel=[["Marteau-piqueur", 1, ""]])
        self.assertIn("n'existe pas dans le catalogue", message)
        self.assertEqual(Dotation.objects.count(), 0)

    def test_le_meme_exemplaire_deux_fois_refuse(self):
        message = self.refus(compte="Compte-001",
                             materiel=[["Câble USB-C", 1, ""],
                                       ["Câble USB-C", 2, ""]])
        self.assertIn("deux fois", message)

    def test_une_quantite_nulle_ou_negative_refuse(self):
        for mauvaise in (0, -3):
            message = self.refus(compte="Compte-001",
                                 materiel=[["Câble USB-C", mauvaise, ""]])
            self.assertIn("au moins 1", message)

    def test_un_refus_ne_touche_pas_le_sac_existant(self):
        self.poser()
        self.refus(compte="Compte-001", materiel=[["Inconnu", 1, ""]])
        self.assertEqual(Dotation.objects.count(), 1)

    def test_reserve_aux_administrateurs(self):
        with self.assertRaises(ErreurAction) as capture:
            executer("compte.dotations", "Compte-001",
                     {"compte": "Compte-001",
                      "materiel": [["Câble USB-C", 1, ""]]}, False)
        self.assertIn("réservée aux administrateurs", str(capture.exception))

    # -- article supprimé du catalogue ------------------------------------

    def test_un_article_supprime_laisse_une_ligne_visible(self):
        """Elle est signalée pour être corrigée, plutôt que de s'évaporer avec
        ce que la personne détient encore."""
        self.poser()
        Material.objects.filter(pk="Dell Latitude 5450 #3").delete()
        ligne = sacs("Admin", True)["Compte-001"][0]
        self.assertTrue(ligne["manquant"])
        self.assertEqual(ligne["libelle"], "Dell Latitude 5450 #3")
        self.assertEqual(ligne["etiquette"], "")

    # -- qui voit quoi ----------------------------------------------------

    def test_un_non_administrateur_ne_voit_que_son_sac(self):
        """La liste complète dirait qui détient quoi dans toute l'équipe."""
        self.poser(compte="Compte-001")
        self.poser(compte="Admin", materiel=[["Câble USB-C", 1, ""]])
        self.assertEqual(sorted(sacs("Admin", True)), ["Admin", "Compte-001"])
        self.assertEqual(list(sacs("Compte-001", False)), ["Compte-001"])

    def test_le_sac_supprime_avec_le_compte(self):
        self.poser()
        Compte.objects.filter(identifiant="Compte-001").delete()
        self.assertEqual(Dotation.objects.count(), 0)

    # -- contrat HTTP -----------------------------------------------------

    def test_l_api_envoie_les_sacs_dans_chaque_reponse(self):
        self.poser()
        self.client.login(identifiant="Admin", password=self.MOT_DE_PASSE)
        d = self.client.get(reverse("api_state")).json()
        ligne = d["dotations"]["Compte-001"][0]
        self.assertEqual((ligne["etiquette"], ligne["numeroSerie"]),
                         ("PC-003", "8KJ2NS5"))

    def test_l_api_filtre_les_sacs_pour_un_non_administrateur(self):
        self.poser(compte="Admin", materiel=[["Câble USB-C", 1, ""]])
        self.client.login(identifiant="Compte-001", password=self.MOT_DE_PASSE)
        d = self.client.get(reverse("api_state")).json()
        self.assertNotIn("Admin", d["dotations"])

    def test_l_action_passe_par_l_api(self):
        self.client.login(identifiant="Admin", password=self.MOT_DE_PASSE)
        reponse = self.client.post(
            reverse("api_action"),
            data=json.dumps({"action": "compte.dotations",
                             "params": {"compte": "Compte-001",
                                        "materiel": [["Dell Latitude 5450", 1, ""]]}}),
            content_type="application/json")
        self.assertEqual(reponse.status_code, 200)
        d = reponse.json()
        self.assertIn("Sac de « Compte-001 » mis à jour", d["resume"])
        # Le sac revient avec la réponse : l'interface n'a pas à le redemander.
        self.assertEqual(d["dotations"]["Compte-001"][0]["numeroSerie"], "8KJ2LQ3")
