# -*- coding: utf-8 -*-
"""Récupération d'un mot de passe oublié, par un code personnel.

Il n'y a pas de messagerie sur ce réseau : un lien envoyé par courriel n'est pas
une option. À la place, chaque compte peut se donner un **code de
récupération**, généré dans ses réglages. S'il oublie son mot de passe, ce code
— présenté sur la page de connexion — lui permet d'en choisir un nouveau.

Ce que ça garantit, et à quel prix :

- le code est tiré au hasard (100 bits), jamais choisi : il ne se devine pas ;
- il est **haché** comme un mot de passe : la base ne le contient pas en clair, et
  personne — administrateur compris — ne peut le relire. Perdu, il se
  regénère ; il ne se retrouve pas ;
- il ne sert **qu'une fois** : une récupération réussie le consomme, et la
  personne en génère un autre ensuite ;
- les essais sont comptés : cinq erreurs verrouillent la récupération de ce
  compte pour un quart d'heure. Le mot de passe, lui, continue de marcher : le
  verrou ne sert qu'à empêcher de deviner le code, pas à enfermer son
  propriétaire dehors ;
- les messages d'échec sont les mêmes que le compte existe ou non, que le code
  manque ou soit faux, que le compte soit verrouillé ou non.
"""

import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password

# Sans 0/O, 1/I/L : un code se recopie souvent à la main.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LONGUEUR = 20
ECHECS_MAX = 5
BLOCAGE = timedelta(minutes=15)

_FAUX = []


def generer():
    """Un code neuf, en groupes de quatre : ABCD-EFGH-JKMN-PQRS-TUVW."""
    brut = "".join(secrets.choice(ALPHABET) for _ in range(LONGUEUR))
    return "-".join(brut[i:i + 4] for i in range(0, LONGUEUR, 4))


def normaliser(saisie):
    """Ce qu'on compare : majuscules, sans tirets ni espaces."""
    return "".join(c for c in (saisie or "").upper() if c in ALPHABET)


def definir(compte):
    """Donne un code neuf au compte ; renvoie le code, **seule** fois où il existe
    en clair."""
    code = generer()
    compte.code_recuperation = make_password(normaliser(code))
    compte.recuperation_echecs = 0
    compte.recuperation_bloque_jusqu = None
    compte.save(update_fields=["code_recuperation", "recuperation_echecs",
                               "recuperation_bloque_jusqu"])
    return code


def retirer(compte):
    compte.code_recuperation = ""
    compte.recuperation_echecs = 0
    compte.recuperation_bloque_jusqu = None
    compte.save(update_fields=["code_recuperation", "recuperation_echecs",
                               "recuperation_bloque_jusqu"])


def est_bloque(compte, maintenant):
    return bool(compte.recuperation_bloque_jusqu
                and compte.recuperation_bloque_jusqu > maintenant)


def _faux_hachage():
    # Pour qu'un compte inconnu coûte le même temps qu'un compte connu : répondre
    # plus vite renseignerait sur les comptes qui existent.
    if not _FAUX:
        _FAUX.append(make_password("faux-code-de-comparaison"))
    return _FAUX[0]


def verifier(compte, saisie, maintenant):
    """Le code est-il bon ? Compte les échecs, et verrouille au besoin."""
    if compte is None or not compte.code_recuperation or est_bloque(compte, maintenant):
        check_password(normaliser(saisie), _faux_hachage())
        return False
    if check_password(normaliser(saisie), compte.code_recuperation):
        return True
    compte.recuperation_echecs += 1
    if compte.recuperation_echecs >= ECHECS_MAX:
        compte.recuperation_bloque_jusqu = maintenant + BLOCAGE
        compte.recuperation_echecs = 0
    compte.save(update_fields=["recuperation_echecs", "recuperation_bloque_jusqu"])
    return False
