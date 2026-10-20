# -*- coding: utf-8 -*-
"""Les prêts de matériel personnel : se demander, accepter, refuser.

Le sac d'une personne lui appartient : on ne s'y sert pas, on le lui demande.
Une demande suit un chemin court :

    en attente ──accepter──▶ acceptée   (le matériel sort à l'emprunteur)
        │
        ├────refuser─────▶ refusée     (avec, au besoin, une raison)
        └────annuler─────▶ annulée     (par celui qui avait demandé)

Une demande acceptée devient un **emprunt ordinaire** (`MaterialReservation`),
marqué du sac qui l'a consenti (`sac_de`). Elle entre donc sans rien de plus dans
la mission, dans le journal et dans les écrans de retour ; et au retour, le
matériel regagne simplement le sac, qui n'a jamais été vidé.

Disponibilité : une ligne de sac porte une quantité ; ce qui est déjà prêté en est
retranché. Elle est vérifiée à la demande, puis **de nouveau** à l'acceptation —
entre les deux, le sac a pu prêter ailleurs.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from comptes.models import Compte, Dotation

from ..models import (DemandePret, Equipe, Material, MaterialReservation,
                      Mission)
from . import action, journaux
from .champs import ErreurAction, qte, texte
from .gestion import effectifs_de, exiger_gestion
from .materiel import creer_emprunt, mission_demandee, mission_existante

SANS_MISSION = Mission.SANS_MISSION
MAX_EN_ATTENTE = 30
HISTORIQUE = timedelta(days=30)


# --------------------------------------------------------------------------
# Disponibilité
# --------------------------------------------------------------------------

def _ouverts():
    return MaterialReservation.objects.filter(returned_by__isnull=True,
                                              returned_at__isnull=True)


def disponible_sac(ligne, materiel):
    """Ce qu'une ligne de sac peut encore prêter."""
    prete = sum(r.qty for r in _ouverts().filter(sac_de=ligne.compte_id,
                                                  material=materiel))
    return max(0, min(ligne.quantite - prete, materiel.disponible()))


def _ligne_de_sac(proprietaire, cle):
    ligne = Dotation.objects.filter(compte_id=proprietaire, material_id=cle).first()
    materiel = Material.objects.filter(pk=cle).first()
    if ligne is None or materiel is None:
        raise ErreurAction(
            "« %s » n'a plus cet article dans son sac. Rechargez la page."
            % proprietaire)
    return ligne, materiel


def _membres(mission):
    """Les comptes de l'effectif de la mission (voir `services/gestion.py`)."""
    return effectifs_de(mission)


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

@action("pret.demander")
def pret_demander(utilisateur, p):
    proprietaire = texte(p, "proprietaire", maxi=150)
    cle = texte(p, "article", maxi=200)
    n = qte(p)
    mission = mission_demandee(p)
    motif = texte(p, "motif", obligatoire=False, maxi=300)

    if proprietaire == utilisateur:
        raise ErreurAction("Le matériel de votre propre sac est déjà à vous.")
    if not Compte.objects.filter(pk=proprietaire, actif=True).exists():
        raise ErreurAction("Le compte « %s » n'existe pas." % proprietaire)
    ligne, materiel = _ligne_de_sac(proprietaire, cle)

    libre = disponible_sac(ligne, materiel)
    if n > libre:
        raise ErreurAction(
            "Le sac de « %s » ne peut prêter que %d × %s (%d demandé(s))."
            % (proprietaire, libre, materiel.nom_affiche, n))

    nom_mission = mission.name if mission else SANS_MISSION
    if mission is not None:
        if mission.archived:
            raise ErreurAction("La mission « %s » est archivée." % mission.name)
        if proprietaire in _membres(mission.name):
            raise ErreurAction(
                "« %s » fait partie de la mission « %s » : il emporte déjà son "
                "sac." % (proprietaire, mission.name))

    en_attente = DemandePret.objects.filter(demandeur=utilisateur,
                                            statut=DemandePret.EN_ATTENTE)
    if en_attente.filter(proprietaire=proprietaire, material_id=cle,
                         mission=nom_mission).exists():
        raise ErreurAction("Vous avez déjà fait cette demande : elle attend la "
                           "réponse de « %s »." % proprietaire)
    if en_attente.count() >= MAX_EN_ATTENTE:
        raise ErreurAction("Trop de demandes en attente (%d). Attendez des "
                           "réponses, ou annulez-en." % MAX_EN_ATTENTE)

    DemandePret.objects.create(
        demandeur=utilisateur, proprietaire=proprietaire, material_id=cle,
        quantite=n, mission=nom_mission, motif=motif)
    return ("Demande envoyée à « %s » : %d × %s" % (proprietaire, n, materiel.nom_affiche), [])


