# -*- coding: utf-8 -*-
"""Les actions sur le matériel : catalogue, emprunts, consommables, séries.

Trois notions qu'il faut tenir séparées :

- **la quantité** ne bouge qu'à la réception, à la suppression, et à la
  consommation d'un consommable. Emprunter ne la change pas ;
- **la disponibilité** est la quantité moins ce qui est dehors. C'est elle
  qu'on vérifie avant de sortir quoi que ce soit ;
- **la consommation** est le seul cas où du matériel sorti ne revient pas. Elle
  est réservée aux articles de catégorie « Consommable » : un outil cassé
  relève d'une correction d'inventaire, et mélanger les deux rendrait le suivi
  des consommables illisible.
"""

from datetime import date

from django.db.models import Max
from django.utils import timezone

from ..models import Material, MaterialLog, MaterialReservation, Mission
from . import action, journaux
from .droits import exiger_emprunt_pour, exiger_rendre
from .gestion import exiger_gestion
from .champs import (AFFECTATIONS, ErreurAction, affectation, ligne, qte,
                     texte)

SANS_MISSION = Mission.SANS_MISSION
CATEGORIE_CONSOMMABLE = Material.CATEGORIE_CONSOMMABLE


# --------------------------------------------------------------------------
# Lectures communes
# --------------------------------------------------------------------------

def article(nom):
    m = Material.objects.filter(pk=nom).first()
    if m is None:
        raise ErreurAction("L'article « %s » n'existe plus. Rechargez la page." % nom)
    return m


def par_libelle(libelle):
    """Tous les exemplaires portant ce nom visible, dans l'ordre du catalogue."""
    return list(Material.objects.filter(libelle__iexact=libelle)
                | Material.objects.filter(libelle="", name__iexact=libelle))


def identifie(nom, etiquette, numero_serie):
    """L'exemplaire exactement décrit par ce triplet, ou rien.

    C'est ce qui permet à une réception de retomber sur la bonne ligne : deux
    perceuses de même nom mais d'étiquettes différentes sont deux articles.
    """
    for m in Material.objects.all():
        if ((m.libelle or m.name).casefold() == nom.casefold()
                and m.etiquette == (etiquette or "")
                and m.numero_serie == (numero_serie or "")):
            return m
    return None


def par_serie(libelle, numero_serie):
    for m in Material.objects.filter(numero_serie=numero_serie):
        if (m.libelle or m.name).casefold() == libelle.casefold():
            return m
    return None


def licence_saisie(p):
    """La date de fin de licence saisie à l'entrée d'un dongle, ou None.

    Facultative, et au format AAAA-MM-JJ. Une date passée est acceptée : on peut
    recevoir un dongle dont la licence est déjà échue, et il faut pouvoir le dire.
    """
    brut = texte(p, "licence", obligatoire=False, maxi=10)
    if not brut:
        return None
    try:
        return date.fromisoformat(brut)
    except ValueError:
        raise ErreurAction("La fin de licence doit être une date (AAAA-MM-JJ).")


