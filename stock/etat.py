# -*- coding: utf-8 -*-
"""Traduction entre les modèles et le JSON attendu par l'interface.

Le format est repris **au caractère près** de l'application Qt : c'est ce qui
permet de garder `index.html` tel quel. Un champ renommé ici casse un écran
là-bas, en silence — c'est précisément ce que le test qui exécute réellement le
JavaScript sert à attraper.

Deux modes de lecture :

- `charger()`       : l'état complet, au démarrage ou après un décrochage ;
- `charger_delta()` : uniquement ce qui a changé depuis une version donnée.

Le second existe parce que l'interface interroge toutes les 2,5 secondes.
Renvoyer l'état entier à chaque fois coûterait une dizaine de kilo-octets pour
n'apprendre, presque toujours, que rien n'a bougé.
"""

from .models import (Cabinet, MaterialLog, MaterialReservation, Material,
                     Mission, MissionTemplate, Operation, Pack, PhoneModel,
                     PhoneMovement, SlotAssignment, Version)
from .services.champs import iso
from .services.equipes import equipes_json

# Au-delà, une session trop en retard reçoit l'état complet : garder
# l'historique de toutes les opérations depuis toujours pour un onglet resté
# ouvert trois semaines ne vaut pas la place.
OPERATIONS_CONSERVEES = 400


# --------------------------------------------------------------------------
# Fragments
# --------------------------------------------------------------------------

def _mouvement(x):
    return {"who": x.who, "qty": x.qty, "variantIdx": x.variant_idx,
            "variant": x.variant, "iso": iso(x.horodatage)}


def _mouvement_journal(m):
    return {"iso": iso(m.horodatage), "user": m.user, "label": m.label,
            "loc": m.loc, "kind": m.kind}


def _log_journal(e):
    return {"iso": iso(e.horodatage), "kind": e.kind, "item": e.item,
            "qty": e.qty, "who": e.who, "mission": e.mission,
            "commentaire": e.commentaire, "identite": e.identite}


def _mission_json(m):
    return {"name": m.name, "owner": m.owner,
            "date": m.planned_date.isoformat() if m.planned_date else "",
            "archived": bool(m.archived)}


def _emprunt_json(r):
    entree = {"qty": r.qty, "mission": r.mission, "by": r.taken_by,
              "iso": iso(r.taken_at), "pack": r.pack or "",
              "equipe": r.equipe or ""}
    if r.returned_by or r.returned_at:
        entree["returned"] = {"by": r.returned_by or "",
                              "iso": iso(r.returned_at)}
    return entree


def _variante_json(v):
    return {"capa": v.capa, "color": v.color, "swatch": v.swatch, "qty": v.qty}


def _ref_json(ref):
    return {
        "id": ref.id, "brand": ref.brand, "model": ref.model, "mpn": ref.mpn,
        "commercialName": ref.commercial_name,
        "variants": [_variante_json(v) for v in ref.variants.all()],
        "reservations": [_mouvement(r) for r in ref.reservations.all()],
        "outs": [_mouvement(o) for o in ref.outs.all()],
    }


def _materiel_json(m):
    return {"id": m.name, "name": m.libelle or m.name, "cat": m.cat,
            "affectation": m.affectation, "qty": m.qty, "seuil": m.seuil,
            "etiquette": m.etiquette, "numeroSerie": m.numero_serie}


def _template_json(t):
    """Un template tel que l'interface le lit.

    `genre` vaut « type » ou « exemplaire » et décide comment lire la ligne :
    un type se désigne par son `libelle`, un exemplaire par son `id`, qui est la
    clé d'un article du catalogue. `ligne` identifie la ligne elle-même — deux
    lignes peuvent porter le même libellé sans se confondre.
    """
    return {
        "name": t.name, "owner": t.owner,
        "items": [{"ligne": i.id, "genre": i.kind, "libelle": i.libelle,
                   "id": i.material_id, "qty": i.qty}
                  for i in t.items.all()],
    }


def _pack_json(pack, articles):
    """Une malette et son contenu.

    Le libellé de chaque ligne est résolu à la lecture, pas conservé dans la
    table : c'est le nom actuel de l'article qui doit s'afficher, pas celui
    qu'il portait le jour où on l'a rangé. `manquant` signale la ligne dont
    l'article a été supprimé — elle reste visible pour être corrigée, plutôt
    que de disparaître en silence avec son contenu.
    """
    lignes = []
    for item in pack.items.all():
        m = articles.get(item.material_id)
        lignes.append({
            "ligne": item.id, "id": item.material_id,
            "libelle": (m.libelle or m.name) if m else item.material_id,
            "etiquette": m.etiquette if m else "",
            "numeroSerie": m.numero_serie if m else "",
            "qty": item.qty, "manquant": m is None,
        })
    return {"name": pack.name, "owner": pack.owner,
            "etiquette": pack.etiquette, "items": lignes}


def _packs_json():
    # Les articles sont lus une seule fois : un pack de vingt lignes ferait
    # sinon vingt requêtes, et il y a plusieurs packs.
    articles = {m.name: m for m in Material.objects.all()}
    return [_pack_json(x, articles) for x in
            Pack.objects.all().prefetch_related("items")]


def _refs_json(queryset):
    return [_ref_json(r) for r in
            queryset.prefetch_related("variants", "reservations", "outs")]


# --------------------------------------------------------------------------
# Lecture complète
# --------------------------------------------------------------------------

