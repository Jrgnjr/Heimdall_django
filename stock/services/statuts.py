# -*- coding: utf-8 -*-
"""L'ordre des statuts d'une mission : on avance, on ne recule pas.

    PRÉVUE ──▶ EN COURS ──▶ TERMINÉE            ANNULÉE (à part)

Deux choses gouvernent le statut, et chacune a sa règle de non-régression :

**Le statut calculé** — qui avance seul avec la date et les emprunts — ne doit pas
revenir en arrière non plus. Or il le pourrait : rendre le dernier emprunt d'une
mission sans date la ramène à « prévue » ; repousser sa date aussi ; lui
affecter du matériel après sa fin la remet « en cours ». C'est pourquoi chaque
mission retient le **plus haut statut atteint** (`status_max`), qui sert de
plancher : le statut affiché n'est jamais inférieur à lui.

Le plancher doit être posé **avant** ce qui pourrait faire régresser le calcul :
`figer_statuts()` est donc appelé au début de chaque action, par `stock.api`.

**Le statut imposé à la main** — par le menu de la carte — suit la même règle,
avec une exception : le gestionnaire de la mission (celui qui l'a créée) et les
administrateurs peuvent revenir en arrière. Tout le monde peut avancer ou annuler.

« Annulée » n'est pas un cran de l'échelle. Y entrer est permis tant que la
mission n'est pas terminée ; en sortir, ou annuler une mission terminée, c'est
revenir sur ce qui était acquis, et revient donc au gestionnaire et aux
administrateurs.
"""

from collections import defaultdict

from django.utils import timezone

from ..models import MaterialReservation, Mission

ORDRE = (Mission.PREVUE, Mission.EN_COURS, Mission.TERMINEE)


def rang(statut):
    return ORDRE.index(statut) if statut in ORDRE else None


def peut_reculer(mission, utilisateur, administrateur):
    """Un gestionnaire de la mission, ou un administrateur."""
    from .gestion import peut_gerer
    return peut_gerer(mission.name, utilisateur, administrateur)


def changement_permis(actuel, voulu, mission, reculer):
    """(permis, message de refus). Doit rester identique à
    `changementStatutPermis()` d'index.html."""
    if voulu == actuel:
        return True, ""
    from .gestion import gestionnaires_de
    gestionnaires = ", ".join(gestionnaires_de(mission.name)) or "son créateur"
    reserve = ("Seul un gestionnaire de la mission (%s) ou un administrateur "
               "peut le faire." % gestionnaires)
    if actuel == Mission.ANNULEE:
        if reculer:
            return True, ""
        return False, "Une mission annulée ne se rouvre pas. " + reserve
    if voulu == Mission.ANNULEE:
        if actuel == Mission.TERMINEE and not reculer:
            return False, "Une mission terminée ne s'annule pas. " + reserve
        return True, ""
    if rang(voulu) < rang(actuel) and not reculer:
        return False, ("Un statut ne revient pas en arrière (%s → %s). %s"
                       % (actuel, voulu, reserve))
    return True, ""


def statut_de(nom, aujourdhui=None):
    """Le statut d'une mission par son nom, qu'elle ait ou non sa ligne."""
    mission = Mission.objects.filter(pk=nom).first() or Mission(name=nom)
    lignes = list(MaterialReservation.objects.filter(mission=nom))
    return mission.statut(lignes, aujourdhui or timezone.localdate())


def figer_statuts(aujourdhui=None):
    """Retient, pour chaque mission, le plus haut statut atteint jusqu'ici."""
    aujourdhui = aujourdhui or timezone.localdate()
    par_mission = defaultdict(list)
    for r in MaterialReservation.objects.all():
        par_mission[r.mission].append(r)
    for m in Mission.objects.all():
        statut = m.statut(par_mission.get(m.name, []), aujourdhui)
        if rang(statut) is not None and (rang(m.status_max) is None
                                         or rang(statut) > rang(m.status_max)):
            m.status_max = statut
            m.save(update_fields=["status_max"])
