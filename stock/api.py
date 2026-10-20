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

from comptes.models import Compte, Groupe
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import etat
from .models import MaterialLog, Mission, Operation, PhoneMovement, Version
from .services import ACTIONS, ErreurAction, executer
from .services.droits import (groupe_de, groupe_du_compte,
                                  membres_du_groupe)
from .services.gestion import gestion_par_mission
from .services.prets import etat_prets
from .services.statuts import figer_statuts


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

    Un administrateur peut agir au nom de n'importe quel compte, un chef de groupe
    au nom de ses effectifs — pour enregistrer une sortie que quelqu'un a faite
    sans se connecter. La liste ne leur est envoyée que dans ce cas : elle n'aurait
    aucun usage ailleurs, et la donner renseignerait sur la composition de
    l'équipe.
    """
    if request.user.administrateur:
        return list(Compte.objects.filter(actif=True)
                    .values_list("identifiant", flat=True))
    if request.user.chef_de_groupe:
        return sorted(groupe_de(request.user.identifiant))
    return []


def _roles(request):
    """Le rôle de l'appelant, son groupe, et — pour un administrateur — tous les autres.

    Un effectif n'a besoin que du sien ; un chef de groupe y ajoute la liste de ses
    effectifs ; un administrateur voit tous les rôles et tous les groupes, pour les
    régler.
    """
    u = request.user
    moi = {"role": u.role, "chef": u.chef_id or "",
           "effectifs": sorted(groupe_de(u.identifiant)) if u.chef_de_groupe else []}
    # Le groupe, tel que ses membres le voient : lui-même, son chef, ses pairs.
    g = groupe_du_compte(u.identifiant)
    membres = membres_du_groupe(u.identifiant)
    moi["groupe"] = ({"id": g.pk, "nom": g.nom, "chef": g.chef_id or "",
                      "membres": membres, "affectation": g.affectation}
                     if g is not None else None)
    tous, groupes = {}, []
    if u.administrateur:
        # Tous les comptes, désactivés compris : c'est l'écran qui décide de ce qu'il
        # montre, et qui permet de réactiver.
        tous = {c.identifiant: {"role": c.role, "chef": c.chef_id or "",
                                "groupe": c.membre_de_id, "actif": c.actif,
                                "visite": c.derniere_visite.isoformat()
                                if c.derniere_visite else None}
                for c in Compte.objects.select_related("membre_de")}
        groupes = [{"id": x.pk, "nom": x.nom, "materiel": x.materiel,
                    "chef": x.chef_id or "",
                    "membres": sorted(Compte.objects.filter(membre_de=x)
                                      .values_list("identifiant", flat=True))}
                   for x in Groupe.objects.all()]
    return moi, tous, groupes


def _enveloppe(request, charge):
    # `dotations` voyage ici et pas dans le différentiel, pour deux raisons :
    # son contenu dépend de qui demande — un non-administrateur ne voit que le
    # sien —, et l'interface le relit à chaque réponse comme elle relit
    # `comptes`. Le faire passer par `etat.charger()`, qui ignore l'utilisateur,
    # aurait montré les sacs de toute l'équipe à tout le monde.
    from .services.dotations import sacs
    moi, roles, groupes = _roles(request)
    charge.update({
        "user": request.user.identifiant,
        "admin": bool(request.user.administrateur),
        "comptes": _comptes(request),
        # Les réglages du compte : l'interface les applique au démarrage, de
        # sorte que chacun retrouve les siens en se connectant.
        "reglages": request.user.reglages or {},
        # Prêts de matériel personnel : demandes reçues et émises, prêts en
        # cours, contenu des autres sacs. Propre à chaque compte.
        "pret": etat_prets(request.user.identifiant),
        # Le plus haut statut atteint par chaque mission : l'interface calcule
        # le statut, et ne le laisse pas descendre sous ce plancher.
        # Qui gère chaque mission : une information de la mission, pas un secret.
        "gestionMissions": gestion_par_mission(),
        # Les comptes actifs, pour désigner une gestion ou un effectif. Seuls les
        # administrateurs recevaient cette liste (`comptes`) ; composer une mission
        # est à la portée de tous.
        "annuaire": list(Compte.objects.filter(actif=True)
                         .values_list("identifiant", flat=True)),
        "moi": moi,
        "comptesRoles": roles,
        "groupes": groupes,
        "plancherMissions": {m.name: m.status_max for m in
                             Mission.objects.exclude(status_max__isnull=True)
                             .exclude(status_max="")},
        "dotations": sacs(request.user.identifiant,
                          bool(request.user.administrateur),
                          set(groupe_de(request.user.identifiant))
                          | set(membres_du_groupe(request.user.identifiant))),
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
    # Un administrateur, pour n'importe quel compte ; un chef de groupe, pour l'un de
    # ses effectifs. Les autres n'agissent qu'en leur nom.
    if not request.user.administrateur and not request.user.chef_de_groupe:
        raise ErreurAction("Vous ne pouvez pas agir au nom d'un autre compte.")
    if demande not in _comptes(request):
        raise ErreurAction(
            "Le compte « %s » n'existe pas%s." % (
                demande, "" if request.user.administrateur
                else " dans votre groupe : un chef de groupe n'agit qu'au nom de ses effectifs"))
    return demande


# --------------------------------------------------------------------------
# Réglages du compte
# --------------------------------------------------------------------------

TAILLES_PAGE = {"stockPhonePageSize", "stockMaterialPageSize"}
TAILLES_ADMIN = {"adminPhoneSize", "adminMaterialSize", "adminConsoSize"}
TEXTES = {"brand", "cabinet", "matCat", "logFilter"}
BOOLEENS = {"showArchived"}
THEMES = ("sombre", "clair", "auto")
# Les cartes du profil. La liste est aussi dans l'interface (`WIDGETS`) : un
# identifiant ajouté d'un côté seulement serait refusé, ou ignoré.
WIDGETS_PROFIL = {
    "compteurs", "a_recommander", "sac", "sorties", "missions", "activite",
    "missions_jour", "retard", "stock_bas", "equipes", "etat_stock",
    "acces_rapides", "prets", "demandes", "groupe",
}


def _disposition_valide(valeur):
    """Une liste de {id, taille}, sans doublon, d'identifiants connus."""
    if not isinstance(valeur, list) or len(valeur) > len(WIDGETS_PROFIL):
        return False
    vus = set()
    for carte in valeur:
        if not isinstance(carte, dict) or set(carte) != {"id", "taille"}:
            return False
        if carte["id"] not in WIDGETS_PROFIL or carte["id"] in vus:
            return False
        if carte["taille"] not in ("s", "l"):
            return False
        vus.add(carte["id"])
    return True



