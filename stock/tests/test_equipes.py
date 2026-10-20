# -*- coding: utf-8 -*-
"""Les équipes d'une mission : des personnes, et leur matériel."""

from comptes.models import Compte
from stock.models import Equipe, MaterialReservation, Mission
from stock.services import ErreurAction, executer
from stock.services.equipes import equipes_json

from .socle import BaseStock


class Composition(BaseStock):

    def setUp(self):
        super().setUp()
        self.mission("Chantier Nord")
        self.mission("Chantier Sud")
        Compte.objects.create_user("Compte-001", "un-mot-de-passe")
        Compte.objects.create_user("Compte-002", "un-mot-de-passe")

    def equipe(self, nom="Équipe Nord", mission="Chantier Nord"):
        return self.agir("mission.equipe.creer", mission=mission, nom=nom)

    # -- création ---------------------------------------------------------

    def test_creation(self):
        self.equipe()
        e = Equipe.objects.get()
        self.assertEqual((e.mission_id, e.nom), ("Chantier Nord", "Équipe Nord"))

    def test_deux_equipes_de_meme_nom_dans_la_meme_mission_refusees(self):
        self.equipe()
        self.assertIn("existe déjà", self.refus("mission.equipe.creer",
                                               mission="Chantier Nord",
                                               nom="équipe nord"))

    def test_deux_missions_peuvent_avoir_la_meme_equipe(self):
        """« Équipe A » dans deux missions différentes est normal."""
        self.equipe(nom="Équipe A", mission="Chantier Nord")
        self.equipe(nom="Équipe A", mission="Chantier Sud")
        self.assertEqual(Equipe.objects.filter(nom="Équipe A").count(), 2)

    def test_une_mission_inconnue_refuse(self):
        self.assertIn("n'existe plus", self.refus("mission.equipe.creer",
                                                 mission="Jamais créée",
                                                 nom="Équipe A"))

    def test_reserve_aux_gestionnaires_et_aux_administrateurs(self):
        """Composer les équipes revient à la gestion de la mission, plus aux seuls
        administrateurs : un tiers est refusé, un administrateur passe."""
        with self.assertRaises(ErreurAction) as capture:
            executer("mission.equipe.creer", "Quelqu'un d'autre",
                     {"mission": "Chantier Nord", "nom": "Équipe A"}, False)
        self.assertIn("Réservé aux gestionnaires", str(capture.exception))
        executer("mission.equipe.creer", "Quelqu'un d'autre",
                 {"mission": "Chantier Nord", "nom": "Équipe A"}, True)
        self.assertEqual(Equipe.objects.count(), 1)

    def test_le_gestionnaire_de_la_mission_compose_ses_equipes(self):
        """Le créateur de la mission en est le gestionnaire par défaut."""
        executer("mission.equipe.creer", self.UTILISATEUR,
                 {"mission": "Chantier Nord", "nom": "Équipe A"}, False)
        self.assertEqual(Equipe.objects.count(), 1)

    # -- renommage --------------------------------------------------------

    def test_renommage_suit_le_materiel_attribue(self):
        """Une ligne d'emprunt dit où **est** le matériel, pas où il était."""
        self.equipe()
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=2,
                  mission="Chantier Nord", equipe="Équipe Nord")
        self.agir("mission.equipe.renommer", mission="Chantier Nord",
                  nom="Équipe Nord", nouveauNom="Équipe Alpha")
        self.assertEqual(MaterialReservation.objects.get().equipe, "Équipe Alpha")
        self.assertEqual(Equipe.objects.get().nom, "Équipe Alpha")

    def test_renommer_vers_un_nom_pris_refuse(self):
        self.equipe(nom="Équipe A")
        self.equipe(nom="Équipe B")
        message = self.refus("mission.equipe.renommer", mission="Chantier Nord",
                             nom="Équipe A", nouveauNom="Équipe B")
        self.assertIn("existe déjà", message)

    # -- suppression ------------------------------------------------------

    def test_suppression_refusee_si_elle_detient_du_materiel(self):
        self.equipe()
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=2,
                  mission="Chantier Nord", equipe="Équipe Nord")
        message = self.refus("mission.equipe.supprimer", mission="Chantier Nord",
                             nom="Équipe Nord")
        self.assertIn("détient encore", message)
        self.assertTrue(Equipe.objects.exists())

    def test_suppression_possible_apres_restitution(self):
        """Ce qui est rendu garde le nom de l'équipe dans l'historique."""
        self.equipe()
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=2,
                  mission="Chantier Nord", equipe="Équipe Nord")
        self.agir("materiel.mission.restituer", mission="Chantier Nord")
        self.agir("mission.equipe.supprimer", mission="Chantier Nord",
                  nom="Équipe Nord")
        self.assertFalse(Equipe.objects.exists())
        self.assertEqual(MaterialReservation.objects.get().equipe, "Équipe Nord")

    def test_les_equipes_partent_avec_leur_mission(self):
        self.equipe()
        Mission.objects.filter(pk="Chantier Nord").delete()
        self.assertFalse(Equipe.objects.exists())

    # -- membres ----------------------------------------------------------

    def test_composer_les_membres(self):
        self.equipe()
        self.agir("mission.equipe.membres", mission="Chantier Nord",
                  nom="Équipe Nord", membres=["Compte-001", "Compte-002"])
        self.assertEqual(
            sorted(Equipe.objects.get().membres.values_list("identifiant", flat=True)),
            ["Compte-001", "Compte-002"])

    def test_la_liste_des_membres_est_remplacee(self):
        self.equipe()
        self.agir("mission.equipe.membres", mission="Chantier Nord",
                  nom="Équipe Nord", membres=["Compte-001", "Compte-002"])
        self.agir("mission.equipe.membres", mission="Chantier Nord",
                  nom="Équipe Nord", membres=["Compte-002"])
        self.assertEqual(
            list(Equipe.objects.get().membres.values_list("identifiant", flat=True)),
            ["Compte-002"])

    def test_un_compte_inconnu_refuse(self):
        self.equipe()
        message = self.refus("mission.equipe.membres", mission="Chantier Nord",
                             nom="Équipe Nord", membres=["Personne"])
        self.assertIn("n'existe pas", message)
        self.assertEqual(Equipe.objects.get().membres.count(), 0)

    def test_le_meme_membre_deux_fois_refuse(self):
        self.equipe()
        message = self.refus("mission.equipe.membres", mission="Chantier Nord",
                             nom="Équipe Nord",
                             membres=["Compte-001", "Compte-001"])
        self.assertIn("deux fois", message)

    def test_un_compte_supprime_quitte_ses_equipes(self):
        """La composition est un état courant, pas un historique."""
        self.equipe()
        self.agir("mission.equipe.membres", mission="Chantier Nord",
                  nom="Équipe Nord", membres=["Compte-001"])
        Compte.objects.filter(identifiant="Compte-001").delete()
        self.assertEqual(Equipe.objects.get().membres.count(), 0)


