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
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import onglets
from . import recuperation
from .models import ActiviteCompte, Compte


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
            return redirect(onglets.vers_compte(
                request, reverse("mot_de_passe"), compte.identifiant))
        suite = request.GET.get("next") or ""
        if not suite or not url_has_allowed_host_and_scheme(
                suite, allowed_hosts={request.get_host()}):
            suite = reverse("accueil")
        # L'onglet devient celui du compte : `/u/Admin/…`.
        return redirect(onglets.vers_compte(request, suite, compte.identifiant))

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


# --------------------------------------------------------------------------
# Mot de passe oublié
# --------------------------------------------------------------------------

# Un seul message pour tous les échecs : compte inconnu, code absent ou faux,
# récupération verrouillée. Les distinguer dirait à qui essaie quels comptes
# existent, et lesquels ont un code.
ECHEC_RECUPERATION = ("Identifiant ou code de récupération incorrect — ou trop "
                      "d'essais récents. Réessayez dans quelques minutes.")


def mot_de_passe_oublie(request):
    """Choisir un nouveau mot de passe avec son code de récupération.

    Sans session : la personne ne peut, par définition, plus se connecter.
    """
    erreurs = []
    identifiant = ""
    if request.method == "POST":
        identifiant = (request.POST.get("identifiant") or "").strip()
        code = request.POST.get("code") or ""
        mdp1 = request.POST.get("password1") or ""
        mdp2 = request.POST.get("password2") or ""

        compte = Compte.objects.filter(pk=identifiant, actif=True).first()
        if not recuperation.verifier(compte, code, timezone.now()):
            erreurs.append(ECHEC_RECUPERATION)
        elif mdp1 != mdp2:
            erreurs.append("Les deux mots de passe ne correspondent pas.")
        else:
            try:
                validate_password(mdp1, user=compte)
            except ValidationError as refus:
                erreurs.extend(refus.messages)
            else:
                compte.set_password(mdp1)
                compte.doit_changer = False
                compte.save(update_fields=["password", "doit_changer"])
                # Le code est à usage unique. Changer le mot de passe referme
                # aussi les sessions ouvertes : leur empreinte ne correspond plus.
                recuperation.retirer(compte)
                ActiviteCompte.objects.create(
                    acteur=compte.identifiant,
                    action="mot de passe réinitialisé (code de récupération)",
                    nouveau_nom=compte.identifiant)
                messages.success(request,
                                 "Mot de passe modifié. Connectez-vous avec le "
                                 "nouveau, puis générez un nouveau code de "
                                 "récupération dans vos réglages.")
                return redirect("connexion")
    return render(request, "comptes/mot_de_passe_oublie.html", {
        "erreurs": erreurs, "identifiant": identifiant})


@login_required
def code_recuperation(request):
    """Générer, regénérer ou supprimer son code de récupération.

    Le mot de passe actuel est redemandé : une session laissée ouverte ne doit
    pas suffire à se donner un code, et à reprendre le compte ensuite.
    """
    if request.user.doit_changer:
        return redirect("mot_de_passe")
    compte = request.user
    erreur = ""
    code = ""
    if request.method == "POST":
        if not compte.check_password(request.POST.get("motdepasse") or ""):
            erreur = "Mot de passe actuel incorrect."
        elif request.POST.get("action") == "supprimer":
            recuperation.retirer(compte)
            ActiviteCompte.objects.create(
                acteur=compte.identifiant, action="code de récupération supprimé",
                nouveau_nom=compte.identifiant)
            messages.success(request, "Code de récupération supprimé.")
            return redirect("code_recuperation")
        else:
            code = recuperation.definir(compte)
            ActiviteCompte.objects.create(
                acteur=compte.identifiant, action="code de récupération généré",
                nouveau_nom=compte.identifiant)
    return render(request, "comptes/code_recuperation.html", {
        "defini": bool(compte.code_recuperation), "code": code, "erreur": erreur})
