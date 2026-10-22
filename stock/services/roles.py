# -*- coding: utf-8 -*-
"""Les actions d'administration des comptes et des groupes.

Réservé aux administrateurs. Un **groupe** est une entité à part entière : on le crée,
on y place des membres, et l'on nomme un chef plus tard — ou jamais. Le chef est un
membre du groupe, et ne dirige qu'un seul groupe ; il peut avoir un adjoint, autre
membre, aux droits identiques. Un compte n'est membre que d'un groupe. Les contrôles ci-dessous maintiennent cela.

L'administrateur, lui, n'appartient à aucun groupe et se règle dans l'administration
Django : c'est le rôle qui donne tous les droits, et il ne se distribue pas depuis
l'écran du stock.
"""

import secrets

from django.db.models import Q

from comptes import recuperation
from comptes.models import ActiviteCompte, Compte, Groupe

from . import action
from .champs import ErreurAction, texte
from .droits import acteur


def _compte(identifiant):
    c = Compte.objects.filter(pk=identifiant).first()
    if c is None:
        raise ErreurAction("Le compte « %s » n'existe pas." % identifiant)
    return c


def _groupe(identifiant):
    try:
        g = Groupe.objects.filter(pk=int(identifiant)).first()
    except (TypeError, ValueError):
        g = None
    if g is None:
        raise ErreurAction("Ce groupe n'existe pas.")
    return g


def _nom_groupe(p, g=None):
    nom = texte(p, "nom", maxi=80)
    autre = Groupe.objects.filter(nom__iexact=nom)
    if g is not None:
        autre = autre.exclude(pk=g.pk)
    if autre.exists():
        raise ErreurAction("Un groupe s'appelle déjà « %s »." % nom)
    return nom


def _materiel(p):
    voulu = texte({"m": p.get("materiel")}, "m", obligatoire=False, maxi=1)
    if voulu not in ("", "1", "2", "3"):
        raise ErreurAction("Matériel inconnu : « %s » (Groupe 1, 2 ou 3, ou aucun)." % voulu)
    return voulu


def _membre_possible(identifiant):
    c = _compte(identifiant)
    if c.administrateur:
        raise ErreurAction(
            "« %s » est administrateur : un administrateur n'appartient à aucun "
            "groupe, il a déjà tous les droits." % c.identifiant)
    if not c.actif:
        raise ErreurAction("Le compte « %s » est désactivé." % c.identifiant)
    return c


def _placer(compte, groupe):
    """Met `compte` dans `groupe` (None : hors de tout groupe).

    Un chef (ou un adjoint) qu'on déplace ou qu'on retire perd sa fonction : on ne
    dirige que le groupe dont on est membre, et jamais sans en être.
    """
    for champ in ("chef", "adjoint"):
        dirige = Groupe.objects.filter(**{champ + "_id": compte.pk}).first()
        if dirige is not None and (groupe is None or dirige.pk != groupe.pk):
            setattr(dirige, champ, None)
            dirige.save(update_fields=[champ])
    compte.membre_de = groupe
    compte.save(update_fields=["membre_de"])


def est_dirigeant(pk):
    return Groupe.objects.filter(Q(chef_id=pk) | Q(adjoint_id=pk)).exists()


def _chef_possible(g, identifiant, role="chef"):
    """`role` : « chef » ou « adjoint »."""
    c = _membre_possible(identifiant)
    autre = Groupe.objects.filter(Q(chef_id=c.pk) | Q(adjoint_id=c.pk)).exclude(pk=g.pk).first()
    if autre is not None:
        raise ErreurAction("« %s » dirige déjà le groupe « %s »." % (c.identifiant, autre.nom))
    if role == "chef" and g.adjoint_id == c.pk:
        raise ErreurAction("« %s » est l'adjoint de ce groupe : retirez-le d'abord de ce "
                           "rôle." % c.identifiant)
    if role == "adjoint" and g.chef_id == c.pk:
        raise ErreurAction("« %s » est déjà le chef de ce groupe." % c.identifiant)
    if c.membre_de_id not in (None, g.pk):
        raise ErreurAction(
            "« %s » est membre du groupe « %s » : retirez-le-en d'abord, ou nommez-le "
            "chef de ce groupe-là." % (c.identifiant, c.membre_de.nom))
    return c


