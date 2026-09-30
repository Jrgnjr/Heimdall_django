# -*- coding: utf-8 -*-
"""Les modèles du stock.

Les noms de tables (`stock_…`) et de colonnes sont ceux de la base existante,
volontairement : c'est ce qui permet de reprendre `donnees.db` sans conversion,
et de revenir à l'application Qt si le déploiement serveur ne convainc pas.
`db_table` et `db_column` ne sont donc pas de la décoration — les retirer
casserait la reprise.

Trois partis pris qui reviennent partout :

- **clés naturelles.** Une référence est « R1 », un article est son nom, une
  mission et une malette sont leur nom. L'interface les manipule comme
  identifiants dans chaque appel d'API ; leur substituer des entiers
  obligerait à réécrire l'interface, pour rien.
- **`ordre` plutôt que l'ordre d'insertion.** L'utilisateur range son
  catalogue ; une colonne explicite le dit, là où `ORDER BY id` ne dirait que
  l'ordre de saisie.
- **`seq` négatif dans les journaux.** Les lignes s'empilent par le haut : la
  plus récente porte le plus petit rang, si bien que les N dernières lignes
  s'obtiennent sans compter la table entière.
"""

from django.db import models


# --------------------------------------------------------------------------
# Version et historique des opérations
# --------------------------------------------------------------------------

class Version(models.Model):
    """Compteur unique, incrémenté à chaque action.

    C'est lui qui permet à l'interface de demander « qu'est-ce qui a changé
    depuis la version N ». Une seule ligne, dont l'identifiant vaut toujours 1.
    """

    valeur = models.IntegerField(default=0)

    class Meta:
        db_table = "stock_version"

    def __str__(self):
        return "version %d" % self.valeur

    @classmethod
    def courante(cls):
        ligne = cls.objects.filter(pk=1).first()
        return ligne.valeur if ligne else 0

    @classmethod
    def poser(cls, valeur):
        cls.objects.update_or_create(pk=1, defaults={"valeur": valeur})


class Operation(models.Model):
    """Ce qu'a fait chaque version, pour pouvoir répondre en différentiel.

    `cibles` dit ce que l'action a touché — une référence, un article, les
    armoires — et c'est ce qui permet de ne renvoyer que cela. `nb_mouvements`
    et `nb_matlog` comptent les lignes de journal ajoutées : le journal
    s'empilant par le haut, connaître le nombre suffit à retrouver lesquelles.
    """

    version = models.IntegerField(unique=True, db_index=True)
    horodatage = models.DateTimeField()
    auteur = models.CharField(max_length=150)
    type = models.CharField(max_length=60)
    parametres = models.TextField()
    resume = models.CharField(max_length=400)
    cibles = models.TextField()
    nb_mouvements = models.IntegerField(default=0)
    nb_matlog = models.IntegerField(default=0)

    class Meta:
        db_table = "stock_operation"
        ordering = ["version"]

    def __str__(self):
        return "v%d %s" % (self.version, self.type)


# --------------------------------------------------------------------------
# Téléphones
# --------------------------------------------------------------------------

class PhoneModel(models.Model):
    """Une référence de téléphone : une marque, un modèle, une réf. fabricant."""

    id = models.CharField(max_length=64, primary_key=True)
    ordre = models.IntegerField(default=0)
    brand = models.CharField("marque", max_length=120)
    model = models.CharField("modèle", max_length=120)
    mpn = models.CharField("référence fabricant", max_length=120, blank=True, default="")
    commercial_name = models.CharField("nom commercial", max_length=200,
                                       blank=True, default="")

    class Meta:
        db_table = "stock_phonemodel"
        ordering = ["ordre", "id"]
        verbose_name = "référence de téléphone"
        verbose_name_plural = "références de téléphones"

    def __str__(self):
        return "%s %s" % (self.brand, self.model)

    @property
    def quantite(self):
        return sum(v.qty for v in self.variants.all())


