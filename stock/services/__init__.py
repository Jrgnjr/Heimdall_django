# -*- coding: utf-8 -*-
"""Le registre des actions métier.

Une action, c'est une intention de l'utilisateur : réceptionner, emprunter,
consommer. Trois règles les gouvernent toutes, et ce sont elles qui rendent le
reste sûr :

- **tout ou rien.** Chaque action s'exécute dans une transaction unique. Un
  emprunt groupé à moitié appliqué serait pire qu'un refus ;
- **refuser en parlant.** Un refus lève `ErreurAction`, dont le message est
  écrit pour être lu par un humain dans l'interface ;
- **déclarer ce qu'on a touché.** Chaque action retourne ses cibles, ce qui
  permet de ne renvoyer à l'interface que la différence plutôt que l'état
  entier toutes les 2,5 secondes.

Le registre est peuplé à l'import : `charger()` importe les modules d'action,
dont les décorateurs `@action` s'enregistrent au passage.
"""

from .champs import ErreurAction  # noqa: F401  (ré-exporté pour les appelants)

ACTIONS = {}

# Actions réservées aux administrateurs : celles qui touchent à la structure du
# stock plutôt qu'à son usage quotidien.
#
# Placer un téléphone dans un casier n'en fait pas partie : c'est du travail
# courant. Dimensionner une armoire, créer ou supprimer un article, régler un
# seuil, poser un numéro de série : oui.
#
# La liste est ici, et pas dans l'interface : cacher un bouton n'empêche rien,
# c'est le serveur qui doit refuser. Et contrairement à l'application Qt — où
# la base était un fichier sur le poste de l'utilisateur, à sa portée —, ce
# refus a désormais du poids : la base est sur le serveur.
ACTIONS_ADMINISTRATEUR = {
    "armoire.ajouter",
    "armoire.supprimer",
    "armoire.dimension",
    "telephone.creer",
    "telephone.reception",
    "telephone.variante.ajouter",
    "telephone.importer_xlsx",
    "materiel.creer",
    "materiel.reception",
    "materiel.seuil",
    "materiel.identifiants",
    "materiel.creer.lot",
    "telephone.supprimer",
    "materiel.supprimer",
    "mission.supprimer",
    "mission.template.creer",
    "mission.template.modifier",
    "mission.template.supprimer",
    # Le sac de dotation engage ce qu'une personne détient durablement : le
    # composer relève de l'encadrement, pas du travail quotidien.
    "compte.dotations",
    # Composer les équipes d'une mission, c'est de l'organisation. Y répartir
    # le matériel, non : `materiel.equipe.affecter` reste ouvert à tous, comme
    # emprunter.
    "mission.equipe.creer",
    "mission.equipe.renommer",
    "mission.equipe.supprimer",
    "mission.equipe.membres",
}


def action(nom):
    """Enregistre une fonction comme action nommée."""
    def decorateur(fn):
        if nom in ACTIONS:
            raise RuntimeError("Action déclarée deux fois : %s" % nom)
        ACTIONS[nom] = fn
        return fn
    return decorateur


def charger():
    """Importe les modules d'action pour peupler le registre.

    Appelé par `StockConfig.ready()`. Les imports sont faits ici plutôt qu'en
    tête de fichier : les modules d'action importent les modèles, qui ne sont
    pas encore chargés au moment où ce paquet l'est.
    """
    from . import (armoires, dotations, equipes, materiel,  # noqa: F401
                   missions, packs, telephones, templates)


def executer(nom, utilisateur, params, administrateur=False):
    """Exécute une action et retourne (résumé, cibles touchées).

    Ne gère ni transaction ni version : c'est le rôle de `stock.api`, qui sait
    aussi inscrire l'opération dans l'historique.
    """
    fn = ACTIONS.get(nom)
    if fn is None:
        raise ErreurAction("Action inconnue : %s." % nom)
    if nom in ACTIONS_ADMINISTRATEUR and not administrateur:
        raise ErreurAction("Cette action est réservée aux administrateurs.")
    return fn(utilisateur, params)
