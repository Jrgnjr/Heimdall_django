# -*- coding: utf-8 -*-
"""Les équipes d'une mission : des personnes, et leur matériel.

Une mission se divise souvent en groupes qui partent chacun de leur côté.
Sans équipes, le matériel d'une mission est un tas unique et personne ne sait
qui emporte quoi.

Deux choses distinctes, et il faut les tenir séparées :

- **les membres** sont un état courant. Composer l'équipe, c'est dire qui en
  fait partie aujourd'hui ; rien n'est conservé de la composition d'avant ;
- **le matériel** est un historique. Chaque ligne d'emprunt garde le nom de
  l'équipe à qui elle était attribuée, y compris après son retour et y compris
  si l'équipe est supprimée — le journal doit continuer à dire ce qui est
  parti avec qui.

Le matériel se répartit **après** l'emprunt autant qu'au moment de l'emprunt :
on rassemble ce qu'il faut pour la mission, puis on le divise. `equipe` sur un
emprunt est donc modifiable, contrairement à `pack` qui dit d'où l'objet sort.
"""

from django.db.models import Max

from comptes.models import Compte

from ..models import Equipe, MaterialReservation, Mission
from . import action, journaux
from .champs import ErreurAction, ligne, texte
from .droits import acteur, dans_le_groupe, est_admin, est_chef
from .gestion import effectifs_de, exiger_gestion, gestionnaires_de
from .statuts import statut_de

SANS_EQUIPE = ""


# --------------------------------------------------------------------------
# Lectures communes
# --------------------------------------------------------------------------

def mission_existante(nom):
    m = Mission.objects.filter(pk=nom).first()
    if m is None:
        raise ErreurAction("La mission « %s » n'existe plus. Rechargez la page."
                           % nom)
    return m


def equipe_existante(mission, nom):
    e = Equipe.objects.filter(mission=mission, nom=nom).first()
    if e is None:
        raise ErreurAction(
            "L'équipe « %s » n'existe pas dans « %s ». Rechargez la page."
            % (nom, mission.name if hasattr(mission, "name") else mission))
    return e


def _homonyme(mission, nom, sauf=None):
    """Deux équipes de même nom dans la même mission ne se distingueraient pas.

    Le contrôle ne porte que sur la mission : deux missions peuvent chacune
    avoir leur « Équipe A », et c'est normal.
    """
    return any(e.nom.casefold() == nom.casefold() and e.nom != sauf
               for e in mission.equipes.all())


def equipe_demandee(p, mission_nom, cle="equipe"):
    """L'équipe indiquée par l'interface, ou « aucune ».

    Une valeur absente vaut « rattaché à la mission sans plus de précision » :
    c'est le cas des missions sans équipes, et de tout ce qui existait avant
    qu'elles n'existent.
    """
    nom = texte(p, cle, obligatoire=False)
    if not nom:
        return SANS_EQUIPE
    if not mission_nom or mission_nom == Mission.SANS_MISSION:
        raise ErreurAction(
            "Une équipe n'a de sens que dans une mission : choisissez d'abord "
            "la mission.")
    mission = mission_existante(mission_nom)
    return equipe_existante(mission, nom).nom


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------

@action("mission.equipe.creer")
def mission_equipe_creer(utilisateur, p):
    mission = mission_existante(texte(p, "mission", maxi=200))
    exiger_gestion(mission.name, utilisateur, p)
    nom = texte(p, "nom", maxi=200)
    if _homonyme(mission, nom):
        raise ErreurAction(
            "L'équipe « %s » existe déjà dans « %s »." % (nom, mission.name))
    if mission.equipes.count() >= 50:
        raise ErreurAction("Trop d'équipes dans une seule mission.")
    ordre = (mission.equipes.aggregate(m=Max("ordre"))["m"] or 0) + 1
    Equipe.objects.create(mission=mission, nom=nom, ordre=ordre)
    return ("Équipe « %s » créée dans « %s »" % (nom, mission.name),
            [["equipes", ""], ["mission", mission.name]])


@action("mission.equipe.renommer")
def mission_equipe_renommer(utilisateur, p):
    """Renomme une équipe, et suit ses emprunts.

    Le renommage se propage aux lignes d'emprunt, contrairement à ce que fait
    le journal du matériel : une ligne d'emprunt dit **où est** le matériel,
    pas où il était, et une équipe renommée doit continuer de le retrouver.
    """
    mission = mission_existante(texte(p, "mission", maxi=200))
    exiger_gestion(mission.name, utilisateur, p)
    nom = texte(p, "nom", maxi=200)
    equipe = equipe_existante(mission, nom)
    nouveau = texte(p, "nouveauNom", maxi=200)
    if nouveau == nom:
        return ("Équipe « %s » inchangée" % nom, [["equipes", ""]])
    if _homonyme(mission, nouveau, sauf=nom):
        raise ErreurAction(
            "L'équipe « %s » existe déjà dans « %s »." % (nouveau, mission.name))

    equipe.nom = nouveau
    equipe.save(update_fields=["nom"])
    MaterialReservation.objects.filter(mission=mission.name, equipe=nom) \
                               .update(equipe=nouveau)
    return ("Équipe « %s » renommée en « %s »" % (nom, nouveau),
            [["equipes", ""], ["mission", mission.name]])