class Variant(models.Model):
    """Une déclinaison : capacité et couleur, avec son propre stock.

    `idx` est le rang de la déclinaison dans sa référence. L'interface le passe
    en paramètre (`variantIdx`) plutôt que la clé de la ligne, et c'est ce rang
    qui figure dans les réservations et les sorties.
    """

    idx = models.IntegerField()
    capa = models.CharField("capacité", max_length=60)
    color = models.CharField("couleur", max_length=80)
    swatch = models.CharField(max_length=32, blank=True, default="")
    qty = models.IntegerField("quantité", default=0)
    phone = models.ForeignKey(PhoneModel, on_delete=models.CASCADE,
                              db_column="phone_id", related_name="variants",
                              db_index=True)

    class Meta:
        db_table = "stock_variant"
        ordering = ["idx", "id"]
        verbose_name = "déclinaison"
        verbose_name_plural = "déclinaisons"

    def __str__(self):
        return "%s %s" % (self.capa, self.color)


class MouvementTelephone(models.Model):
    """Base commune aux réservations et aux sorties.

    Les deux portent exactement les mêmes colonnes et ne se distinguent que par
    ce qu'elles signifient : une réservation ne quitte pas le casier, une
    sortie oui. Deux tables séparées parce que l'interface les affiche et les
    résout différemment.
    """

    seq = models.IntegerField()
    who = models.CharField("au nom de", max_length=120)
    qty = models.IntegerField("quantité")
    variant_idx = models.IntegerField()
    variant = models.CharField(max_length=160)
    horodatage = models.DateTimeField()

    # `phone` n'est pas déclaré ici : Django refuse qu'une classe concrète
    # redéfinisse un champ hérité d'une abstraite, et chaque table a besoin de
    # son propre `related_name`. Les deux filles le déclarent donc elles-mêmes.

    class Meta:
        abstract = True
        ordering = ["seq", "id"]

    def __str__(self):
        return "%d × %s" % (self.qty, self.variant)


class PhoneReservation(MouvementTelephone):
    """Réservée : l'appareil n'a pas quitté son casier."""

    phone = models.ForeignKey(PhoneModel, on_delete=models.CASCADE,
                              db_column="phone_id", db_index=True,
                              related_name="reservations")

    class Meta(MouvementTelephone.Meta):
        abstract = False
        db_table = "stock_phonereservation"
        verbose_name = "réservation de téléphone"
        verbose_name_plural = "réservations de téléphones"


class PhoneOut(MouvementTelephone):
    """Sortie : l'appareil est parti, et le stock a été décrémenté."""

    phone = models.ForeignKey(PhoneModel, on_delete=models.CASCADE,
                              db_column="phone_id", db_index=True,
                              related_name="outs")

    class Meta(MouvementTelephone.Meta):
        abstract = False
        db_table = "stock_phoneout"
        verbose_name = "sortie de téléphone"
        verbose_name_plural = "sorties de téléphones"


class Cabinet(models.Model):
    """Une armoire : des étagères et des colonnes, donc des casiers."""

    id = models.CharField(max_length=32, primary_key=True)
    ordre = models.IntegerField(default=0)
    shelves = models.IntegerField("étagères", default=1)
    cols = models.IntegerField("colonnes", default=1)

    class Meta:
        db_table = "stock_cabinet"
        ordering = ["ordre", "id"]
        verbose_name = "armoire"
        verbose_name_plural = "armoires"

    def __str__(self):
        return self.id

    @property
    def casiers(self):
        return self.shelves * self.cols


class SlotAssignment(models.Model):
    """Un casier choisi à la main, qui l'emporte sur le placement automatique."""

    phone = models.OneToOneField(PhoneModel, on_delete=models.CASCADE,
                                 db_column="phone_id", primary_key=True,
                                 related_name="casier")
    loc = models.CharField(max_length=64)

    class Meta:
        db_table = "stock_slotassignment"
        verbose_name = "casier fixé"
        verbose_name_plural = "casiers fixés"

    def __str__(self):
        return "%s → %s" % (self.phone_id, self.loc)


