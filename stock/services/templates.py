# -*- coding: utf-8 -*-
"""Les templates de mission : ce qu'il faut emporter.

Un template décrit **ce qu'il faut emporter**, pas ce qui est réservé. La
distinction commande tout le reste :

- à sa création, aucune vérification de stock ni de disponibilité — un article
  actuellement emprunté a toute sa place dans un template, qui sert à préparer
  une mission future ;
- à son emploi, le stock est vérifié et les exemplaires sont choisis.

Une ligne vise soit un type d'article, soit un exemplaire nommément désigné.
Les deux cohabitent : « la perceuse étiquetée A-12, plus deux perceuses
quelconques » est une demande légitime, et c'est le genre de la ligne, pas une
convention implicite, qui dit de laquelle il s'agit.
"""

from django.utils import timezone

from ..models import Material, MissionTemplate, MissionTemplateItem
from . import action
from .champs import ErreurAction, qte, texte
from .materiel import article, par_libelle


def _lignes(p):
    """Valide la composition envoyée par l'interface."""
    brutes = p.get("lignes")
    if not isinstance(brutes, list) or not brutes:
        raise ErreurAction("Un template doit contenir au moins un article.")
    lignes, vues = [], set()
    for brute in brutes:
        if not isinstance(brute, dict):
            raise ErreurAction("Ligne de template invalide.")
        genre = texte(brute, "genre", maxi=12)
        if genre not in MissionTemplateItem.GENRES:
            raise ErreurAction("Genre de ligne inconnu : « %s »." % genre)
        quantite = qte(brute)
        if genre == MissionTemplateItem.EXEMPLAIRE:
            m = article(texte(brute, "id", maxi=200))
            ligne = {"kind": genre, "libelle": m.nom_affiche,
                     "material_id": m.name, "qty": quantite}
            cle = (genre, m.name)
        else:
            libelle = texte(brute, "libelle", maxi=200)
            if not par_libelle(libelle):
                raise ErreurAction("Aucun article ne porte le nom « %s »." % libelle)
            ligne = {"kind": genre, "libelle": libelle,
                     "material_id": None, "qty": quantite}
            cle = (genre, libelle.casefold())
        if cle in vues:
            raise ErreurAction("« %s » figure deux fois dans le template."
                               % ligne["libelle"])
        vues.add(cle)
        lignes.append(ligne)
    return lignes


def _ecrire_lignes(template, lignes):
    """Remplace la composition, dans l'ordre reçu.

    Effacer puis réécrire plutôt que rapprocher ligne à ligne : la composition
    est courte, et l'ordre des lignes est celui que l'utilisateur a composé —
    le préserver vaut mieux que d'économiser trois écritures.
    """
    template.items.all().delete()
    MissionTemplateItem.objects.bulk_create([
        MissionTemplateItem(template=template, ordre=rang, kind=l["kind"],
                            libelle=l["libelle"], material_id=l["material_id"],
                            qty=l["qty"])
        for rang, l in enumerate(lignes, 1)
    ])


def _homonyme(nom, sauf=None):
    return any(t.name.casefold() == nom.casefold() and t.name != sauf
               for t in MissionTemplate.objects.all())


def choix_exemplaires(p):
    """Ce que la personne qui part en mission a désigné, ligne par ligne.

    Forme attendue : { "<id de ligne>": { "<article>": quantité } }. Les
    quantités nulles sont écartées ici plutôt que refusées : l'interface envoie
    une case par exemplaire, et la plupart restent à zéro.
    """
    brut = p.get("choix") or {}
    if not isinstance(brut, dict):
        raise ErreurAction("Exemplaires choisis invalides.")
    choix = {}
    for cle, repartition in brut.items():
        if not isinstance(repartition, dict):
            raise ErreurAction("Exemplaires choisis invalides.")
        retenus = {}
        for nom, quantite in repartition.items():
            n = qte({"qty": quantite}, mini=0)
            if n:
                retenus[str(nom)] = n
        if retenus:
            choix[str(cle)] = retenus
    return choix