@action("groupe.creer")
def groupe_creer(utilisateur, p):
    """Crée un groupe — avec ou sans chef, avec ou sans membres.

    Paramètres : `nom`, et facultativement `materiel` (« 1 », « 2 », « 3 »), `chef`,
    `adjoint` et `membres` (identifiants). Un groupe vide et sans chef est tout à fait valable : on
    le remplit ensuite.
    """
    nom = _nom_groupe(p)
    materiel = _materiel(p)
    ident = [texte({"c": m}, "c", maxi=150) for m in (p.get("membres") or [])]
    chef = texte({"c": p.get("chef")}, "c", obligatoire=False, maxi=150)
    adjoint = texte({"c": p.get("adjoint")}, "c", obligatoire=False, maxi=150)
    if adjoint and adjoint == chef:
        raise ErreurAction("Le chef et l'adjoint doivent être deux personnes différentes.")
    for r in (chef, adjoint):
        if r and r not in ident:
            ident.append(r)
    # Tout est vérifié **avant** de créer : un refus ne laisse pas un groupe à moitié fait.
    candidats = []
    for m in dict.fromkeys(ident):
        c = _membre_possible(m)
        if c.membre_de_id is not None:
            raise ErreurAction("« %s » est déjà membre du groupe « %s »."
                               % (c.identifiant, c.membre_de.nom))
        if m in (chef, adjoint) and est_dirigeant(c.pk):
            raise ErreurAction("« %s » dirige déjà un groupe." % c.identifiant)
        candidats.append(c)
    g = Groupe.objects.create(nom=nom, materiel=materiel)
    for c in candidats:
        _placer(c, g)
        if c.identifiant == chef:
            g.chef = c
            g.save(update_fields=["chef"])
        elif c.identifiant == adjoint:
            g.adjoint = c
            g.save(update_fields=["adjoint"])
    ActiviteCompte.objects.create(acteur=utilisateur, action="groupe créé", nouveau_nom=nom)
    return "Groupe « %s » créé" % nom, []


@action("groupe.modifier")
def groupe_modifier(utilisateur, p):
    """Renomme un groupe, change son matériel affecté, nomme ou retire son chef.

    Paramètres : `groupe` (identifiant), puis, parmi ceux-ci, ce qui change : `nom`,
    `materiel` ("" pour aucun), `chef` et `adjoint` ("" pour retirer — il reste membre).
    """
    g = _groupe(p.get("groupe"))
    modifie, details = [], []
    if "nom" in p:
        nom = _nom_groupe(p, g)
        if nom != g.nom:
            details.append("renommé « %s »" % nom)
            g.nom = nom
            modifie.append("nom")
    if "materiel" in p:
        materiel = _materiel(p)
        if materiel != g.materiel:
            g.materiel = materiel
            modifie.append("materiel")
            details.append("matériel : %s" % (g.affectation or "aucun"))
    if "chef" in p:
        voulu = texte({"c": p["chef"]}, "c", obligatoire=False, maxi=150)
        if voulu:
            c = _chef_possible(g, voulu)
            if g.chef_id != c.pk:
                _placer(c, g)
                g.chef = c
                modifie.append("chef")
                details.append("chef : %s" % c.identifiant)
        elif g.chef_id:
            g.chef = None
            modifie.append("chef")
            details.append("sans chef")
    if "adjoint" in p:
        voulu = texte({"c": p["adjoint"]}, "c", obligatoire=False, maxi=150)
        if voulu:
            c = _chef_possible(g, voulu, "adjoint")
            if g.adjoint_id != c.pk:
                _placer(c, g)
                g.adjoint = c
                modifie.append("adjoint")
                details.append("adjoint : %s" % c.identifiant)
        elif g.adjoint_id:
            g.adjoint = None
            modifie.append("adjoint")
            details.append("sans adjoint")
    if not modifie:
        return "Groupe « %s » : rien à changer" % g.nom, []
    g.save(update_fields=modifie)
    ActiviteCompte.objects.create(acteur=utilisateur, action="groupe modifié",
                                  nouveau_nom=g.nom)
    return "Groupe « %s » : %s" % (g.nom, ", ".join(details)), []


@action("groupe.supprimer")
def groupe_supprimer(utilisateur, p):
    """Supprime un groupe. Ses membres n'en ont plus, rien d'autre n'est touché."""
    g = _groupe(p.get("groupe"))
    nom, n = g.nom, g.membres.count()
    g.delete()
    ActiviteCompte.objects.create(acteur=utilisateur, action="groupe supprimé",
                                  ancien_nom=nom)
    return "Groupe « %s » supprimé (%d membre%s sans groupe)" % (nom, n, "s" if n > 1 else ""), []


@action("groupe.membre")
def groupe_membre(utilisateur, p):
    """Place un compte dans un groupe, le change de groupe, ou l'en retire.

    Paramètres : `compte`, et `groupe` (identifiant ; vide pour retirer). Un chef qu'on
    déplace ou retire perd la direction de son groupe.
    """
    cible = _compte(texte(p, "compte", maxi=150))
    brut = p.get("groupe")
    if brut in (None, ""):
        if cible.membre_de_id is None:
            return "« %s » n'avait pas de groupe" % cible.identifiant, []
        ancien = cible.membre_de.nom
        _placer(cible, None)
        ActiviteCompte.objects.create(acteur=utilisateur, action="groupe : membre retiré",
                                      ancien_nom=ancien, nouveau_nom=cible.identifiant)
        return "« %s » quitte le groupe « %s »" % (cible.identifiant, ancien), []
    g = _groupe(brut)
    _membre_possible(cible.identifiant)
    if cible.membre_de_id == g.pk:
        return "« %s » est déjà dans « %s »" % (cible.identifiant, g.nom), []
    _placer(cible, g)
    ActiviteCompte.objects.create(acteur=utilisateur, action="groupe : membre ajouté",
                                  ancien_nom=g.nom, nouveau_nom=cible.identifiant)
    return "« %s » rejoint le groupe « %s »" % (cible.identifiant, g.nom), []


