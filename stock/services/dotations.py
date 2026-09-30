# -*- coding: utf-8 -*-
"""Le sac de dotation : ce qui a été remis à quelqu'un, et qui reste chez lui.

Ce n'est pas un emprunt. Un emprunt a un retour attendu et pèse sur la
disponibilité ; une dotation est sortie du stock commun pour de bon, et reste
attachée à la personne. C'est pourquoi elle ne passe pas par
`MaterialReservation` — elle n'a pas à apparaître dans les écrans d'emprunts en
cours.

Une ligne désigne un **exemplaire précis** du catalogue. C'est ce qui permet de
dire lequel des trois portables identiques est dans quel sac, et d'afficher son
étiquette et son numéro de série.
"""

from django.db.models import Max

from comptes.models import ActiviteCompte, Compte, Dotation

from ..models import Material
from . import action
from .champs import ErreurAction, qte, texte


def _lignes(p):
    """Valide le sac envoyé par l'interface.

    Forme attendue : `[[article, quantité, détail], …]`, celle de l'application
    Qt — l'interface est la sienne et l'envoie déjà ainsi.
    """
    brutes = p.get("materiel")
    if brutes is None:
        brutes = []
    if not isinstance(brutes, list):
        raise ErreurAction("Sac invalide.")
    if len(brutes) > 200:
        raise ErreurAction("Trop d'articles dans un seul sac.")

    lignes, vues = [], set()
    for brute in brutes:
        if isinstance(brute, dict):
            cle, quantite, detail = (brute.get("article"), brute.get("quantite"),
                                     brute.get("detail"))
        elif isinstance(brute, (list, tuple)) and len(brute) >= 2:
            cle = brute[0]
            quantite = brute[1]
            detail = brute[2] if len(brute) > 2 else ""
        else:
            raise ErreurAction("Ligne de sac invalide.")

        nom = texte({"article": cle}, "article", maxi=200)
        n = qte({"qty": quantite})
        m = Material.objects.filter(pk=nom).first()
        if m is None:
            raise ErreurAction(
                "L'article « %s » n'existe pas dans le catalogue. "
                "Rechargez la page." % nom)
        if m.name in vues:
            raise ErreurAction(
                "« %s » figure deux fois dans le sac." % m.designation)
        vues.add(m.name)
        lignes.append({
            "material_id": m.name, "quantite": n,
            "detail": texte({"d": detail}, "d", obligatoire=False, maxi=200),
        })
    return lignes


@action("compte.dotations")
def compte_dotations(utilisateur, p):
    """Remplace le sac d'un compte, entièrement.

    Remplacer plutôt que modifier ligne à ligne : l'interface envoie le sac
    complet tel qu'elle l'affiche, et une quantité nulle y signifie « retirer ».
    Rapprocher les deux listes ici reviendrait à deviner ce que l'écran voulait
    dire.
    """
    identifiant = texte(p, "compte", maxi=150)
    compte = Compte.objects.filter(pk=identifiant).first()
    if compte is None:
        raise ErreurAction("Ce compte n'existe plus.")

    lignes = _lignes(p)

    compte.dotations.all().delete()
    Dotation.objects.bulk_create([
        Dotation(compte=compte, ordre=rang, material_id=l["material_id"],
                 quantite=l["quantite"], detail=l["detail"])
        for rang, l in enumerate(lignes, 1)
    ])
    ActiviteCompte.objects.create(
        acteur=utilisateur, action="sac modifié (%d ligne(s))" % len(lignes),
        nouveau_nom=identifiant)

    # Pas de cible : le sac voyage dans l'enveloppe de chaque réponse, pas dans
    # le différentiel. L'interface le reçoit donc immédiatement, et à chaque
    # interrogation suivante.
    return ("Sac de « %s » mis à jour." % identifiant, [])


def sacs(demandeur, administrateur):
    """Les sacs tels que l'interface les lit : { compte: [lignes] }.

    Un non-administrateur ne voit que le sien. Ce n'est pas seulement de la
    discrétion : la liste dirait sinon qui détient quoi dans toute l'équipe, ce
    qu'aucun écran ne propose par ailleurs.

    Le libellé, l'étiquette et le numéro de série sont résolus ici, à la
    lecture, et pas conservés dans la table : c'est l'identité **actuelle** de
    l'exemplaire qui doit s'afficher. `manquant` signale celui qui a été
    supprimé du catalogue — la ligne reste visible pour être corrigée, plutôt
    que de disparaître avec ce que la personne détient encore.
    """
    lignes = Dotation.objects.all()
    if not administrateur:
        lignes = lignes.filter(compte_id=demandeur)

    articles = {m.name: m for m in Material.objects.all()}
    resultat = {}
    for d in lignes:
        m = articles.get(d.material_id)
        resultat.setdefault(d.compte_id, []).append({
            "article": d.material_id,
            "libelle": (m.libelle or m.name) if m else d.material_id,
            "etiquette": m.etiquette if m else "",
            "numeroSerie": m.numero_serie if m else "",
            "cat": m.cat if m else "",
            "quantite": d.quantite,
            "detail": d.detail,
            "manquant": m is None,
        })
    return resultat
