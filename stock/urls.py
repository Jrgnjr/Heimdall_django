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
    path("api/state", api.state, name="api_state"),
    path("api/action", api.action, name="api_action"),
    # Sans session : interrogée par Docker et les répartiteurs de charge.
    path("sante/", views.sante, name="sante"),
]
