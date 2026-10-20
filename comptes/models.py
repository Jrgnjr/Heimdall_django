# -*- coding: utf-8 -*-
"""Les comptes.

Un modèle sur mesure plutôt que le `User` de Django, pour trois raisons qui
tiennent toutes au métier existant :

- l'identifiant est le nom du compte (« Admin », « Compte-001 ») et c'est lui
  qui est inscrit dans les journaux. Le faire cohabiter avec un `username`
  Django en doublon inviterait à les désynchroniser ;
- `groupe` porte l'affectation du matériel (« 1 », « 2 », « 3 »). Ce n'est pas
  un groupe de permissions Django, c'est une donnée métier ;
- `doit_changer` impose un renouvellement à la première connexion. Django n'a
  pas cette notion.

Ce que les comptes protègent, et ce qu'ils ne protègent pas : contrairement à
l'application Qt, où la base était un fichier sur le poste de l'utilisateur, ici
elle vit sur le serveur et n'est pas à portée. `administrateur` empêche donc
réellement, au lieu de seulement attribuer.
"""

from django.contrib.auth.models import (AbstractBaseUser, BaseUserManager,
                                        PermissionsMixin)
from django.db import models
from django.utils import timezone


class GestionnaireComptes(BaseUserManager):
    """Création des comptes, avec ou sans mot de passe choisi."""

    use_in_migrations = True

    def create_user(self, identifiant, password=None, **extra):
        identifiant = (identifiant or "").strip()
        if not identifiant:
            raise ValueError("Un compte doit avoir un identifiant.")
        compte = self.model(identifiant=identifiant, **extra)
        if password:
            compte.set_password(password)
        else:
            # Un compte sans mot de passe utilisable n'est pas un compte
            # ouvert : `set_unusable_password` empêche toute connexion, au
            # lieu de laisser une empreinte vide qui pourrait passer.
            compte.set_unusable_password()
        compte.save(using=self._db)
        return compte

    def create_superuser(self, identifiant, password=None, **extra):
        extra.setdefault("administrateur", True)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("doit_changer", False)
        if not extra.get("administrateur"):
            raise ValueError("Un superutilisateur est forcément administrateur.")
        return self.create_user(identifiant, password, **extra)


class Compte(AbstractBaseUser, PermissionsMixin):
    identifiant = models.CharField("identifiant", max_length=150, primary_key=True)
    groupe = models.CharField("groupe", max_length=20, blank=True, default="")
    administrateur = models.BooleanField(
        "administrateur", default=False,
        help_text="Autorise les actions qui touchent à la structure du stock : "
                  "armoires, création et suppression d'articles, seuils, "
                  "numéros de série.")
    actif = models.BooleanField("actif", default=True)
    doit_changer = models.BooleanField(
        "doit changer de mot de passe", default=True,
        help_text="Le compte est redirigé vers le changement de mot de passe "
                  "tant que ce drapeau est levé.")
    cree_le = models.DateTimeField("créé le", default=timezone.now)
    derniere_visite = models.DateTimeField("dernière visite", null=True, blank=True)
    # Les réglages d'affichage de la personne : ils la suivent d'un poste à
    # l'autre, et chaque compte retrouve les siens en se connectant.
    reglages = models.JSONField("réglages", default=dict, blank=True)

    # Le groupe auquel appartient le compte (voir `Groupe`). Un groupe est une entité
    # à part entière : il existe avant d'avoir un chef, et il survit à son départ.
    membre_de = models.ForeignKey(
        "comptes.Groupe", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="membres", verbose_name="groupe",
        help_text="Le groupe dont ce compte est membre.")

    # Récupération d'un mot de passe oublié (voir comptes/recuperation.py). Le
    # code n'est jamais stocké en clair : `code_recuperation` en est l'empreinte.
    code_recuperation = models.CharField("empreinte du code de récupération",
                                         max_length=300, blank=True, default="")
    recuperation_echecs = models.PositiveSmallIntegerField(
        "essais de récupération ratés", default=0)
    recuperation_bloque_jusqu = models.DateTimeField(
        "récupération verrouillée jusqu'à", null=True, blank=True)

    # `is_staff` gouverne l'accès à /admin/ et rien d'autre : être
    # administrateur du stock n'ouvre pas l'administration Django, qui permet
    # d'écrire n'importe quoi sans passer par les règles métier.
    is_staff = models.BooleanField("accès à l'administration Django", default=False)

    objects = GestionnaireComptes()

    USERNAME_FIELD = "identifiant"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "comptes"
        verbose_name = "compte"
        verbose_name_plural = "comptes"
        ordering = ["identifiant"]

    def __str__(self):
        return self.identifiant

    # Django interroge `is_active` pour refuser une connexion ; le métier parle
    # d'un compte « actif ». Un seul champ, deux noms, et pas de recopie à
    # tenir à jour.
    @property
    def role(self):
        """administrateur, chef de groupe ou effectif — le plus haut l'emporte."""
        if self.administrateur:
            return "admin"
        return "chef de groupe" if self.chef_de_groupe else "effectif"

    # Le rôle de chef est porté par le **groupe** (`Groupe.chef`), pas par le compte :
    # ces deux propriétés le relisent, pour que le reste du code parle de « chef de
    # groupe » sans connaître la table.
    @property
    def chef_de_groupe(self):
        return bool(self.pk) and Groupe.objects.filter(chef_id=self.pk).exists()

    @property
    def chef_id(self):
        """Le chef du groupe de ce compte, s'il en a un et que ce n'est pas lui."""
        g = self.membre_de
        return g.chef_id if g is not None and g.chef_id and g.chef_id != self.pk else None

    @property
    def is_active(self):
        return self.actif

    @is_active.setter
    def is_active(self, valeur):
        self.actif = bool(valeur)

    def get_username(self):
        return self.identifiant

    @property
    def affectation(self):
        """L'étiquette d'affectation du matériel, telle que l'interface l'écrit.

        Les comptes portent « 1 », « 2 », « 3 » ; le stock parle de
        « Groupe 1 ». La traduction est ici, en un seul endroit.
        """
        groupe = (self.groupe or "").strip()
        return "Groupe %s" % groupe if groupe else "Commun"