def charger():
    """Recompose l'état applicatif complet.

    Retourne (version, état). Une version à 0 signifie une base vierge :
    l'interface affiche alors une application vide, que les premières saisies
    rempliront.
    """
    v = Version.courante()
    if v == 0:
        return 0, None

    mat_res = {}
    for r in MaterialReservation.objects.all().order_by("material_id", "seq"):
        mat_res.setdefault(r.material_id, []).append(_emprunt_json(r))

    etat = {
        "refs": _refs_json(PhoneModel.objects.all()),
        "cabinets": [{"id": c.id, "shelves": c.shelves, "cols": c.cols}
                     for c in Cabinet.objects.all()],
        "assignments": {a.phone_id: a.loc for a in SlotAssignment.objects.all()},
        "movements": [_mouvement_journal(m) for m in PhoneMovement.objects.all()],
        "materiel": [_materiel_json(m) for m in Material.objects.all()],
        "matRes": mat_res,
        "matLog": [_log_journal(e) for e in MaterialLog.objects.all()],
        "missions": [_mission_json(m) for m in Mission.objects.filter(is_meta=True)],
        "missionStatus": {m.name: m.status_override for m in
                          Mission.objects.exclude(status_override__isnull=True)},
        "templates": [_template_json(t) for t in
                      MissionTemplate.objects.all().prefetch_related("items")],
        "packs": _packs_json(),
        "equipes": equipes_json(),
    }
    return v, etat


# --------------------------------------------------------------------------
# Lecture par différence
# --------------------------------------------------------------------------

def charger_delta(depuis):
    """Ce qui a changé depuis la version `depuis`, ou None si c'est impossible.

    Retourne None — et l'appelant renverra alors l'état complet — dans deux
    cas : la session est trop en retard pour que les opérations correspondantes
    existent encore, ou la modification n'est pas passée par une action
    (correction faite dans l'administration Django, par exemple).
    """
    courante = Version.courante()
    if depuis >= courante:
        return courante, {}

    operations = list(Operation.objects.filter(version__gt=depuis).order_by("version"))
    # Il faut la chaîne complète : s'il manque ne serait-ce qu'une version
    # intermédiaire, on ignore ce qu'elle a modifié.
    attendues = list(range(depuis + 1, courante + 1))
    if [o.version for o in operations] != attendues:
        return courante, None

    import json

    refs_touchees, materiels_touches, missions_touchees = set(), set(), set()
    cabinets = assignments = templates = packs = equipes = False
    for op in operations:
        try:
            cibles = json.loads(op.cibles or "[]")
        except ValueError:
            return courante, None
        for cible in cibles:
            if not isinstance(cible, list) or len(cible) != 2:
                continue
            genre, cle = cible
            if genre == "ref":
                refs_touchees.add(cle)
            elif genre == "materiel":
                materiels_touches.add(cle)
            elif genre in ("mission", "missionSupprimee"):
                missions_touchees.add(cle)
            elif genre == "cabinets":
                cabinets = True
            elif genre == "assignments":
                assignments = True
            elif genre == "templates":
                templates = True
            elif genre == "packs":
                packs = True
            elif genre == "equipes":
                equipes = True

    delta = {}

    if refs_touchees:
        presentes = PhoneModel.objects.filter(pk__in=refs_touchees)
        delta["refs"] = _refs_json(presentes)
        disparues = sorted(refs_touchees - {r["id"] for r in delta["refs"]})
        if disparues:
            delta["refsSupprimes"] = disparues

    if materiels_touches:
        presents = {m.name: m for m in Material.objects.filter(pk__in=materiels_touches)}
        delta["materiel"] = [_materiel_json(m) for m in presents.values()]
        # Une liste vide est significative : elle veut dire « cet article n'a
        # plus aucun emprunt ». Le destinataire doit alors supprimer la clé,
        # pour rester identique à l'état complet, qui n'inscrit que les
        # articles réellement empruntés.
        delta["matRes"] = {
            nom: [_emprunt_json(r) for r in
                  MaterialReservation.objects.filter(material_id=nom).order_by("seq")]
            for nom in presents
        }
        disparus = sorted(materiels_touches - set(presents))
        if disparus:
            delta["materielSupprimes"] = disparus

    # Missions, armoires, affectations, templates et packs sont de petites
    # collections : les renvoyer entières coûte moins cher que de calculer une
    # différence.
    if missions_touchees:
        delta["missions"] = [_mission_json(m) for m in
                             Mission.objects.filter(is_meta=True)]
        delta["missionStatus"] = {
            m.name: m.status_override
            for m in Mission.objects.exclude(status_override__isnull=True)}
    if cabinets:
        delta["cabinets"] = [{"id": c.id, "shelves": c.shelves, "cols": c.cols}
                             for c in Cabinet.objects.all()]
    if assignments or cabinets:
        delta["assignments"] = {a.phone_id: a.loc
                                for a in SlotAssignment.objects.all()}
    if templates:
        delta["templates"] = [_template_json(t) for t in
                              MissionTemplate.objects.all().prefetch_related("items")]
    if packs:
        delta["packs"] = _packs_json()
    # Les équipes suivent les missions : renvoyées entières, comme elles.
    if equipes or missions_touchees:
        delta["equipes"] = equipes_json()

    # Les journaux s'empilent par le haut : les N lignes de plus petit rang sont
    # exactement les N plus récentes.
    n_mouvements = sum(o.nb_mouvements for o in operations)
    if n_mouvements:
        delta["movementsNouveaux"] = [
            _mouvement_journal(m) for m in PhoneMovement.objects.all()[:n_mouvements]]
    n_matlog = sum(o.nb_matlog for o in operations)
    if n_matlog:
        delta["matLogNouveaux"] = [
            _log_journal(e) for e in MaterialLog.objects.all()[:n_matlog]]

    return courante, delta
