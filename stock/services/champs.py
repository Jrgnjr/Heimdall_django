# -*- coding: utf-8 -*-
"""Lecture et validation des paramètres reçus de l'interface.

Les messages de refus sont repris **mot pour mot** de l'application Qt. Ce
sont eux que lit l'utilisateur ; les faire varier au passage à Django
n'apporterait rien et ferait mentir les tests qui servent de filet.

Ces fonctions ne connaissent rien du métier : elles disent seulement si un
paramètre est lisible. Ce qui est réalisable ou non se décide dans les modules
d'action.
"""

from datetime import datetime

from django.utils import timezone

from ..models import Material, Mission

QTE_MAX = 100_000          # au-delà, c'est une faute de frappe, pas un stock
TEXTE_MAX = 200
AFFECTATIONS = ["Groupe 1", "Groupe 2", "Groupe 3", "Commun"]
AFFECTATION_DEFAUT = "Commun"
SANS_MISSION = Mission.SANS_MISSION


class ErreurAction(Exception):
    """Refus métier : la demande est comprise, mais elle n'est pas réalisable.

    Son message est destiné à être lu par un humain dans l'interface, qui
    l'affiche tel quel. La vue la traduit en HTTP 422.
    """


def qte(params, cle="qty", mini=1):
    valeur = params.get(cle)
    try:
        n = int(valeur)
    except (TypeError, ValueError):
        raise ErreurAction("La quantité doit être un nombre entier.")
    if n < mini:
        raise ErreurAction("La quantité doit être d'au moins %d." % mini)
    if n > QTE_MAX:
        raise ErreurAction("Quantité irréaliste (%d)." % n)
    return n


def texte(params, cle, obligatoire=True, defaut="", maxi=TEXTE_MAX):
    valeur = params.get(cle)
    valeur = "" if valeur is None else str(valeur).strip()
    if not valeur:
        if obligatoire:
            raise ErreurAction("Le champ « %s » est obligatoire." % cle)
        return defaut
    if len(valeur) > maxi:
        raise ErreurAction("Le champ « %s » est trop long (%d caractères, "
                           "maximum %d)." % (cle, len(valeur), maxi))
    return valeur


def entier(params, cle, mini, maxi):
    try:
        n = int(params.get(cle))
    except (TypeError, ValueError):
        raise ErreurAction("Le champ « %s » doit être un nombre entier." % cle)
    if not mini <= n <= maxi:
        raise ErreurAction("Le champ « %s » doit être compris entre %d et %d."
                           % (cle, mini, maxi))
    return n


def affectation(params, cle="affectation", obligatoire=False):
    """Étiquette d'affectation, choisie dans une liste fermée.

    `obligatoire` distingue deux situations. À la création d'un article, ne
    rien préciser vaut « Commun ». Mais sur une demande de changement, une
    valeur absente ne peut pas valoir « Commun » : ce serait affecter
    l'article à autre chose que ce qui a été demandé.
    """
    brut = params.get(cle)
    if brut is None or not str(brut).strip():
        if obligatoire:
            raise ErreurAction("Aucune affectation indiquée.")
        return AFFECTATION_DEFAUT
    valeur = texte(params, cle, maxi=20)
    if valeur not in AFFECTATIONS:
        raise ErreurAction("Affectation inconnue : « %s ». Valeurs acceptées : %s."
                           % (valeur, ", ".join(AFFECTATIONS)))
    return valeur


def date_prevue(params, cle="date"):
    """Date prévue d'une mission : une vraie date, ou rien.

    Elle vient d'un champ <input type="date">, qui produit toujours de l'ISO.
    """
    valeur = texte(params, cle, obligatoire=False)
    if not valeur:
        return None
    try:
        return datetime.strptime(valeur, "%Y-%m-%d").date()
    except ValueError:
        raise ErreurAction("Date invalide (format attendu : AAAA-MM-JJ).")


def iso(moment):
    """Horodatage tel que l'interface le reçoit et le resigne.

    Doit rester identique à ce que produisait l'application Qt : l'interface
    calcule des empreintes de lignes à partir de cette chaîne, et un format
    différent ferait échouer toutes les résolutions de réservation.
    """
    if moment is None:
        return ""
    if timezone.is_aware(moment):
        moment = timezone.localtime(moment)
    return moment.isoformat(sep=" ")


def empreinte(objet):
    """Signature d'une ligne, pour détecter qu'elle a changé sous nos pieds.

    Doit rester identique à `empreinte()` d'index.html, y compris la forme de
    l'horodatage : l'interface signe avec ce qu'on lui a envoyé.
    """
    if isinstance(objet, Material) or hasattr(objet, "taken_by"):
        return "%s|%s|%s" % (objet.qty, objet.mission, objet.taken_by)
    return "%s|%s|%s|%s" % (objet.who, objet.qty, objet.variant_idx,
                            iso(objet.horodatage))


def ligne(liste, params, description, cle="index"):
    """Retrouve une ligne par sa position, en vérifiant son empreinte.

    L'interface ne connaît les réservations, sorties et emprunts que par leur
    rang dans une liste. Si quelqu'un en a supprimé un entre-temps, ce rang
    désigne désormais une autre ligne : l'empreinte permet de s'en apercevoir
    et de refuser, plutôt que d'agir sur la mauvaise.
    """
    try:
        i = int(params.get(cle))
    except (TypeError, ValueError):
        raise ErreurAction("Ligne non identifiée.")
    if not 0 <= i < len(liste):
        raise ErreurAction("Cette %s n'existe plus. Rechargez la page." % description)
    objet = liste[i]
    attendue = params.get("empreinte")
    if attendue is not None and str(attendue) != empreinte(objet):
        raise ErreurAction("Cette %s a été modifiée par quelqu'un d'autre. "
                           "Rechargez la page et recommencez." % description)
    return objet
