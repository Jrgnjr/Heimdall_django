# -*- coding: utf-8 -*-
"""Routes du stock.

L'interface construit ses appels en relatif (`api/state`) : monter ce fichier
sous un préfixe déplace donc l'API avec la page, sans rien changer au
JavaScript.
"""
from django.urls import path

from . import api, views

urlpatterns = [
    path("", views.accueil, name="accueil"),
    # Les navigateurs réclament cette adresse d'eux-mêmes, avant de lire la page.
    path("favicon.ico", views.favicon, name="favicon"),
    path("api/state", api.state, name="api_state"),
    path("api/action", api.action, name="api_action"),
    path("api/reglages", api.reglages, name="api_reglages"),
    # `path` et non `str` : le nom d'une mission est sa clé et peut contenir « / ».
    path("missions/<path:nom>/", views.mission_tableau, name="mission_tableau"),
    # Sans session : interrogée par Docker et les répartiteurs de charge.
    path("sante/", views.sante, name="sante"),
]
