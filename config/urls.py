# -*- coding: utf-8 -*-
"""Routes du projet.

L'interface est servie à la racine ; l'API qu'elle interroge vit sous `/api/`.
L'administration Django reste disponible pour les corrections qu'aucun écran
ne prévoit — elle travaille sur les mêmes modèles, donc sur les mêmes données.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Montées à la racine : index.html y redirige en relatif.
    path("", include("comptes.urls")),
    path("", include("stock.urls")),
]
