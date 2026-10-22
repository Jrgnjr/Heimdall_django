# -*- coding: utf-8 -*-
"""Qui gère une mission, et qui en fait partie.

Deux rôles, **exclusifs** sur une même mission :

- **gestionnaire** : il en a la charge. Il compose l'effectif, force au besoin des
  prêts dans le sac d'une personne absente, et peut revenir en arrière sur les
  statuts. Il peut y en avoir plusieurs ; celui qui crée la mission les désigne,
  et en fait partie par défaut ;
- **effectif** : il est de la mission, dans une de ses équipes. Il emporte son sac
  — ce qui est la raison pour laquelle on ne lui demande pas de prêt pour elle.

Une même personne ne peut pas être les deux sur la même mission : on la gère, ou
on y travaille. Le contrôle se fait **des deux côtés** — nommer gestionnaire
quelqu'un de l'effectif, ou le mettre dans une équipe alors qu'il gère — et il ne
porte que sur ce qu'on ajoute : un état antérieur n'est pas rétroactivement
refusé.

Un administrateur a les droits d'un gestionnaire sur **toutes** les missions.

Compatibilité : une mission créée avant cette règle n'a pas de gestionnaire
enregistré ; son créateur (`owner`) fait alors office de gestionnaire, tant qu'on
n'en désigne pas explicitement.
"""

from comptes.models import Compte

from ..models import Equipe, GestionMission, Mission
from . import action
from .champs import ErreurAction, texte


# --------------------------------------------------------------------------
# Lectures
# --------------------------------------------------------------------------

def gestionnaires_de(nom):
    """Les gestionnaires d'une mission, par ordre alphabétique."""
    explicites = list(GestionMission.objects.filter(mission_id=nom)
                      .values_list("compte", flat=True))
    if explicites:
        return sorted(explicites)
    m = Mission.objects.filter(pk=nom).first()
    return [m.owner] if (m and m.owner) else []


def effectifs_de(nom):
    """Les comptes membres d'une équipe de la mission."""
    return {identifiant
            for e in Equipe.objects.filter(mission_id=nom).prefetch_related("membres")
            for identifiant in e.membres.values_list("identifiant", flat=True)}


def peut_gerer(nom, utilisateur, administrateur):
    """Un gestionnaire de la mission, ou un administrateur."""
    return bool(administrateur) or utilisateur in gestionnaires_de(nom)


def exiger_gestion(nom, utilisateur, p, ce_qui=None):
    """Refuse, en le disant, à qui n'a pas la gestion de cette mission.

    Les droits se jugent sur l'**acteur** — la personne réellement connectée —, pas
    sur l'auteur au nom de qui l'on agit (voir `droits.py`).
    """
    from .droits import acteur
    if peut_gerer(nom, acteur(p, utilisateur), p.get("_administrateur")):
        return
    raise ErreurAction(
        "%séservé aux gestionnaires de la mission « %s » (%s) et aux "
        "administrateurs." % (ce_qui + " : r" if ce_qui else "R", nom,
                              ", ".join(gestionnaires_de(nom)) or "aucun"))


def gestion_par_mission():
    """{mission: [gestionnaires]} pour toutes les missions, en une passe."""
    explicites = {}
    for ligne in GestionMission.objects.all():
        explicites.setdefault(ligne.mission_id, []).append(ligne.compte)
    resultat = {}
    for m in Mission.objects.all():
        liste = sorted(explicites.get(m.name, [])) or ([m.owner] if m.owner else [])
        if liste:
            resultat[m.name] = liste
    return resultat


# --------------------------------------------------------------------------
# Désignation
# --------------------------------------------------------------------------

def valider_gestionnaires(brut):
    """La liste des gestionnaires envoyée, validée : comptes actifs, sans doublon, au
    moins un. Un gestionnaire peut très bien être aussi membre d'une équipe."""
    if not isinstance(brut, list) or not brut:
        raise ErreurAction("Une mission a besoin d'au moins un gestionnaire.")
    if len(brut) > 50:
        raise ErreurAction("Trop de gestionnaires pour une seule mission.")
    liste, vus = [], set()
    for valeur in brut:
        identifiant = texte({"g": valeur}, "g", maxi=150)
        if identifiant in vus:
            raise ErreurAction("« %s » figure deux fois parmi les gestionnaires." % identifiant)
        vus.add(identifiant)
        if not Compte.objects.filter(pk=identifiant, actif=True).exists():
            raise ErreurAction("Le compte « %s » n'existe pas." % identifiant)
        liste.append(identifiant)
    return liste


def poser_gestionnaires(mission, liste):
    GestionMission.objects.filter(mission=mission).delete()
    GestionMission.objects.bulk_create(
        [GestionMission(mission=mission, compte=c) for c in liste])


@action("mission.gestion")
def mission_gestion(utilisateur, p):
    """Remplace les gestionnaires d'une mission.

    Réservé aux gestionnaires en place et aux administrateurs. Remplacer plutôt
    qu'ajouter et retirer un à un, comme pour les membres d'une équipe : l'écran
    envoie la liste telle qu'il l'affiche.
    """
    nom = texte(p, "mission", maxi=200)
    mission = Mission.objects.filter(pk=nom).first()
    if mission is None:
        raise ErreurAction("La mission « %s » n'existe plus. Rechargez la page." % nom)
    exiger_gestion(nom, utilisateur, p)

    liste = valider_gestionnaires(p.get("gestionnaires"))
    poser_gestionnaires(mission, liste)
    return ("Gestion de « %s » : %s" % (nom, ", ".join(sorted(liste))),
            [["mission", nom]])