@action("compte.etat")
def compte_etat(utilisateur, p):
    """Active ou désactive un compte.

    Un compte désactivé ne peut plus se connecter, et sa session ouverte cesse d'être
    reconnue à la requête suivante : Django relit `is_active` à chaque fois. Rien
    n'est supprimé — son historique, ses emprunts, son sac restent.

    Deux refus, parce que deux erreurs enfermeraient quelqu'un dehors : se désactiver
    soi-même, et désactiver le **dernier administrateur actif** (plus personne ne
    pourrait rien réparer). Un chef qu'on désactive perd la direction de son groupe.
    """
    cible = _compte(texte(p, "compte", maxi=150))
    actif = bool(p.get("actif"))
    if actif == cible.actif:
        return "« %s » : état inchangé" % cible.identifiant, []
    if not actif:
        if cible.identifiant == acteur(p, utilisateur):
            raise ErreurAction("Vous ne pouvez pas désactiver votre propre compte.")
        if cible.administrateur and not Compte.objects.filter(
                administrateur=True, actif=True).exclude(pk=cible.pk).exists():
            raise ErreurAction(
                "« %s » est le dernier administrateur actif : le désactiver ne "
                "laisserait plus personne pour administrer." % cible.identifiant)
        # Un chef désactivé ne dirige plus son groupe, qui reste (avec ses membres).
        Groupe.objects.filter(chef_id=cible.pk).update(chef=None)
        Groupe.objects.filter(adjoint_id=cible.pk).update(adjoint=None)
    cible.actif = actif
    cible.save(update_fields=["actif"])
    ActiviteCompte.objects.create(
        acteur=utilisateur, action="compte réactivé" if actif else "compte désactivé",
        nouveau_nom=cible.identifiant)
    return "« %s » %s" % (cible.identifiant, "réactivé" if actif else "désactivé"), []


# Sans 0/O, 1/I/L : un mot de passe provisoire se dicte et se recopie à la main.
_ALPHABET_PROVISOIRE = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


@action("compte.mot_de_passe")
def compte_mot_de_passe(utilisateur, p):
    """Réinitialise le mot de passe d'un compte, par un mot de passe provisoire.

    Le mot de passe est tiré au hasard **ici** et rendu à l'appelant — **une seule
    fois**, par la clé `_secret` des paramètres, que `stock.api` retire avant d'écrire
    l'historique : il n'entre ni dans le journal des opérations ni dans le résumé. La
    personne devra le remplacer à sa première connexion (`doit_changer`), et ses
    sessions ouvertes se ferment, l'empreinte du mot de passe ayant changé.

    On ne se réinitialise pas soi-même par ici : on change son mot de passe depuis son
    profil, en le connaissant.
    """
    cible = _compte(texte(p, "compte", maxi=150))
    if cible.identifiant == acteur(p, utilisateur):
        raise ErreurAction(
            "Changez votre propre mot de passe depuis votre profil, en le "
            "connaissant : une réinitialisation est faite pour quelqu'un d'autre.")
    provisoire = "".join(secrets.choice(_ALPHABET_PROVISOIRE) for _ in range(12))
    cible.set_password(provisoire)
    cible.doit_changer = True
    cible.save(update_fields=["password", "doit_changer"])
    ActiviteCompte.objects.create(
        acteur=utilisateur, action="mot de passe réinitialisé par un administrateur",
        nouveau_nom=cible.identifiant)
    p["_secret"] = provisoire
    return "Mot de passe de « %s » réinitialisé" % cible.identifiant, []


@action("compte.recuperation")
def compte_recuperation(utilisateur, p):
    """Retire le code de récupération d'un compte.

    Utile si le code a pu être vu par quelqu'un d'autre : il cesse de fonctionner.
    La personne en génère un nouveau depuis ses réglages.
    """
    cible = _compte(texte(p, "compte", maxi=150))
    if not cible.code_recuperation:
        return "« %s » n'avait pas de code de récupération" % cible.identifiant, []
    recuperation.retirer(cible)
    ActiviteCompte.objects.create(
        acteur=utilisateur, action="code de récupération retiré par un administrateur",
        nouveau_nom=cible.identifiant)
    return "Code de récupération de « %s » retiré" % cible.identifiant, []
