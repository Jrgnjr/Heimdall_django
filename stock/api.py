# -*- coding: utf-8 -*-
"""Les deux points d'entrée que l'interface interroge.

    GET  /api/state           -> {"version": V, "state": {...}}
    GET  /api/state?since=N   -> {"changed": false, "version": N}
                              ou {"changed": true, "version": V, "delta": {...}}
                              ou {"changed": true, "version": V, "state": {...}}
    POST /api/action          -> 200 {"ok", "version", "delta", "user", "resume"}
                              -> 422 {"error"} pour un refus métier

Deux codes ont un sens précis pour l'interface, qui s'en sert pour rediriger
elle-même : **401** veut dire « pas connecté », **403** veut dire « mot de passe
à changer ». Les confondre enverrait l'utilisateur sur le mauvais écran.
"""

import json

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import etat
from .models import MaterialLog, Operation, PhoneMovement, Version
from .services import ACTIONS, ErreurAction, executer


# --------------------------------------------------------------------------
# Garde
# --------------------------------------------------------------------------

def _refus_session(request):
    """401 si personne n'est connecté, 403 si le mot de passe doit changer.

    Retourne une réponse à renvoyer telle quelle, ou None si la requête peut
    continuer.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Session expirée."}, status=401)
    if request.user.doit_changer:
        return JsonResponse(
            {"error": "Mot de passe à renouveler avant toute action."},
            status=403)
    return None


def _comptes(request):
    """Les identifiants proposables comme auteur d'une action.

    Seul un administrateur peut agir au nom d'un autre — pour enregistrer une
    sortie que quelqu'un a faite sans se connecter. La liste ne lui est envoyée
    que dans ce cas : elle n'aurait aucun usage ailleurs, et la donner
    renseignerait sur la composition de l'équipe.
    """
    if not request.user.administrateur:
        return []
    from comptes.models import Compte
    return list(Compte.objects.filter(actif=True)
                .values_list("identifiant", flat=True))


def _enveloppe(request, charge):
    charge.update({
        "user": request.user.identifiant,
        "admin": bool(request.user.administrateur),
        "comptes": _comptes(request),
    })
    return charge


def _auteur_effectif(request, params):
    """Au nom de qui l'action est enregistrée.

    Un administrateur peut emprunter l'identité d'un autre compte ; n'importe
    qui d'autre agit forcément en son nom. La vérification est ici et pas dans
    l'interface : un paramètre `auteur` fabriqué à la main ne doit pas suffire.
    """
    demande = (params or {}).get("auteur")
    if not demande:
        return request.user.identifiant
    demande = str(demande).strip()
    if demande == request.user.identifiant:
        return demande
    if not request.user.administrateur:
        raise ErreurAction("Vous ne pouvez pas agir au nom d'un autre compte.")
    if demande not in _comptes(request):
        raise ErreurAction("Le compte « %s » n'existe pas." % demande)
    return demande


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

@require_GET
@ensure_csrf_cookie
def state(request):
    """L'état, complet ou différentiel.

    `ensure_csrf_cookie` parce que c'est le premier appel que fait l'interface :
    c'est lui qui doit déposer le jeton qu'elle renverra ensuite en en-tête.
    """
    refus = _refus_session(request)
    if refus is not None:
        return refus

    brut = request.GET.get("since")
    if brut is None:
        version, complet = etat.charger()
        charge = {"version": version}
        if complet is not None:
            charge["state"] = complet
        return JsonResponse(_enveloppe(request, charge))

    try:
        depuis = int(brut)
    except (TypeError, ValueError):
        depuis = 0

    courante, delta = etat.charger_delta(depuis)
    if delta == {} and depuis >= courante:
        return JsonResponse(_enveloppe(request,
                                       {"changed": False, "version": courante}))
    if delta is None:
        # Trop en retard, ou modification faite hors des actions : l'état
        # complet est la seule réponse honnête.
        _, complet = etat.charger()
        charge = {"changed": True, "version": courante}
        if complet is not None:
            charge["state"] = complet
        return JsonResponse(_enveloppe(request, charge))
    return JsonResponse(_enveloppe(request,
                                   {"changed": True, "version": courante,
                                    "delta": delta}))


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------

@require_POST
def action(request):
    """Applique une action et retourne la différence à envoyer à l'interface.

    Toute l'écriture se fait dans une transaction unique : un refus métier
    annule ce qui a pu être écrit avant lui, et la version n'avance pas.
    """
    refus = _refus_session(request)
    if refus is not None:
        return refus

    try:
        corps = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Requête illisible."}, status=400)
    if not isinstance(corps, dict):
        return JsonResponse({"error": "Requête illisible."}, status=400)

    nom = corps.get("action")
    params = corps.get("params") or {}
    if not isinstance(params, dict):
        return JsonResponse({"error": "Paramètres illisibles."}, status=400)
    if nom not in ACTIONS:
        return JsonResponse({"error": "Action inconnue : %s." % nom}, status=422)

    try:
        with transaction.atomic():
            auteur = _auteur_effectif(request, params)
            depart = Version.courante()
            avant_mv = PhoneMovement.objects.count()
            avant_ml = MaterialLog.objects.count()

            resume, cibles = executer(nom, auteur, params,
                                      request.user.administrateur)

            nouvelle = depart + 1
            Version.poser(nouvelle)
            # L'historique porte le compte réellement connecté, jamais le nom
            # emprunté : `params` conserve `auteur`, si bien que la ligne dit
            # qui a agi et pour qui.
            Operation.objects.create(
                version=nouvelle, horodatage=timezone.now(),
                auteur=request.user.identifiant, type=nom,
                parametres=json.dumps(params, ensure_ascii=False, default=str),
                resume=(resume or "")[:400],
                cibles=json.dumps(cibles, ensure_ascii=False),
                nb_mouvements=PhoneMovement.objects.count() - avant_mv,
                nb_matlog=MaterialLog.objects.count() - avant_ml,
            )
    except ErreurAction as souci:
        return JsonResponse({"error": str(souci)}, status=422)

    _purger_operations()
    _, delta = etat.charger_delta(depart)
    return JsonResponse(_enveloppe(request, {
        "ok": True, "version": nouvelle, "resume": (resume or "")[:400],
        "delta": delta,
    }))


def _purger_operations():
    """Ne garder que l'historique utile aux sessions encore à jour.

    Hors transaction : perdre une purge n'a aucune conséquence, alors qu'elle
    tiendrait un verrou d'écriture pour rien.
    """
    total = Operation.objects.count()
    if total <= etat.OPERATIONS_CONSERVEES:
        return
    seuil = (Operation.objects.order_by("-version")
             .values_list("version", flat=True)[etat.OPERATIONS_CONSERVEES - 1:
                                                etat.OPERATIONS_CONSERVEES])
    seuil = list(seuil)
    if seuil:
        Operation.objects.filter(version__lt=seuil[0]).delete()
