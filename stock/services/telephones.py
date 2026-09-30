# -*- coding: utf-8 -*-
"""Les actions sur les téléphones.

Réserver et sortir ne sont pas la même chose, et la différence commande tout :
une réservation ne quitte pas le casier — le stock ne bouge pas, on note
seulement qu'une part est promise — tandis qu'une sortie décrémente le stock.
D'où deux tables, deux écrans, et deux façons de résoudre une ligne.
"""

import base64
import binascii
import io

from django.db.models import Max

from ..models import (PhoneModel, PhoneOut, PhoneReservation, SlotAssignment,
                      Variant)
from . import action, journaux
from .champs import ErreurAction, ligne, qte, texte
from .emplacements import emplacement_de


# --------------------------------------------------------------------------
# Lectures communes
# --------------------------------------------------------------------------

def reference(params, cle="refId"):
    ref = PhoneModel.objects.filter(pk=params.get(cle)).first()
    if ref is None:
        raise ErreurAction("Cette référence n'existe plus. "
                           "Rechargez la page pour voir l'état à jour.")
    return ref


def declinaison(ref, params, cle="variantIdx"):
    liste = list(ref.variants.all())
    if not liste:
        raise ErreurAction("%s %s n'a aucune déclinaison." % (ref.brand, ref.model))
    try:
        i = int(params.get(cle, 0))
    except (TypeError, ValueError):
        i = 0
    if not 0 <= i < len(liste):
        raise ErreurAction("Cette déclinaison n'existe plus. Rechargez la page.")
    return i, liste[i]


def libelle(ref, variante):
    return ("%s %s %s %s" % (ref.brand, ref.model, variante.capa,
                             variante.color)).strip()


def prochain_id():
    existants = set(PhoneModel.objects.values_list("id", flat=True))
    n = 1
    while "R%d" % n in existants:
        n += 1
    return "R%d" % n