class PhoneMovement(models.Model):
    """Journal des mouvements de téléphones."""

    seq = models.IntegerField()
    user = models.CharField("par", max_length=120)
    label = models.CharField(max_length=400)
    loc = models.CharField("emplacement", max_length=64, blank=True, default="")
    kind = models.CharField("genre", max_length=40)
    horodatage = models.DateTimeField()

    class Meta:
        db_table = "stock_phonemovement"
        ordering = ["seq", "id"]
        verbose_name = "mouvement de téléphone"
        verbose_name_plural = "mouvements de téléphones"

    def __str__(self):
        return "%s · %s" % (self.kind, self.label)


# --------------------------------------------------------------------------
# Matériel
# --------------------------------------------------------------------------

class Material(models.Model):
    """Un article de matériel, ou un exemplaire d'article.

    Deux façons de s'en servir, et c'est la présence d'un numéro de série qui
    les distingue :

    - **groupé** : une ligne, une quantité. Des câbles, des chargeurs — rien ne
      distingue le troisième du quatrième ;
    - **exemplaire** : une ligne par objet, quantité 1, son numéro de série.
      C'est ce qui permet de dire lequel est sorti, et lequel a été consommé.

    `name` est la clé et `libelle` le nom affiché : deux exemplaires du même
    article portent le même libellé et des clés distinctes (« Cartouche »,
    « Cartouche #2 »). L'interface les regroupe par libellé.
    """

    CATEGORIE_CONSOMMABLE = "Consommable"
    CATEGORIES = ["Stockage", "Dongle", "Outil", "Ordinateur",
                  CATEGORIE_CONSOMMABLE, "Autre"]

    name = models.CharField("clé", max_length=200, primary_key=True)
    ordre = models.IntegerField(default=0)
    cat = models.CharField("catégorie", max_length=80)
    qty = models.IntegerField("quantité", default=0)
    seuil = models.IntegerField(
        "seuil d'alerte", default=0,
        help_text="Stock en dessous duquel l'article est signalé à "
                  "recommander. Zéro ne déclenche rien.")
    affectation = models.CharField(max_length=20, default="Commun")
    libelle = models.CharField("libellé", max_length=200, blank=True, default="")
    etiquette = models.CharField(max_length=200, blank=True, default="")
    numero_serie = models.CharField("numéro de série", max_length=200,
                                    blank=True, default="")

    class Meta:
        db_table = "stock_material"
        ordering = ["ordre", "name"]
        verbose_name = "article de matériel"
        verbose_name_plural = "articles de matériel"

    def __str__(self):
        return self.designation

    @property
    def nom_affiche(self):
        return self.libelle or self.name

    @property
    def identite(self):
        """Ce qui distingue un exemplaire de ses jumeaux, ou rien.

        Doit rester identique à `exemplaireDetail()` d'index.html : la même
        forme est affichée à l'écran et recopiée dans le journal, et deux
        écritures différentes donneraient l'impression de deux articles.
        """
        marques = []
        if self.etiquette:
            marques.append("étiquette %s" % self.etiquette)
        if self.numero_serie:
            marques.append("série %s" % self.numero_serie)
        return " · ".join(marques)

    @property
    def designation(self):
        """Comment nommer l'exemplaire à l'utilisateur.

        Sans cela, un refus parlerait de « Perceuse » quand trois articles
        portent ce nom.
        """
        marques = self.identite
        return "%s (%s)" % (self.nom_affiche, marques) if marques else self.nom_affiche

    @property
    def est_consommable(self):
        return self.cat == self.CATEGORIE_CONSOMMABLE

    def disponible(self):
        """Stock réellement empruntable : le stock moins ce qui est dehors.

        Un emprunt rendu ne compte plus. La quantité, elle, ne bouge qu'à la
        réception, à la suppression, et à la consommation d'un consommable.
        """
        pris = sum(r.qty for r in self.emprunts.all()
                   if not (r.returned_by or r.returned_at))
        return self.qty - pris


