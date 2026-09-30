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

from ..models import MaterialReservation, Mission
from . import action, journaux
from .champs import ErreurAction, date_prevue, texte


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
    from .templates import choix_exemplaires, servir_template

    nom = texte(p, "nom", maxi=200)
    existante = Mission.objects.filter(pk=nom).first()
    if existante is not None and existante.is_meta:
        raise ErreurAction("La mission « %s » existe déjà." % nom)

    template_nom = texte(p, "template", obligatoire=False, maxi=200)
    prepare = (servir_template(template_nom, choix_exemplaires(p))
               if template_nom else [])

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

    from .materiel import creer_emprunt
    cibles = [["mission", nom]]
    for m, quantite in prepare:
        creer_emprunt(m, quantite, nom, utilisateur)
        journaux.materiel("SORTIE", m.nom_affiche, quantite, utilisateur, nom,
                          identite=m.identite)
        cibles.append(["materiel", m.name])

    resume = "Mission « %s » créée" % nom
    if template_nom:
        resume += " avec le template « %s »" % template_nom
    return resume, cibles


@action("mission.date")
def mission_date(utilisateur, p):
    m = mission_existante(texte(p, "nom", maxi=200))
    m.planned_date = date_prevue(p)
    m.save(update_fields=["planned_date"])
    return "Date de « %s » modifiée" % m.name, [["mission", m.name]]


@action("mission.statut")
def mission_statut(utilisateur, p):
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
    m.status_override = statut
    m.save(update_fields=["status_override"])
    return "« %s » : %s" % (nom, statut), [["mission", nom]]


@action("mission.archiver")
def mission_archiver(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    archive = bool(p.get("archive"))
    m = Mission.objects.filter(pk=nom).first()
    if m is None:
        raise ErreurAction("La mission « %s » n'existe plus." % nom)
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