def creer_reference(ref_id, marque, modele, mpn, nom_commercial=""):
    ordre = (PhoneModel.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1
    return PhoneModel.objects.create(
        id=ref_id, ordre=ordre, brand=marque, model=modele, mpn=mpn,
        commercial_name=nom_commercial or "")


def creer_variante(ref, capa, couleur, quantite):
    idx = (ref.variants.aggregate(m=Max("idx"))["m"] or -1) + 1
    return Variant.objects.create(phone=ref, idx=idx, capa=capa, color=couleur,
                                  swatch="", qty=quantite)


def variante_par_attributs(ref, capa, couleur):
    return ref.variants.filter(capa=capa, color=couleur).first()


def _mouvement_ligne(modele, ref, qui, quantite, idx, variante):
    from django.utils import timezone
    seq = (modele.objects.filter(phone=ref).aggregate(m=Max("seq"))["m"])
    seq = -1 if seq is None else seq
    return modele.objects.create(
        phone=ref, seq=seq + 1, who=qui, qty=quantite, variant_idx=idx,
        variant=variante, horodatage=timezone.now())


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

@action("telephone.creer")
def telephone_creer(utilisateur, p):
    marque = texte(p, "brand", obligatoire=False, defaut="Sans marque", maxi=120)
    modele = texte(p, "model", obligatoire=False, defaut="Modèle inconnu", maxi=120)
    mpn = texte(p, "mpn", obligatoire=False, defaut="—", maxi=120)
    capa = texte(p, "capa", obligatoire=False, defaut="Indéterminé", maxi=60)
    couleur = texte(p, "color", obligatoire=False, defaut="Standard", maxi=80)
    n = qte(p)

    ref = PhoneModel.objects.filter(brand=marque, model=modele).first()
    if ref is None:
        ref = creer_reference(prochain_id(), marque, modele, mpn)

    v = variante_par_attributs(ref, capa, couleur)
    if v:
        v.qty += n
        v.save(update_fields=["qty"])
    else:
        v = creer_variante(ref, capa, couleur, n)

    casier = texte(p, "slot", obligatoire=False)
    if casier:
        from .emplacements import verifier_casier
        verifier_casier(casier)
        SlotAssignment.objects.update_or_create(
            phone=ref, defaults={"loc": casier})

    loc = emplacement_de(ref.id)
    journaux.mouvement(
        utilisateur,
        "Réception — %d × %s %s %s %s" % (n, ref.brand, ref.model, capa, couleur),
        loc, "ENTRÉE")
    return ("Réception de %d × %s %s" % (n, ref.brand, ref.model),
            [["ref", ref.id], ["assignments", ""], ["movements", ""]])


@action("telephone.reception")
def telephone_reception(utilisateur, p):
    ref = reference(p)
    _, v = declinaison(ref, p)
    n = qte(p)

    v.qty += n
    v.save(update_fields=["qty"])

    journaux.mouvement(utilisateur,
                       "Réception — %d × %s" % (n, libelle(ref, v)),
                       emplacement_de(ref.id), "ENTRÉE")
    return ("Réception de %d × %s" % (n, libelle(ref, v)),
            [["ref", ref.id], ["movements", ""]])


@action("telephone.variante.ajouter")
def telephone_variante_ajouter(utilisateur, p):
    ref = reference(p)
    capa = texte(p, "capa", maxi=60)
    couleur = texte(p, "color", obligatoire=False, defaut="Standard", maxi=80)
    n = qte(p)

    v = variante_par_attributs(ref, capa, couleur)
    if v:
        v.qty += n
        v.save(update_fields=["qty"])
    else:
        v = creer_variante(ref, capa, couleur, n)

    journaux.mouvement(utilisateur,
                       "Réception — %d × %s" % (n, libelle(ref, v)),
                       emplacement_de(ref.id), "ENTRÉE")
    return ("Réception de %d × %s" % (n, libelle(ref, v)),
            [["ref", ref.id], ["movements", ""]])


@action("telephone.supprimer")
def telephone_supprimer(utilisateur, p):
    ref = PhoneModel.objects.filter(pk=p.get("refId")).first()
    if ref is None:
        raise ErreurAction("Ce téléphone n'existe plus.")
    if ref.reservations.exists() or ref.outs.exists():
        raise ErreurAction(
            "Ce téléphone ne peut pas être supprimé tant qu'il possède "
            "des réservations ou des sorties en cours.")
    marque, modele, ref_id = ref.brand, ref.model, ref.id
    # Les déclinaisons, réservations, sorties et le casier fixé partent avec la
    # référence : la cascade est déclarée sur les clés étrangères.
    ref.delete()
    return ("Téléphone %s %s supprimé" % (marque, modele),
            [["ref", ref_id], ["assignments", ""]])


@action("telephone.sortie")
def telephone_sortie(utilisateur, p):
    ref = reference(p)
    i, v = declinaison(ref, p)
    n = qte(p)

    if n > v.qty:
        raise ErreurAction(
            "Stock insuffisant : %d unité(s) disponible(s) pour %s · %s, "
            "%d demandée(s)." % (v.qty, v.capa, v.color, n))

    v.qty -= n
    v.save(update_fields=["qty"])
    _mouvement_ligne(PhoneOut, ref, utilisateur, n, i,
                     "%s · %s" % (v.capa, v.color))
    journaux.mouvement(utilisateur, "Vente — %d × %s" % (n, libelle(ref, v)),
                       emplacement_de(ref.id), "SORTIE")
    return ("Sortie de %d × %s" % (n, libelle(ref, v)),
            [["ref", ref.id], ["movements", ""]])


@action("telephone.reservation")
def telephone_reservation(utilisateur, p):
    ref = reference(p)
    i, v = declinaison(ref, p)
    n = qte(p)

    deja = sum(r.qty for r in ref.reservations.all() if r.variant_idx == i)
    if n + deja > v.qty:
        libre = max(0, v.qty - deja)
        raise ErreurAction(
            "Stock insuffisant : %d unité(s) réservable(s) pour %s · %s "
            "(%d en stock, %d déjà réservée(s))." % (libre, v.capa, v.color,
                                                     v.qty, deja))

    _mouvement_ligne(PhoneReservation, ref, utilisateur, n, i,
                     "%s · %s" % (v.capa, v.color))
    journaux.mouvement(utilisateur,
                       "Réservation — %d × %s" % (n, libelle(ref, v)),
                       emplacement_de(ref.id), "RÉSERV.")
    return ("Réservation de %d × %s" % (n, libelle(ref, v)),
            [["ref", ref.id], ["movements", ""]])


@action("telephone.reservation.vendre")
def telephone_reservation_vendre(utilisateur, p):
    ref = reference(p)
    r = ligne(list(ref.reservations.all()), p, "réservation")
    liste = list(ref.variants.all())
    v = liste[r.variant_idx] if 0 <= r.variant_idx < len(liste) else liste[0]

    if r.qty > v.qty:
        raise ErreurAction(
            "Stock insuffisant : %d unité(s) en stock, %d réservée(s). "
            "Corrigez le stock avant de vendre." % (v.qty, r.qty))

    v.qty -= r.qty
    v.save(update_fields=["qty"])
    _mouvement_ligne(PhoneOut, ref, r.who, r.qty, r.variant_idx, r.variant)
    quantite, variante, qui = r.qty, r.variant, r.who
    r.delete()
    journaux.mouvement(
        qui, "Vente sur réservation — %d × %s %s %s"
        % (quantite, ref.brand, ref.model, variante),
        emplacement_de(ref.id), "SORTIE")
    return ("Vente sur réservation de %d × %s %s" % (quantite, ref.brand, ref.model),
            [["ref", ref.id], ["movements", ""]])


@action("telephone.reservation.annuler")
def telephone_reservation_annuler(utilisateur, p):
    ref = reference(p)
    r = ligne(list(ref.reservations.all()), p, "réservation")
    quantite, variante, qui = r.qty, r.variant, r.who
    r.delete()
    journaux.mouvement(
        qui, "Réservation annulée — %d × %s %s %s"
        % (quantite, ref.brand, ref.model, variante),
        emplacement_de(ref.id), "ANNUL.")
    return ("Réservation annulée : %d × %s %s" % (quantite, ref.brand, ref.model),
            [["ref", ref.id], ["movements", ""]])


@action("telephone.sortie.retour")
def telephone_sortie_retour(utilisateur, p):
    ref = reference(p)
    o = ligne(list(ref.outs.all()), p, "sortie")
    liste = list(ref.variants.all())
    v = liste[o.variant_idx] if 0 <= o.variant_idx < len(liste) else liste[0]

    v.qty += o.qty
    v.save(update_fields=["qty"])
    quantite, variante, qui = o.qty, o.variant, o.who
    o.delete()
    journaux.mouvement(
        qui, "Retour — %d × %s %s %s" % (quantite, ref.brand, ref.model, variante),
        emplacement_de(ref.id), "RETOUR")
    return ("Retour de %d × %s %s" % (quantite, ref.brand, ref.model),
            [["ref", ref.id], ["movements", ""]])


# --------------------------------------------------------------------------
# Import d'un classeur
# --------------------------------------------------------------------------

@action("telephone.importer_xlsx")
def telephone_importer_xlsx(utilisateur, p):
    """Importe un classeur de stock, entièrement ou pas du tout.

    Colonnes imposées, dans cet ordre : Fabricant, Modèle, Nom commercial,
    Quantité. « Modèle » est la référence fabricant, « Nom commercial » le nom
    affiché.
    """
    try:
        contenu = base64.b64decode(p.get("xlsxBase64", ""), validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise ErreurAction("Le fichier XLSX est invalide.")
    if not contenu:
        raise ErreurAction("Aucun fichier XLSX n'a été fourni.")

    from .champs import QTE_MAX

    feuille = None
    touches, total = [], 0
    try:
        from openpyxl import load_workbook
        classeur = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
        feuille = classeur.active
        lignes = feuille.iter_rows(values_only=True)
        entetes = next(lignes, None)
        attendues = ("Fabricant", "Modèle", "Nom commercial", "Quantité")
        if tuple(str(x).strip() if x is not None else "" for x in (entetes or ())) != attendues:
            raise ErreurAction("Les colonnes attendues sont : Fabricant, Modèle, "
                               "Nom commercial, Quantité.")
        for numero, brute in enumerate(lignes, start=2):
            if not any(v is not None and str(v).strip() for v in brute):
                continue
            if len(brute) < 4:
                raise ErreurAction("La ligne %d est incomplète." % numero)
            valeurs = ["" if v is None else str(v).strip() for v in brute[:4]]
            marque, modele, nom_commercial, quantite = valeurs
            if not quantite:
                quantite = 0
            else:
                try:
                    nombre = float(quantite)
                    if not nombre.is_integer():
                        raise ValueError
                    quantite = int(nombre)
                except (TypeError, ValueError):
                    raise ErreurAction(
                        "La quantité de la ligne %d doit être un nombre entier."
                        % numero)
            if not 0 <= quantite <= QTE_MAX:
                raise ErreurAction(
                    "La quantité de la ligne %d doit être comprise entre 0 et %d."
                    % (numero, QTE_MAX))

            ref = PhoneModel.objects.filter(brand=marque, model=nom_commercial).first()
            if ref is None:
                ref = creer_reference(prochain_id(), marque, nom_commercial,
                                      modele, nom_commercial)
            elif ref.commercial_name != nom_commercial:
                ref.commercial_name = nom_commercial
                ref.save(update_fields=["commercial_name"])

            v = variante_par_attributs(ref, "Standard", "Standard")
            if v:
                v.qty += quantite
                v.save(update_fields=["qty"])
            else:
                creer_variante(ref, "Standard", "Standard", quantite)
            if quantite:
                journaux.mouvement(
                    utilisateur,
                    "Import XLSX — %d × %s %s" % (quantite, ref.brand, ref.model),
                    emplacement_de(ref.id), "ENTRÉE")
            if ref.id not in touches:
                touches.append(ref.id)
            total += quantite
    except ErreurAction:
        raise
    except Exception as souci:
        raise ErreurAction("Impossible de lire le fichier XLSX : %s" % souci)
    finally:
        if feuille is not None:
            feuille.parent.close()

    if not touches:
        raise ErreurAction("Le fichier XLSX ne contient aucune ligne de stock.")
    # Le contenu du fichier n'a rien à faire dans l'historique des opérations :
    # quelques centaines de kilo-octets en base64 par import, illisibles.
    p["xlsxBase64"] = "[fichier importé]"
    return ("Import de %d ligne(s), %d téléphone(s)" % (len(touches), total),
            [["ref", ref_id] for ref_id in touches] + [["movements", ""]])