class MaterialReservation(models.Model):
    """Un emprunt de matériel, ouvert ou rendu.

    `pack` retient la malette d'où l'article est sorti, et reste vide pour un
    emprunt pris à l'unité. C'est ce qui permet de rendre une malette d'un
    geste, et de dire à l'écran laquelle est dehors.
    """

    seq = models.IntegerField()
    qty = models.IntegerField("quantité")
    mission = models.CharField(max_length=200, default="—")
    taken_by = models.CharField("pris par", max_length=120)
    returned_by = models.CharField("rendu par", max_length=120, null=True, blank=True)
    material = models.ForeignKey(Material, on_delete=models.CASCADE,
                                 db_column="material_id", db_index=True,
                                 related_name="emprunts")
    taken_at = models.DateTimeField("pris le", null=True, blank=True)
    returned_at = models.DateTimeField("rendu le", null=True, blank=True)
    pack = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "stock_materialreservation"
        ordering = ["material_id", "seq"]
        verbose_name = "emprunt de matériel"
        verbose_name_plural = "emprunts de matériel"

    def __str__(self):
        return "%d × %s" % (self.qty, self.material_id)

    @property
    def ouvert(self):
        return not (self.returned_by or self.returned_at)


class MaterialLog(models.Model):
    """Journal du matériel : créations, entrées, sorties, retours, consommations.

    `identite` est recopiée au moment du mouvement plutôt que relue à
    l'affichage : l'article peut être supprimé ou réétiqueté plus tard, la
    ligne doit continuer à dire ce qui est réellement sorti ce jour-là.
    """

    CREATION = "CRÉATION"
    ENTREE = "ENTRÉE"
    SORTIE = "SORTIE"
    RETOUR = "RETOUR"
    CONSOMME = "CONSOMMÉ"

    seq = models.IntegerField()
    kind = models.CharField("genre", max_length=40)
    item = models.CharField("article", max_length=200)
    qty = models.IntegerField("quantité")
    who = models.CharField("par", max_length=120, default="—")
    mission = models.CharField(max_length=200, default="—")
    commentaire = models.CharField(max_length=500, blank=True, default="")
    identite = models.CharField(max_length=200, blank=True, default="")
    horodatage = models.DateTimeField()

    class Meta:
        db_table = "stock_materiallog"
        ordering = ["seq", "id"]
        verbose_name = "ligne de journal du matériel"
        verbose_name_plural = "journal du matériel"

    def __str__(self):
        return "%s · %d × %s" % (self.kind, self.qty, self.item)


# --------------------------------------------------------------------------
# Missions
# --------------------------------------------------------------------------

class Mission(models.Model):
    """Une mission, réelle ou déduite.

    `is_meta` distingue les deux : une mission créée dans l'écran « Missions »
    est réelle et s'affiche même sans matériel ; une mission qui n'existe que
    parce qu'un emprunt la nomme est implicite, et disparaît avec lui.
    """

    PREVUE = "PRÉVUE"
    EN_COURS = "EN COURS"
    TERMINEE = "TERMINÉE"
    STATUTS = (PREVUE, EN_COURS, TERMINEE)
    SANS_MISSION = "—"

    name = models.CharField(max_length=200, primary_key=True)
    ordre = models.IntegerField(null=True, blank=True)
    is_meta = models.BooleanField("mission réelle", default=True)
    owner = models.CharField("créée par", max_length=120, blank=True, default="")
    status_override = models.CharField("statut imposé", max_length=40,
                                       null=True, blank=True)
    archived = models.BooleanField("archivée", default=False)
    planned_date = models.DateField("date prévue", null=True, blank=True)

    class Meta:
        db_table = "stock_mission"
        # `ordre IS NULL, ordre, name` d'origine : les missions rangées
        # d'abord, les autres derrière, par ordre alphabétique.
        ordering = [models.F("ordre").asc(nulls_last=True), "name"]
        verbose_name = "mission"
        verbose_name_plural = "missions"

    def __str__(self):
        return self.name


