# -*- coding: utf-8 -*-
"""Reprend les bases de l'application Qt dans la base Django.

    python manage.py reprendre_heimdall chemin/donnees.db [chemin/comptes.db]

Les tables de Heimdall-Django portent les mêmes noms et les mêmes colonnes que
celles de l'application Qt : il n'y a donc rien à convertir, seulement à
recopier — y compris vers PostgreSQL, où un simple fichier SQLite ne pourrait
pas être ouvert.

Les **mots de passe sont repris** : Heimdall hachait déjà en scrypt, et
`comptes.hashers.ScryptHeimdall` lit ce format. Personne n'a à changer de mot de
passe, contrairement au trajet inverse où c'était impossible.

Les bases d'origine ne sont jamais modifiées : elles sont ouvertes en lecture
seule.
"""


import sqlite3
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from comptes.models import ActiviteCompte, Compte
from stock.models import (Cabinet, Material, MaterialLog, MaterialReservation,
                          Mission, MissionTemplate, MissionTemplateItem,
                          Operation, Pack, PackItem, PhoneModel, PhoneMovement,
                          PhoneOut, PhoneReservation, SlotAssignment, Variant,
                          Version)


def _ouvrir(chemin):
    """En lecture seule : la base d'origine doit rester intacte."""
    cx = sqlite3.connect("file:%s?mode=ro" % Path(chemin).as_posix(), uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def _colonnes(cx, table):
    return {r[1] for r in cx.execute("PRAGMA table_info(%s)" % table)}


def _table_existe(cx, table):
    return cx.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (table,)).fetchone() is not None


def _lire(cx, table):
    if not _table_existe(cx, table):
        return []
    return [dict(r) for r in cx.execute("SELECT * FROM %s" % table)]


def _moment(brut):
    """Les horodatages de Heimdall sont du texte ISO, parfois vide.

    Rendus conscients du fuseau : `USE_TZ` est actif, et une date naïve
    déclencherait un avertissement à chaque ligne.
    """
    if not brut:
        return None
    if isinstance(brut, datetime):
        valeur = brut
    else:
        texte = str(brut).strip().replace("T", " ")
        for forme in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                      "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                valeur = datetime.strptime(texte, forme)
                break
            except ValueError:
                continue
        else:
            return None
    if timezone.is_naive(valeur):
        valeur = timezone.make_aware(valeur, timezone.get_default_timezone())
    return valeur


def _jour(brut):
    if not brut:
        return None
    if isinstance(brut, date) and not isinstance(brut, datetime):
        return brut
    moment = _moment(brut)
    return moment.date() if moment else None


