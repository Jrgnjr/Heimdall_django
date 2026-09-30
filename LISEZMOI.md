# Heimdall-Django

Gestion de stock, en application Django avec serveur. Reprise de Heimdall —
l'application Qt autonome — remise sur un vrai serveur, pour que plusieurs
personnes puissent travailler en même temps.

L'interface est la même : `templates/stock/index.html` est le fichier de
Heimdall, à deux retouches près (le logo passe par `staticfiles`). Les 39
actions métier, leurs contrôles et **leurs messages de refus au mot près** sont
conservés.

---

## Ce que ça change par rapport à Heimdall

| Heimdall (Qt) | Heimdall-Django |
|---|---|
| Un exécutable à double-cliquer | Un serveur, et un navigateur |
| **Un seul poste à la fois** | Plusieurs personnes en même temps |
| SQLite à côté de l'exécutable | PostgreSQL en production, SQLite en dev |
| Règles métier en SQL écrit à la main | Modèles Django et ORM |
| Comptes maison, base séparée | `AUTH_USER_MODEL` et sessions Django |
| Comptes = attribution seulement | Les droits empêchent réellement |
| Aucun écran d'administration | `/admin/` sur tous les modèles |

Le point important est le troisième et le sixième. Dans Heimdall, la base était
un fichier sur le poste de l'utilisateur : les comptes servaient à savoir qui
avait fait quoi, pas à empêcher quoi que ce soit — c'était écrit dans son
LISEZMOI. Ici la base est sur le serveur, hors de portée : le refus opposé à un
non-administrateur a du poids.

Et la garde « un seul poste à la fois, sinon la base peut se corrompre sans
message d'erreur » disparaît avec PostgreSQL. C'était la vraie limite de la
version autonome.

---

## Démarrer

```
python -m venv %USERPROFILE%\venvs\heimdall-django
%USERPROFILE%\venvs\heimdall-django\Scripts\python.exe -m pip install -r requirements.txt
%USERPROFILE%\venvs\heimdall-django\Scripts\python.exe manage.py migrate
%USERPROFILE%\venvs\heimdall-django\Scripts\python.exe manage.py createsuperuser
%USERPROFILE%\venvs\heimdall-django\Scripts\python.exe manage.py runserver
```

Puis `http://127.0.0.1:8000/`.

Sans configuration, le projet démarre sur SQLite en mode `DEBUG` : c'est le
mode de développement. Mettez l'environnement virtuel **hors du projet** si
celui-ci est dans un dossier synchronisé — les milliers de fichiers d'un venv
ralentissent OneDrive sans aucun bénéfice.

### Reprendre les données de Heimdall

```
manage.py reprendre_heimdall ..\Heimdall\Heimdall\donnees.db ..\Heimdall\Heimdall\comptes.db
```

Les tables portent les mêmes noms et les mêmes colonnes : il n'y a rien à
convertir, seulement à recopier — y compris vers PostgreSQL, où un fichier
SQLite ne pourrait pas être ouvert directement. Les bases d'origine sont
ouvertes en lecture seule et ne sont jamais modifiées.

**Les mots de passe sont repris.** Heimdall hachait déjà en scrypt, et
`comptes.hashers.ScryptHeimdall` lit son encodage : personne n'a à changer de
mot de passe. C'est l'inverse du trajet Django → Heimdall, où la conversion
était impossible.

> `--vider` efface les données Django existantes avant de reprendre. Sans cette
> option, la commande refuse d'écrire dans une base déjà peuplée.

---

## Mettre en service

Renseignez l'environnement — voir `.env.exemple` :

```ini
DJANGO_SECRET_KEY=...          # obligatoire : le projet refuse de démarrer sans
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=stock.exemple.fr
DJANGO_CSRF_TRUSTED_ORIGINS=https://stock.exemple.fr
DATABASE_URL=postgres://heimdall:...@127.0.0.1:5432/heimdall
DJANGO_DERRIERE_PROXY=1        # si un reverse proxy termine TLS
```

```
manage.py migrate
manage.py collectstatic --noinput
```

Puis un serveur WSGI. Sous Windows, gunicorn ne fonctionne pas — `waitress` est
dans `requirements.txt` pour cette raison :

```
waitress-serve --listen=127.0.0.1:8750 config.wsgi:application
```

`DJANGO_SECRET_KEY` absente hors `DEBUG` lève une erreur au démarrage, plutôt
que de tirer une clé au hasard : une clé qui change à chaque redémarrage
invaliderait toutes les sessions et tous les jetons CSRF sans rien dire.

---

## Organisation du code

