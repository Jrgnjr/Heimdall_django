# -*- coding: utf-8 -*-
"""Une session par onglet : deux personnes, deux onglets, un navigateur.

Un navigateur ne garde qu'un cookie de session par site, donc se connecter avec
un second compte remplaçait le premier. Ici, chaque onglet vit sous **sa propre
adresse**, et ses cookies de session et CSRF y sont attachés par leur chemin
(`Path=/u/Admin/`). Le navigateur les garde donc séparés, sans que le serveur
ait à « choisir » entre plusieurs comptes :

- un onglet ne voit jamais le cookie d'un autre, et rien ne permet de passer
  d'un compte à l'autre sans mot de passe ;
- chaque session est une session Django ordinaire, avec son mot de passe, son
  expiration, sa déconnexion.

Deux sortes d'adresses :

- `/s-1a2b3c4d5e6f/…` : un onglet **pas encore connecté**. Le serveur ne sait
  pas encore qui va se présenter, l'adresse est donc tirée au hasard ;
- `/u/Admin/…` : l'onglet **d'un compte**. Dès la connexion, on y est renvoyé,
  et les cookies y sont posés. Deux onglets du même compte ont la même adresse
  et partagent donc la même session — se déconnecter dans l'un ferme l'autre.

Se rendre sur `/u/Bob/` avec la session d'Admin n'ouvre pas celle de Bob :
l'adresse ne prouve rien, c'est le cookie, attaché à ce chemin, qui authentifie.

L'interface construit déjà tous ses appels en relatif (`api/state`) : sous un
préfixe, elle fonctionne sans changement. Côté Django, le préfixe est traité
comme un `SCRIPT_NAME` : les routes, `reverse()` et les redirections le
retrouvent d'eux-mêmes.

Les noms des cookies portent aussi l'onglet (`sessionid_u-…`). Sans cela, un
cookie posé à la racine — ancien, ou d'un client qui n'utilise pas d'onglet —
serait envoyé en même temps que celui de l'onglet, sous le même nom, et la
session de l'un servirait à l'autre.
"""

import re
import secrets
from urllib.parse import quote, unquote, urlsplit

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import get_script_prefix, set_script_prefix

MOTIF = re.compile(r"^/(?P<onglet>s-[0-9a-f]{12}|u/[^/]+)(?P<reste>/.*)?$")

# Ce qui n'appartient pas à un onglet : fichiers statiques, API consommée par
# des outils, sonde de santé. Les pages, elles, sont redirigées vers un onglet.
EXTERIEUR = ("/static/", "/api/", "/sante/", "/favicon.ico")

CLE_ONGLET = "HEIMDALL_ONGLET"
CLE_FINAL = "HEIMDALL_ONGLET_FINAL"


def _cookies():
    return (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME)


def suffixe(onglet):
    """Ce qui s'ajoute au nom des cookies. Un nom de cookie n'accepte pas
    n'importe quel caractère : l'identifiant d'un compte est donc passé en
    hexadécimal."""
    if onglet.startswith("u/"):
        return "u-" + onglet[2:].encode("utf-8").hex()
    return onglet


def chemin(onglet):
    """Le chemin du cookie, tel qu'on l'écrit dans une adresse."""
    return quote("/" + onglet) + "/"


def nom_utilisable(identifiant):
    """Un compte dont le nom peut figurer dans une adresse."""
    return bool(identifiant) and "/" not in identifiant and identifiant.isprintable()


def vers_compte(request, destination, identifiant):
    """La même destination, dans l'onglet propre au compte qui se connecte.

    Appelée à la connexion : c'est ici qu'un onglet anonyme (`/s-…/`) devient
    l'onglet du compte (`/u/Admin/`). Les cookies que la réponse pose sont
    rangés sous cette nouvelle adresse (voir `OngletMiddleware`).
    """
    actuel = request.META.get(CLE_ONGLET)
    if (not getattr(settings, "ONGLETS_ISOLES", True) or not actuel
            or not nom_utilisable(identifiant)):
        return destination
    final = "u/" + identifiant
    request.META[CLE_FINAL] = final
    morceaux = urlsplit(destination)
    chemin_dest = unquote(morceaux.path)
    # Une destination qui nomme un onglet — le sien, celui d'un autre compte —
    # n'en garde que ce qui suit : on n'atterrit jamais dans l'onglet d'un autre.
    trouve = MOTIF.match(chemin_dest)
    if trouve:
        chemin_dest = trouve.group("reste") or "/"
    if not chemin_dest.startswith("/"):
        chemin_dest = "/"
    adresse = quote("/" + final) + quote(chemin_dest)
    if morceaux.query:
        adresse += "?" + morceaux.query
    return adresse


class OngletMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        trouve = MOTIF.match(request.path_info)
        if not trouve:
            return self._sans_onglet(request)

        onglet = trouve.group("onglet")
        prefixe = "/" + onglet
        reste = trouve.group("reste")
        if reste is None:
            return HttpResponseRedirect(quote(prefixe) + "/" + self._requete(request))

        request.path_info = reste
        request.path = prefixe + reste
        request.META["SCRIPT_NAME"] = prefixe
        request.META[CLE_ONGLET] = onglet
        # Rétabli à la sortie : le préfixe est un état du fil d'exécution, il ne
        # doit pas déborder sur la requête — ou le test — suivante.
        ancien_prefixe = get_script_prefix()
        set_script_prefix(prefixe + "/")
        try:
            return self._servir(request, onglet)
        finally:
            set_script_prefix(ancien_prefixe)

    def _servir(self, request, onglet):
        # Ce que Django lira comme « le » cookie de session est celui de cet
        # onglet, et seulement lui.
        for nom in _cookies():
            propre = "%s_%s" % (nom, suffixe(onglet))
            if propre in request.COOKIES:
                request.COOKIES[nom] = request.COOKIES[propre]
            else:
                request.COOKIES.pop(nom, None)

        reponse = self.get_response(request)

        # Et ce qu'il écrit est rangé sous le nom et le chemin de l'onglet — de
        # l'onglet **du compte**, si la requête vient de le connecter.
        final = request.META.get(CLE_FINAL, onglet)
        for nom in _cookies():
            if nom not in reponse.cookies:
                continue
            morceau = reponse.cookies.pop(nom)
            propre = "%s_%s" % (nom, suffixe(final))
            reponse.cookies[propre] = morceau.value
            for cle, valeur in morceau.items():
                reponse.cookies[propre][cle] = valeur
            reponse.cookies[propre]["path"] = chemin(final)
        return reponse

    def _sans_onglet(self, request):
        """Une page demandée sans onglet en reçoit un, neuf."""
        if (getattr(settings, "ONGLETS_ISOLES", True)
                and request.method == "GET"
                and not request.path_info.startswith(EXTERIEUR)):
            onglet = "s-" + secrets.token_hex(6)
            return HttpResponseRedirect(
                "/%s%s%s" % (onglet, quote(request.path_info), self._requete(request)))
        return self.get_response(request)

    @staticmethod
    def _requete(request):
        texte = request.META.get("QUERY_STRING", "")
        return "?" + texte if texte else ""


class CoherenceOnglet:
    """Une adresse `/u/Admin/…` n'existe que pour la session d'Admin.

    Placé après l'authentification. Sans session de ce compte — personne, ou
    quelqu'un d'autre —, l'adresse n'a pas lieu d'être : on renvoie sur une
    connexion à adresse neutre, en retenant seulement la page demandée. Il n'y a
    donc jamais de page de connexion « au nom » d'un compte, ni de destination
    qui mène d'un compte à l'autre.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        onglet = request.META.get(CLE_ONGLET, "")
        if (onglet.startswith("u/")
                and getattr(settings, "ONGLETS_ISOLES", True)
                and not (request.user.is_authenticated
                         and request.user.identifiant == onglet[2:])):
            if request.path_info.startswith("/api/"):
                return JsonResponse({"error": "Session expirée."}, status=401)
            neuf = "/s-" + secrets.token_hex(6)
            suite = ""
            if not request.path_info.startswith(("/connexion/", "/deconnexion/")):
                suite = "?next=" + quote(request.path_info)
            return HttpResponseRedirect(neuf + "/connexion/" + suite)
        return self.get_response(request)
