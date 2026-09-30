# -*- coding: utf-8 -*-
"""Affectation automatique des casiers.

Portage fidèle de la fonction `placement()` d'index.html. Elle était jusqu'ici
calculée dans le navigateur ; le serveur en a besoin à son tour pour inscrire
l'emplacement dans le journal des mouvements, et pour répondre lui-même à la
question « où se trouve ce modèle ».

Le principe, en trois passes :

1. les casiers choisis à la main sont réservés en priorité absolue, et
   plusieurs modèles peuvent partager le même casier ;
2. les modèles restants sont groupés par marque, chaque groupe cherchant une
   plage de casiers libres consécutifs qui commence une étagère ou tient
   entièrement sur une seule ;
3. ce qui n'a pas trouvé de plage est casé dans les trous restants, dans
   l'ordre.
"""


def construire_casiers(cabinets):
    """Liste ordonnée de tous les casiers existants.

    `cabinets` : itérable de (id, etageres, colonnes), déjà dans l'ordre
    d'affichage.
    """
    casiers = []
    for cab_id, etageres, colonnes in cabinets:
        for e in range(1, etageres + 1):
            for c in range(1, colonnes + 1):
                casiers.append({
                    "cab": cab_id,
                    "shelf": f"E{e}",
                    "col": f"C{c}",
                    "key": f"{cab_id}E{e}",          # identité de l'étagère
                    "loc": f"{cab_id}·E{e}·C{c}",
                })
    return casiers


def placement(cabinets, refs, assignments, extra=None):
    """Emplacement de chaque référence.

    `refs` : liste de (id, marque) dans l'ordre d'affichage.
    `assignments` : dict {ref_id: loc} des casiers choisis à la main.
    `extra` : affectations supplémentaires à simuler sans les enregistrer.

    Retourne {ref_id: casier ou None}. `None` signifie « aucun casier
    disponible », ce que l'interface affiche « NON PLACÉ ».
    """
    casiers = construire_casiers(cabinets)
    occupe = [False] * len(casiers)
    par_loc = {}
    for i, c in enumerate(casiers):
        par_loc.setdefault(c["loc"], i)

    ids = [r[0] for r in refs]
    connus = set(ids)
    carte = {}

    # 1. casiers choisis manuellement
    manuel = dict(assignments)
    if extra:
        manuel.update(extra)
    for ref_id, loc in manuel.items():
        i = par_loc.get(loc)
        if i is not None and ref_id in connus:
            occupe[i] = True
            carte[ref_id] = casiers[i]

    # 2. regroupement par marque, dans l'ordre d'apparition
    marques = []
    for _, marque in refs:
        if marque not in marques:
            marques.append(marque)

    en_attente = []
    for marque in marques:
        bloc = [r for r in refs if r[1] == marque and r[0] not in carte]
        if not bloc:
            continue
        debut = -1
        for i in range(len(casiers)):
            if occupe[i]:
                continue
            if i + len(bloc) > len(casiers):
                continue
            if any(occupe[i + j] for j in range(len(bloc))):
                continue
            commence_etagere = casiers[i]["col"] == "C1"
            meme_etagere = casiers[i + len(bloc) - 1]["key"] == casiers[i]["key"]
            if commence_etagere or meme_etagere:
                debut = i
                break
        if debut >= 0:
            for j, (ref_id, _) in enumerate(bloc):
                carte[ref_id] = casiers[debut + j]
                occupe[debut + j] = True
        else:
            en_attente.extend(ref_id for ref_id, _ in bloc)

    # 3. les laissés-pour-compte prennent les trous restants
    p = 0
    for i in range(len(casiers)):
        if p >= len(en_attente):
            break
        if not occupe[i]:
            occupe[i] = True
            carte[en_attente[p]] = casiers[i]
            p += 1
    for reste in en_attente[p:]:
        carte[reste] = None

    for ref_id in ids:
        carte.setdefault(ref_id, None)
    return carte


def emplacement(carte, ref_id):
    """Libellé d'emplacement tel qu'attendu par le journal."""
    casier = carte.get(ref_id)
    return casier["loc"] if casier else "NON PLACÉ"
