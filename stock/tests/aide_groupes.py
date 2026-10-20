# -*- coding: utf-8 -*-
"""Constituer des groupes dans les tests, sans passer par les actions."""

from comptes.models import Compte, Groupe


def faire_groupe(nom, chef=None, membres=(), materiel=""):
    """Crée un groupe ; le chef (s'il y en a un) en est aussi membre."""
    g = Groupe.objects.create(nom=nom, materiel=materiel)
    for m in ([chef] if chef else []) + list(membres):
        Compte.objects.filter(pk=m).update(membre_de=g)
    if chef:
        g.chef_id = chef
        g.save(update_fields=["chef"])
    return g