# Les filtres par colonne des tableaux, par tableau puis par colonne. La liste est aussi
# dans l'interface (`FILTRES_VIDES`) : une colonne ajoutée d'un côté seulement serait
# refusée ici.
COLONNES_FILTRABLES = {
    "materiel": {"article", "cat", "affectation", "qte", "mission", "reservation"},
    "stock": {"reference", "emplacement", "qte", "casier"},
    "journal": {"date", "article", "qte", "personne", "mission", "type"},
}


def _filtres_valides(valeur):
    if not isinstance(valeur, dict):
        return False
    for tableau, colonnes in valeur.items():
        if tableau not in COLONNES_FILTRABLES or not isinstance(colonnes, dict):
            return False
        for colonne, texte in colonnes.items():
            if colonne not in COLONNES_FILTRABLES[tableau]:
                return False
            if not isinstance(texte, str) or len(texte) > 80:
                return False
    return True


def _reglage_valide(cle, valeur):
    """Seuls les réglages connus, avec des valeurs que l'interface sait lire.

    Une liste fermée plutôt qu'un dictionnaire libre : ce que le client envoie
    est stocké tel quel et renvoyé à chaque démarrage, il ne doit pas pouvoir y
    déposer n'importe quoi.
    """
    if cle in BOOLEENS:
        return isinstance(valeur, bool)
    if cle in TAILLES_PAGE:
        return not isinstance(valeur, bool) and valeur in ("auto", "all", 20, 50)
    if cle in TAILLES_ADMIN:
        return not isinstance(valeur, bool) and valeur in ("all", 10, 20, 50, 100)
    if cle in TEXTES:
        return isinstance(valeur, str) and len(valeur) <= 80
    if cle == "theme":
        return valeur in THEMES
    if cle == "profilWidgets":
        return _disposition_valide(valeur)
    if cle == "colFiltres":
        return _filtres_valides(valeur)
    return False