class Command(BaseCommand):
    help = "Reprend donnees.db (et comptes.db) de l'application Qt."

    def add_arguments(self, parser):
        parser.add_argument("donnees", help="chemin de donnees.db")
        parser.add_argument("comptes", nargs="?",
                            help="chemin de comptes.db (facultatif)")
        parser.add_argument(
            "--vider", action="store_true",
            help="efface les données Django existantes avant de reprendre. "
                 "Sans cette option, la commande refuse d'écrire dans une base "
                 "déjà peuplée.")

    def handle(self, *args, **options):
        chemin = Path(options["donnees"])
        if not chemin.is_file():
            raise CommandError("Fichier introuvable : %s" % chemin)

        deja = (PhoneModel.objects.exists() or Material.objects.exists()
                or Version.courante() > 0)
        if deja and not options["vider"]:
            raise CommandError(
                "La base Django contient déjà des données. Relancez avec "
                "--vider pour les remplacer, ou reprenez dans une base neuve.")

        with transaction.atomic():
            if options["vider"]:
                self._vider()
            self._reprendre_donnees(chemin)
            if options["comptes"]:
                self._reprendre_comptes(Path(options["comptes"]))

        self.stdout.write(self.style.SUCCESS("Reprise terminée."))
        self.stdout.write("  version           : %d" % Version.courante())
        self.stdout.write("  références        : %d" % PhoneModel.objects.count())
        self.stdout.write("  articles          : %d" % Material.objects.count())
        self.stdout.write("  packs             : %d" % Pack.objects.count())
        self.stdout.write("  missions          : %d" % Mission.objects.count())
        self.stdout.write("  comptes           : %d" % Compte.objects.count())

    # ------------------------------------------------------------------
    def _vider(self):
        for modele in (PackItem, Pack, MissionTemplateItem, MissionTemplate,
                       MaterialReservation, MaterialLog, Material,
                       PhoneReservation, PhoneOut, SlotAssignment, Variant,
                       PhoneMovement, PhoneModel, Cabinet, Mission, Operation,
                       Version):
            modele.objects.all().delete()

    def _reprendre_donnees(self, chemin):
        cx = _ouvrir(chemin)
        try:
            self._phones(cx)
            self._armoires(cx)
            self._materiel(cx)
            self._missions(cx)
            self._packs(cx)
            self._journaux(cx)
            self._version(cx)
        finally:
            cx.close()

    def _phones(self, cx):
        PhoneModel.objects.bulk_create([
            PhoneModel(id=r["id"], ordre=r["ordre"], brand=r["brand"],
                       model=r["model"], mpn=r.get("mpn") or "",
                       commercial_name=r.get("commercial_name") or "")
            for r in _lire(cx, "stock_phonemodel")])

        Variant.objects.bulk_create([
            Variant(idx=r["idx"], capa=r["capa"], color=r["color"],
                    swatch=r.get("swatch") or "", qty=r["qty"],
                    phone_id=r["phone_id"])
            for r in _lire(cx, "stock_variant")])

        for table, modele in (("stock_phonereservation", PhoneReservation),
                              ("stock_phoneout", PhoneOut)):
            modele.objects.bulk_create([
                modele(seq=r["seq"], who=r["who"], qty=r["qty"],
                       variant_idx=r["variant_idx"], variant=r["variant"],
                       phone_id=r["phone_id"],
                       horodatage=_moment(r["horodatage"]) or timezone.now())
                for r in _lire(cx, table)])

    def _armoires(self, cx):
        Cabinet.objects.bulk_create([
            Cabinet(id=r["id"], ordre=r["ordre"], shelves=r["shelves"],
                    cols=r["cols"])
            for r in _lire(cx, "stock_cabinet")])
        # Les casiers fixés visant une référence disparue sont écartés : la clé
        # étrangère les refuserait, et ils ne désignent plus rien.
        connues = set(PhoneModel.objects.values_list("id", flat=True))
        SlotAssignment.objects.bulk_create([
            SlotAssignment(phone_id=r["phone_id"], loc=r["loc"])
            for r in _lire(cx, "stock_slotassignment")
            if r["phone_id"] in connues])

    def _materiel(self, cx):
        colonnes = _colonnes(cx, "stock_material")
        Material.objects.bulk_create([
            Material(name=r["name"], ordre=r["ordre"], cat=r["cat"],
                     qty=r["qty"], seuil=r.get("seuil") or 0,
                     affectation=r.get("affectation") or "Commun",
                     libelle=(r.get("libelle") or "") if "libelle" in colonnes else "",
                     etiquette=r.get("etiquette") or "",
                     numero_serie=r.get("numero_serie") or "")
            for r in _lire(cx, "stock_material")])

        res_colonnes = _colonnes(cx, "stock_materialreservation")
        connus = set(Material.objects.values_list("name", flat=True))
        MaterialReservation.objects.bulk_create([
            MaterialReservation(
                seq=r["seq"], qty=r["qty"], mission=r.get("mission") or "—",
                taken_by=r.get("taken_by") or "", returned_by=r.get("returned_by"),
                material_id=r["material_id"],
                taken_at=_moment(r.get("taken_at")) if "taken_at" in res_colonnes else None,
                returned_at=_moment(r.get("returned_at")),
                pack=(r.get("pack") or "") if "pack" in res_colonnes else "")
            for r in _lire(cx, "stock_materialreservation")
            if r["material_id"] in connus])

    def _missions(self, cx):
        Mission.objects.bulk_create([
            Mission(name=r["name"], ordre=r["ordre"], is_meta=bool(r["is_meta"]),
                    owner=r.get("owner") or "",
                    status_override=r.get("status_override"),
                    archived=bool(r.get("archived")),
                    planned_date=_jour(r.get("planned_date")))
            for r in _lire(cx, "stock_mission")])

        MissionTemplate.objects.bulk_create([
            MissionTemplate(name=r["name"], owner=r.get("owner") or "",
                            created_at=_moment(r.get("created_at")) or timezone.now())
            for r in _lire(cx, "stock_mission_template")])

        connus = set(MissionTemplate.objects.values_list("name", flat=True))
        MissionTemplateItem.objects.bulk_create([
            MissionTemplateItem(
                template_id=r["template_name"], ordre=r["ordre"],
                kind=r["kind"], libelle=r.get("libelle") or "",
                material_id=r.get("material_id"), qty=r["qty"])
            for r in _lire(cx, "stock_mission_template_item")
            if r["template_name"] in connus])

    def _packs(self, cx):
        Pack.objects.bulk_create([
            Pack(name=r["name"], ordre=r["ordre"], owner=r.get("owner") or "",
                 etiquette=r.get("etiquette") or "",
                 created_at=_moment(r.get("created_at")) or timezone.now())
            for r in _lire(cx, "stock_pack")])

        connus = set(Pack.objects.values_list("name", flat=True))
        PackItem.objects.bulk_create([
            PackItem(pack_id=r["pack_name"], ordre=r["ordre"],
                     material_id=r["material_id"], qty=r["qty"])
            for r in _lire(cx, "stock_pack_item")
            if r["pack_name"] in connus])

    def _journaux(self, cx):
        PhoneMovement.objects.bulk_create([
            PhoneMovement(seq=r["seq"], user=r["user"], label=r["label"],
                          loc=r.get("loc") or "", kind=r["kind"],
                          horodatage=_moment(r["horodatage"]) or timezone.now())
            for r in _lire(cx, "stock_phonemovement")])

        colonnes = _colonnes(cx, "stock_materiallog")
        MaterialLog.objects.bulk_create([
            MaterialLog(
                seq=r["seq"], kind=r["kind"], item=r["item"], qty=r["qty"],
                who=r.get("who") or "—", mission=r.get("mission") or "—",
                commentaire=(r.get("commentaire") or "") if "commentaire" in colonnes else "",
                identite=(r.get("identite") or "") if "identite" in colonnes else "",
                horodatage=_moment(r["horodatage"]) or timezone.now())
            for r in _lire(cx, "stock_materiallog")])

    def _version(self, cx):
        lignes = _lire(cx, "stock_version")
        Version.poser(lignes[0]["valeur"] if lignes else 0)
        # L'historique des opérations n'est pas repris : il ne sert qu'à répondre
        # en différentiel aux sessions ouvertes, et il n'y en a aucune sur une
        # base qu'on vient de reprendre. Les interfaces recevront l'état complet
        # à leur premier appel, ce qui est exactement ce qu'il faut.

    # ------------------------------------------------------------------
    def _reprendre_comptes(self, chemin):
        if not chemin.is_file():
            raise CommandError("Fichier introuvable : %s" % chemin)
        cx = _ouvrir(chemin)
        try:
            comptes = _lire(cx, "comptes")
            for r in comptes:
                identifiant = r["identifiant"]
                compte = Compte(
                    identifiant=identifiant,
                    groupe=r.get("groupe") or "",
                    administrateur=bool(r.get("administrateur")),
                    actif=bool(r.get("actif", 1)),
                    doit_changer=bool(r.get("doit_changer")),
                    cree_le=_moment(r.get("cree_le")) or timezone.now(),
                    derniere_visite=_moment(r.get("derniere_visite")),
                    # Un administrateur du stock n'obtient pas /admin/ au
                    # passage : c'est une décision à prendre compte par compte.
                    is_staff=False,
                )
                # L'empreinte est recopiée telle quelle : son format est celui
                # que `ScryptHeimdall` sait relire.
                compte.password = r["empreinte"]
                compte.save()

            for r in _lire(cx, "activite_comptes"):
                ActiviteCompte.objects.create(
                    horodatage=_moment(r.get("horodatage")) or timezone.now(),
                    acteur=r.get("acteur") or "",
                    action=r.get("action") or "",
                    ancien_nom=r.get("ancien_nom") or "",
                    nouveau_nom=r.get("nouveau_nom") or "")

            self.stdout.write(
                "  mots de passe repris : %d (format scrypt conservé)"
                % len(comptes))
        finally:
            cx.close()