```
manage.py
config/
  settings.py          réglages, tout depuis l'environnement
  urls.py              /admin/, les comptes à la racine, le stock
comptes/
  models.py            Compte (AUTH_USER_MODEL), ActiviteCompte
  hashers.py           scrypt au format de Heimdall
  views.py             connexion, renouvellement imposé, déconnexion
stock/
  models.py            les 17 modèles, aux noms de tables d'origine
  placement.py         attribution des casiers (repris tel quel)
  etat.py              modèles -> JSON de l'interface, complet ou différentiel
  api.py               /api/state et /api/action
  views.py             la page
  admin.py             administration Django
  services/            les 39 actions métier
    __init__.py        registre, liste des actions réservées, executer()
    champs.py          validation des paramètres, messages de refus
    journaux.py        écriture dans les deux journaux
    emplacements.py    où se trouve une référence
    telephones.py      armoires.py  materiel.py  packs.py
    missions.py        templates.py
  management/commands/
    reprendre_heimdall.py
  tests/               138 tests
templates/stock/index.html   l'interface de Heimdall
static/stock/
```

### Pourquoi une couche `services` et pas des méthodes de modèle

Une action n'est pas une opération sur un objet : « emprunter un pack pour une
mission » touche le pack, plusieurs articles, les emprunts et deux journaux, et
doit refuser proprement au milieu. Mise sur un modèle, elle appartiendrait
arbitrairement à l'un des cinq.

Le registre sert aussi de contrat avec l'interface : celle-ci envoie un nom
d'action, et `ACTIONS_ADMINISTRATEUR` dit lesquelles sont refusées à un compte
ordinaire. **Cette liste est côté serveur, et pas dans l'interface** : cacher un
bouton n'empêche rien.

### Pourquoi l'API reste un couple state/action

L'interface est du JavaScript qui interroge le serveur toutes les 2,5 secondes.
Elle demande « qu'est-ce qui a changé depuis la version N » et reçoit une
différence, pas l'état entier : une dizaine de kilo-octets toutes les 2,5
secondes pour n'apprendre, presque toujours, que rien n'a bougé, ne passerait
pas à plusieurs.

C'est `stock_operation` qui rend ce différentiel possible : chaque action y
inscrit ce qu'elle a touché. Une session trop en retard — ou un changement fait
dans `/admin/`, qui ne passe pas par les actions — reçoit l'état complet.

### Deux codes de retour qui sont un contrat

L'interface se redirige elle-même : **401** veut dire « pas connecté »,
**403** veut dire « mot de passe à renouveler ». Les confondre enverrait
l'utilisateur sur le mauvais écran. `stock/tests/test_api.py` les verrouille.

### Ce que `/admin/` permet, et ce qu'il contourne

L'administration Django écrit directement dans les tables : elle ne passe ni
par les contrôles métier, ni par l'incrément de version. Une correction faite
là n'apparaîtra dans les navigateurs ouverts qu'à leur prochain rechargement
complet. C'est utile pour réparer, dangereux pour travailler — d'où
`is_staff`, distinct de `administrateur`.

---

## Tests

```
manage.py test
```

138 tests : les règles métier domaine par domaine, et le contrat HTTP de l'API.
Ils couvrent en particulier ce qui ne se voit pas à l'œil nu :

- **l'atomicité** — un emprunt groupé, un lot d'exemplaires sériés ou une
  mission servie par un template n'écrivent rien s'ils refusent ;
- **le cumul de la demande** — un article réclamé par une malette *et* à
  l'unité ne doit pas passer deux fois le même contrôle de stock ;
- **la consommation** — ce qui est déclaré utilisé quitte le stock, le reste
  rentre, et le journal porte deux lignes plutôt qu'une ;
- **la traçabilité** — `identite` est recopiée au moment du mouvement, si bien
  que réétiqueter un exemplaire plus tard ne réécrit pas l'histoire ;
- **les mots de passe repris** — une empreinte au format de l'application Qt
  reste valide.

---

## Ce qui n'a pas été porté

- **La fenêtre Qt** (`heimdall.py`, `interface/`) et la compilation en
  exécutable. Un serveur et un navigateur les remplacent ; les garder
  supposerait de maintenir deux façons d'afficher la même chose.
- **Les dialogues Qt de gestion des comptes** (`interface/dialogues.py`) :
  créer, renommer, désactiver un compte passe désormais par `/admin/`, qui fait
  la même chose et davantage.

  L'onglet « Comptes » de l'administration du stock, lui, **fonctionne** : il
  n'a jamais rien demandé de plus au serveur que la liste des identifiants et
  l'état courant, et il continue d'afficher qui détient quoi.
- **L'historique des opérations** n'est pas repris par
  `reprendre_heimdall` : il ne sert qu'à répondre en différentiel aux sessions
  ouvertes, et il n'y en a aucune sur une base qu'on vient de reprendre.