@require_POST
def reglages(request):
    """Enregistre des réglages du compte connecté (fusion avec les existants)."""
    refus = _refus_session(request)
    if refus is not None:
        return refus
    try:
        corps = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Requête illisible."}, status=400)
    envoyes = corps.get("reglages") if isinstance(corps, dict) else None
    if not isinstance(envoyes, dict):
        return JsonResponse({"error": "Requête illisible."}, status=400)
    for cle, valeur in envoyes.items():
        if not _reglage_valide(cle, valeur):
            return JsonResponse({"error": "Réglage refusé : %s." % cle}, status=422)

    compte = request.user
    compte.reglages = {**(compte.reglages or {}), **envoyes}
    compte.save(update_fields=["reglages"])
    return JsonResponse({"ok": True, "reglages": compte.reglages})


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

def _verrou_ecriture():
    """Sérialise les actions d'écriture, au niveau de la base.

    Un verrou de ligne sur l'unique compteur de version : toute action qui
    écrit doit d'abord l'obtenir, si bien que deux actions ne s'exécutent
    jamais en parallèle. C'est ce que faisait le verrou en mémoire de
    l'application Qt — sauf qu'un verrou en mémoire ne couvrirait qu'un seul
    worker gunicorn, et il y en a plusieurs, dans des processus distincts.

    Sans lui, deux requêtes simultanées lisent la version N, calculent toutes
    les deux N+1, et la seconde se heurte à la contrainte d'unicité de
    `stock_operation.version` : une erreur 500 au lieu d'un refus propre.
    Mesuré avant ce verrou : six requêtes sur dix.

    Il couvre aussi, par construction, toutes les autres courses du même
    genre — la quantité lue puis réécrite, l'attribution du prochain
    identifiant, le suffixage d'une clé d'article. Aucune n'a besoin de son
    propre verrou puisque deux écritures ne se croisent plus.

    Ce qu'il ne ralentit pas : les lectures. `/api/state`, que chaque
    navigateur appelle toutes les 2,5 secondes, ne prend aucun verrou.
    """
    ligne = Version.objects.select_for_update().filter(pk=1).first()
    if ligne is not None:
        return ligne

    # Base adoptée sans sa ligne de version — les migrations la posent, mais
    # une base corrigée à la main peut l'avoir perdue. Le `atomic` imbriqué
    # crée un point de reprise : si une autre requête gagne la course, seule
    # cette insertion est annulée, pas l'action entière.
    try:
        with transaction.atomic():
            Version.objects.create(pk=1, valeur=0)
    except IntegrityError:
        pass
    return Version.objects.select_for_update().get(pk=1)


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
    params.pop("_secret", None)  # clé interne : jamais fournie par un client
    if nom not in ACTIONS:
        return JsonResponse({"error": "Action inconnue : %s." % nom}, status=422)

    try:
        with transaction.atomic():
            # Le verrou d'abord, avant toute lecture : c'est lui qui rend le
            # reste de ce bloc sûr à plusieurs.
            ligne_version = _verrou_ecriture()
            # Les statuts sont figés **avant** l'action : ce qu'elle va changer
            # (un emprunt rendu, une date repoussée) ne doit pas les faire reculer.
            figer_statuts()
            auteur = _auteur_effectif(request, params)
            depart = ligne_version.valeur
            avant_mv = PhoneMovement.objects.count()
            avant_ml = MaterialLog.objects.count()

            resume, cibles = executer(nom, auteur, params,
                                      request.user.administrateur,
                                      acteur=request.user.identifiant)
            # Une action peut rendre un secret à celui qui l'a demandée (un mot de
            # passe provisoire). Il est retiré **avant** l'écriture de l'historique : il
            # ne doit exister qu'en réponse à cet appel.
            secret = params.pop("_secret", None)

            nouvelle = depart + 1
            ligne_version.valeur = nouvelle
            ligne_version.save(update_fields=["valeur"])
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
    reponse = {"ok": True, "version": nouvelle, "resume": (resume or "")[:400],
               "delta": delta}
    if secret:
        reponse["secret"] = secret
    return JsonResponse(_enveloppe(request, reponse))


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