def servir_template(template_nom, choix=None):
    """Traduit un template en emprunts concrets, sans rien écrire.

    Une ligne « exemplaire » désigne son article. Une ligne « type » laisse le
    choix ouvert, et il se règle ici de deux façons :

    - ce que la personne a désigné dans `choix` est servi tel quel. Le template
      dit « une perceuse » ; c'est elle qui sait laquelle elle a prise, et c'est
      ce nom-là qui doit figurer dans le journal ;
    - le reste est servi sur les exemplaires du libellé, dans l'ordre du
      catalogue. Ne rien désigner reste donc possible, et sert trois perceuses
      avec deux lignes de stock si besoin.

    Désigner moins que la quantité demandée est accepté : « j'ai pris celle-ci
    et deux autres, peu importe lesquelles » est une demande courante. En
    désigner plus est une contradiction, et c'est refusé.

    `pris` retient ce que les lignes précédentes ont déjà engagé, faute de quoi
    deux lignes visant le même article promettraient chacune un stock que
    l'autre a consommé.
    """
    template = MissionTemplate.objects.filter(pk=template_nom).first()
    if template is None:
        raise ErreurAction("Le template « %s » n'existe plus." % template_nom)
    choix = choix or {}
    pris, prepare = {}, []

    def libre(m):
        return m.disponible() - pris.get(m.name, 0)

    def prendre(m, quantite):
        pris[m.name] = pris.get(m.name, 0) + quantite
        prepare.append((m, quantite))

    for l in template.items.all():
        if l.kind == MissionTemplateItem.EXEMPLAIRE:
            m = Material.objects.filter(pk=l.material_id).first()
            if m is None:
                raise ErreurAction(
                    "L'exemplaire « %s » du template n'existe plus. Corrigez "
                    "le template avant de l'employer." % l.libelle)
            candidats = [m]
        else:
            candidats = par_libelle(l.libelle)
            if not candidats:
                raise ErreurAction(
                    "Aucun article ne porte le nom « %s ». Corrigez le "
                    "template avant de l'employer." % l.libelle)

        reste = l.qty
        # Une ligne « exemplaire » ne laisse rien à désigner : son article est
        # déjà nommé par le template.
        designes = (choix.get(str(l.id), {})
                    if l.kind == MissionTemplateItem.TYPE else {})
        if designes:
            total = sum(designes.values())
            if total > l.qty:
                raise ErreurAction(
                    "Vous avez désigné %d exemplaire(s) pour « %s », qui n'en "
                    "demande que %d." % (total, l.libelle, l.qty))
            par_nom = {m.name: m for m in candidats}
            for nom, quantite in designes.items():
                m = par_nom.get(nom)
                if m is None:
                    raise ErreurAction(
                        "« %s » n'est pas un exemplaire de « %s ». Rechargez "
                        "la page." % (nom, l.libelle))
                if quantite > libre(m):
                    raise ErreurAction(
                        "L'exemplaire « %s » n'a plus que %d unité(s) "
                        "disponible(s), %d demandée(s). La mission n'a pas "
                        "été créée."
                        % (m.designation, max(0, libre(m)), quantite))
                prendre(m, quantite)
                reste -= quantite

        for m in candidats:
            if reste <= 0:
                break
            part = min(reste, max(0, libre(m)))
            if part:
                prendre(m, part)
                reste -= part
        if reste:
            raise ErreurAction(
                "Stock insuffisant pour « %s » : %d disponible(s), %d "
                "demandée(s). La mission n'a pas été créée."
                % (l.libelle, l.qty - reste, l.qty))

    # Un même article servi par deux lignes — la ligne « exemplaire » et le
    # complément d'une ligne « type », par exemple — ne doit donner qu'un seul
    # emprunt : deux lignes identiques dans une mission ne s'expliqueraient pas
    # depuis l'écran.
    fusionne = {}
    for m, quantite in prepare:
        if m.name in fusionne:
            fusionne[m.name][1] += quantite
        else:
            fusionne[m.name] = [m, quantite]
    return [(m, quantite) for m, quantite in fusionne.values()]


@action("mission.template.creer")
def mission_template_creer(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    if _homonyme(nom):
        raise ErreurAction("Le template « %s » existe déjà." % nom)
    lignes = _lignes(p)
    template = MissionTemplate.objects.create(name=nom, owner=utilisateur,
                                              created_at=timezone.now())
    _ecrire_lignes(template, lignes)
    return "Template « %s » créé" % nom, [["templates", ""]]


@action("mission.template.modifier")
def mission_template_modifier(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    template = MissionTemplate.objects.filter(pk=nom).first()
    if template is None:
        raise ErreurAction("Ce template n'existe plus.")
    nouveau = texte(p, "nouveauNom", obligatoire=False, defaut=nom, maxi=200)
    if _homonyme(nouveau, sauf=nom):
        raise ErreurAction("Le template « %s » existe déjà." % nouveau)
    lignes = _lignes(p)

    if nouveau != nom:
        cible = MissionTemplate.objects.create(name=nouveau, owner=template.owner,
                                               created_at=template.created_at)
        template.items.all().update(template=cible)
        template.delete()
        template = cible
    _ecrire_lignes(template, lignes)

    if nouveau != nom:
        return ("Template « %s » renommé en « %s »" % (nom, nouveau),
                [["templates", ""]])
    return "Template « %s » modifié" % nom, [["templates", ""]]


@action("mission.template.supprimer")
def mission_template_supprimer(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    if not MissionTemplate.objects.filter(pk=nom).exists():
        raise ErreurAction("Ce template n'existe plus.")
    MissionTemplate.objects.filter(pk=nom).delete()
    return "Template « %s » supprimé" % nom, [["templates", ""]]
