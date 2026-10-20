# -*- coding: utf-8 -*-
"""Les packs : une malette, prise d'un seul geste.

Ce qu'un pack n'est pas : un template de mission. Un template décrit ce qu'il
faut emporter et n'existe qu'au moment de partir ; un pack est un objet posé
sur une étagère, dont le contenu est connu. De là trois différences qui
commandent le reste :

- n'importe quel compte le crée et le modifie. Composer une malette est du
  travail d'atelier, pas de la configuration ;
- il s'emprunte directement, sans passer par une mission ;
- **il ne réserve rien.** Ranger un adaptateur dans une malette ne le retire
  pas du stock : la disponibilité se vérifie au départ, comme partout ailleurs.
  Un pack promet un contenu, pas une exclusivité dessus.

Il part entier par défaut — c'est le geste qu'on veut — mais reste sécable :
`lignes` permet de n'en sortir qu'une partie, et le retour se fait au choix
d'un geste (`pack.retour`) ou ligne à ligne, par le retour d'emprunt ordinaire.
"""

from django.db.models import Max
from django.utils import timezone

from ..models import Material, MaterialReservation, Pack, PackItem
from . import action, journaux
from .champs import ErreurAction, qte, texte
from .droits import exiger_rendre
from .materiel import article, creer_emprunt, mission_pour_emprunt


# --------------------------------------------------------------------------
# Lectures communes
# --------------------------------------------------------------------------

def pack_existant(nom):
    pack = Pack.objects.filter(pk=nom).first()
    if pack is None:
        raise ErreurAction("Le pack « %s » n'existe plus. Rechargez la page." % nom)
    return pack


def _homonyme(nom, sauf=None):
    return any(x.name.casefold() == nom.casefold() and x.name != sauf
               for x in Pack.objects.all())


def _lignes(p):
    """Valide le contenu envoyé par l'interface.

    Une ligne désigne toujours un exemplaire du catalogue, jamais un libellé :
    une malette contient des objets, et on doit pouvoir dire lesquels. C'est la
    différence avec un template, dont une ligne peut rester ouverte.
    """
    brutes = p.get("lignes")
    if not isinstance(brutes, list) or not brutes:
        raise ErreurAction("Un pack doit contenir au moins un article.")
    if len(brutes) > 200:
        raise ErreurAction("Trop d'articles dans un seul pack.")
    lignes, vues = [], set()
    for brute in brutes:
        if not isinstance(brute, dict):
            raise ErreurAction("Ligne de pack invalide.")
        m = article(texte(brute, "id", maxi=200))
        if m.name in vues:
            raise ErreurAction("« %s » figure deux fois dans le pack." % m.designation)
        vues.add(m.name)
        lignes.append({"material_id": m.name, "qty": qte(brute)})
    return lignes


def _ecrire_contenu(pack, lignes):
    """Remplace le contenu d'un pack, dans l'ordre reçu.

    Effacer puis réécrire plutôt que rapprocher ligne à ligne : le contenu
    d'une malette tient en quelques lignes, et leur ordre est celui dans lequel
    la personne l'a composée.
    """
    pack.items.all().delete()
    PackItem.objects.bulk_create([
        PackItem(pack=pack, ordre=rang, material_id=l["material_id"], qty=l["qty"])
        for rang, l in enumerate(lignes, 1)
    ])


def pack_deja_dehors(pack_nom):
    """Ce qui est sorti de la malette et pas encore rentré, par article.

    Une malette amputée n'est plus la malette : la reprendre entière
    promettrait un contenu qui n'y est pas.
    """
    deja = {}
    for r in MaterialReservation.objects.filter(pack=pack_nom,
                                                returned_by__isnull=True):
        deja[r.material_id] = deja.get(r.material_id, 0) + r.qty
    return deja


