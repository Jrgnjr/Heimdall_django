# -*- coding: utf-8 -*-
"""Mesure ce qui se passe quand plusieurs personnes écrivent en même temps.

Deux questions distinctes :

1. le compteur de version tient-il ? Deux actions simultanées lisent la même
   version et écrivent toutes les deux la suivante ;
2. le stock tient-il ? Deux emprunts simultanés vérifient la disponibilité
   avant que l'autre n'ait écrit, et passent tous les deux.

L'essai tape sur un serveur en marche, avec de vraies requêtes HTTP. Il crée
un article « Essai concurrence », l'emprunte dix fois en parallèle, puis
nettoie derrière lui.

    HEIMDALL_MOTDEPASSE=… python outils/essai_concurrence.py

Mesuré avant le verrou de `stock.api` : quatre acceptations, aucun refus, six
erreurs 500. Après : cinq acceptations, cinq refus, rien de trop sorti.
"""

import http.cookiejar
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("HEIMDALL_URL", "http://localhost:8750")
IDENTIFIANT = os.environ.get("HEIMDALL_IDENTIFIANT", "Admin")
MOT_DE_PASSE = os.environ.get("HEIMDALL_MOTDEPASSE", "Admin")

if not MOT_DE_PASSE:
    raise SystemExit(
        "Renseignez les identifiants avant de lancer l'essai :\n"
        "  HEIMDALL_MOTDEPASSE=… python outils/essai_concurrence.py\n"
        "Autres variables : HEIMDALL_URL, HEIMDALL_IDENTIFIANT.\n"
        "Le compte doit être administrateur : l'essai crée un article."
    )


class PolitiqueLocalhost(http.cookiejar.DefaultCookiePolicy):
    """Traite `http://localhost` comme un contexte sécurisé.

    Les cookies sont marqués `Secure` (parce que DEBUG=0), et `http.cookiejar`
    refuse donc de les renvoyer en clair. Les navigateurs et curl, eux, font
    une exception pour localhost — c'est dans la spécification des contextes
    sécurisés. On reproduit ce comportement pour pouvoir mesurer la
    concurrence, au lieu de buter dessus.

    `SESSION_SAVE_EVERY_REQUEST` renvoyant le cookie à chaque réponse, corriger
    le drapeau après coup ne suffisait pas : il faut le faire à la lecture.
    """

    def return_ok_secure(self, cookie, request):
        return True


def ouvrir_session():
    """Un opener par fil : un cookiejar partagé n'est pas fait pour ça."""
    jar = http.cookiejar.CookieJar(policy=PolitiqueLocalhost())
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPRedirectHandler())
    page = opener.open(BASE + "/connexion/").read().decode("utf-8")
    jeton = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    donnees = urllib.parse.urlencode({
        "csrfmiddlewaretoken": jeton,
        "username": IDENTIFIANT,
        "password": MOT_DE_PASSE,
    }).encode()
    requete = urllib.request.Request(BASE + "/connexion/", data=donnees)
    requete.add_header("Referer", BASE + "/connexion/")
    opener.open(requete).read()
    csrf = next((c.value for c in jar if c.name == "csrftoken"), None)
    if not csrf:
        raise SystemExit("connexion échouée : pas de jeton CSRF")
    return opener, csrf


def agir(opener, csrf, nom, params):
    corps = json.dumps({"action": nom, "params": params}).encode()
    requete = urllib.request.Request(BASE + "/api/action", data=corps)
    requete.add_header("Content-Type", "application/json")
    requete.add_header("X-CSRFToken", csrf)
    requete.add_header("Referer", BASE + "/")
    try:
        with opener.open(requete) as reponse:
            return reponse.status, json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        brut = erreur.read().decode("utf-8", "replace")
        try:
            return erreur.code, json.loads(brut)
        except ValueError:
            return erreur.code, {"brut": brut[:200]}


def etat(opener):
    with opener.open(BASE + "/api/state") as reponse:
        return json.loads(reponse.read().decode("utf-8"))


