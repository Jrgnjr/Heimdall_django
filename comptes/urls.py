# -*- coding: utf-8 -*-
"""Routes des comptes.

Montées à la racine, et pas sous un préfixe : l'interface redirige elle-même
vers « connexion/ » et « mot-de-passe/ », et poste sa déconnexion sur
« deconnexion/ », en relatif depuis la page. Ces trois chemins sont un contrat
avec index.html.
"""
from django.urls import path

from . import views

urlpatterns = [
    path("connexion/", views.connexion, name="connexion"),
    path("mot-de-passe/", views.mot_de_passe, name="mot_de_passe"),
    path("deconnexion/", views.deconnexion, name="deconnexion"),
]
