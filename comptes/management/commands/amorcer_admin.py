# -*- coding: utf-8 -*-
"""Crée le premier compte administrateur, s'il n'y en a aucun.

Sans cela, un conteneur fraîchement déployé n'a aucune porte d'entrée : pas de
compte, donc pas de connexion, donc aucun moyen d'en créer un sans ouvrir un
shell dans le conteneur.

Reprend le comportement de l'application Qt au premier démarrage : un compte
`Admin`, un mot de passe affiché **une seule fois**, et l'obligation de le
remplacer à la première connexion.

Idempotente : si un compte administrateur existe déjà, elle ne fait rien. Elle
peut donc être appelée à chaque démarrage du conteneur sans surprise.
"""

import secrets
import string

from django.core.management.base import BaseCommand

from comptes.models import ActiviteCompte, Compte

# Sans les caractères que l'on confond en les recopiant depuis un journal :
# 0/O, 1/l/I. Un mot de passe provisoire se lit à l'œil avant d'être tapé.
ALPHABET = ("".join(c for c in string.ascii_letters + string.digits
                    if c not in "0O1lI"))


class Command(BaseCommand):
    help = "Crée le compte Admin si aucun administrateur n'existe."

    def add_arguments(self, parser):
        parser.add_argument("--identifiant", default="Admin")
        parser.add_argument(
            "--mot-de-passe", default=None,
            help="mot de passe à poser. Sans lui, un mot de passe est tiré au "
                 "hasard et affiché une seule fois.")
        parser.add_argument(
            "--staff", action="store_true",
            help="ouvre aussi l'accès à /admin/ à ce compte.")

    def handle(self, *args, **options):
        if Compte.objects.filter(administrateur=True).exists():
            self.stdout.write("Un administrateur existe déjà : rien à faire.")
            return

        identifiant = options["identifiant"].strip() or "Admin"
        if Compte.objects.filter(identifiant=identifiant).exists():
            self.stdout.write(self.style.WARNING(
                "Le compte « %s » existe mais n'est pas administrateur. "
                "Corrigez-le depuis /admin/ ou choisissez un autre "
                "identifiant." % identifiant))
            return

        impose = options["mot_de_passe"]
        mot_de_passe = impose or "".join(secrets.choice(ALPHABET) for _ in range(14))

        Compte.objects.create_user(
            identifiant, mot_de_passe,
            administrateur=True,
            actif=True,
            # Un mot de passe que le déployeur a vu passer dans un journal ou
            # une variable d'environnement doit être remplacé. Un mot de passe
            # explicitement choisi appartient déjà à quelqu'un : on ne l'impose
            # pas une seconde fois.
            doit_changer=not impose,
            is_staff=options["staff"],
            is_superuser=options["staff"],
        )
        ActiviteCompte.objects.create(
            acteur="amorçage", action="compte administrateur créé",
            nouveau_nom=identifiant)

        self.stdout.write(self.style.SUCCESS(
            "Compte administrateur « %s » créé." % identifiant))
        if not impose:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "  Mot de passe provisoire : %s" % mot_de_passe))
            self.stdout.write(
                "  Il ne sera plus affiché. Notez-le, connectez-vous, "
                "remplacez-le.")
            self.stdout.write("")