class Groupe(models.Model):
    """Un groupe de personnes, créé et réglé par un administrateur.

    Il existe **indépendamment de son chef** : on le crée, on y place des membres, et
    l'on nomme un chef plus tard — ou jamais. Sans chef, les membres se voient quand
    même entre eux (page « Mon groupe »), et seuls les administrateurs le gèrent.

    `materiel` fait le lien avec le stock : « 1 », « 2 » ou « 3 » désigne l'étiquette
    « Groupe n » de l'affectation des articles.

    Le chef est lui-même membre de son groupe (`Compte.membre_de`), et ne dirige
    qu'un seul groupe.
    """
    CHOIX_MATERIEL = [("1", "Groupe 1"), ("2", "Groupe 2"), ("3", "Groupe 3")]

    nom = models.CharField("nom", max_length=80, unique=True)
    materiel = models.CharField(
        "matériel affecté", max_length=1, blank=True, default="",
        choices=CHOIX_MATERIEL,
        help_text="L'étiquette « Groupe n » du stock de matériel qui désigne celui de "
                  "ce groupe.")
    chef = models.OneToOneField(
        "comptes.Compte", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="groupe_dirige", verbose_name="chef de groupe")
    cree_le = models.DateTimeField("créé le", default=timezone.now)

    class Meta:
        db_table = "groupes"
        verbose_name = "groupe"
        verbose_name_plural = "groupes"
        ordering = ["nom"]

    def __str__(self):
        return self.nom

    @property
    def affectation(self):
        """L'étiquette du stock (« Groupe 2 »), ou "" si aucun matériel n'est affecté."""
        return "Groupe %s" % self.materiel if self.materiel else ""


class Dotation(models.Model):
    """Une ligne du sac de dotation d'un compte.

    Le sac, c'est ce qui a été remis à quelqu'un **à son arrivée** et qui reste
    chez lui : ce n'est pas un emprunt, il n'a pas de retour attendu. D'où une
    table à part des emprunts, et pas un `MaterialReservation` sans date de
    retour — qui aurait fait apparaître la dotation dans tous les écrans
    d'emprunt en cours.

    `material_id` désigne un **exemplaire précis** du catalogue, pas un
    libellé : c'est ce qui permet d'afficher son étiquette et son numéro de
    série, et donc de savoir lequel des trois portables identiques est parti
    dans quel sac.

    Pas de clé étrangère vers `Material`, pour la même raison que les lignes de
    pack et de template : un article supprimé ne doit pas faire disparaître en
    silence la trace de ce que quelqu'un détient. La ligne reste, signalée comme
    cassée, et c'est à l'administrateur de la corriger.
    """

    compte = models.ForeignKey(Compte, on_delete=models.CASCADE,
                               db_column="identifiant",
                               related_name="dotations", db_index=True)
    ordre = models.IntegerField(default=0)
    material_id = models.CharField("exemplaire", max_length=200)
    quantite = models.IntegerField("quantité", default=1)
    detail = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "materiel_personnel"
        ordering = ["compte_id", "ordre", "id"]
        verbose_name = "ligne de dotation"
        verbose_name_plural = "sacs de dotation"

    def __str__(self):
        return "%s : %d × %s" % (self.compte_id, self.quantite, self.material_id)


class ActiviteCompte(models.Model):
    """Qui a créé, renommé, désactivé ou supprimé quel compte.

    Séparé du journal du stock : ce registre parle des comptes eux-mêmes, et il
    doit rester lisible même quand le stock est vide.
    """

    horodatage = models.DateTimeField(default=timezone.now)
    acteur = models.CharField(max_length=150)
    action = models.CharField(max_length=60)
    ancien_nom = models.CharField(max_length=150, blank=True, default="")
    nouveau_nom = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        db_table = "activite_comptes"
        verbose_name = "activité de compte"
        verbose_name_plural = "activités de comptes"
        ordering = ["-id"]

    def __str__(self):
        return "%s %s %s" % (self.acteur, self.action, self.nouveau_nom or self.ancien_nom)
