# -*- coding: utf-8 -*-
from django.apps import AppConfig


class StockConfig(AppConfig):
    name = "stock"
    verbose_name = "Stock"
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        # Peuple le registre des actions. Fait ici et pas à l'import du paquet
        # `services` : les modules d'action importent les modèles, qui ne sont
        # pas chargés avant ce point.
        from .services import charger
        charger()
