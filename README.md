# Heimdall — gestion de stock

Application web de gestion de stock pour une équipe : **téléphones** rangés en
armoire, **matériel** et **consommables**, **missions** qui en emportent, **sacs
personnels** dont on se prête le contenu, **journal** de tous les mouvements.

Elle se consulte depuis un navigateur, sur le réseau local de l'équipe. Plusieurs
personnes y travaillent en même temps ; chacune a son compte, son profil et ses
réglages.

> Ce document présente l'application, ses règles et son fonctionnement. Le
> déploiement et le portage depuis l'ancienne version Qt sont détaillés dans
> [LISEZMOI.md](LISEZMOI.md).

---

## Sommaire

1. [Ce que fait l'application](#ce-que-fait-lapplication)
2. [Rôles et droits](#rôles-et-droits)
3. [Les règles qui comptent](#les-règles-qui-comptent)
4. [Démarrage rapide](#démarrage-rapide)
5. [Configuration](#configuration)
6. [Utiliser l'application sur le réseau local](#utiliser-lapplication-sur-le-réseau-local)
7. [Sessions, onglets et sécurité](#sessions-onglets-et-sécurité)
8. [Développer](#développer)
9. [Architecture](#architecture)
10. [API et adresses](#api-et-adresses)
11. [Exploitation](#exploitation)
12. [Dépannage](#dépannage)
13. [Tests](#tests)
14. [Limites connues](#limites-connues)

---

## Ce que fait l'application

Une interface unique, six écrans plus le profil, dans une barre latérale :

| Écran | Pour quoi faire |
|---|---|
| **Profil** | Page d'ouverture : ce que je détiens, mes missions, mes prêts et demandes, mon activité. Une disposition en *widgets* que chacun compose |
| **Stock de téléphone** | Références, déclinaisons, quantités ; sortir, réserver, ajouter |
| **Plan de l'armoire** | Où se trouve chaque référence : étagère, casier, placement manuel ou automatique |
| **Stock de matériel** | Accessoires, outils, ordinateurs, consommables ; emprunter, réserver, attribuer à un sac |
| **Missions en cours** | Créer et suivre les missions, leur matériel, leur équipe, leur gestion |
| **Journal** | Chaque mouvement de téléphone ou de matériel, filtrable |
| **Administration** | Structure du stock : articles, références, armoires, templates, comptes (réservé aux administrateurs) |

### Téléphones et armoires

- Des **références** (marque, modèle, référence fabricant) portent des
  **déclinaisons** (capacité, couleur) et une quantité.
- Les références sont **placées** dans des casiers (étagère × colonne) : placement
  automatique, ou choisi à la main et verrouillé.
- On peut **sortir** un téléphone (il quitte l'armoire, à votre nom) ou le
  **réserver** (il reste en casier mais n'est plus vendable).
- Import de références depuis un fichier **XLSX**.

### Matériel et consommables

- Chaque article est soit **groupé** (une ligne, une quantité : des câbles), soit
  un **exemplaire** (une ligne par objet, avec étiquette et numéro de série : trois
  portables identiques se distinguent).
- Les **consommables** ont un **seuil d'alerte réglé par catégorie** (les
  exemplaires de même nom sont regroupés) : sous le seuil, la catégorie est « à
  recommander » et les administrateurs en sont avertis dans leur profil.
- Les **malettes** (packs) réunissent des articles qui sortent ensemble.
- Un administrateur peut **corriger un stock** (inventaire) : l'écart est inscrit au
  journal.

### Missions

Une mission regroupe du matériel, une date prévue, une **gestion** et un
**effectif** réparti en **équipes**. Elle a un statut qui suit un ordre précis
(voir [les règles](#les-règles-qui-comptent)).

- Création avec ou sans **template** (liste type de matériel à emporter).
- Matériel affecté à la mission, réparti entre ses équipes, **restitué** au retour,
  avec déclaration des consommables utilisés.
- Une page **tableau de bord** par mission (`/missions/<nom>/`), à partager par
  lien sur le réseau.
- Archivage des missions terminées ou annulées.

### Sacs personnels et prêts

Chaque personne a un **sac de dotation** : du matériel qui lui est attribué
durablement. Son contenu lui appartient — on le lui **demande** :

1. on cherche un type de matériel parmi les sacs des autres, et on choisit à qui
   s'adresser, avec ou sans mission ;
2. la personne reçoit une **notification** dans son profil et **accepte** ou
   **refuse** (avec une raison facultative) ;
3. si elle accepte, le matériel sort à l'emprunteur comme n'importe quel emprunt, et
   figure dans le widget **« Mes prêts »** du prêteur ;
4. au retour, il regagne le sac, qui n'a jamais été vidé.

Un **gestionnaire de mission** peut **forcer** un prêt — sans attendre la réponse —
quand la personne est absente ou n'a pas accès à la plateforme. Le prêt est alors
marqué *« forcé par X »* chez le prêteur, et le journal en garde la trace.

### Comptes, profil et réglages

- Un **profil** par compte, comme page d'ouverture, composé de **widgets** : on
  choisit lesquels, leur ordre (glisser-déposer) et leur taille. 15 widgets au
  catalogue (compteurs, sac, sorties, missions, activité, à recommander, mes prêts,
  mes demandes, stock bas, mes équipes, état du stock, accès rapides, et **Mon
  groupe** pour les chefs de groupe…).
- Des **réglages** par compte, enregistrés sur le serveur — ils suivent la personne
  d'un poste à l'autre : thème **sombre / clair / automatique**, lignes par page,
  filtres.
- Un **code de récupération** personnel pour changer son mot de passe en cas
  d'oubli (voir [sécurité](#sessions-onglets-et-sécurité)).
- Un administrateur peut **agir au nom d'un autre compte** (enregistrer une sortie
  faite par quelqu'un qui ne s'est pas connecté) ; un bandeau jaune le rappelle en
  permanence.

---

## Rôles et droits

Quatre rôles. Trois sont portés par le **compte**, le quatrième est propre à
**chaque mission**.

| Rôle | Portée | En deux mots |
|---|---|---|
| **Effectif** | Compte (rôle de base) | Il travaille, emprunte pour lui, demande du matériel, répond aux demandes de son sac |
| **Chef de groupe** | Compte | Il a un **groupe** d'effectifs. Il crée des missions et répond à leur place quand ils sont absents |
| **Gestionnaire de mission** | Une mission | Il a la charge d'*une* mission : statut, équipes, matériel, prêts forcés |
| **Admin** | Compte | Tous les droits, y compris ceux d'un gestionnaire sur **toutes** les missions |

La hiérarchie est *admin ⊃ chef de groupe ⊃ effectif*. Le gestionnaire est à part :
un effectif comme un chef de groupe peut l'être, et **aucun ne l'est d'office** — le
chef qui crée une mission peut la confier à quelqu'un d'autre sans la gérer.

- Un **groupe** est une entité créée par un administrateur, avec ou sans chef (voir
  « Les groupes »). Le chef de groupe est le membre qui le dirige.
- Sur une même mission, on est **gestionnaire ou membre de l'effectif** (d'une de ses
  équipes), jamais les deux. On peut gérer une mission et travailler sur une autre.

### Ce que peut chaque rôle

| Droit | Effectif | Chef de groupe | Gestionnaire *(sa mission)* | Admin |
|---|:-:|:-:|:-:|:-:|
| Consulter le stock, son profil, ses réglages | ✓ | ✓ | ✓ | ✓ |
| Emprunter pour soi, **sans mission** | ✓ | ✓ | ✓ | ✓ |
| Emprunter **pour une mission** | si équipier | si l'un de ses effectifs est équipier | ✓ | ✓ |
| Rendre une ligne d'emprunt | la sienne | celles de ses effectifs | celles de sa mission | ✓ |
| Demander du matériel dans un sac | ✓ | ✓ | ✓ | ✓ |
| Répondre à une demande de **son** sac | ✓ | ✓, et **à la place de ses effectifs** | — | ✓ |
| Forcer un prêt | — | dans les sacs de **son groupe** | ✓ | ✓ |
| Créer une mission | — | ✓ | — | ✓ |
| Statut, date, archivage d'une mission | — | — | ✓ | ✓ |
| Reculer un statut | — | — | ✓ | ✓ |
| Désassigner / restituer le matériel d'une mission | restituer **sa** ligne | — | ✓ | ✓ |
| Répartir le matériel entre les équipes | — | — | ✓ | ✓ |
| Composer les équipes d'une mission | — | placer **ses** effectifs | ✓ | ✓ |
| Nommer les gestionnaires d'une mission | — | — | ✓ | ✓ |
| Voir le profil d'un effectif, agir en son nom | — | **son groupe** | — | ✓ (tous) |
| Composer le sac d'un effectif | — | **son groupe** | — | ✓ (tous) |
| Structure du stock, templates, inventaire | — | — | — | ✓ |
| Supprimer une mission, importer un XLSX | — | — | — | ✓ |
| **Créer et régler les groupes** (membres, chef, matériel) | — | — | — | ✓ |

### Filtres par colonne

Les tableaux **Stock de matériel**, **Stock de téléphone** et **Journal** se filtrent
colonne par colonne : un entonnoir à côté du titre ouvre le filtre de la colonne (une
liste de valeurs déjà déroulée, ou un champ de saisie pour les textes). Les filtres se
cumulent entre eux et avec la recherche ; l'entonnoir barré, en tête du tableau, les
retire tous. Ils font partie des **réglages du compte** : on les retrouve d'une visite
à l'autre, sur n'importe quel poste.

### Les groupes

Un **groupe** est une entité à part entière, créée par un administrateur : il existe
**avant d'avoir un chef**, et peut rester sans chef. On y place des membres ; le **chef**
est l'un d'eux, nommé quand on le souhaite. Un compte n'est membre que d'un groupe, un
chef ne dirige qu'un groupe, et un administrateur n'appartient à aucun groupe.

Sans chef, personne ne répond à la place d'un absent ni ne compose les sacs : seuls les
administrateurs gèrent le groupe. Supprimer un groupe, ou retirer son chef, ne supprime
aucun compte : les membres se retrouvent sans groupe (ou sans chef).

Tout membre d'un groupe (avec ou sans chef) a une page **Mon groupe** dans le menu : les
membres, ce que chacun détient (sac de dotation et emprunts), et le **matériel affecté au
groupe** dans le stock. Elle est en lecture ; seuls le chef et les administrateurs
modifient les sacs. Le serveur n'envoie à un membre que les sacs de son groupe.

Le lien avec le stock de matériel est l'étiquette **Groupe 1 / 2 / 3** (colonne
« affectation » du stock) : un administrateur choisit le « matériel affecté » **du
groupe**. Sans choix, la page le dit et n'affiche aucun article ; l'étiquette « Commun »
n'est celle d'aucun groupe.

### Administrer les comptes

**Administration → Comptes** montre une **vignette par compte** (avatar, nom, rôle,
unités détenues). Un clic ouvre la **fiche** du compte, une grande fenêtre qui
rassemble tout ce qu'un administrateur peut faire concernant cette personne :

- **Rôle et groupe** : son groupe, et — s'il en a un — « Nommer chef du groupe » ou
  « Retirer la direction ». Le rôle *admin* se règle dans l'administration Django
  (`/admin/`), comme la création et le renommage d'un compte.
- **Sécurité** : réinitialiser le mot de passe (un mot de passe provisoire de 12
  caractères est affiché **une seule fois** et la personne doit le remplacer à sa
  connexion ; ses sessions ouvertes se ferment), retirer son code de récupération,
  **désactiver / réactiver** le compte.
- **Sac, emprunts, missions** : son sac de dotation (avec « Modifier le sac »), ce
  qu'elle détient, ses missions et leur statut. En pied : *Voir son profil* et
  *Agir en son nom*.

**Les groupes** se gèrent dans le bandeau « Groupes » au-dessus des vignettes :
« + Nouveau groupe » (nom, matériel affecté), puis, dans la fenêtre du groupe, le
renommer, choisir son chef (ou « sans chef »), ajouter ou retirer des membres, le
supprimer.

Filtres : Tous / Admins / Chefs / Effectifs, « Même sans possession », « Afficher les
désactivés ».

Garde-fous : un nom de groupe est unique, on ne nomme pas chef quelqu'un qui est membre
d'un autre groupe ou qui en dirige déjà un, et déplacer ou retirer un chef lui ôte la
direction de son groupe. On ne se désactive pas soi-même, on ne désactive pas le
**dernier administrateur actif** (désactiver un chef lui retire la direction), et on ne
réinitialise pas son propre mot de passe par ce biais. Un compte désactivé garde son
historique, son sac et ses emprunts. Chaque changement est inscrit au registre des
comptes ; le mot de passe provisoire n'est écrit ni dans l'historique ni dans le registre.

> **À la première mise à jour vers ce système**, tous les comptes non administrateurs
> deviennent *effectifs* : personne, sauf les administrateurs, ne peut plus créer de
> mission tant que des chefs de groupe n'ont pas été nommés.

### Qui agit : l'auteur et l'acteur

Une action a deux identités : l'**auteur**, au nom de qui elle est enregistrée, et
l'**acteur**, la personne réellement connectée. Elles diffèrent quand un
administrateur ou un chef de groupe agit au nom de quelqu'un. **Les droits se jugent
sur l'acteur** : un chef de groupe qui agit au nom d'un effectif garde son autorité de
chef, et n'acquiert pas celle de gestionnaire d'une mission que cet effectif gérerait.

Ces droits sont **vérifiés par le serveur**, jamais par l'interface seule : cacher
un bouton n'empêche rien, c'est le refus côté serveur qui compte. Le serveur écrase
toute identité ou tout droit que le client enverrait dans ses paramètres.

---

## Les règles qui comptent

### Statuts d'une mission

```
PRÉVUE ──▶ EN COURS ──▶ TERMINÉE            ANNULÉE (à part)
```

- Le statut **avance seul** : une mission est *prévue* tant que sa date n'est pas
  arrivée, *en cours* à partir de ce jour (ou dès qu'elle détient du matériel, sans
  date), *terminée* quand tout ce qu'elle détenait est rendu. On peut aussi le
  poser à la main (menu de la carte).
- **On avance et on annule librement. On ne recule pas** — sauf un gestionnaire de
  la mission ou un administrateur. Rouvrir une mission annulée, ou annuler une
  mission terminée, c'est aussi reculer.
- Le statut calculé **ne régresse jamais tout seul** : chaque mission retient son
  plus haut statut atteint, qui sert de plancher. Rendre le dernier emprunt d'une
  mission ou repousser sa date ne la fait pas redevenir « prévue ».

### Désassigner et restituer

| Mission | Bouton | Effet |
|---|---|---|
| **Prévue** | *Désassigner* | La réservation est défaite : la ligne disparaît de la mission et le matériel est rendu (au stock, ou au sac qui l'avait prêté) |
| **En cours** (ou plus tard) | *Restituer* | La ligne se **ferme** dans la mission — elle reste dans son historique — et le matériel est rendu |

*Restituer tout* (équipe ou mission entière) permet en plus de déclarer des
consommables utilisés : ils quittent le stock au lieu d'y revenir.

### Prêts de sac

- Une demande est refusée si l'article n'est plus dans le sac, si la quantité
  dépasse ce que le sac peut encore prêter, ou si la personne **fait partie de
  l'effectif** de la mission (elle emporte déjà son sac).
- La disponibilité est vérifiée à la demande, puis **de nouveau** à l'acceptation.
- Seul le sollicité répond ; seul le demandeur annule ; une demande ne se traite
  qu'une fois. Les demandes ne sont visibles que des personnes concernées — et du
  gestionnaire de la mission visée.

### Traçabilité

- Tout mouvement de matériel s'inscrit au **journal**, avec l'identité de
  l'exemplaire (étiquette, série) **recopiée au moment du mouvement** : réétiqueter
  un exemplaire plus tard ne réécrit pas l'histoire.
- Les actions sont **atomiques** : un emprunt groupé, un lot d'exemplaires ou une
  mission servie par un template n'écrivent rien s'ils refusent en cours de route.

---

## Démarrage rapide

Avec Docker — deux conteneurs, l'application et sa base :

```bash
cp .env.exemple .env          # puis renseigner les variables obligatoires
docker compose up -d --build
docker compose logs -f web    # le mot de passe du premier compte s'y affiche
```

Puis ouvrez `http://localhost:8750/`.

Au premier démarrage, un compte **Admin** est créé avec un mot de passe tiré au
hasard, **affiché une seule fois dans les journaux** et à remplacer à la première
connexion. Pour le choisir vous-même, renseignez `HEIMDALL_ADMIN_MOTDEPASSE`.

Pour mettre à jour après un changement de code :

```bash
docker compose up -d --build web     # reconstruit l'image, applique les migrations
```

---

## Configuration

Tout se règle par variables d'environnement, lues depuis un fichier `.env` à côté
de `docker-compose.yml` (modèle : [.env.exemple](.env.exemple)). **Ce fichier ne
doit jamais être commité** : il est ignoré par git.

### Obligatoires

| Variable | Rôle |
|---|---|
| `DJANGO_SECRET_KEY` | Clé secrète. Générer : `python -c "import secrets; print(secrets.token_urlsafe(64))"`. Une clé qui change à chaque démarrage invaliderait toutes les sessions |
| `POSTGRES_PASSWORD` | Mot de passe de la base (avec Docker) |
| `DJANGO_ALLOWED_HOSTS` | Noms d'hôte et adresses sous lesquels le site répond, séparés par des virgules |
| `DATABASE_URL` | Hors Docker : `postgres://utilisateur:mdp@hôte:5432/base`. PostgreSQL, et lui seul |

### Réseau et TLS

| Variable | Défaut | Rôle |
|---|---|---|
| `HEIMDALL_PORT` | `8750` | Port exposé sur la machine |
| `DJANGO_HTTPS` | `1` | Le site est-il servi en HTTPS ? **À mettre à `0` pour un usage en `http://` sur le réseau local**, sinon personne ne peut se connecter |
| `DJANGO_DERRIERE_PROXY` | `0` | À `1` si un reverse proxy termine TLS devant Django |
| `DJANGO_FORCE_HTTPS`, `DJANGO_HSTS_SECONDS` | `0` | Redirection HTTPS et HSTS — seulement quand le site est réellement en HTTPS |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | | Origines autorisées à poster, avec le schéma |

### Autres

| Variable | Défaut | Rôle |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_DB` | `heimdall` | Identité et nom de la base |
| `DJANGO_TIME_ZONE` | `Europe/Paris` | Fuseau horaire |
| `DJANGO_SESSION_AGE` | `43200` (12 h) | Durée d'une session |
| `DJANGO_DEBUG` | `0` | Mode développement |
| `HEIMDALL_AMORCER_ADMIN` | `1` | Crée le premier administrateur s'il n'en existe aucun |
| `HEIMDALL_ADMIN_IDENTIFIANT` | `Admin` | Son identifiant |
| `HEIMDALL_ADMIN_MOTDEPASSE` | | Son mot de passe (sinon tiré au hasard, affiché une fois) |
| `HEIMDALL_ONGLETS_ISOLES` | `1` | `0` désactive les sessions par onglet |
| `HEIMDALL_ATTENTE_BASE` | `60` | Secondes d'attente de la base au démarrage |

---

## Utiliser l'application sur le réseau local

1. **Adresses autorisées** — mettez l'IP ou le nom du serveur dans
   `DJANGO_ALLOWED_HOSTS` (sinon : « Bad Request (400) » depuis les autres postes).
2. **HTTP simple** — `DJANGO_HTTPS=0`, sinon l'écran de connexion reboucle sans
   message.
3. **Pare-feu** — autorisez le port `8750` (Windows : règle entrante).
4. **IP fixe** — réservez une IP au serveur, pour que les liens ne cassent pas.
5. **Liens de mission** — le bouton « Copier le lien » (ou un clic sur le nom de la
   mission) donne une adresse partageable ; la personne passe par sa connexion
   puis arrive sur la page.

Un lien du type `http://192.168.1.50:8750/missions/Chantier%20Nord/` fonctionne
pour tout poste du même réseau qui atteint le serveur.

---

## Sessions, onglets et sécurité

### Une session par onglet

Un navigateur ne garde qu'un cookie de session par site, donc se connecter avec un
second compte remplaçait le premier. Ici, **chaque onglet a sa propre session** :

- avant connexion, l'onglet vit sous une adresse aléatoire (`/s-1a2b3c4d5e6f/…`) ;
- après connexion, il est sous `/u/<compte>/…`, et ses cookies de session et CSRF
  sont **attachés à ce chemin** — le navigateur les garde séparés ;
- deux utilisateurs peuvent donc travailler côte à côte dans deux onglets ;
- deux onglets du **même** compte partagent la même session (se déconnecter dans
  l'un ferme l'autre) ;
- **rien ne permet de passer d'un compte à l'autre sans mot de passe** : l'adresse
  ne prouve rien, c'est le cookie du chemin qui authentifie. Taper `/u/Bob/` avec la
  session d'Alice renvoie sur la connexion.

Pour garder la même session au rechargement, conservez l'adresse complète de
l'onglet. Ouvrir l'adresse « nue » du serveur donne un nouvel onglet à connecter.

### Mot de passe oublié

Il n'y a pas de messagerie sur un réseau local : chaque compte se donne un **code
de récupération**.

1. Dans **Profil → Réglages → Sécurité → Code de récupération**, on génère son code
   (le mot de passe actuel est redemandé). Il s'affiche **une seule fois**.
2. Si on oublie son mot de passe : page de connexion → **« Mot de passe oublié ? »**
   → identifiant, code, nouveau mot de passe.

Le code est tiré au hasard (100 bits), **haché** en base (même un administrateur
ne peut pas le relire), **à usage unique**, et la récupération d'un compte est
**verrouillée 15 minutes après 5 erreurs** — sans bloquer la connexion normale. Une
récupération réussie ferme toutes les sessions ouvertes du compte.

Sans code défini, un administrateur réinitialise le mot de passe dans
`/admin/`.

### Résumé des protections

- **CSRF** sur tous les formulaires et appels, jeton propre à chaque onglet.
- **Mots de passe** hachés (scrypt, au format repris de l'ancienne application) et
  validés (longueur, mots de passe courants, similarité).
- **Droits vérifiés côté serveur**. Les actions reçoivent le droit réel de
  l'appelant ; un client ne peut pas s'attribuer `administrateur` en l'envoyant dans
  ses paramètres.
- **Messages d'échec identiques** pour un compte inconnu ou un code faux : on ne
  révèle pas quels comptes existent.
- **Sessions** de 12 h, cookies `Secure` selon `DJANGO_HTTPS`.
- **La base n'est pas exposée** hors du réseau interne de Docker.

---

## Développer

### Environnement

Python 3.12, Django 5.2, PostgreSQL 16. Sans Docker pour l'application, mais avec
une base :

```bash
docker compose up -d base            # PostgreSQL, joignable sur 127.0.0.1:5432
python -m venv env && env\Scripts\activate    # (Linux : source env/bin/activate)
pip install -r requirements.txt
export DATABASE_URL=postgres://heimdall:motdepasse@127.0.0.1:5432/heimdall
export DJANGO_DEBUG=1
python manage.py migrate
python manage.py runserver
```

`DATABASE_URL` est obligatoire : le projet refuse de démarrer sans, et SQLite n'est
plus pris en charge.

### Interface

L'interface est **un seul fichier**, `templates/stock/index.html` : HTML, CSS et
JavaScript sans framework ni étape de build. Elle dialogue avec le serveur par
`fetch()` (voir [API](#api-et-adresses)).

- Les **couleurs** sont des variables CSS (`--c-…`), avec une valeur sombre par
  défaut et une valeur claire sous `html[data-theme="light"]`.
- Les **appels sont relatifs** (`api/state`) : c'est ce qui permet à l'application
  de vivre sous le préfixe `/u/<compte>/` de chaque onglet.
- Le rendu est entièrement recalculé à chaque changement d'état ; les champs de
  saisie portent un `data-k` qui permet de leur rendre le curseur après redessin.

### Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

Toutes les migrations récentes sont **additives** (une colonne, une table) : elles
ne touchent pas aux données existantes et s'appliquent au démarrage du conteneur.

---

## Architecture

```
config/            réglages (tout depuis l'environnement), routes racine
comptes/           comptes, connexion, onglets, récupération du mot de passe
  models.py          Compte (utilisateur), Dotation (sac), ActiviteCompte
  views.py           connexion, déconnexion, changement et oubli de mot de passe
  onglets.py         une session par onglet : adresses /u/…, cookies par chemin
  recuperation.py    code de récupération : génération, vérification, verrou
  hashers.py         scrypt au format de l'ancienne application
stock/             le métier
  models.py          téléphones, matériel, emprunts, missions, équipes, prêts…
  api.py             /api/state, /api/action, /api/reglages
  etat.py            modèles → JSON pour l'interface (complet ou différentiel)
  views.py           la page, le tableau de bord d'une mission, /sante/
  services/          les actions métier (62)
    __init__.py        registre des actions, droits, executer()
    champs.py          validation des paramètres, messages de refus
    journaux.py        écriture dans les journaux
    telephones.py  armoires.py  emplacements.py  materiel.py  packs.py
    missions.py  equipes.py  templates.py  dotations.py
    statuts.py         ordre des statuts, plancher, droit de reculer
    gestion.py         gestionnaires et effectif d'une mission
    droits.py          rôles : qui a le droit de quoi, contrôle de chaque action
    roles.py           groupes, état, mot de passe et code de récupération d'un compte (admin)
    prets.py           demandes, acceptation, refus, prêts forcés
  tests/             631 tests
templates/         index.html (l'interface), mission.html, pages de comptes
static/            icône, logo
docker/            point d'entrée du conteneur
```

### Le couple *state* / *action*

L'interface n'envoie jamais l'état : elle décrit une **intention** (une action
nommée et ses paramètres), et le serveur décide.

- `GET /api/state` renvoie l'état complet, ou — avec `?since=N` — la **différence**
  depuis la version `N`. L'interface l'interroge toutes les 2,5 s.
- `POST /api/action` exécute **une** action dans **une transaction** : un refus
  métier annule tout ce qui a pu être écrit avant lui, et la version n'avance pas.
- Les écritures sont **sérialisées** par un verrou posé avant toute lecture : deux
  personnes qui prennent le dernier article au même instant ne le prennent pas
  toutes les deux.

### Pourquoi une couche `services`

Chaque action est une fonction qui valide ses paramètres, applique la règle,
journalise, et **déclare ce qu'elle a touché**. Cela donne des règles testables sans
HTTP, un contrat d'API stable, et un différentiel précis. Les actions réservées aux
administrateurs sont listées en un seul endroit (`ACTIONS_ADMINISTRATEUR`) ; celles
qui dépendent du rôle ou de la mission visée (équipes, prêts forcés, statut, sacs,
retours) contrôlent leur droit elles-mêmes, par `services/droits.py`.

### Modèles principaux

| Domaine | Modèles |
|---|---|
| Téléphones | `PhoneModel`, `Variant`, `Cabinet`, mouvements et réservations |
| Matériel | `Material`, `MaterialReservation` (un emprunt, avec `sac_de` et `force_par`), `MaterialLog` |
| Missions | `Mission` (statut imposé, plancher `status_max`), `Equipe`, `GestionMission`, `MissionTemplate` |
| Sacs et prêts | `Dotation` (le sac), `DemandePret` |
| Comptes | `Compte` (administrateur, groupe d'appartenance ; réglages JSON ; code de récupération haché), `Groupe` (nom, matériel affecté, chef facultatif), `ActiviteCompte` |

Les noms de tables et de colonnes sont ceux de l'ancienne base : c'est ce qui permet
de reprendre ses données sans conversion.

---

## API et adresses

### API (consommée par l'interface)

| Appel | Rôle |
|---|---|
| `GET /api/state` | État complet |
| `GET /api/state?since=N` | Différence depuis la version `N` |
| `POST /api/action` | `{"action": "…", "params": {…}}` — exécute une action |
| `POST /api/reglages` | `{"reglages": {…}}` — enregistre des réglages du compte |

Chaque réponse porte aussi ce qui est **propre au compte** : ses réglages, ses
prêts et demandes, le contenu des autres sacs, la gestion des missions, l'annuaire
des comptes.

Deux codes ont un sens précis, dont l'interface se sert pour rediriger :
**401** = pas connecté ; **403** = mot de passe à renouveler. Un refus métier
renvoie **422** avec un message écrit pour être lu par une personne.

### Adresses

| Adresse | Rôle |
|---|---|
| `/` | Redirige vers un nouvel onglet (`/s-…/`) |
| `/u/<compte>/` | L'application, pour la session de ce compte |
| `/connexion/`, `/deconnexion/` | Connexion, déconnexion (POST) |
| `/mot-de-passe/` | Changer son mot de passe |
| `/mot-de-passe-oublie/` | Récupération par code |
| `/code-recuperation/` | Générer ou supprimer son code |
| `/missions/<nom>/` | Tableau de bord d'une mission |
| `/admin/` | Administration Django (comptes, corrections) |
| `/sante/` | Santé, sans session : `200` si la base répond, `503` sinon |
| `/favicon.ico` | Icône de l'onglet |

---

## Exploitation

```bash
docker compose logs -f web                        # journaux
docker compose exec web python manage.py migrate  # après une mise à jour du code
docker compose exec web python manage.py createsuperuser
docker compose down                               # arrêter, en gardant les données
docker compose down -v                            # ⚠ supprime aussi le volume
```

### Sauvegarde et restauration

```bash
docker compose exec -T base pg_dump -U heimdall heimdall > sauvegarde.sql
docker compose exec -T base psql -U heimdall -d heimdall < sauvegarde.sql
```

Les données vivent dans le volume Docker `donnees-postgres`. **Sauvegardez-les
avant toute opération risquée.**

### Reprendre les données de l'ancienne application

```bash
docker compose cp donnees.db web:/tmp/donnees.db
docker compose cp comptes.db web:/tmp/comptes.db
docker compose exec web python manage.py reprendre_heimdall /tmp/donnees.db /tmp/comptes.db
```

Les mots de passe repris restent valides : le format d'empreinte est conservé.

### Santé

`GET /sante/` interroge **réellement** la base. C'est ce qu'utilise le `HEALTHCHECK`
de l'image, et ce qui fait attendre le service `web` que la base soit prête.

---

## Dépannage

| Symptôme | Cause probable | Remède |
|---|---|---|
| « Bad Request (400) » depuis un autre poste | L'adresse du serveur n'est pas dans `DJANGO_ALLOWED_HOSTS` | L'ajouter, redémarrer |
| L'écran de connexion reboucle sans message | `DJANGO_HTTPS=1` alors que le site est en `http://` | Mettre `DJANGO_HTTPS=0` |
| Le conteneur `web` redémarre en boucle : « password authentication failed » | Le mot de passe de `.env` n'est pas celui avec lequel la base a été **initialisée** (le volume le garde) | Remettre l'ancien mot de passe dans `.env`, ou changer celui de la base avec `ALTER USER`. Ne pas supprimer le volume : c'est là que sont les données |
| « 403 — jeton CSRF incorrect » à la connexion | Une page de connexion restée ouverte depuis longtemps | Recharger la page |
| Je ne vois pas mes réglages sur un autre poste | Ils sont par **compte** : vérifiez que vous êtes connecté avec le bon | — |
| « Désassigner » est grisé | La mission n'est plus *prévue* | Utiliser « Restituer », ou faire repasser la mission à « prévue » (gestionnaire ou administrateur) |
| Je ne peux pas reculer, ni changer le statut | Seul un gestionnaire de la mission ou un administrateur le peut | Voir « Gestion et effectif » dans « Modifier » |
| Je ne peux pas créer de mission | Réservé aux chefs de groupe et aux administrateurs | Un administrateur vous place dans un groupe et vous en nomme chef (Administration → Comptes) |
| Je n'emprunte pas pour une mission | On n'emprunte pour une mission que si l'on en fait partie (équipier) | Demander à un gestionnaire de vous placer dans une équipe, ou emprunter sans mission |
| Je ne vois pas « Mon groupe » | Vous n'êtes membre d'aucun groupe (le widget « Mon groupe » est réservé aux chefs) | Un administrateur vous place dans un groupe |
| Je ne peux pas demander à une personne | Elle fait partie de l'effectif de la mission (elle emporte son sac), ou l'article n'est plus disponible dans son sac | Une ligne grisée « indisponible » est déjà sortie ou prêtée |
| L'icône de l'onglet ne change pas | Cache du navigateur | Fermer l'onglet et rouvrir, ou vider le cache du site |
| Un mot de passe oublié sans code de récupération | — | Un administrateur le réinitialise dans `/admin/` |

---

## Tests

```bash
python manage.py test stock        # nécessite une base PostgreSQL joignable (DATABASE_URL)
```

**631 tests**, qui couvrent les règles métier domaine par domaine, le contrat HTTP de
l'API et le déploiement. Ils vérifient en particulier ce qui ne se voit pas à l'œil
nu :

- **les droits et les rôles** — pour chaque ligne du tableau des rôles : qui peut créer
  une mission, emprunter pour une mission, rendre une ligne, répondre à la place d'un
  absent, forcer un prêt, composer une équipe ; la hiérarchie des chefs de groupe ;
  et qu'un client ne peut pas se déclarer administrateur ni usurper un acteur ;
- **la non-régression des statuts** — y compris quand le statut calculé aurait
  reculé (dernier emprunt rendu, date repoussée) ;
- **l'exclusivité gestionnaire / effectif**, dans les deux sens ;
- **les prêts** — disponibilité revérifiée à l'acceptation, retour au bon sac,
  confidentialité des demandes ;
- **l'isolement des onglets** — deux comptes dans un même navigateur, jeton CSRF
  propre à chaque onglet, refus d'un onglet pour le compte d'un autre ;
- **la récupération de mot de passe** — usage unique, verrou, messages identiques,
  sessions fermées ;
- **l'atomicité** — une action qui refuse n'écrit rien ;
- **la traçabilité** — l'identité d'un exemplaire est recopiée au journal ;
- **le déploiement** — `/sante/` renvoie 503 si la base est tombée ; l'amorçage du
  premier compte est idempotent.

Les tests ne suivent pas la redirection vers un onglet : le mécanisme est
désactivé par défaut pendant `manage.py test` (les tests d'onglets le réactivent).

---

## Limites connues

- **Pas de notification hors de l'application** : il n'y a pas de messagerie sur le
  réseau local. Les demandes de prêt, alertes de stock et prêts forcés se lisent
  dans le profil, pendant que la personne est connectée.
- **Un statut imposé à la main** bloque ensuite le passage automatique par la date :
  il n'existe pas encore de retour à l'automatique dans le menu.
- **Une mission sans date détient du matériel = « en cours »** dès que du matériel
  lui est affecté : on n'y désassigne donc pas. Lui donner une date future la remet
  « prévue ».
- **L'interface est un seul fichier** de plus de 5 000 lignes, sans build : simple à
  déployer, mais pénible à relire. Un découpage en modules serait la prochaine
  étape de maintenance.
- **Le glisser-déposer des widgets** du profil n'a pas de repli au clavier autre que
  les flèches haut et bas de chaque carte.
- **Les sauvegardes sont manuelles** : aucune sauvegarde planifiée n'est livrée.
