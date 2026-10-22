# -*- coding: utf-8 -*-
"""Les actions sur les missions.

Une mission peut naître de deux façons, et la distinction compte :

- **réelle** (`is_meta`) : créée dans l'écran « Missions », elle s'affiche même
  sans matériel affecté, et peut porter une date prévue ;
- **implicite** : elle n'existe que parce qu'un emprunt la nomme. Changer son
  statut la matérialise, parce qu'un statut a besoin d'une ligne pour être
  rangé quelque part.
"""

from django.db.models import Max

from ..models import Equipe, MaterialReservation, Mission
from . import action, journaux
from .champs import ErreurAction, date_prevue, texte
from .droits import acteur, exiger_createur
from .gestion import exiger_gestion, poser_gestionnaires, valider_gestionnaires
from .statuts import ORDRE, changement_permis, peut_reculer, statut_de


def mission_existante(nom):
    m = Mission.objects.filter(pk=nom).first()
    if m is None or not m.is_meta:
        raise ErreurAction("La mission « %s » n'existe pas. "
                           "Créez-la d'abord dans « Missions en cours »." % nom)
    return m


@action("mission.creer")
def mission_creer(utilisateur, p):
    """Crée une mission, éventuellement servie par un template.

    Servir le template et créer la mission se font dans la même transaction :
    si une seule ligne ne peut pas être servie, la mission n'est pas créée du
    tout. Mieux vaut pas de mission qu'une mission incomplète qu'on croirait
    complète.
    """
    from .equipes import equipes_saisies
    from .templates import choix_exemplaires, servir_template

    exiger_createur(utilisateur, p)
    nom = texte(p, "nom", maxi=200)
    existante = Mission.objects.filter(pk=nom).first()
    if existante is not None and existante.is_meta:
        raise ErreurAction("La mission « %s » existe déjà." % nom)

    template_nom = texte(p, "template", obligatoire=False, maxi=200)
    prepare = (servir_template(template_nom, choix_exemplaires(p))
               if template_nom else [])

    # Qui gère la mission : celui qui la crée, par défaut, ou ceux qu'il désigne.
    # À la création il n'y a pas encore d'effectif, donc pas de conflit possible.
    gestionnaires = valider_gestionnaires(p.get("gestionnaires") or [utilisateur])

    # Les équipes sont vérifiées avant toute écriture, comme le reste.
    equipes = equipes_saisies(
        p.get("equipes"),
        deja=[e.nom for e in existante.equipes.all()] if existante is not None else ())

    quand = date_prevue(p)
    if existante is None:
        ordre = (Mission.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1
        Mission.objects.create(name=nom, ordre=ordre, is_meta=True,
                               owner=utilisateur, archived=False,
                               planned_date=quand)
    else:
        existante.is_meta = True
        existante.owner = existante.owner or utilisateur
        existante.planned_date = quand
        existante.save(update_fields=["is_meta", "owner", "planned_date"])
    mission = Mission.objects.get(pk=nom)
    poser_gestionnaires(mission, gestionnaires)

    depart = (mission.equipes.aggregate(m=Max("ordre"))["m"] or 0) + 1
    for rang, (nom_equipe, membres) in enumerate(equipes, depart):
        equipe = Equipe.objects.create(mission=mission, nom=nom_equipe, ordre=rang)
        equipe.membres.set(membres)

    from .materiel import creer_emprunt
    # Une mission créée avec un template n'a pas encore d'équipe : son matériel
    # arrive donc au niveau de la mission, et se répartit ensuite.
    cibles = [["mission", nom]]
    if equipes:
        cibles.append(["equipes", ""])
    for m, quantite in prepare:
        creer_emprunt(m, quantite, nom, utilisateur)
        journaux.materiel("SORTIE", m.nom_affiche, quantite, utilisateur, nom,
                          identite=m.identite)
        cibles.append(["materiel", m.name])

    resume = "Mission « %s » créée" % nom
    if template_nom:
        resume += " avec le template « %s »" % template_nom
    if equipes:
        resume += " et %d équipe%s" % (len(equipes), "s" if len(equipes) > 1 else "")
    return resume, cibles


@action("mission.date")
def mission_date(utilisateur, p):
    m = mission_existante(texte(p, "nom", maxi=200))
    exiger_gestion(m.name, utilisateur, p, "Changer la date")
    m.planned_date = date_prevue(p)
    m.save(update_fields=["planned_date"])
    return "Date de « %s » modifiée" % m.name, [["mission", m.name]]


@action("mission.statut")
def mission_statut(utilisateur, p):
    """Change le statut d'une mission, dans le respect de l'ordre.

    On avance librement (prévue → en cours → terminée) et on peut annuler ; on ne
    recule pas, sauf pour le gestionnaire de la mission et les administrateurs.
    Voir `services/statuts.py`.
    """
    nom = texte(p, "nom", maxi=200)
    statut = texte(p, "statut", maxi=40)
    if statut not in Mission.STATUTS:
        raise ErreurAction("Statut inconnu : %s." % statut)
    m = Mission.objects.filter(pk=nom).first()
    if m is None:
        # Une mission peut n'exister que dans les emprunts de matériel : il
        # faut une ligne pour ranger son statut.
        m = Mission.objects.create(name=nom, ordre=None, is_meta=False,
                                   owner="", archived=False)

    # Changer le statut, c'est la charge du gestionnaire de la mission : ni un
    # effectif ni un chef de groupe qui ne la gère pas n'y touchent.
    exiger_gestion(nom, utilisateur, p, "Changer le statut")

    actuel = statut_de(nom)
    permis, raison = changement_permis(
        actuel, statut, m,
        peut_reculer(m, acteur(p, utilisateur), p.get("_administrateur")))
    if not permis:
        raise ErreurAction(raison)

    m.status_override = statut
    # Un statut de l'échelle devient le nouveau plancher — y compris plus bas,
    # quand c'est le gestionnaire qui recule : sans cela le calcul remonterait
    # aussitôt la mission à son ancien niveau.
    if statut in ORDRE:
        m.status_max = statut
    m.save(update_fields=["status_override", "status_max"])
    return "« %s » : %s" % (nom, statut), [["mission", nom]]


@action("mission.archiver")
def mission_archiver(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    archive = bool(p.get("archive"))
    m = Mission.objects.filter(pk=nom).first()
    if m is None:
        raise ErreurAction("La mission « %s » n'existe plus." % nom)
    exiger_gestion(nom, utilisateur, p, "Archiver une mission")
    m.archived = archive
    m.save(update_fields=["archived"])
    return ("« %s » %s" % (nom, "archivée" if archive else "désarchivée"),
            [["mission", nom]])


@action("mission.supprimer")
def mission_supprimer(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    if not Mission.objects.filter(pk=nom).exists():
        raise ErreurAction("La mission « %s » n'existe plus." % nom)
    # Les emprunts rendus comptent aussi : ils portent l'histoire de la
    # mission, et la supprimer les laisserait orphelins.
    if MaterialReservation.objects.filter(mission=nom).exists():
        raise ErreurAction("« %s » a encore du matériel affecté. "
                           "Restituez-le d'abord." % nom)
    Mission.objects.filter(pk=nom).delete()
    return ("Mission « %s » supprimée" % nom,
            [["mission", nom], ["missionSupprimee", nom]])