class RepartitionDuMateriel(BaseStock):

    def setUp(self):
        super().setUp()
        self.mission("Chantier Nord")
        for nom in ("Équipe Nord", "Équipe Sud"):
            self.agir("mission.equipe.creer", mission="Chantier Nord", nom=nom)

    def emprunter(self, equipe=None, qty=2, nom="Chargeur USB-C 20 W"):
        params = {"nom": nom, "qty": qty, "mission": "Chantier Nord"}
        if equipe is not None:
            params["equipe"] = equipe
        return self.agir("materiel.emprunt", **params)

    def ligne(self):
        return MaterialReservation.objects.get()

    # -- au moment de l'emprunt -------------------------------------------

    def test_emprunter_pour_une_equipe(self):
        self.emprunter("Équipe Nord")
        self.assertEqual(self.ligne().equipe, "Équipe Nord")

    def test_sans_equipe_le_materiel_reste_au_niveau_mission(self):
        """Le cas des missions sans équipes, et de tout ce qui existait avant."""
        self.emprunter()
        self.assertEqual(self.ligne().equipe, "")

    def test_une_equipe_inconnue_refuse(self):
        message = self.refus("materiel.emprunt", nom="Chargeur USB-C 20 W",
                             qty=1, mission="Chantier Nord", equipe="Équipe Z")
        self.assertIn("n'existe pas dans", message)
        self.assertEqual(MaterialReservation.objects.count(), 0)

    def test_une_equipe_sans_mission_refuse(self):
        message = self.refus("materiel.emprunt", nom="Chargeur USB-C 20 W",
                             qty=1, equipe="Équipe Nord")
        self.assertIn("n'a de sens que dans une mission", message)

    def test_le_panier_groupe_part_dans_une_equipe(self):
        self.agir("materiel.emprunt.groupe", mission="Chantier Nord",
                  equipe="Équipe Sud",
                  lignes=[{"nom": "Chargeur USB-C 20 W", "qty": 1},
                          {"nom": "Câble Lightning 1 m", "qty": 1}])
        self.assertEqual({r.equipe for r in MaterialReservation.objects.all()},
                         {"Équipe Sud"})

    def test_un_pack_part_dans_une_equipe(self):
        self.agir("pack.creer", nom="Malette Nord",
                  lignes=[{"id": "Kit outils démontage", "qty": 1}])
        self.agir("pack.emprunt", pack="Malette Nord", mission="Chantier Nord",
                  equipe="Équipe Nord")
        r = MaterialReservation.objects.get()
        self.assertEqual((r.equipe, r.pack), ("Équipe Nord", "Malette Nord"))

    # -- déplacement après coup -------------------------------------------

    def test_deplacer_une_ligne_vers_une_equipe(self):
        """On rassemble le matériel de la mission, puis on le répartit."""
        self.emprunter()
        self.agir("materiel.equipe.affecter", nom="Chargeur USB-C 20 W",
                  index=0, equipe="Équipe Nord")
        self.assertEqual(self.ligne().equipe, "Équipe Nord")

    def test_deplacer_d_une_equipe_a_l_autre(self):
        self.emprunter("Équipe Nord")
        self.agir("materiel.equipe.affecter", nom="Chargeur USB-C 20 W",
                  index=0, equipe="Équipe Sud")
        self.assertEqual(self.ligne().equipe, "Équipe Sud")

    def test_retirer_une_ligne_de_son_equipe(self):
        self.emprunter("Équipe Nord")
        self.agir("materiel.equipe.affecter", nom="Chargeur USB-C 20 W",
                  index=0, equipe="")
        self.assertEqual(self.ligne().equipe, "")

    def test_le_deplacement_laisse_une_trace(self):
        self.emprunter("Équipe Nord")
        self.agir("materiel.equipe.affecter", nom="Chargeur USB-C 20 W",
                  index=0, equipe="Équipe Sud")
        trace = self.journal("AJUST.")[0]
        self.assertIn("Équipe Nord", trace.commentaire)
        self.assertIn("Équipe Sud", trace.commentaire)

    def test_deplacer_est_ouvert_a_tous(self):
        """Répartir n'est pas de l'organisation : c'est du travail courant."""
        self.emprunter()
        executer("materiel.equipe.affecter", self.UTILISATEUR,
                 {"nom": "Chargeur USB-C 20 W", "index": 0,
                  "equipe": "Équipe Nord"}, False)
        self.assertEqual(self.ligne().equipe, "Équipe Nord")

    def test_une_ligne_rendue_ne_change_plus_d_equipe(self):
        self.emprunter("Équipe Nord")
        self.agir("materiel.mission.restituer", mission="Chantier Nord")
        message = self.refus("materiel.equipe.affecter",
                             nom="Chargeur USB-C 20 W", index=0,
                             equipe="Équipe Sud")
        self.assertIn("déjà rendue", message)

    def test_une_ligne_sans_mission_n_a_pas_d_equipe(self):
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=1)
        message = self.refus("materiel.equipe.affecter",
                             nom="Chargeur USB-C 20 W", index=0,
                             equipe="Équipe Nord")
        self.assertIn("aucune mission", message)

    # -- restitution par équipe -------------------------------------------

    def test_restituer_une_seule_equipe(self):
        self.emprunter("Équipe Nord", qty=2)
        self.emprunter("Équipe Sud", qty=3, nom="Câble Lightning 1 m")
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  equipe="Équipe Nord")
        restants = [r for r in MaterialReservation.objects.all() if r.ouvert]
        self.assertEqual([(r.material_id, r.equipe) for r in restants],
                         [("Câble Lightning 1 m", "Équipe Sud")])

    def test_restituer_toute_la_mission_prend_toutes_les_equipes(self):
        self.emprunter("Équipe Nord", qty=2)
        self.emprunter("Équipe Sud", qty=3, nom="Câble Lightning 1 m")
        self.agir("materiel.mission.restituer", mission="Chantier Nord")
        self.assertFalse(any(r.ouvert for r in MaterialReservation.objects.all()))

    def test_restituer_ce_qui_n_a_pas_d_equipe(self):
        """Une chaîne vide explicite est une demande différente de l'absence."""
        self.emprunter(qty=2)
        self.emprunter("Équipe Nord", qty=3, nom="Câble Lightning 1 m")
        self.agir("materiel.mission.restituer", mission="Chantier Nord",
                  equipe="")
        restants = [r for r in MaterialReservation.objects.all() if r.ouvert]
        self.assertEqual([r.equipe for r in restants], ["Équipe Nord"])

    def test_restituer_une_equipe_vide_refuse(self):
        self.emprunter("Équipe Nord")
        message = self.refus("materiel.mission.restituer",
                             mission="Chantier Nord", equipe="Équipe Sud")
        self.assertIn("l'équipe « Équipe Sud »", message)


class EtatEnvoye(BaseStock):

    def test_les_equipes_arrivent_a_l_interface(self):
        self.mission("Chantier Nord")
        Compte.objects.create_user("Compte-001", "un-mot-de-passe")
        self.agir("mission.equipe.creer", mission="Chantier Nord",
                  nom="Équipe Nord")
        self.agir("mission.equipe.membres", mission="Chantier Nord",
                  nom="Équipe Nord", membres=["Compte-001"])
        self.assertEqual(equipes_json(),
                         [{"mission": "Chantier Nord", "nom": "Équipe Nord",
                           "ordre": 1, "membres": ["Compte-001"]}])

    def test_chaque_emprunt_dit_son_equipe(self):
        from stock import etat
        self.mission("Chantier Nord")
        self.agir("mission.equipe.creer", mission="Chantier Nord",
                  nom="Équipe Nord")
        self.agir("materiel.emprunt", nom="Chargeur USB-C 20 W", qty=2,
                  mission="Chantier Nord", equipe="Équipe Nord")
        _, st = etat.charger()
        self.assertEqual(st["matRes"]["Chargeur USB-C 20 W"][0]["equipe"],
                         "Équipe Nord")
        self.assertEqual(len(st["equipes"]), 1)
