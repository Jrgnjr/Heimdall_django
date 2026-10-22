# -*- coding: utf-8 -*-
"""Qui a le droit de quoi : les rôles, et le contrôle de chaque action.

Quatre rôles. Trois sont **portés par le compte**, un quatrième est **propre à
chaque mission** :

- **effectif** — le rôle de base. Il travaille, emprunte pour lui, demande du
  matériel dans les sacs, répond aux demandes de son propre sac ;
- **chef de groupe** — il a un groupe d'effectifs, que lui rattache un
  administrateur. Il crée des missions, répond aux demandes à la place d'un de ses
  effectifs absent, force des prêts dans leurs sacs, et peut les représenter ;
- **admin** — il a tous les droits, y compris ceux d'un gestionnaire sur **toutes**
  les missions ;
- **gestionnaire d'une mission** (voir `gestion.py`) — il a la charge d'*une*
  mission : son statut, ses équipes, son matériel, ses prêts forcés. Ce n'est pas
  un rôle de compte : un effectif comme un chef de groupe peut l'être, et aucun
  ne l'est d'office.

La hiérarchie est admin ⊃ chef de groupe ⊃ effectif ; le gestionnaire est à part.

**Qui agit.** Une action a deux identités : l'**auteur** (`utilisateur`) — au nom de
qui elle est enregistrée — et l'**acteur** (`_acteur`) — la personne réellement
connectée. Elles diffèrent quand un administrateur ou un chef de groupe agit au
nom de quelqu'un. Les **droits** se jugent sur l'acteur : c'est lui qui engage son
autorité. `executer()` les pose sur les paramètres, écrasant ce que le client aurait
envoyé sous ces noms.

Tout contrôle est fait ici, **côté serveur**. L'interface grise les boutons, ce
n'est qu'une commodité : le refus qui compte est celui-ci.
"""

from django.db.models import Q

from comptes.models import Compte, Groupe

from ..models import Mission
from .champs import ErreurAction
from .gestion import effectifs_de, gestionnaires_de

ADMIN = "admin"
CHEF = "chef de groupe"
EFFECTIF = "effectif"


# --------------------------------------------------------------------------
# Qui est qui
# --------------------------------------------------------------------------

def acteur(p, utilisateur):
    """La personne réellement connectée, à défaut l'auteur."""
    return p.get("_acteur") or utilisateur


def est_admin(p):
    return bool(p.get("_administrateur"))


def role_de(identifiant):
    c = Compte.objects.filter(pk=identifiant).first()
    if c is None:
        return EFFECTIF
    return c.role


def _groupes_diriges(identifiant):
    """Les groupes dont ce compte est le chef ou l'adjoint."""
    return Groupe.objects.filter(Q(chef_id=identifiant) | Q(adjoint_id=identifiant))


def est_chef(identifiant):
    """Chef **ou adjoint** : les deux ont les droits d'un chef de groupe."""
    return bool(identifiant) and _groupes_diriges(identifiant).exists()


def groupe_de(chef):
    """Les identifiants des effectifs du groupe que dirige ce chef (ou cet adjoint).

    Lui est exclu ; et l'adjoint n'a pas la main sur le chef.
    """
    if not chef:
        return set()
    ids = set()
    for g in _groupes_diriges(chef):
        ids |= set(Compte.objects.filter(membre_de=g)
                   .values_list("identifiant", flat=True))
        if g.chef_id != chef:
            ids.discard(g.chef_id)
    ids.discard(chef)
    return ids


def membres_du_groupe(identifiant):
    """Tous les membres actifs du groupe de ce compte, chef compris, triés.

    Le groupe est celui dont le compte est membre, avec ou sans chef. Un compte sans
    groupe renvoie une liste vide. C'est ce que « Mon groupe » montre, et ce que ses
    membres ont le droit de voir les uns des autres.
    """
    c = Compte.objects.filter(pk=identifiant).first()
    if c is None or c.membre_de_id is None:
        return []
    return sorted(Compte.objects.filter(actif=True, membre_de_id=c.membre_de_id)
                  .values_list("identifiant", flat=True))


