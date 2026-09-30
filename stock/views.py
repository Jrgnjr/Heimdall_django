# -*- coding: utf-8 -*-
"""L'écran unique, et l'amorçage de l'application.

L'interface est une page qui parle à l'API par `fetch()`. Elle n'a donc besoin
que d'être servie, et du cookie CSRF que Django dépose au passage.
"""

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView


@login_required
@ensure_csrf_cookie
def accueil(request):
    """La page. Tant que le mot de passe imposé n'est pas changé, on n'entre pas.

    Le contrôle est refait ici en plus de l'API : sans lui, l'application
    s'afficherait et toutes ses actions échoueraient en 403, ce qui est plus
    déroutant qu'une redirection franche.
    """
    if request.user.doit_changer:
        return redirect("mot_de_passe")
    return TemplateView.as_view(template_name="stock/index.html")(request)


@require_GET
def sante(request):
    """Le conteneur est-il en état de servir ?

    Sans session : c'est Docker et les répartiteurs de charge qui interrogent
    cette adresse, et ils n'ont pas de compte.

    La base est réellement interrogée, pas seulement supposée joignable : un
    processus Django qui répond alors que PostgreSQL est tombé serait déclaré
    sain à tort, et continuerait de recevoir du trafic.
    """
    try:
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1")
            curseur.fetchone()
    except Exception as souci:                          # noqa: BLE001
        return JsonResponse({"ok": False, "base": str(souci)[:200]}, status=503)
    return JsonResponse({"ok": True})
