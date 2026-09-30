# -*- coding: utf-8 -*-
"""Écriture dans les deux journaux.

Les lignes s'empilent **par le haut** : la plus récente porte le plus petit
rang, et les N dernières s'obtiennent donc par `ORDER BY seq LIMIT N`, sans
compter la table entière. C'est ce qui permet de ne renvoyer à l'interface que
les lignes ajoutées depuis sa dernière lecture.
"""

from django.db.models import Min
from django.utils import timezone

from ..models import MaterialLog, PhoneMovement


def _rang_suivant(modele):
    plus_petit = modele.objects.aggregate(m=Min("seq"))["m"]
    return 0 if plus_petit is None else plus_petit - 1


def mouvement(utilisateur, libelle, loc, genre):
    """Une ligne au journal des mouvements de téléphones."""
    return PhoneMovement.objects.create(
        seq=_rang_suivant(PhoneMovement),
        user=utilisateur or "—",
        label=libelle,
        loc=loc or "",
        kind=genre,
        horodatage=timezone.now(),
    )


def materiel(genre, article, quantite, qui="—", mission="—", commentaire="",
             identite=""):
    """Une ligne au journal du matériel.

    `identite` distingue l'exemplaire de ses jumeaux — étiquette, numéro de
    série. Elle est **recopiée ici** plutôt que retrouvée à la lecture :
    l'article peut être supprimé ou réétiqueté plus tard, la ligne doit
    continuer à dire ce qui est réellement sorti ce jour-là.
    """
    return MaterialLog.objects.create(
        seq=_rang_suivant(MaterialLog),
        kind=genre,
        item=article,
        qty=quantite,
        who=qui or "—",
        mission=mission or "—",
        commentaire=commentaire or "",
        identite=identite or "",
        horodatage=timezone.now(),
    )
