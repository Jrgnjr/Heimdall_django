# -*- coding: utf-8 -*-
"""Les actions sur les armoires et les casiers.

Deux choses distinctes, et la confusion entre elles coûterait cher :

- **dimensionner** une armoire est de la configuration, réservée aux
  administrateurs ;
- **placer** un téléphone dans un casier est du travail quotidien, ouvert à
  tous.

Le placement est calculé, pas stocké : seuls les casiers choisis à la main sont
enregistrés, et le reste se déduit. Redimensionner une armoire ne laisse donc
jamais d'emplacements périmés en base — mais les casiers fixés qui n'existent
plus doivent être nettoyés, ce que fait `armoire.dimension`.
"""

from django.db.models import Max

from ..models import Cabinet, SlotAssignment
from . import action, journaux
from .champs import ErreurAction, entier, texte
from .emplacements import (carte, emplacement_de, tous_les_casiers,
                           verifier_casier)

MAX_ARMOIRES = 20
MAX_ETAGERES = 8
MAX_COLONNES = 10


def _total(ref):
    return sum(v.qty for v in ref.variants.all())


@action("armoire.affecter")
def armoire_affecter(utilisateur, p):
    from .telephones import reference
    ref = reference(p)
    loc = texte(p, "loc", maxi=64)
    verifier_casier(loc)

    avant = emplacement_de(ref.id)
    SlotAssignment.objects.update_or_create(phone=ref, defaults={"loc": loc})

    # Les modèles déjà présents dans ce casier y sont fixés, pour que le
    # placement automatique ne les déplace pas : le casier devient partagé.
    for autre_id, casier in carte().items():
        if autre_id != ref.id and casier and casier["loc"] == loc:
            SlotAssignment.objects.get_or_create(phone_id=autre_id,
                                                 defaults={"loc": loc})

    if avant != loc:
        journaux.mouvement(
            utilisateur, "Transfert — %d × %s %s (%s → %s)"
            % (_total(ref), ref.brand, ref.model, avant or "sans casier", loc),
            loc, "TRANSF.")
    return ("%s %s placé en %s" % (ref.brand, ref.model, loc),
            [["ref", ref.id], ["assignments", ""], ["movements", ""]])


@action("armoire.liberer")
def armoire_liberer(utilisateur, p):
    from .telephones import reference
    ref = reference(p)
    avant = emplacement_de(ref.id)
    SlotAssignment.objects.filter(phone=ref).delete()
    apres = emplacement_de(ref.id)

    if apres and apres != avant:
        journaux.mouvement(
            utilisateur, "Transfert — %d × %s %s (%s → %s)"
            % (_total(ref), ref.brand, ref.model, avant or "sans casier", apres),
            apres, "TRANSF.")
    return ("%s %s rendu au placement automatique" % (ref.brand, ref.model),
            [["ref", ref.id], ["assignments", ""], ["movements", ""]])


@action("armoire.dimension")
def armoire_dimension(utilisateur, p):
    cab = Cabinet.objects.filter(pk=p.get("cabId")).first()
    if cab is None:
        raise ErreurAction("Cette armoire n'existe plus.")
    champ = p.get("champ")
    if champ not in ("shelves", "cols"):
        raise ErreurAction("Dimension inconnue.")
    delta = entier(p, "delta", -1, 1)
    maxi = MAX_ETAGERES if champ == "shelves" else MAX_COLONNES

    setattr(cab, champ, max(1, min(maxi, getattr(cab, champ) + delta)))
    cab.save(update_fields=[champ])

    # Rétrécir une armoire fait disparaître des casiers : les affectations qui
    # les visaient deviennent impossibles et doivent partir, sans quoi le
    # placement promettrait un emplacement inexistant.
    valides = tous_les_casiers()
    if valides:
        SlotAssignment.objects.exclude(loc__in=valides).delete()
    else:
        SlotAssignment.objects.all().delete()

    return ("Armoire %s : %d étagères × %d casiers"
            % (cab.id, cab.shelves, cab.cols),
            [["cabinets", ""], ["assignments", ""]])


@action("armoire.ajouter")
def armoire_ajouter(utilisateur, p):
    existants = set(Cabinet.objects.values_list("id", flat=True))
    if len(existants) >= MAX_ARMOIRES:
        raise ErreurAction("Nombre maximum d'armoires atteint.")
    n = 1
    while "A%d" % n in existants:
        n += 1
    ordre = (Cabinet.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1
    cab = Cabinet.objects.create(id="A%d" % n, ordre=ordre, shelves=4, cols=5)
    return "Armoire %s créée" % cab.id, [["cabinets", ""]]


@action("armoire.supprimer")
def armoire_supprimer(utilisateur, p):
    if Cabinet.objects.count() <= 1:
        raise ErreurAction("Il doit rester au moins une armoire.")
    cab = Cabinet.objects.filter(pk=p.get("cabId")).first()
    if cab is None:
        raise ErreurAction("Cette armoire n'existe plus.")
    cab_id = cab.id
    # Les casiers fixés dans cette armoire n'ont plus d'objet. Le filtre porte
    # sur le préfixe de l'emplacement, « A1· », qui est la seule trace de
    # l'armoire dans la table des affectations.
    SlotAssignment.objects.filter(loc__startswith=cab_id + "·").delete()
    cab.delete()
    return ("Armoire %s supprimée" % cab_id,
            [["cabinets", ""], ["assignments", ""]])
