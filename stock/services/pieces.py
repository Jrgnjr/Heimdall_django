# -*- coding: utf-8 -*-
"""Les pièces détachées de téléphones : les référencer, en suivre le stock.

Un administrateur crée, corrige et supprime les fiches, et enregistre les entrées. Tout
utilisateur peut déclarer une **sortie** (une réparation) : c'est le geste quotidien, comme
pour le matériel. Chaque entrée et chaque sortie laisse une ligne au journal des téléphones,
et le stock ne descend jamais sous zéro.
"""

from ..models import PhoneModel, PiecePhone
from . import action, journaux
from .champs import ErreurAction, qte, texte

TYPES_USUELS = ["Écran", "Batterie", "Connecteur de charge", "Caméra", "Haut-parleur",
                "Nappe", "Coque", "Autre"]


def _piece(p):
    pk = qte({"id": p.get("id")}, cle="id")
    piece = PiecePhone.objects.filter(pk=pk).first()
    if piece is None:
        raise ErreurAction("Cette pièce n'existe plus. Rechargez la page.")
    return piece


def _nom(p, piece=None):
    nom = texte(p, "nom", maxi=200)
    autre = PiecePhone.objects.filter(name__iexact=nom)
    if piece is not None:
        autre = autre.exclude(pk=piece.pk)
    if autre.exists():
        raise ErreurAction("Une pièce s'appelle déjà « %s »." % nom)
    return nom


def _modeles(p):
    brut = p.get("modeles")
    if brut in (None, ""):
        return []
    if not isinstance(brut, list) or len(brut) > 500:
        raise ErreurAction("Liste de modèles invalide.")
    ids = [texte({"m": m}, "m", maxi=64) for m in brut]
    trouves = list(PhoneModel.objects.filter(pk__in=ids))
    if len(trouves) != len(set(ids)):
        raise ErreurAction("Un modèle de téléphone n'existe plus. Rechargez la page.")
    return trouves


def _libelle(n, piece):
    return "Pièce — %d × %s" % (n, piece.name)


@action("piece.creer")
def piece_creer(utilisateur, p):
    nom = _nom(p)
    modeles = _modeles(p)
    n = qte(p, mini=0) if p.get("qty") not in (None, "") else 0
    piece = PiecePhone.objects.create(
        name=nom, kind=texte(p, "type", obligatoire=False, defaut="Autre", maxi=80),
        mpn=texte(p, "mpn", obligatoire=False, maxi=120), qty=n,
        notes=texte(p, "notes", obligatoire=False, maxi=300))
    piece.modeles.set(modeles)
    if n:
        journaux.mouvement(utilisateur, _libelle(n, piece), "", "CRÉATION")
    return "Pièce « %s » créée" % nom, [["pieces", ""]]


@action("piece.modifier")
def piece_modifier(utilisateur, p):
    piece = _piece(p)
    piece.name = _nom(p, piece)
    piece.kind = texte(p, "type", obligatoire=False, defaut="Autre", maxi=80)
    piece.mpn = texte(p, "mpn", obligatoire=False, maxi=120)
    piece.notes = texte(p, "notes", obligatoire=False, maxi=300)
    piece.save(update_fields=["name", "kind", "mpn", "notes"])
    piece.modeles.set(_modeles(p))
    return "Pièce « %s » modifiée" % piece.name, [["pieces", ""]]


@action("piece.supprimer")
def piece_supprimer(utilisateur, p):
    piece = _piece(p)
    nom = piece.name
    piece.delete()
    return "Pièce « %s » supprimée" % nom, [["pieces", ""]]


@action("piece.entree")
def piece_entree(utilisateur, p):
    piece = _piece(p)
    n = qte(p)
    piece.qty += n
    piece.save(update_fields=["qty"])
    journaux.mouvement(utilisateur, _libelle(n, piece), "", "ENTRÉE")
    return "Entrée de %d × %s" % (n, piece.name), [["pieces", ""]]


@action("piece.sortie")
def piece_sortie(utilisateur, p):
    piece = _piece(p)
    n = qte(p)
    motif = texte(p, "motif", obligatoire=False, maxi=200)
    if n > piece.qty:
        raise ErreurAction("« %s » : %d en stock, %d demandée(s)." % (piece.name, piece.qty, n))
    piece.qty -= n
    piece.save(update_fields=["qty"])
    libelle = _libelle(n, piece) + (" (%s)" % motif if motif else "")
    journaux.mouvement(utilisateur, libelle, "", "SORTIE")
    return "Sortie de %d × %s" % (n, piece.name), [["pieces", ""]]