def contenu_servi(pack_nom, p):
    """Ce qui sort réellement de la malette : tout, ou la part demandée.

    Sans `lignes`, le pack part entier : c'est le geste normal, et il ne doit
    rien demander de plus qu'un clic. Avec `lignes`, on n'en sort qu'une
    partie — les quantités sont plafonnées par ce que le pack contient, pas par
    ce que l'appelant réclame.
    """
    contenu = list(PackItem.objects.filter(pack_id=pack_nom))
    if not contenu:
        raise ErreurAction("Le pack « %s » est vide." % pack_nom)

    voulues = p.get("lignes")
    if voulues is None:
        demande = {l.material_id: l.qty for l in contenu}
    else:
        if not isinstance(voulues, list) or not voulues:
            raise ErreurAction("Aucun article sélectionné dans le pack.")
        demande = {}
        for brute in voulues:
            if not isinstance(brute, dict):
                raise ErreurAction("Ligne de pack invalide.")
            nom = texte(brute, "nom", maxi=200)
            demande[nom] = demande.get(nom, 0) + qte(brute)

    prepare = []
    for l in contenu:
        voulu = demande.pop(l.material_id, 0)
        if not voulu:
            continue
        if voulu > l.qty:
            raise ErreurAction(
                "Le pack « %s » ne contient que %d × « %s », %d demandée(s)."
                % (pack_nom, l.qty, l.material_id, voulu))
        m = Material.objects.filter(pk=l.material_id).first()
        if m is None:
            raise ErreurAction(
                "L'article « %s » du pack « %s » n'existe plus. Corrigez le "
                "pack avant de l'employer." % (l.material_id, pack_nom))
        prepare.append((m, voulu))
    if demande:
        raise ErreurAction(
            "« %s » ne fait pas partie du pack « %s ». Rechargez la page."
            % (sorted(demande)[0], pack_nom))
    if not prepare:
        raise ErreurAction("Aucun article sélectionné dans le pack.")
    return prepare


def commentaire_de_pack(pack_nom, commentaire):
    """Le journal doit dire d'où l'article est sorti.

    La ligne de journal nomme l'article, pas la malette : lue seule, elle ne
    dirait pas pourquoi trois sorties sont parties ensemble. Le commentaire est
    le champ prévu pour ce genre de contexte, et il reste lisible quand la
    personne en a écrit un de son côté.
    """
    mention = "Pack « %s »" % pack_nom
    return "%s · %s" % (mention, commentaire) if commentaire else mention


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------

