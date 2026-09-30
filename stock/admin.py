# -*- coding: utf-8 -*-
"""L'administration Django sur les modèles du stock.

Elle existe pour les corrections qu'aucun écran ne prévoit — une quantité
fausse, une ligne de journal à effacer. **Elle contourne les règles métier** :
écrire ici ne passe ni par les contrôles ni par l'incrément de version, donc
l'interface ne verra le changement qu'à son prochain rechargement complet.
C'est pourquoi l'accès dépend de `is_staff`, distinct de l'administration du
stock.
"""
from django.contrib import admin

from .models import (Cabinet, Material, MaterialLog, MaterialReservation,
                     Mission, MissionTemplate, MissionTemplateItem, Operation,
                     Pack, PackItem, PhoneModel, PhoneMovement, PhoneOut,
                     PhoneReservation, SlotAssignment, Variant, Version)


class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0


@admin.register(PhoneModel)
class PhoneModelAdmin(admin.ModelAdmin):
    list_display = ("id", "brand", "model", "mpn", "commercial_name", "quantite")
    search_fields = ("id", "brand", "model", "mpn", "commercial_name")
    list_filter = ("brand",)
    inlines = [VariantInline]

    @admin.display(description="stock")
    def quantite(self, obj):
        return obj.quantite


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("name", "libelle", "cat", "qty", "seuil", "affectation",
                    "etiquette", "numero_serie", "restant")
    search_fields = ("name", "libelle", "etiquette", "numero_serie")
    list_filter = ("cat", "affectation")

    @admin.display(description="disponible")
    def restant(self, obj):
        return obj.disponible()


@admin.register(MaterialReservation)
class MaterialReservationAdmin(admin.ModelAdmin):
    list_display = ("material", "qty", "mission", "pack", "taken_by",
                    "taken_at", "returned_by", "returned_at")
    list_filter = ("mission", "pack")
    search_fields = ("material__name", "mission", "pack", "taken_by")


@admin.register(MaterialLog)
class MaterialLogAdmin(admin.ModelAdmin):
    list_display = ("horodatage", "kind", "item", "identite", "qty", "who",
                    "mission")
    list_filter = ("kind",)
    search_fields = ("item", "identite", "who", "mission", "commentaire")
    date_hierarchy = "horodatage"


@admin.register(PhoneMovement)
class PhoneMovementAdmin(admin.ModelAdmin):
    list_display = ("horodatage", "kind", "label", "loc", "user")
    list_filter = ("kind",)
    search_fields = ("label", "loc", "user")
    date_hierarchy = "horodatage"


class PackItemInline(admin.TabularInline):
    model = PackItem
    extra = 0


@admin.register(Pack)
class PackAdmin(admin.ModelAdmin):
    list_display = ("name", "etiquette", "owner", "created_at")
    search_fields = ("name", "etiquette", "owner")
    inlines = [PackItemInline]


class MissionTemplateItemInline(admin.TabularInline):
    model = MissionTemplateItem
    extra = 0


@admin.register(MissionTemplate)
class MissionTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name", "owner")
    inlines = [MissionTemplateItemInline]


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ("name", "is_meta", "owner", "planned_date",
                    "status_override", "archived")
    list_filter = ("is_meta", "archived")
    search_fields = ("name", "owner")


@admin.register(Cabinet)
class CabinetAdmin(admin.ModelAdmin):
    list_display = ("id", "shelves", "cols", "casiers")

    @admin.display(description="casiers")
    def casiers(self, obj):
        return obj.casiers


@admin.register(Operation)
class OperationAdmin(admin.ModelAdmin):
    list_display = ("version", "horodatage", "auteur", "type", "resume")
    search_fields = ("type", "auteur", "resume")
    date_hierarchy = "horodatage"


admin.site.register([Version, SlotAssignment, PhoneReservation, PhoneOut])

admin.site.site_header = "Heimdall — administration"
admin.site.site_title = "Heimdall"
admin.site.index_title = "Données du stock"