def creer_article(nom, cat, affect, quantite, etiquette="", numero_serie="",
                  licence_fin=None):
    """Crée un exemplaire, en suffixant la clé si le nom est déjà pris.

    `name` est la clé, `libelle` le nom affiché : deux exemplaires du même
    article portent le même libellé et des clés distinctes.
    """
    cle = nom
    suffixe = 2
    while Material.objects.filter(pk=cle).exists():
        cle = "%s #%d" % (nom, suffixe)
        suffixe += 1
    ordre = (Material.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1
    return Material.objects.create(
        name=cle, ordre=ordre, cat=cat, qty=quantite, seuil=0,
        affectation=affect or "Commun", libelle=nom,
        etiquette=etiquette or "", numero_serie=numero_serie or "",
        # Seul un dongle porte une licence : la date n'a pas de sens ailleurs.
        licence_fin=licence_fin if cat == Material.CATEGORIE_DONGLE else None)


def creer_emprunt(m, quantite, mission, par_qui, pack="", equipe="", sac_de="",
                  force_par=""):
    """`pack` retient la malette d'où l'article est sorti, ou reste vide.

    `equipe` retient l'équipe de la mission à qui la ligne est attribuée. Vide
    signifie « rattaché à la mission sans plus de précision » — le cas des
    missions sans équipes, et de tout ce qui existait avant elles.

    `sac_de` désigne le compte dont le sac a prêté l'article (voir
    `services/prets.py`) ; vide pour un emprunt au stock commun.
    """
    seq = MaterialReservation.objects.filter(material=m).aggregate(m=Max("seq"))["m"]
    seq = -1 if seq is None else seq
    return MaterialReservation.objects.create(
        material=m, seq=seq + 1, qty=quantite, mission=mission,
        taken_by=par_qui, returned_by=None, taken_at=timezone.now(),
        returned_at=None, pack=pack or "", equipe=equipe or "",
        sac_de=sac_de or "", force_par=force_par or "")


def emprunts_ouverts_de_mission(nom, equipe=None):
    """Ce qu'une mission détient encore, éventuellement d'une seule équipe.

    `equipe=None` prend toute la mission ; une chaîne vide prend ce qui n'est
    attribué à aucune équipe. Les deux sont des demandes légitimes et
    différentes, d'où le `None` plutôt qu'un défaut à chaîne vide.
    """
    lignes = MaterialReservation.objects.filter(mission=nom,
                                                returned_by__isnull=True)
    if equipe is not None:
        lignes = lignes.filter(equipe=equipe)
    return list(lignes.order_by("material_id", "seq"))


def mission_existante(nom):
    m = Mission.objects.filter(pk=nom).first()
    if m is None or not m.is_meta:
        raise ErreurAction("La mission « %s » n'existe pas. "
                           "Créez-la d'abord dans « Missions en cours »." % nom)
    return m


def mission_demandee(p):
    nom = texte(p, "mission", obligatoire=False, defaut=SANS_MISSION)
    return None if nom == SANS_MISSION else mission_existante(nom)


def mission_pour_emprunt(p, utilisateur):
    """La mission pour laquelle on emprunte — que l'on a le droit de servir.

    Sans mission, l'emprunt est libre. Pour une mission, il faut en faire partie
    (équipier), la gérer, ou être administrateur : voir `droits.exiger_emprunt_pour`.
    """
    mission = mission_demandee(p)
    if mission is not None:
        exiger_emprunt_pour(mission.name, utilisateur, utilisateur, p)
    return mission


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

@action("materiel.creer")
def materiel_creer(utilisateur, p):
    nom = texte(p, "nom", maxi=200)
    n = qte(p)
    etiquette = texte(p, "etiquette", obligatoire=False, maxi=200)
    numero_serie = texte(p, "numeroSerie", obligatoire=False, maxi=200)
    licence = licence_saisie(p)

    # Un article exactement identique — même nom, même étiquette, même série —
    # est un réapprovisionnement, pas un nouvel article.
    existant = identifie(nom, etiquette, numero_serie)
    if existant:
        existant.qty += n
        champs = ["qty"]
        if licence and existant.cat == Material.CATEGORIE_DONGLE:
            existant.licence_fin = licence
            champs.append("licence_fin")
        existant.save(update_fields=champs)
        journaux.materiel("ENTRÉE", existant.nom_affiche, n, utilisateur,
                          identite=existant.identite)
        return ("Entrée de %d × %s" % (n, existant.nom_affiche),
                [["materiel", existant.name], ["matLog", ""]])

    m = creer_article(nom, texte(p, "cat", obligatoire=False,
                                 defaut="Accessoire", maxi=80),
                      affectation(p), n, etiquette, numero_serie, licence)
    journaux.materiel("CRÉATION", m.nom_affiche, n, utilisateur,
                      identite=m.identite)
    return "Article « %s » créé" % m.nom_affiche, [["materiel", m.name], ["matLog", ""]]


@action("materiel.reception")
def materiel_reception(utilisateur, p):
    m = article(texte(p, "nom", maxi=200))
    n = qte(p)
    licence = licence_saisie(p)
    m.qty += n
    champs = ["qty"]
    # Recevoir un dongle renouvelé met sa licence à jour.
    if licence and m.cat == Material.CATEGORIE_DONGLE:
        m.licence_fin = licence
        champs.append("licence_fin")
    m.save(update_fields=champs)
    journaux.materiel("ENTRÉE", m.nom_affiche, n, utilisateur,
                      identite=m.identite)
    return ("Entrée de %d × %s" % (n, m.nom_affiche),
            [["materiel", m.name], ["matLog", ""]])


@action("materiel.ajuster")
def materiel_ajuster(utilisateur, p):
    """Fixe le stock d'un article à une valeur, pour corriger un écart.

    À la différence d'une réception, qui ajoute, on dit ici combien il y en a
    réellement : un inventaire, une erreur de saisie. L'écart est inscrit au
    journal avec l'ancienne et la nouvelle valeur, pour qu'une correction ne
    passe jamais inaperçue.

    Le stock ne peut pas descendre sous ce qui est actuellement sorti : ces
    unités existent, elles sont chez quelqu'un.
    """
    m = article(texte(p, "nom", maxi=200))
    nouveau = qte(p, "qty", mini=0)
    dehors = sum(r.qty for r in m.emprunts.all() if r.ouvert)
    if nouveau < dehors:
        raise ErreurAction("« %s » : %d unité(s) sont sorties, le stock ne peut "
                           "pas descendre sous ce nombre." % (m.designation, dehors))
    ancien = m.qty
    if nouveau == ancien:
        return "« %s » : stock inchangé" % m.nom_affiche, [["materiel", m.name]]
    m.qty = nouveau
    m.save(update_fields=["qty"])
    journaux.materiel("AJUST.", m.nom_affiche, abs(nouveau - ancien), utilisateur,
                      commentaire="Stock corrigé de %d à %d" % (ancien, nouveau),
                      identite=m.identite)
    return ("« %s » : stock %d → %d" % (m.nom_affiche, ancien, nouveau),
            [["materiel", m.name], ["matLog", ""]])


@action("materiel.affectation")
def materiel_affectation(utilisateur, p):
    m = article(texte(p, "nom", maxi=200))
    nouvelle = affectation(p, obligatoire=True)
    if nouvelle == m.affectation:
        return "%s : affectation inchangée" % m.nom_affiche, [["materiel", m.name]]
    m.affectation = nouvelle
    m.save(update_fields=["affectation"])
    return ("%s affecté à « %s »" % (m.nom_affiche, nouvelle),
            [["materiel", m.name]])


@action("materiel.supprimer")
def materiel_supprimer(utilisateur, p):
    m = article(texte(p, "nom", maxi=200))
    if any(r.ouvert for r in m.emprunts.all()):
        raise ErreurAction("« %s » est encore emprunté. Attendez son retour."
                           % m.designation)
    nom, affiche = m.name, m.nom_affiche
    m.delete()
    return ("Article « %s » supprimé" % affiche, [["materiel", nom]])


# --------------------------------------------------------------------------
# Exemplaires identifiés
#
# Un consommable dont on veut savoir lequel a servi est enregistré exemplaire
# par exemplaire : une ligne, une quantité de 1, son numéro de série. C'est le
# modèle déjà employé pour les portables et les SSD, et il n'en faut pas un
# second — la traçabilité vient alors d'elle-même, puisque le journal recopie
# `identite` à chaque mouvement.
# --------------------------------------------------------------------------

def _serie_libre(libelle, serie, sauf):
    """Un numéro de série ne peut désigner qu'un exemplaire.

    Le contrôle porte sur le libellé, pas sur tout le stock : deux familles
    d'articles peuvent numéroter les leurs à partir de 1 sans se gêner, et
    refuser « 0001 » parce qu'un autre produit le porte déjà serait absurde.
    """
    if not serie:
        return
    autre = par_serie(libelle, serie)
    if autre is not None and autre.name != sauf:
        raise ErreurAction(
            "Le numéro de série « %s » est déjà porté par un exemplaire de "
            "« %s »." % (serie, libelle))


@action("materiel.identifiants")
def materiel_identifiants(utilisateur, p):
    """Pose ou corrige l'étiquette et le numéro de série d'un exemplaire.

    Ni la clé ni le libellé ne bougent : les emprunts, les lignes de pack et
    les templates citent la clé, et la réécrire les ferait pointer dans le vide.
    """
    m = article(texte(p, "nom", maxi=200))
    etiquette = texte(p, "etiquette", obligatoire=False, maxi=200)
    serie = texte(p, "numeroSerie", obligatoire=False, maxi=200)
    libelle = m.nom_affiche
    _serie_libre(libelle, serie, sauf=m.name)
    if (m.etiquette, m.numero_serie) == (etiquette, serie):
        return "%s : identifiants inchangés" % m.designation, [["materiel", m.name]]
    m.etiquette, m.numero_serie = etiquette, serie
    m.save(update_fields=["etiquette", "numero_serie"])
    return ("%s : %s" % (libelle, m.identite or "plus d'identifiant"),
            [["materiel", m.name]])


@action("materiel.modifier")
def materiel_modifier(utilisateur, p):
    """Corrige les caractéristiques d'un article : nom, catégorie, étiquette, numéro de
    série, affectation, fin de licence d'un dongle.

    Deux niveaux, comme à l'écran. Le **nom** et la **catégorie** sont ceux de la famille :
    tous les exemplaires qui portent le même nom les prennent ensemble, pour qu'ils restent
    regroupés. L'**étiquette**, le **numéro de série**, l'**affectation** et la **licence**
    sont propres à l'exemplaire désigné.

    La clé ne bouge jamais : les emprunts, les malettes et les sacs la citent. Les lignes de
    modèle de mission qui désignent un *type* d'article par son nom suivent le renommage ; le
    journal garde, lui, le nom qu'avait l'article le jour du mouvement.
    """
    from ..models import MissionTemplateItem

    m = article(texte(p, "nom", maxi=200))
    ancien = m.nom_affiche
    nouveau = texte(p, "libelle", maxi=200) if p.get("libelle") not in (None, "") else ancien
    cat = texte(p, "cat", obligatoire=False, defaut=m.cat, maxi=80)
    etiquette = texte(p, "etiquette", obligatoire=False, maxi=200)
    serie = texte(p, "numeroSerie", obligatoire=False, maxi=200)
    affect = affectation(p, obligatoire=True) if p.get("affectation") else m.affectation
    licence = licence_saisie(p)

    famille = par_libelle(ancien)
    # Aucun numéro de série ne doit se retrouver en double sous le nouveau nom, et aucun
    # exemplaire ne doit devenir le sosie exact d'un autre.
    for f in famille:
        f_serie = serie if f.name == m.name else f.numero_serie
        f_etiq = etiquette if f.name == m.name else f.etiquette
        _serie_libre(nouveau, f_serie, sauf=f.name)
        sosie = identifie(nouveau, f_etiq, f_serie)
        if sosie is not None and sosie.name != f.name:
            raise ErreurAction(
                "Un exemplaire identique existe déjà sous le nom « %s » (même étiquette, "
                "même numéro de série)." % nouveau)

    for f in famille:
        f.libelle = nouveau
        f.cat = cat
        champs = ["libelle", "cat"]
        if f.name == m.name:
            f.etiquette, f.numero_serie, f.affectation = etiquette, serie, affect
            champs += ["etiquette", "numero_serie", "affectation"]
            # Seul un dongle porte une licence ; une nouvelle date remplace l'ancienne,
            # et changer de catégorie l'efface.
            if cat != Material.CATEGORIE_DONGLE:
                f.licence_fin = None
            elif "licence" in p:
                f.licence_fin = licence
            champs.append("licence_fin")
        elif cat != Material.CATEGORIE_DONGLE and f.licence_fin is not None:
            f.licence_fin = None
            champs.append("licence_fin")
        f.save(update_fields=champs)

    if nouveau != ancien:
        MissionTemplateItem.objects.filter(kind="type", libelle__iexact=ancien).update(
            libelle=nouveau)

    cibles = [["materiel", f.name] for f in famille] + [["templates", ""], ["packs", ""]]
    return "« %s » modifié" % nouveau, cibles


@action("materiel.creer.lot")
def materiel_creer_lot(utilisateur, p):
    """Enregistre plusieurs exemplaires d'un même article, un par série.

    Chaque série donne une ligne de quantité 1 : c'est ce qui permettra de dire
    lequel a été consommé. Tout est vérifié avant la première écriture — un lot
    de cinquante à moitié enregistré laisserait l'inventaire dans un état que
    personne ne saurait rattraper.
    """
    nom = texte(p, "nom", maxi=200)
    cat = texte(p, "cat", obligatoire=False, defaut="Accessoire", maxi=80)
    affect = affectation(p)
    licence = licence_saisie(p)
    brutes = p.get("series")
    if not isinstance(brutes, list) or not brutes:
        raise ErreurAction("Aucun numéro de série fourni.")
    if len(brutes) > 500:
        raise ErreurAction("Trop d'exemplaires en une seule fois (maximum 500).")

    series, vues = [], set()
    for brute in brutes:
        serie = texte({"s": brute}, "s", maxi=200)
        cle = serie.casefold()
        if cle in vues:
            raise ErreurAction(
                "Le numéro de série « %s » figure deux fois dans la liste." % serie)
        vues.add(cle)
        _serie_libre(nom, serie, sauf=None)
        series.append(serie)

    etiquettes = p.get("etiquettes") or {}
    if not isinstance(etiquettes, dict):
        raise ErreurAction("Étiquettes invalides.")

    cibles = [["matLog", ""]]
    for serie in series:
        m = creer_article(nom, cat, affect, 1,
                          texte(etiquettes, serie, obligatoire=False, maxi=200),
                          serie, licence)
        journaux.materiel("CRÉATION", m.nom_affiche, 1, utilisateur,
                          identite=m.identite)
        cibles.append(["materiel", m.name])
    return ("%d exemplaire(s) de « %s » enregistrés" % (len(series), nom), cibles)


@action("materiel.seuil")
def materiel_seuil(utilisateur, p):
    """Le stock en dessous duquel l'article est signalé à recommander.

    Zéro vaut « pas de seuil » : c'est la valeur de départ de tous les
    articles, et elle ne doit rien déclencher.

    Le seuil se règle par `libelle` : il vaut pour tout ce qui porte ce nom, et
    est posé sur chacun de ses exemplaires, qui restent ainsi d'accord. L'alerte
    se compare au stock cumulé du groupe. `nom` désigne un seul article.
    """
    seuil = qte(p, "seuil", mini=0)
    libelle = texte(p, "libelle", obligatoire=False, maxi=200)
    if libelle:
        membres = par_libelle(libelle)
        if not membres:
            raise ErreurAction("L'article « %s » n'existe plus. Rechargez la page."
                               % libelle)
    else:
        membres = [article(texte(p, "nom", maxi=200))]
    for m in membres:
        m.seuil = seuil
        m.save(update_fields=["seuil"])
    nom = membres[0].nom_affiche
    cibles = [["materiel", m.name] for m in membres]
    if not seuil:
        return "%s : plus de seuil d'alerte" % nom, cibles
    return "%s : alerte sous %d unité(s)" % (nom, seuil), cibles


# --------------------------------------------------------------------------
# Emprunts
# --------------------------------------------------------------------------

@action("materiel.emprunt")
def materiel_emprunt(utilisateur, p):
    m = article(texte(p, "nom", maxi=200))
    n = qte(p)
    mission = mission_pour_emprunt(p, utilisateur)
    commentaire = texte(p, "commentaire", obligatoire=False, maxi=500)

    libre = m.disponible()
    if n > libre:
        raise ErreurAction(
            "Stock insuffisant : %d unité(s) disponible(s) de « %s » hors "
            "emprunts en cours, %d demandée(s)." % (libre, m.nom_affiche, n))

    from .equipes import equipe_demandee
    nom_mission = mission.name if mission else SANS_MISSION
    equipe = equipe_demandee(p, nom_mission)
    creer_emprunt(m, n, nom_mission, utilisateur, equipe=equipe)
    journaux.materiel("SORTIE", m.nom_affiche, n, utilisateur, nom_mission,
                      commentaire, m.identite)
    resume = ("Emprunt de %d × %s" % (n, m.nom_affiche) if mission is None else
              "Emprunt de %d × %s pour « %s »" % (n, m.nom_affiche, mission.name))
    if equipe:
        resume += " (%s)" % equipe
    return resume, [["materiel", m.name], ["matLog", ""]]


@action("materiel.emprunt.groupe")
def materiel_emprunt_groupe(utilisateur, p):
    """Un panier : des articles à l'unité, des malettes entières, ou les deux.

    Tout part ensemble ou rien ne part. Mêler des malettes rend la règle plus
    nécessaire encore — sortir la malette puis buter sur un câble laisserait la
    moitié du chargement dehors, et personne ne saurait laquelle.

    La demande est **cumulée** avant d'être confrontée au stock. Un adaptateur
    peut être réclamé deux fois — une fois dans une malette, une fois à
    l'unité — et chaque ligne prise isolément passerait alors qu'ensemble elles
    ne passent pas. C'est `pris` qui l'empêche.
    """
    from .packs import contenu_servi, pack_deja_dehors, pack_existant
    from .packs import commentaire_de_pack

    mission = mission_pour_emprunt(p, utilisateur)
    commentaire = texte(p, "commentaire", obligatoire=False, maxi=500)

    lignes = p.get("lignes") or []
    noms_packs = p.get("packs") or []
    if not isinstance(lignes, list) or not isinstance(noms_packs, list):
        raise ErreurAction("Sélection invalide.")
    if not lignes and not noms_packs:
        raise ErreurAction("Aucun article sélectionné.")
    if len(lignes) > 200:
        raise ErreurAction("Trop d'articles en une seule fois.")
    if len(noms_packs) > 50:
        raise ErreurAction("Trop de malettes en une seule fois.")

    prepare, pris, vus = [], {}, set()

    def engager(m, n, pack_nom, equipe_voulue=None):
        restant = m.disponible() - pris.get(m.name, 0)
        if n > restant:
            origine = (" Le pack « %s » n'est pas sorti." % pack_nom if pack_nom
                       else "")
            raise ErreurAction(
                "Stock insuffisant pour « %s » : %d disponible(s), %d "
                "demandée(s). Aucun emprunt n'a été enregistré.%s"
                % (m.designation, max(0, restant), n, origine))
        pris[m.name] = pris.get(m.name, 0) + n
        prepare.append((m, n, pack_nom, equipe_voulue))

    for brut in noms_packs:
        # Une malette est un nom, ou {"nom", "equipe"} pour la ranger dans une équipe.
        equipe_pack = brut.get("equipe") if isinstance(brut, dict) else None
        nom = texte({"nom": brut.get("nom") if isinstance(brut, dict) else brut},
                    "nom", maxi=200)
        if nom in vus:
            raise ErreurAction("Le pack « %s » est sélectionné deux fois." % nom)
        vus.add(nom)
        pack = pack_existant(nom)
        deja = pack_deja_dehors(pack.name)
        for m, n in contenu_servi(pack.name, {}):
            if deja.get(m.name):
                raise ErreurAction(
                    "« %s » est déjà sorti du pack « %s » (%d unité(s)). "
                    "Rendez-le avant de reprendre la malette."
                    % (m.designation, pack.name, deja[m.name]))
            engager(m, n, pack.name, equipe_pack)

    for l in lignes:
        if not isinstance(l, dict):
            raise ErreurAction("Ligne d'emprunt invalide.")
        engager(article(texte(l, "nom", maxi=200)), qte(l), "", l.get("equipe"))

    from .equipes import equipe_demandee
    nom_mission = mission.name if mission else SANS_MISSION
    # L'équipe du panier tout entier (`equipe`), que chaque ligne ou malette peut
    # remplacer par la sienne : c'est ce qui permet de répartir au moment de partir.
    equipe = equipe_demandee(p, nom_mission)
    equipes_vues = {}

    def equipe_de(voulue):
        if voulue is None:
            return equipe
        if voulue not in equipes_vues:
            equipes_vues[voulue] = equipe_demandee({"equipe": voulue}, nom_mission)
        return equipes_vues[voulue]

    cibles = [["matLog", ""]]
    if noms_packs:
        cibles.append(["packs", ""])
    for m, n, pack_nom, voulue in prepare:
        creer_emprunt(m, n, nom_mission, utilisateur, pack=pack_nom,
                      equipe=equipe_de(voulue))
        note = (commentaire_de_pack(pack_nom, commentaire) if pack_nom
                else commentaire)
        journaux.materiel("SORTIE", m.nom_affiche, n, utilisateur, nom_mission,
                          note, m.identite)
        cibles.append(["materiel", m.name])

    morceaux = []
    if lignes:
        morceaux.append("%d article(s)" % len(lignes))
    if noms_packs:
        morceaux.append("%d malette(s)" % len(noms_packs))
    resume = " et ".join(morceaux) + " empruntés"
    if mission:
        resume += " pour « %s »" % mission.name
        if equipe:
            resume += " (%s)" % equipe
    return resume, cibles


@action("materiel.emprunt.retour")
def materiel_emprunt_retour(utilisateur, p):
    m = article(texte(p, "nom", maxi=200))
    r = ligne(list(m.emprunts.all()), p, "ligne d'emprunt")
    exiger_rendre(r, utilisateur, p)
    quantite, mission = r.qty, r.mission
    r.delete()
    journaux.materiel("RETOUR", m.nom_affiche, quantite, utilisateur, mission,
                      identite=m.identite)
    return ("Retour de %d × %s" % (quantite, m.nom_affiche),
            [["materiel", m.name], ["matLog", ""]])


# --------------------------------------------------------------------------
# Restitution de mission, et consommation
# --------------------------------------------------------------------------

@action("materiel.mission.restituer_ligne")
def materiel_mission_restituer_ligne(utilisateur, p):
    """Rend **une** ligne d'une mission, sans toucher aux autres.

    C'est le geste de la fiche de mission une fois celle-ci en cours : le matériel
    ne se « désassigne » plus (voir `materiel.mission.desassigner`, réservé aux
    missions prévues), il se rend. La ligne se ferme — elle reste dans l'historique
    de la mission, contrairement à un retour par suppression — et le matériel
    regagne le stock, ou le sac qui l'avait prêté.

    La ligne est rendue **entière** : pour déclarer des consommables utilisés, la
    restitution de toute la mission (`materiel.mission.restituer`) est le bon geste.
    """
    m = article(texte(p, "nom", maxi=200))
    r = ligne(list(m.emprunts.all()), p, "ligne d'emprunt")
    if not r.ouvert:
        raise ErreurAction("Cette ligne est déjà rendue.")
    if r.mission == SANS_MISSION or not r.mission:
        raise ErreurAction("Cette ligne n'est affectée à aucune mission : rendez-la "
                           "par le retour habituel.")
    exiger_rendre(r, utilisateur, p)

    mission = r.mission
    r.returned_by, r.returned_at = utilisateur, timezone.now()
    r.save(update_fields=["returned_by", "returned_at"])
    journaux.materiel("RETOUR", m.nom_affiche, r.qty, utilisateur, mission,
                      identite=m.identite)
    return ("%d × %s restitué(s) pour « %s »" % (r.qty, m.nom_affiche, mission),
            [["materiel", m.name], ["matLog", ""], ["mission", mission]])


def _consommations(p, en_cours):
    """Ce que la personne déclare avoir consommé, article par article.

    Forme attendue : { "<article>": quantité }. Les quantités nulles sont
    écartées ici plutôt que refusées : l'interface envoie une case par ligne
    rendue, et la plupart restent à zéro.

    Trois refus, parce que trois erreurs sont possibles et qu'aucune ne doit
    passer en silence : consommer ce qui n'est pas un consommable, consommer un
    article que la mission n'a pas emprunté, en consommer plus qu'il n'en était
    sorti.
    """
    brut = p.get("consommes") or {}
    if not isinstance(brut, dict):
        raise ErreurAction("Quantités consommées invalides.")

    sortis = {}
    for r in en_cours:
        sortis[r.material_id] = sortis.get(r.material_id, 0) + r.qty

    consommes = {}
    for cle, valeur in brut.items():
        n = qte({"qty": valeur}, mini=0)
        if not n:
            continue
        nom = str(cle)
        m = Material.objects.filter(pk=nom).first()
        if m is None or nom not in sortis:
            raise ErreurAction(
                "« %s » ne fait pas partie de ce qui est sorti pour cette "
                "mission. Rechargez la page." % nom)
        if not m.est_consommable:
            raise ErreurAction(
                "« %s » n'est pas un consommable : il revient au stock. "
                "Seuls les articles de catégorie « %s » peuvent être déclarés "
                "utilisés." % (m.designation, CATEGORIE_CONSOMMABLE))
        if n > sortis[nom]:
            raise ErreurAction(
                "%d × « %s » déclarés utilisés, alors que %d seulement "
                "étaient sortis." % (n, m.designation, sortis[nom]))
        consommes[nom] = n
    return consommes


@action("materiel.mission.restituer")
def materiel_mission_restituer(utilisateur, p):
    """Rentre le matériel d'une mission, en déduisant ce qui a été consommé.

    Un consommable déclaré utilisé ne revient pas au stock : sa ligne d'emprunt
    se ferme comme les autres — la mission est bien terminée — mais la quantité
    correspondante est retirée du stock, parce qu'elle n'existe plus. Le journal
    porte alors deux lignes, CONSOMMÉ et RETOUR, et non une seule qui mentirait
    sur ce qui est rentré.

    Ce qui reste est réparti sur les lignes d'emprunt dans l'ordre : une mission
    peut avoir sorti le même article en deux fois, et « 8 utilisés » ne dit pas
    de quelle sortie ils venaient.
    """
    nom = texte(p, "mission", maxi=200)
    exiger_gestion(nom, utilisateur, p, "Restituer le matériel d'une mission")
    # `equipe` absente rend toute la mission ; présente, seulement cette
    # équipe. Une chaîne vide explicite rend ce qui n'a pas d'équipe.
    equipe = p.get("equipe")
    equipe = None if equipe is None else texte({"e": equipe}, "e",
                                               obligatoire=False)
    en_cours = emprunts_ouverts_de_mission(nom, equipe)
    if not en_cours:
        if equipe:
            raise ErreurAction(
                "Aucun matériel à restituer pour l'équipe « %s »." % equipe)
        raise ErreurAction("Aucun matériel à restituer pour « %s »." % nom)

    consommes = _consommations(p, en_cours)
    commentaire = texte(p, "commentaire", obligatoire=False, maxi=500)

    quand = timezone.now()
    cibles = [["matLog", ""]]
    reste = dict(consommes)
    for r in en_cours:
        m = r.material
        consomme = min(r.qty, reste.get(r.material_id, 0))
        if consomme:
            reste[r.material_id] -= consomme
            m.qty -= consomme
            m.save(update_fields=["qty"])
            journaux.materiel("CONSOMMÉ", m.nom_affiche, consomme, utilisateur,
                              nom, commentaire, m.identite)
        r.returned_by, r.returned_at = utilisateur, quand
        r.save(update_fields=["returned_by", "returned_at"])
        if r.qty - consomme:
            journaux.materiel("RETOUR", m.nom_affiche, r.qty - consomme,
                              utilisateur, nom, identite=m.identite)
        cibles.append(["materiel", r.material_id])

    total = sum(consommes.values())
    resume = "%d ligne(s) restituées pour « %s »" % (len(en_cours), nom)
    if equipe:
        resume += " (%s)" % equipe
    if total:
        resume += ", dont %d unité(s) consommées" % total
    return resume, cibles