def _demande(p, utilisateur, role):
    """La demande en attente désignée, pour la personne qui a le droit d'y répondre."""
    pk = qte({"id": p.get("id")}, cle="id")
    d = DemandePret.objects.filter(pk=pk).first()
    if d is None:
        raise ErreurAction("Cette demande n'existe plus. Rechargez la page.")
    if getattr(d, role) != utilisateur:
        raise ErreurAction("Cette demande ne vous est pas adressée."
                           if role == "proprietaire"
                           else "Cette demande n'est pas la vôtre.")
    if d.statut != DemandePret.EN_ATTENTE:
        raise ErreurAction("Cette demande a déjà reçu une réponse (%s)." % d.statut.lower())
    return d


@action("pret.accepter")
def pret_accepter(utilisateur, p):
    d = _demande(p, utilisateur, "proprietaire")
    ligne, materiel = _ligne_de_sac(utilisateur, d.material_id)

    libre = disponible_sac(ligne, materiel)
    if d.quantite > libre:
        raise ErreurAction(
            "Il ne reste que %d × %s disponible(s) dans votre sac, pour %d "
            "demandé(s). Refusez, ou attendez un retour." % (libre, materiel.nom_affiche, d.quantite))

    if d.mission != SANS_MISSION:
        mission = mission_existante(d.mission)
        if mission.archived:
            raise ErreurAction("La mission « %s » est archivée : refusez la demande." % d.mission)

    creer_emprunt(materiel, d.quantite, d.mission, d.demandeur, sac_de=utilisateur)
    journaux.materiel("SORTIE", materiel.nom_affiche, d.quantite, d.demandeur, d.mission,
                      "Prêté par %s" % utilisateur, materiel.identite)
    d.statut = DemandePret.ACCEPTEE
    d.repondu_le = timezone.now()
    d.save(update_fields=["statut", "repondu_le"])
    return ("Prêt accordé à « %s » : %d × %s" % (d.demandeur, d.quantite, materiel.nom_affiche),
            [["materiel", materiel.name], ["matLog", ""]])