class MissionTemplate(models.Model):
    """Un template : ce qu'il faut emporter, sans rien contenir.

    À sa création, aucune vérification de stock — un article emprunté a toute
    sa place dans un template, qui sert à préparer une mission future. C'est à
    son emploi que le stock est vérifié et que les exemplaires sont choisis.
    """

    name = models.CharField(max_length=200, primary_key=True)
    owner = models.CharField("créé par", max_length=120, blank=True, default="")
    created_at = models.DateTimeField()

    class Meta:
        db_table = "stock_mission_template"
        ordering = ["name"]
        verbose_name = "template de mission"
        verbose_name_plural = "templates de mission"

    def __str__(self):
        return self.name


class MissionTemplateItem(models.Model):
    """Une ligne de template : un type d'article, ou un exemplaire désigné.

    Les deux cohabitent : « la perceuse étiquetée A-12, plus deux perceuses
    quelconques » est une demande légitime, et c'est `kind` qui dit de laquelle
    il s'agit — pas une convention implicite.

    Pas de clé étrangère vers `Material` : un exemplaire supprimé ne doit pas
    faire disparaître la ligne qui le nommait. Elle reste, signalée comme
    cassée, et c'est à l'utilisateur de la corriger.
    """

    TYPE = "type"
    EXEMPLAIRE = "exemplaire"
    GENRES = (TYPE, EXEMPLAIRE)

    template = models.ForeignKey(MissionTemplate, on_delete=models.CASCADE,
                                 db_column="template_name",
                                 related_name="items", db_index=True)
    ordre = models.IntegerField(default=0)
    kind = models.CharField("genre", max_length=12)
    libelle = models.CharField(max_length=200, blank=True, default="")
    material_id = models.CharField("exemplaire désigné", max_length=200,
                                   null=True, blank=True)
    qty = models.IntegerField("quantité", default=1)

    class Meta:
        db_table = "stock_mission_template_item"
        ordering = ["ordre", "id"]
        verbose_name = "ligne de template"
        verbose_name_plural = "lignes de template"

    def __str__(self):
        return "%d × %s" % (self.qty, self.libelle)


# --------------------------------------------------------------------------
# Packs
# --------------------------------------------------------------------------

class Pack(models.Model):
    """Une malette : des articles rangés dans un même contenant physique.

    Ce qu'elle n'est pas : un template. Un template décrit une liste à
    emporter ; une malette est un objet posé sur une étagère, dont le contenu
    est connu. De là trois différences : n'importe quel compte la compose, elle
    s'emprunte sans passer par une mission, et **elle ne réserve rien** —
    ranger un adaptateur dedans ne le retire pas du stock. La disponibilité se
    vérifie au départ, comme partout ailleurs.
    """

    name = models.CharField(max_length=200, primary_key=True)
    ordre = models.IntegerField(default=0)
    owner = models.CharField("composée par", max_length=120, blank=True, default="")
    etiquette = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField()

    class Meta:
        db_table = "stock_pack"
        ordering = ["ordre", "name"]
        verbose_name = "pack"
        verbose_name_plural = "packs"

    def __str__(self):
        return self.name


class PackItem(models.Model):
    """Une ligne de contenu de malette.

    Toujours un exemplaire du catalogue, jamais un libellé : une malette
    contient des objets, pas des intentions. C'est la différence avec une ligne
    de template, qui peut rester ouverte.

    Pas de clé étrangère, pour la même raison que les lignes de template — un
    article supprimé laisse une ligne cassée, visible et corrigible, plutôt
    qu'un contenu qui s'évapore.
    """

    pack = models.ForeignKey(Pack, on_delete=models.CASCADE,
                             db_column="pack_name", related_name="items",
                             db_index=True)
    ordre = models.IntegerField(default=0)
    material_id = models.CharField("exemplaire", max_length=200)
    qty = models.IntegerField("quantité", default=1)

    class Meta:
        db_table = "stock_pack_item"
        ordering = ["ordre", "id"]
        verbose_name = "ligne de pack"
        verbose_name_plural = "lignes de pack"

    def __str__(self):
        return "%d × %s" % (self.qty, self.material_id)