@action("mission.equipe.supprimer")
def mission_equipe_supprimer(utilisateur, p):
    """Supprime une équipe, si elle ne détient plus rien.

    Ce qu'elle a rendu garde son nom dans l'historique : la colonne est une
    chaîne, pas une relation, et c'est précisément pour ça. Mais ce qui est
    encore dehors doit d'abord être rendu ou déplacé — sinon du matériel se
    retrouverait attribué à une équipe qui n'existe plus, et l'écran ne saurait
    plus où le ranger.
    """
    mission = mission_existante(texte(p, "mission", maxi=200))
    exiger_gestion(mission.name, utilisateur, p)
    nom = texte(p, "nom", maxi=200)
    equipe = equipe_existante(mission, nom)

    ouverts = MaterialReservation.objects.filter(
        mission=mission.name, equipe=nom, returned_by__isnull=True).count()
    if ouverts:
        raise ErreurAction(
            "« %s » détient encore %d ligne(s) de matériel. Rendez-les, ou "
            "déplacez-les vers une autre équipe." % (nom, ouverts))

    equipe.delete()
    return ("Équipe « %s » supprimée" % nom,
            [["equipes", ""], ["mission", mission.name]])


@action("mission.equipe.membres")
def mission_equipe_membres(utilisateur, p):
    """Remplace la liste des membres d'une équipe.

    Remplacer plutôt qu'ajouter et retirer un à un : l'interface envoie la
    composition telle qu'elle l'affiche, et rapprocher deux listes ici
    reviendrait à deviner ce que l'écran voulait dire.

    Un gestionnaire (ou un administrateur) compose l'équipe comme il l'entend. Un
    **chef de groupe**, qui ne gère pas la mission, ne peut y placer ou en retirer
    que **ses** effectifs : le contrôle plus bas porte sur ce qui change.
    """
    mission = mission_existante(texte(p, "mission", maxi=200))
    qui = acteur(p, utilisateur)
    gestionnaire = est_admin(p) or qui in gestionnaires_de(mission.name)
    if not gestionnaire and not est_chef(qui):
        exiger_gestion(mission.name, utilisateur, p)
    nom = texte(p, "nom", maxi=200)
    equipe = equipe_existante(mission, nom)

    brut = p.get("membres")
    if brut is None:
        brut = []
    if not isinstance(brut, list):
        raise ErreurAction("Liste de membres invalide.")
    if len(brut) > 200:
        raise ErreurAction("Trop de membres dans une seule équipe.")

    identifiants, vus = [], set()
    for valeur in brut:
        identifiant = texte({"m": valeur}, "m", maxi=150)
        if identifiant in vus:
            raise ErreurAction("« %s » figure deux fois dans l'équipe."
                               % identifiant)
        vus.add(identifiant)
        if not Compte.objects.filter(pk=identifiant).exists():
            raise ErreurAction("Le compte « %s » n'existe pas." % identifiant)
        identifiants.append(identifiant)

    # On est gestionnaire ou effectif, pas les deux. Seuls les ajouts sont
    # contrôlés : quelqu'un déjà dans l'équipe n'est pas refusé rétroactivement.
    deja = set(equipe.membres.values_list("identifiant", flat=True))
    if not gestionnaire:
        # Chef de groupe : seuls les mouvements de ses effectifs lui reviennent.
        etrangers = [c for c in (set(identifiants) ^ deja) if not dans_le_groupe(qui, c)]
        if etrangers:
            raise ErreurAction(
                "Un chef de groupe ne place dans une équipe que ses propres effectifs "
                "(%s n'en fait pas partie). Le reste est réservé aux gestionnaires "
                "de la mission « %s » (%s) et aux administrateurs."
                % (", ".join(sorted(etrangers)), mission.name,
                   ", ".join(gestionnaires_de(mission.name)) or "aucun"))
    gestion = set(gestionnaires_de(mission.name))
    for identifiant in identifiants:
        if identifiant in gestion and identifiant not in deja:
            raise ErreurAction(
                "« %s » gère la mission « %s » : on est soit en gestion, soit en "
                "effectif. Retirez-le d'abord de la gestion." % (identifiant, mission.name))

    equipe.membres.set(identifiants)
    return ("« %s » : %d membre(s)" % (nom, len(identifiants)),
            [["equipes", ""], ["mission", mission.name]])


# --------------------------------------------------------------------------
# Répartition du matériel
# --------------------------------------------------------------------------