@action("pack.creer")
def pack_creer(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    if _homonyme(nom):
        raise ErreurAction("Le pack « %s » existe déjà." % nom)
    lignes = _lignes(p)
    ordre = (Pack.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1
    pack = Pack.objects.create(
        name=nom, ordre=ordre, owner=utilisateur,
        etiquette=texte(p, "etiquette", obligatoire=False, maxi=200),
        created_at=timezone.now())
    _ecrire_contenu(pack, lignes)
    return "Pack « %s » créé" % nom, [["packs", ""]]


@action("pack.modifier")
def pack_modifier(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    pack = pack_existant(nom)
    nouveau = texte(p, "nouveauNom", obligatoire=False, defaut=nom, maxi=200)
    if _homonyme(nouveau, sauf=nom):
        raise ErreurAction("Le pack « %s » existe déjà." % nouveau)
    etiquette = texte(p, "etiquette", obligatoire=False, maxi=200)
    lignes = _lignes(p)

    if nouveau != nom:
        # Le renommage suit les emprunts en cours, sans quoi la malette
        # renommée ne se rendrait plus d'un geste. Ailleurs on garde la trace
        # d'origine — le journal doit dire ce qui est réellement sorti — mais
        # ici l'emprunt doit suivre.
        ancien = Pack.objects.create(name=nouveau, ordre=pack.ordre,
                                     owner=pack.owner, etiquette=etiquette,
                                     created_at=pack.created_at)
        pack.items.all().update(pack=ancien)
        MaterialReservation.objects.filter(pack=nom).update(pack=nouveau)
        pack.delete()
        pack = ancien
    else:
        pack.etiquette = etiquette
        pack.save(update_fields=["etiquette"])
    _ecrire_contenu(pack, lignes)

    if nouveau != nom:
        return ("Pack « %s » renommé en « %s »" % (nom, nouveau), [["packs", ""]])
    return "Pack « %s » modifié" % nom, [["packs", ""]]


@action("pack.supprimer")
def pack_supprimer(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    pack_existant(nom)
    if MaterialReservation.objects.filter(pack=nom, returned_by__isnull=True).exists():
        raise ErreurAction("« %s » est encore dehors. Restituez-le d'abord." % nom)
    Pack.objects.filter(pk=nom).delete()
    return "Pack « %s » supprimé" % nom, [["packs", ""]]


# --------------------------------------------------------------------------
# Emprunt et retour
# --------------------------------------------------------------------------

@action("pack.emprunt")
def pack_emprunt(utilisateur, p):
    """Sort une malette, entière ou en partie.

    Tout est vérifié avant d'écrire : une malette à moitié sortie parce que la
    troisième ligne manquait serait pire qu'un refus — on la croirait complète
    en la chargeant dans le camion.
    """
    pack = pack_existant(texte(p, "pack", maxi=200))
    mission = mission_pour_emprunt(p, utilisateur)
    commentaire = texte(p, "commentaire", obligatoire=False, maxi=500)

    deja = pack_deja_dehors(pack.name)
    prepare = contenu_servi(pack.name, p)
    for m, n in prepare:
        sorti = deja.get(m.name, 0)
        if sorti:
            raise ErreurAction(
                "« %s » est déjà sorti du pack « %s » (%d unité(s)). Rendez-le "
                "avant de reprendre la malette, ou sortez les autres articles "
                "un par un." % (m.designation, pack.name, sorti))
        libre = m.disponible()
        if n > libre:
            raise ErreurAction(
                "Stock insuffisant pour « %s » : %d disponible(s), %d "
                "demandée(s). Le pack « %s » n'est pas sorti."
                % (m.designation, libre, n, pack.name))

    from .equipes import equipe_demandee
    from .materiel import SANS_MISSION
    nom_mission = mission.name if mission else SANS_MISSION
    equipe = equipe_demandee(p, nom_mission)
    note = commentaire_de_pack(pack.name, commentaire)
    cibles = [["matLog", ""], ["packs", ""]]
    for m, n in prepare:
        creer_emprunt(m, n, nom_mission, utilisateur, pack=pack.name,
                      equipe=equipe)
        journaux.materiel("SORTIE", m.nom_affiche, n, utilisateur, nom_mission,
                          note, m.identite)
        cibles.append(["materiel", m.name])
    resume = "Pack « %s » emprunté (%d article(s))" % (pack.name, len(prepare))
    if mission:
        resume += " pour « %s »" % mission.name
        if equipe:
            resume += " (%s)" % equipe
    return resume, cibles


@action("pack.retour")
def pack_retour(utilisateur, p):
    """Rend d'un geste tout ce qui est encore dehors sous ce pack.

    Le pack peut avoir disparu entre-temps — ce que `pack.supprimer` refuse,
    mais qu'une base corrigée à la main peut produire. On rend quand même : du
    matériel dehors qu'on ne pourrait plus rentrer serait pire.
    """
    nom = texte(p, "pack", maxi=200)
    en_cours = list(MaterialReservation.objects
                    .filter(pack=nom, returned_by__isnull=True)
                    .order_by("material_id", "seq"))
    if not en_cours:
        raise ErreurAction("Aucun article à rendre pour le pack « %s »." % nom)
    for r in en_cours:                 # tout rendre, ou rien : on vérifie avant d'écrire
        exiger_rendre(r, utilisateur, p)

    quand = timezone.now()
    note = commentaire_de_pack(nom, "")
    cibles = [["matLog", ""], ["packs", ""]]
    for r in en_cours:
        r.returned_by, r.returned_at = utilisateur, quand
        r.save(update_fields=["returned_by", "returned_at"])
        m = Material.objects.filter(pk=r.material_id).first()
        libelle = m.nom_affiche if m else r.material_id
        journaux.materiel("RETOUR", libelle, r.qty, utilisateur, r.mission,
                          note, m.identite if m else "")
        cibles.append(["materiel", r.material_id])
    return ("Pack « %s » rendu (%d ligne(s))" % (nom, len(en_cours)), cibles)
