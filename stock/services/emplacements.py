# -*- coding: utf-8 -*-
"""Où se trouve une référence.

Le placement automatique est calculé, jamais stocké : seuls les casiers choisis
à la main sont enregistrés. Recalculer à la demande évite qu'une base
contienne des emplacements devenus faux après un redimensionnement d'armoire.
"""

from ..models import Cabinet, PhoneModel, SlotAssignment
from ..placement import construire_casiers, placement
from .champs import ErreurAction

NON_PLACE = "NON PLACÉ"


def armoires():
    return [(c.id, c.shelves, c.cols) for c in Cabinet.objects.all()]


def casiers_fixes():
    return {a.phone_id: a.loc for a in SlotAssignment.objects.all()}


def carte(extra=None):
    """{ref_id: casier ou None} pour toutes les références."""
    refs = [(r.id, r.brand) for r in PhoneModel.objects.all()]
    return placement(armoires(), refs, casiers_fixes(), extra)


def emplacement_de(ref_id, extra=None):
    casier = carte(extra).get(ref_id)
    return casier["loc"] if casier else NON_PLACE


def verifier_casier(loc):
    """Un emplacement doit exister réellement dans une armoire."""
    for cab_id, etageres, colonnes in armoires():
        for e in range(1, etageres + 1):
            for k in range(1, colonnes + 1):
                if loc == "%s·E%d·C%d" % (cab_id, e, k):
                    return
    raise ErreurAction("L'emplacement %s n'existe pas." % loc)


def tous_les_casiers():
    return [c["loc"] for c in construire_casiers(armoires())]
