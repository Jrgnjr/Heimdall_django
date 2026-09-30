# -*- coding: utf-8 -*-
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ActiviteCompte, Compte, Dotation


class DotationInline(admin.TabularInline):
    """Le sac, directement sur la fiche du compte.

    `material_id` est un champ texte et non une liste déroulante : il n'y a pas
    de clé étrangère vers le catalogue, volontairement — un article supprimé
    doit laisser sa ligne visible plutôt que de faire disparaître la trace de ce
    que la personne détient.
    """

    model = Dotation
    extra = 0
    fields = ("ordre", "material_id", "quantite", "detail")


@admin.register(Compte)
class CompteAdmin(UserAdmin):
    """L'administration des comptes, réordonnée autour de l'identifiant.

    `UserAdmin` attend un champ `username` ; l'identifiant en tient lieu, et
    les ensembles de champs sont redéclarés pour ne pas parler de données que ce
    modèle n'a pas (prénom, courriel).
    """

    ordering = ("identifiant",)
    inlines = [DotationInline]
    list_display = ("identifiant", "groupe", "administrateur", "actif",
                    "doit_changer", "is_staff", "derniere_visite")
    list_filter = ("administrateur", "actif", "doit_changer", "is_staff", "groupe")
    search_fields = ("identifiant",)
    readonly_fields = ("cree_le", "derniere_visite", "last_login")

    fieldsets = (
        (None, {"fields": ("identifiant", "password")}),
        ("Métier", {"fields": ("groupe", "administrateur", "actif",
                               "doit_changer")}),
        ("Django", {"fields": ("is_staff", "is_superuser", "groups",
                              "user_permissions")}),
        ("Dates", {"fields": ("cree_le", "derniere_visite", "last_login")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",),
                "fields": ("identifiant", "password1", "password2",
                           "groupe", "administrateur", "doit_changer")}),
    )


@admin.register(ActiviteCompte)
class ActiviteCompteAdmin(admin.ModelAdmin):
    list_display = ("horodatage", "acteur", "action", "ancien_nom", "nouveau_nom")
    search_fields = ("acteur", "action", "ancien_nom", "nouveau_nom")
    date_hierarchy = "horodatage"
