# -*- coding: utf-8 -*-
"""Les prêts à une personne sans compte : se déclarer, se rendre, se signaler.

Prêter du matériel à quelqu'un qui n'a pas de compte ne passe par aucune demande :
la personne n'est pas là pour répondre. Le prêteur le **déclare** — quoi, à qui, pour
quelle mission (ou aucune), avec un commentaire et une échéance. La déclaration ne
touche pas au stock ; elle garde la trace, et sert de rappel.

Passée l'échéance, tant que le matériel n'est pas rendu, le prêt est en retard et
l'interface le signale sur le profil du prêteur, de son chef de groupe, de son
adjoint et des administrateurs. Le retard est **calculé** à chaque lecture, jamais
stocké : rien à tenir à jour, et rendre le matériel éteint l'alerte aussitôt.
"""

from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from comptes.models import Compte, Groupe

from ..models import Material, Mission, PretExterne
from . import action
from .champs import ErreurAction, qte, texte
from .droits import acteur, dans_le_groupe, est_admin
from .materiel import mission_demandee

HISTORIQUE = timedelta(days=30)
SANS_MISSION = Mission.SANS_MISSION


def _echeance(p):
    brut = texte(p, "echeance", obligatoire=False, maxi=10)
    if not brut:
        return None
    try:
        jour = date.fromisoformat(brut)
    except ValueError:
        raise ErreurAction("L'échéance doit être une date (AAAA-MM-JJ).")
    if jour < timezone.localdate():
        raise ErreurAction("L'échéance ne peut pas être dans le passé.")
    return jour


@action("pret.externe.declarer")
def pret_externe_declarer(utilisateur, p):
    cle = texte(p, "article", maxi=200)
    materiel = Material.objects.filter(pk=cle).first()
    if materiel is None:
        raise ErreurAction("Cet article n'existe plus. Rechargez la page.")
    n = qte(p)
    emprunteur = texte(p, "emprunteur", maxi=120)
    if Compte.objects.filter(identifiant__iexact=emprunteur).exists():
        raise ErreurAction(
            "« %s » a un compte : passez par une demande de prêt, pas par une "
            "déclaration." % emprunteur)
    mission = mission_demandee(p)
    PretExterne.objects.create(
        preteur=utilisateur, emprunteur=emprunteur, material_id=materiel.pk,
        article=materiel.nom_affiche, quantite=n,
        mission=mission.name if mission else SANS_MISSION,
        commentaire=texte(p, "commentaire", obligatoire=False, maxi=300),
        echeance=_echeance(p))
    return ("Prêt déclaré à « %s » : %d × %s" % (emprunteur, n, materiel.nom_affiche), [])


def _pret(p):
    pret = PretExterne.objects.filter(pk=qte({"id": p.get("id")}, cle="id")).first()
    if pret is None:
        raise ErreurAction("Ce prêt n'existe plus.")
    return pret


def _peut_gerer(pret, utilisateur, p):
    """Son prêteur, son chef de groupe ou son adjoint, un administrateur."""
    qui = acteur(p, utilisateur)
    return est_admin(p) or qui == pret.preteur or dans_le_groupe(qui, pret.preteur)


@action("pret.externe.rendre")
def pret_externe_rendre(utilisateur, p):
    pret = _pret(p)
    if not _peut_gerer(pret, utilisateur, p):
        raise ErreurAction("Seuls son prêteur (%s), son chef de groupe ou un "
                           "administrateur enregistrent ce retour." % pret.preteur)
    if pret.rendu_le is not None:
        raise ErreurAction("Ce prêt est déjà rendu.")
    pret.rendu_le = timezone.now()
    pret.rendu_par = acteur(p, utilisateur)
    pret.save(update_fields=["rendu_le", "rendu_par"])
    return "Prêt rendu par « %s » : %d × %s" % (pret.emprunteur, pret.quantite, pret.article), []


@action("pret.externe.supprimer")
def pret_externe_supprimer(utilisateur, p):
    """Efface une déclaration faite par erreur : son prêteur, ou un administrateur."""
    pret = _pret(p)
    if not (est_admin(p) or acteur(p, utilisateur) == pret.preteur):
        raise ErreurAction("Seul le prêteur (%s) retire sa déclaration." % pret.preteur)
    pret.delete()
    return "Déclaration retirée", []


def _a_surveiller(compte):
    """Les comptes dont `compte` voit les prêts : les autres membres d'un groupe qu'il
    dirige, comme chef ou comme adjoint — chacun voit donc ceux de l'autre."""
    ids = set()
    for g in Groupe.objects.filter(Q(chef_id=compte) | Q(adjoint_id=compte)):
        ids |= set(Compte.objects.filter(membre_de=g).values_list("identifiant", flat=True))
    ids.discard(compte)
    return ids


def etat_externes(compte, administrateur):
    """Les prêts à des personnes sans compte que `compte` peut voir, tels que
    l'interface les lit : les siens, ceux de son groupe s'il le dirige, tous s'il est
    administrateur. Les prêts en cours d'abord, les plus pressés en tête ; les prêts
    rendus restent visibles trente jours."""
    if administrateur:
        qs = PretExterne.objects.all()
    else:
        qs = PretExterne.objects.filter(
            Q(preteur=compte) | Q(preteur__in=_a_surveiller(compte)))
    qs = qs.filter(Q(rendu_le__isnull=True) | Q(rendu_le__gte=timezone.now() - HISTORIQUE))
    aujourdhui = timezone.localdate()
    liste = [{
        "id": x.pk, "preteur": x.preteur, "emprunteur": x.emprunteur,
        "article": x.article, "quantite": x.quantite, "mission": x.mission,
        "commentaire": x.commentaire,
        "echeance": x.echeance.isoformat() if x.echeance else "",
        "iso": x.cree_le.isoformat(), "rendu": x.rendu_le is not None,
        "enRetard": x.rendu_le is None and x.echeance is not None and x.echeance < aujourdhui,
    } for x in qs]
    liste.sort(key=lambda x: (x["rendu"], x["echeance"] or "9999", x["id"]))
    return liste