@action("pret.forcer")
def pret_forcer(utilisateur, p):
    """Accorde un prêt **sans attendre la réponse** de celui dont le sac le prête.

    Pour une mission : le gestionnaire qui en a la charge peut avoir besoin du
    matériel d'une personne absente, ou sans accès à la plateforme — à qui l'on ne
    peut donc pas demander. Réservé aux gestionnaires de la mission et aux
    administrateurs.

    Ce n'est pas un passe-droit discret : le prêt est marqué comme **forcé** et
    nomme celui qui l'a forcé, ce que le prêteur lit dans « Mes prêts », et le
    journal en garde la trace. Les règles de fond demeurent : le sac doit
    contenir l'article en quantité suffisante, et on ne prend pas à quelqu'un de
    l'effectif, qui emporte déjà son sac.

    `pour` désigne l'emprunteur ; à défaut, c'est celui qui force.
    """
    nom_mission = texte(p, "mission", maxi=200)
    mission = mission_existante(nom_mission)
    exiger_gestion(mission.name, utilisateur, p)

    proprietaire = texte(p, "proprietaire", maxi=150)
    cle = texte(p, "article", maxi=200)
    n = qte(p)
    pour = texte(p, "pour", obligatoire=False, maxi=150) or utilisateur

    if proprietaire == pour:
        raise ErreurAction("Le matériel du sac de « %s » est déjà à lui." % pour)
    if not Compte.objects.filter(pk=proprietaire, actif=True).exists():
        raise ErreurAction("Le compte « %s » n'existe pas." % proprietaire)
    if not Compte.objects.filter(pk=pour, actif=True).exists():
        raise ErreurAction("Le compte « %s » n'existe pas." % pour)
    if mission.archived:
        raise ErreurAction("La mission « %s » est archivée." % mission.name)
    if proprietaire in _membres(mission.name):
        raise ErreurAction(
            "« %s » fait partie de la mission « %s » : il emporte déjà son sac."
            % (proprietaire, mission.name))

    ligne, materiel = _ligne_de_sac(proprietaire, cle)
    libre = disponible_sac(ligne, materiel)
    if n > libre:
        raise ErreurAction(
            "Le sac de « %s » ne peut prêter que %d × %s (%d demandé(s))."
            % (proprietaire, libre, materiel.nom_affiche, n))

    creer_emprunt(materiel, n, mission.name, pour, sac_de=proprietaire,
                  force_par=utilisateur)
    journaux.materiel("SORTIE", materiel.nom_affiche, n, pour, mission.name,
                      "Prêt forcé par %s depuis le sac de %s" % (utilisateur, proprietaire),
                      materiel.identite)
    return ("Prêt forcé : %d × %s du sac de « %s » pour « %s »"
            % (n, materiel.nom_affiche, proprietaire, mission.name),
            [["materiel", materiel.name], ["matLog", ""], ["mission", mission.name]])


@action("pret.refuser")
def pret_refuser(utilisateur, p):
    d = _demande(p, utilisateur, "proprietaire")
    d.statut = DemandePret.REFUSEE
    d.raison_refus = texte(p, "raison", obligatoire=False, maxi=300)
    d.repondu_le = timezone.now()
    d.save(update_fields=["statut", "raison_refus", "repondu_le"])
    return "Demande de « %s » refusée" % d.demandeur, []


@action("pret.annuler")
def pret_annuler(utilisateur, p):
    d = _demande(p, utilisateur, "demandeur")
    d.statut = DemandePret.ANNULEE
    d.repondu_le = timezone.now()
    d.save(update_fields=["statut", "repondu_le"])
    return "Demande à « %s » annulée" % d.proprietaire, []


@action("pret.rendu")
def pret_rendu(utilisateur, p):
    """Le prêteur constate que son matériel lui est revenu."""
    pk = qte({"id": p.get("id")}, cle="id")
    r = _ouverts().filter(pk=pk).select_related("material").first()
    if r is None:
        raise ErreurAction("Ce prêt n'existe plus ou est déjà rendu. Rechargez la page.")
    if r.sac_de != utilisateur:
        raise ErreurAction("Ce prêt n'est pas le vôtre.")
    m = r.material
    quantite, mission = r.qty, r.mission
    r.delete()
    journaux.materiel("RETOUR", m.nom_affiche, quantite, utilisateur, mission,
                      "Revenu dans le sac de %s" % utilisateur, m.identite)
    return ("Retour de %d × %s dans votre sac" % (quantite, m.nom_affiche),
            [["materiel", m.name], ["matLog", ""]])


# --------------------------------------------------------------------------
# Lecture : ce que voit chacun
# --------------------------------------------------------------------------

def _iso(horodatage):
    return horodatage.isoformat() if horodatage else None