# --------------------------------------------------------------------------
print("=== préparation ===")
principal, csrf_principal = ouvrir_session()

ARTICLE = "Essai concurrence"
code, reponse = agir(principal, csrf_principal, "materiel.creer",
                     {"nom": ARTICLE, "cat": "Autre", "qty": 10})
print("  article créé (10 unités) :", code, reponse.get("resume", reponse))

d = etat(principal)
version_avant = d["version"]
print("  version avant :", version_avant)

# --------------------------------------------------------------------------
# Essai 1 — dix emprunts simultanés de 2 unités sur un stock de 10.
# Attendu d'un système correct : 5 acceptés, 5 refusés, disponible = 0.
# --------------------------------------------------------------------------
print()
print("=== essai 1 : 10 emprunts simultanés de 2 unités, stock de 10 ===")

sessions = [ouvrir_session() for _ in range(10)]
barriere = threading.Barrier(10)


def emprunter(i):
    opener, csrf = sessions[i]
    barriere.wait()          # tous partent au même instant
    return agir(opener, csrf, "materiel.emprunt", {"nom": ARTICLE, "qty": 2})


with ThreadPoolExecutor(max_workers=10) as pool:
    resultats = list(pool.map(emprunter, range(10)))

codes = {}
for code, _ in resultats:
    codes[code] = codes.get(code, 0) + 1
print("  codes de retour :", dict(sorted(codes.items())))

acceptes = sum(1 for code, _ in resultats if code == 200)
refuses = sum(1 for code, _ in resultats if code == 422)
erreurs = [(c, r) for c, r in resultats if c not in (200, 422)]
print("  acceptés : %d   refusés : %d   erreurs serveur : %d"
      % (acceptes, refuses, len(erreurs)))
for code, r in erreurs[:3]:
    print("     %s : %s" % (code, str(r)[:150]))

d = etat(principal)
art = next((m for m in d.get("state", {}).get("materiel", [])
            if m["name"] == ARTICLE), None)
if art is None:
    # Réponse différentielle : on redemande l'état complet.
    art = {"qty": "?"}
emprunts = d.get("state", {}).get("matRes", {}).get(ARTICLE, [])
sortis = sum(e["qty"] for e in emprunts if "returned" not in e)
print("  quantité en base : %s" % art.get("qty"))
print("  total sorti      : %d unités sur %s" % (sortis, art.get("qty")))
print("  version après    : %d (attendu : %d + %d = %d)"
      % (d["version"], version_avant, acceptes, version_avant + acceptes))

verdict = []
if len(erreurs):
    verdict.append("%d requête(s) ont renvoyé une erreur serveur" % len(erreurs))
if d["version"] != version_avant + acceptes:
    verdict.append("le compteur de version a sauté : %d au lieu de %d"
                   % (d["version"], version_avant + acceptes))
if acceptes + refuses != 10:
    verdict.append("%d requête(s) n'ont ni abouti ni été refusées"
                   % (10 - acceptes - refuses))
if sortis > 10:
    verdict.append("SURVENTE : %d unités sorties d'un stock de 10" % sortis)
if acceptes > 5:
    verdict.append("%d emprunts acceptés au lieu de 5 au maximum" % acceptes)

print()
if verdict:
    print("  >>> PROBLÈMES :")
    for v in verdict:
        print("      - " + v)
else:
    print("  >>> cohérent : 5 acceptés, 5 refusés, rien de trop sorti")

# --------------------------------------------------------------------------
# Nettoyage : on rend tout, puis on retire l'article d'essai.
# --------------------------------------------------------------------------
print()
print("=== nettoyage ===")
for _ in range(20):
    code, _r = agir(principal, csrf_principal, "materiel.emprunt.retour",
                    {"nom": ARTICLE, "index": 0})
    if code != 200:
        break
code, r = agir(principal, csrf_principal, "materiel.supprimer", {"nom": ARTICLE})
print("  article d'essai retiré :", code, r.get("resume", r.get("error", "")))