@action("materiel.equipe.affecter")
def materiel_equipe_affecter(utilisateur, p):
    """Déplace une ligne d'emprunt vers une équipe, ou l'en retire.

    C'est ce qui permet de travailler dans l'ordre naturel : rassembler le
    matériel de la mission, puis le répartir. Sans cela, il faudrait rendre et
    ressortir pour corriger une répartition, ce qui laisserait deux lignes de
    journal pour rien.

    Une équipe vide remet la ligne au niveau de la mission.
    """
    from .materiel import article

    m = article(texte(p, "nom", maxi=200))
    r = ligne(list(m.emprunts.all()), p, "ligne d'emprunt")
    if not r.ouvert:
        raise ErreurAction(
            "Cette ligne est déjà rendue : son équipe appartient à "
            "l'historique et ne se change plus.")
    if r.mission == Mission.SANS_MISSION or not r.mission:
        raise ErreurAction(
            "Cette ligne n'est rattachée à aucune mission : il n'y a pas "
            "d'équipe où la mettre.")

    exiger_gestion(r.mission, utilisateur, p, "Répartir le matériel d'une mission")
    mission = mission_existante(r.mission)
    voulue = texte(p, "equipe", obligatoire=False)
    cible = equipe_existante(mission, voulue).nom if voulue else SANS_EQUIPE

    if cible == r.equipe:
        return ("%s : équipe inchangée" % m.nom_affiche, [["materiel", m.name]])

    avant = r.equipe or "la mission"
    r.equipe = cible
    r.save(update_fields=["equipe"])
    journaux.materiel(
        "AJUST.", m.nom_affiche, r.qty, utilisateur, r.mission,
        "Réaffecté de %s vers %s" % (avant, cible or "la mission"), m.identite)
    return ("%d × %s → %s" % (r.qty, m.nom_affiche, cible or "la mission"),
            [["materiel", m.name], ["matLog", ""], ["mission", r.mission]])


@action("materiel.mission.desassigner")
def materiel_mission_desassigner(utilisateur, p):
    """Retire une ligne d'une mission **prévue**, et rend le matériel.

    Tant que la mission est prévue, le matériel qu'on lui a affecté n'est pas
    parti : c'est une réservation. La défaire, c'est le rendre — il regagne le
    stock, ou le sac qui l'avait prêté. C'est la correction d'une affectation à
    tort, ou d'un besoin qui a changé.

    La ligne est **supprimée**, et non fermée comme le fait une restitution : une
    ligne fermée resterait dans la mission, et une mission dont toutes les lignes
    sont rendues est calculée « terminée » — la mission prévue, vidée de son
    matériel, passerait donc à « terminée » le jour de sa date. Le journal garde
    la trace, avec un RETOUR.

    Une fois la mission en cours, on ne désassigne plus : on **restitue**
    (`materiel.mission.restituer_ligne`), et la ligne reste dans son histoire.
    """
    from .materiel import article

    m = article(texte(p, "nom", maxi=200))
    r = ligne(list(m.emprunts.all()), p, "ligne d'emprunt")
    if not r.ouvert:
        raise ErreurAction(
            "Cette ligne est déjà rendue : elle n'est plus affectée à la mission.")
    if r.mission == Mission.SANS_MISSION or not r.mission:
        raise ErreurAction("Cette ligne n'est affectée à aucune mission.")

    exiger_gestion(r.mission, utilisateur, p, "Désassigner du matériel")
    statut = statut_de(r.mission)
    if statut != Mission.PREVUE:
        raise ErreurAction(
            "La mission « %s » est %s : on ne désassigne du matériel que tant "
            "qu'elle est prévue. Restituez-le à la place." % (r.mission, statut.lower()))

    mission, quantite, preteur = r.mission, r.qty, r.sac_de
    r.delete()
    journaux.materiel(
        "RETOUR", m.nom_affiche, quantite, utilisateur, mission,
        "Désassigné de la mission prévue" + (" (revient dans le sac de %s)" % preteur
                                              if preteur else ""),
        m.identite)
    return ("%d × %s désassigné(s) de « %s » et rendu(s)" % (quantite, m.nom_affiche, mission),
            [["materiel", m.name], ["matLog", ""], ["mission", mission]])


# --------------------------------------------------------------------------
# Lecture pour l'interface
# --------------------------------------------------------------------------

def equipes_json():
    """Les équipes telles que l'interface les lit.

    Une liste plate, pas un dictionnaire par mission : l'interface regroupe
    déjà ses lignes par mission, et une liste se fusionne plus simplement dans
    le différentiel.
    """
    return [
        {"mission": e.mission_id, "nom": e.nom, "ordre": e.ordre,
         "membres": sorted(e.membres.values_list("identifiant", flat=True))}
        for e in Equipe.objects.all().prefetch_related("membres")
    ]
