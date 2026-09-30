# -*- coding: utf-8 -*-
"""Connexion, renouvellement imposé, déconnexion.

L'interface connaît ces trois adresses et s'y redirige elle-même : un 401 sur
l'API l'envoie sur `connexion/`, un 403 sur `mot-de-passe/`. Les noms de routes
sont donc un contrat, pas un détail interne.
"""

from django.contrib import messages
from django.contrib.auth import login as ouvrir_session
from django.contrib.auth import logout as fermer_session
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ActiviteCompte


class FormulaireConnexion(AuthenticationForm):
    """Le formulaire de Django, avec le vocabulaire du métier.

    Le message d'échec est volontairement le même pour un identifiant inconnu
    et un mot de passe faux : distinguer les deux dirait à qui essaie quels
    comptes existent.
    """

    error_messages = dict(AuthenticationForm.error_messages, **{
        "invalid_login": "Identifiant ou mot de passe incorrect.",
        "inactive": "Ce compte est désactivé.",
    })

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Identifiant"
        self.fields["username"].widget.attrs.update(
            {"autofocus": True, "autocomplete": "username",
             "placeholder": "Admin"})
        self.fields["password"].label = "Mot de passe"
        self.fields["password"].widget.attrs.update(
            {"autocomplete": "current-password"})


def connexion(request):
    if request.user.is_authenticated and not request.user.doit_changer:
        return redirect("accueil")

    formulaire = FormulaireConnexion(request, data=request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        compte = formulaire.get_user()
        ouvrir_session(request, compte)
        # `update_fields` pour ne pas réécrire l'empreinte au passage : une
        # sauvegarde complète ici écraserait un changement concurrent.
        compte.derniere_visite = timezone.now()
        compte.save(update_fields=["derniere_visite"])
        if compte.doit_changer:
            messages.info(request,
                          "Ce mot de passe vous a été attribué : "
                          "remplacez-le avant de continuer.")
            return redirect("mot_de_passe")
        return redirect(request.GET.get("next") or "accueil")

    return render(request, "comptes/connexion.html", {"formulaire": formulaire})


class FormulaireMotDePasse(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password2"].label = "Confirmation"
        for champ in self.fields.values():
            champ.widget.attrs.update({"autocomplete": "new-password"})


@login_required
def mot_de_passe(request):
    """Renouvellement, imposé ou volontaire."""
    formulaire = FormulaireMotDePasse(request.user, data=request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        compte = formulaire.save()
        compte.doit_changer = False
        compte.save(update_fields=["doit_changer"])
        # Sans cela, changer son mot de passe déconnecte : la session porte une
        # empreinte du mot de passe, que Django revérifie à chaque requête.
        update_session_auth_hash(request, compte)
        ActiviteCompte.objects.create(
            acteur=compte.identifiant, action="mot de passe changé",
            nouveau_nom=compte.identifiant)
        messages.success(request, "Mot de passe enregistré.")
        return redirect("accueil")

    return render(request, "comptes/mot_de_passe.html", {
        "formulaire": formulaire,
        "impose": request.user.doit_changer,
    })


@require_POST
def deconnexion(request):
    """Déconnexion par POST uniquement.

    En GET, n'importe quelle image ou lien préchargé pourrait déconnecter à
    l'insu de la personne.
    """
    fermer_session(request)
    return redirect("connexion")
