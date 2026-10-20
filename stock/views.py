# -*- coding: utf-8 -*-
"""L'écran unique, et l'amorçage de l'application.

L'interface est une page qui parle à l'API par `fetch()`. Elle n'a donc besoin
que d'être servie, et du cookie CSRF que Django dépose au passage.
"""

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from .models import Equipe, MaterialReservation, Mission
from .services.gestion import gestionnaires_de


def theme_de(compte):
    """Le thème du compte, tel que la page le lit : light, dark ou auto.

    Posé par le serveur dans la page même, et non par le script une fois l'état
    chargé : sinon un thème clair s'afficherait d'abord en sombre.
    """
    choix = (compte.reglages or {}).get("theme")
    return {"clair": "light", "auto": "auto"}.get(choix, "dark")


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
    return TemplateView.as_view(
        template_name="stock/index.html",
        extra_context={"theme": theme_de(request.user)})(request)


@require_GET
def favicon(request):
    """L'icône de l'onglet, là où les navigateurs la cherchent d'office.

    Renvoie vers le fichier statique plutôt que de le dupliquer. L'adresse est
    calculée à l'appel : avec le manifeste des statiques, elle porte une empreinte
    qui n'existe qu'une fois `collectstatic` passé.
    """
    return redirect(static("stock/heimdall.ico"), permanent=True)


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


@login_required
def mission_tableau(request, nom):
    """La fiche d'une mission : un tableau de bord à lire, pas à manipuler.

    Pensé pour être ouvert depuis un lien partagé sur le réseau local : même
    session que l'application, donc même contrôle d'accès. La page n'écrit
    rien ; elle se recharge d'elle-même pour rester à jour.

    Le statut suit la règle de l'écran « Missions » (`Mission.statut`).
    """
    if request.user.doit_changer:
        return redirect("mot_de_passe")
    mission = get_object_or_404(Mission, pk=nom)

    lignes = list(MaterialReservation.objects.filter(mission=nom)
                  .select_related("material").order_by("material_id", "seq"))
    equipes = list(Equipe.objects.filter(mission=mission)
                   .prefetch_related("membres"))

    statut = mission.statut(lignes, timezone.localdate())

    def ligne(l):
        return {"article": l.material.designation, "qty": l.qty,
                "pris_par": l.taken_by, "rendu": not l.ouvert}

    groupes = [{"nom": e.nom,
                "membres": [m.identifiant for m in e.membres.all()],
                "lignes": [ligne(l) for l in lignes if l.equipe == e.nom]}
               for e in equipes]
    connues = {e.nom for e in equipes}
    sans_equipe = [ligne(l) for l in lignes if l.equipe not in connues]

    return render(request, "stock/mission.html", {
        "mission": mission, "statut": statut, "groupes": groupes,
        "sans_equipe": sans_equipe,
        "nb_sorties": sum(1 for l in lignes if l.ouvert),
        "nb_rendues": sum(1 for l in lignes if not l.ouvert),
        "nb_membres": len({m for g in groupes for m in g["membres"]}),
        "theme": theme_de(request.user),
        "gestion": gestionnaires_de(nom),
    })