def etat_prets(compte):
    """Ce qui concerne `compte`, tel que l'interface le lit.

    - `recues` : demandes qui attendent **sa** réponse ;
    - `emises` : celles qu'il a faites, en attente ou récentes (réponse, raison) ;
    - `prets` : ce que son sac a prêté et qui n'est pas revenu ;
    - `sacs` : le contenu des **autres** sacs, de quoi choisir à qui demander ;
    - `missions` : les demandes en attente qui portent sur une mission dont il
      est **responsable**, et qui ne le concernent pas autrement — de quoi les
      voir sur la carte de la mission sans avoir à les traiter.

    Les demandes des autres ne sont jamais envoyées : n'en voient le contenu que
    les deux personnes concernées, et le responsable de la mission visée.
    """
    materiaux = {m.name: m for m in Material.objects.all()}

    def identite(cle):
        m = materiaux.get(cle)
        return (m.libelle or m.name) if m else cle, (m.identite if m else "")

    pretes = {}
    for r in _ouverts().exclude(sac_de=""):
        cle = (r.sac_de, r.material_id)
        pretes[cle] = pretes.get(cle, 0) + r.qty

    recues = []
    for d in DemandePret.objects.filter(proprietaire=compte, statut=DemandePret.EN_ATTENTE):
        libelle, detail = identite(d.material_id)
        m = materiaux.get(d.material_id)
        ligne = Dotation.objects.filter(compte_id=compte, material_id=d.material_id).first()
        recues.append({
            "id": d.pk, "de": d.demandeur, "article": d.material_id,
            "libelle": libelle, "detail": detail, "quantite": d.quantite,
            "mission": d.mission, "motif": d.motif, "iso": _iso(d.cree_le),
            "disponible": disponible_sac(ligne, m) if (ligne and m) else 0})

    depuis = timezone.now() - HISTORIQUE
    emises = []
    visibles = DemandePret.objects.filter(demandeur=compte).filter(
        Q(statut=DemandePret.EN_ATTENTE) | Q(cree_le__gte=depuis))[:60]
    for d in visibles:
        libelle, detail = identite(d.material_id)
        emises.append({
            "id": d.pk, "a": d.proprietaire, "libelle": libelle, "detail": detail,
            "quantite": d.quantite, "mission": d.mission, "motif": d.motif,
            "statut": d.statut, "raison": d.raison_refus,
            "iso": _iso(d.cree_le), "repondu": _iso(d.repondu_le)})

    prets = []
    for r in _ouverts().filter(sac_de=compte).order_by("taken_at"):
        libelle, detail = identite(r.material_id)
        prets.append({
            "id": r.pk, "article": r.material_id, "libelle": libelle,
            "detail": detail, "quantite": r.qty, "a": r.taken_by,
            "mission": r.mission, "iso": _iso(r.taken_at),
            "forcePar": r.force_par})

    actifs = set(Compte.objects.filter(actif=True).values_list("identifiant", flat=True))
    sacs = {}
    for d in Dotation.objects.exclude(compte_id=compte):
        if d.compte_id not in actifs:
            continue
        m = materiaux.get(d.material_id)
        if m is None:
            continue
        libre = max(0, min(d.quantite - pretes.get((d.compte_id, d.material_id), 0),
                           m.disponible()))
        sacs.setdefault(d.compte_id, []).append({
            "article": d.material_id, "libelle": m.libelle or m.name,
            "detail": " · ".join(x for x in (m.identite, d.detail) if x),
            "cat": m.cat, "quantite": d.quantite, "disponible": libre})

    missions = []
    mes_missions = list(Mission.objects.filter(owner=compte).values_list("name", flat=True))
    if mes_missions:
        sur_mes_missions = (DemandePret.objects
                            .filter(statut=DemandePret.EN_ATTENTE, mission__in=mes_missions)
                            .exclude(demandeur=compte).exclude(proprietaire=compte))
        for d in sur_mes_missions:
            libelle, detail = identite(d.material_id)
            missions.append({
                "id": d.pk, "de": d.demandeur, "a": d.proprietaire,
                "libelle": libelle, "detail": detail, "quantite": d.quantite,
                "mission": d.mission, "motif": d.motif, "iso": _iso(d.cree_le)})

    return {"recues": recues, "emises": emises, "prets": prets, "sacs": sacs,
            "missions": missions}