def groupe_du_compte(identifiant):
    """Le `Groupe` de ce compte, ou None."""
    c = Compte.objects.filter(pk=identifiant).select_related("membre_de").first()
    return c.membre_de if c is not None else None


def affectation_du_groupe(identifiant):
    """L'étiquette du stock (« Groupe 1 »…) du groupe de ce compte, ou ""."""
    g = groupe_du_compte(identifiant)
    return g.affectation if g is not None else ""


def dans_le_groupe(chef, compte):
    """`compte` est-il un effectif du groupe que dirige `chef` (chef ou adjoint) ?"""
    return bool(chef) and compte in groupe_de(chef)


def chef_de(compte):
    c = Compte.objects.filter(pk=compte).first()
    return (c.chef_id or "") if c else ""


# --------------------------------------------------------------------------
# Missions
# --------------------------------------------------------------------------

def exiger_createur(utilisateur, p):
    """Créer une mission : chef de groupe ou administrateur."""
    if est_admin(p) or est_chef(acteur(p, utilisateur)):
        return
    raise ErreurAction(
        "Créer une mission est réservé aux chefs de groupe et aux administrateurs.")


def gere(nom, utilisateur, p):
    """L'acteur est-il gestionnaire de cette mission, ou administrateur ?
    (Pour refuser en le disant : `gestion.exiger_gestion`.)"""
    return est_admin(p) or acteur(p, utilisateur) in gestionnaires_de(nom)


def exiger_emprunt_pour(nom, sujet, utilisateur, p):
    """Emprunter pour une mission : équipier, gestionnaire, administrateur — ou
    chef d'un groupe dont un effectif est équipier.

    `sujet` est celui qui emprunte (l'auteur) ; l'acteur peut être un autre, qui
    l'a représenté. Sans mission, l'emprunt reste libre : on n'arrive pas ici.
    """
    qui = acteur(p, utilisateur)
    if est_admin(p) or qui in gestionnaires_de(nom):
        return
    equipiers = effectifs_de(nom)
    if sujet in equipiers or qui in equipiers:
        return
    if est_chef(qui) and groupe_de(qui) & equipiers:
        return
    raise ErreurAction(
        "On n'emprunte pour la mission « %s » que si l'on en fait partie : "
        "demandez à un gestionnaire (%s) de vous y placer, ou empruntez sans mission."
        % (nom, ", ".join(gestionnaires_de(nom)) or "aucun"))


# --------------------------------------------------------------------------
# Emprunts
# --------------------------------------------------------------------------

def peut_rendre(r, utilisateur, p):
    """Rendre une ligne d'emprunt : son emprunteur, le gestionnaire de sa mission,
    celui dont le sac l'a prêtée, le chef de l'emprunteur, ou un administrateur."""
    qui = acteur(p, utilisateur)
    if est_admin(p) or qui == r.taken_by:
        return True
    if r.mission and r.mission != Mission.SANS_MISSION and qui in gestionnaires_de(r.mission):
        return True
    if r.sac_de and qui == r.sac_de:
        return True
    return dans_le_groupe(qui, r.taken_by)


def exiger_rendre(r, utilisateur, p):
    if not peut_rendre(r, utilisateur, p):
        raise ErreurAction(
            "Seul l'emprunteur (%s), le gestionnaire de la mission, le chef de son "
            "groupe ou un administrateur peut rendre cette ligne." % r.taken_by)


# --------------------------------------------------------------------------
# Sacs et prêts
# --------------------------------------------------------------------------

def peut_repondre_pour(proprietaire, utilisateur, p):
    """Répondre à une demande adressée à `proprietaire` : lui-même, son chef de
    groupe (s'il est absent), ou un administrateur."""
    qui = acteur(p, utilisateur)
    return est_admin(p) or qui == proprietaire or dans_le_groupe(qui, proprietaire)


def peut_representer(compte, utilisateur, p):
    """Agir au nom d'un compte : un administrateur, ou son chef de groupe."""
    return est_admin(p) or dans_le_groupe(acteur(p, utilisateur), compte)
