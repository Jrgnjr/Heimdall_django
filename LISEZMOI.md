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
| SQLite à côté de l'exécutable | PostgreSQL, sur le serveur |
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

### Comment l'écriture à plusieurs est rendue sûre

PostgreSQL empêche la corruption, mais pas une logique applicative qui lit
avant d'écrire. L'application Qt s'en protégeait avec un verrou en mémoire —
son commentaire décrivait le scénario : *« deux requêtes simultanées pourraient
lire la version 6 et écrire toutes les deux la version 7 »*. Un verrou en
mémoire ne suffit plus ici : gunicorn tourne avec plusieurs workers, dans des
processus distincts.

La sérialisation est donc passée dans la base. Toute action d'écriture commence
par prendre un **verrou de ligne sur le compteur de version**
(`stock.api._verrou_ecriture`) : deux actions ne s'exécutent jamais en
parallèle, et toutes les courses du même genre disparaissent par la même
occasion — la quantité lue puis réécrite, l'attribution du prochain
identifiant, le suffixage d'une clé d'article. Aucune n'a besoin de son propre
verrou.

Les **lectures ne prennent aucun verrou** : `/api/state`, que chaque navigateur
appelle toutes les 2,5 secondes, n'est pas ralenti.

Mesuré avant ce verrou, dix emprunts simultanés de deux unités sur un stock de
dix donnaient quatre acceptations, aucun refus, et **six erreurs 500**.
`stock/tests/test_concurrence.py` verrouille ce comportement : dix requêtes
lancées au même instant doivent toutes trancher — abouti ou refusé — sans
qu'aucune erreur serveur, aucun trou dans la suite des versions ni aucune
survente n'apparaisse.

```
manage.py test stock.tests.test_concurrence
```

---

## Une seule base : PostgreSQL

`DATABASE_URL` est **obligatoire** — le projet refuse de démarrer sans, avec un
message qui dit quoi faire.

SQLite a servi de repli pendant le portage, et a été retiré. Le garder
signifiait deux bases aux contenus différents sur le même poste — la version
Docker et la version locale divergeaient sans que rien ne le signale — et cette
confusion coûtait plus que la commodité de développer sans serveur. Les tests
de concurrence, en particulier, ne veulent rien dire sur SQLite : il ne sait
pas écrire à plusieurs.

**Avec Docker**, rien à faire : `docker-compose.yml` fabrique la `DATABASE_URL`
du conteneur vers `base:5432`. Voir « Déployer avec Docker » ci-dessous.

**Hors conteneur** — pour les tests, `runserver`, ou `psql` —, la base de
Compose est exposée sur `127.0.0.1` :

```
docker compose up -d base
```

puis, `DATABASE_URL` étant renseignée dans `.env` :

```
python -m venv %USERPROFILE%\venvs\heimdall-django
%USERPROFILE%\venvs\heimdall-django\Scripts\python.exe -m pip install -r requirements.txt
%USERPROFILE%\venvs\heimdall-django\Scripts\python.exe manage.py migrate
%USERPROFILE%\venvs\heimdall-django\Scripts\python.exe manage.py runserver
```

Puis `http://127.0.0.1:8000/`.

> Mettez l'environnement virtuel **hors du projet** si celui-ci est dans un
> dossier synchronisé : les milliers de fichiers d'un venv ralentissent OneDrive
> sans aucun bénéfice.
>
> Sur un serveur où personne ne développe, retirez la section `ports:` du
> service `base` : l'application passe par le réseau interne de Compose.

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

## Déployer avec Docker

C'est la voie la plus courte : deux conteneurs, l'application et sa base.

```
cp .env.exemple .env           # puis renseigner les trois variables obligatoires
docker compose up -d --build
docker compose logs -f web     # le mot de passe du premier compte s'y affiche
```

Puis `http://localhost:8750/`.

Trois variables sont obligatoires, et la composition **refuse de démarrer** sans
elles plutôt que d'inventer des valeurs :

| Variable | Pourquoi |
|---|---|
| `DJANGO_SECRET_KEY` | Une clé qui change à chaque redémarrage invaliderait toutes les sessions |
| `POSTGRES_PASSWORD` | Le mot de passe de la base |
| `DJANGO_ALLOWED_HOSTS` | Les noms d'hôte sous lesquels le site répond |

Générer la clé :

```
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### Ce que fait le démarrage

Le point d'entrée du conteneur attend que PostgreSQL accepte les connexions,
applique les migrations, puis crée un compte administrateur **s'il n'en existe
aucun** — mot de passe tiré au hasard, affiché une seule fois dans les journaux,
à remplacer à la première connexion. C'est le comportement de l'application Qt
au premier lancement.

Pour choisir ce mot de passe vous-même, renseignez `HEIMDALL_ADMIN_MOTDEPASSE` :
il n'est alors pas imposé à changer, puisqu'il ne transite par aucun journal.

L'opération est idempotente, et c'est voulu : elle est rejouée à chaque
démarrage sans avoir à se demander si c'est le premier.

> Si une migration échoue, le conteneur s'arrête au lieu de démarrer quand même.
> Servir une application dont le schéma ne correspond pas au code ferait
> apparaître l'erreur au premier clic de quelqu'un, et pas dans les journaux de
> déploiement.

### Ce qu'il n'y a pas, et pourquoi

**Pas de nginx.** WhiteNoise sert les fichiers statiques depuis le processus
Django : pour un dossier de CSS et d'images, un conteneur de plus et un fichier
de configuration à maintenir ne se justifient pas. En production il compresse et
versionne chaque fichier, donc un cache long sans risque de servir une ancienne
version après un déploiement.

**Pas de TLS dans le conteneur.** Mettez-le derrière votre reverse proxy
habituel, et activez alors `DJANGO_DERRIERE_PROXY=1` : sans cela Django croit la
requête en clair et génère des redirections en `http`.

**La base n'est pas exposée.** Aucun `ports:` sur le service `base` — elle est
joignable depuis le réseau interne de Compose, sous le nom `base`, et de nulle
part ailleurs. Ajoutez `ports: ["5432:5432"]` seulement pour l'inspecter.

### Exploitation

```
docker compose logs -f web                       # journaux
docker compose exec web python manage.py migrate # après une mise à jour du code
docker compose exec web python manage.py createsuperuser
docker compose down                              # arrêter, en gardant les données
docker compose down -v                           # ⚠ supprime aussi le volume
```

Sauvegarde et restauration de la base :

```
docker compose exec -T base pg_dump -U heimdall heimdall > sauvegarde.sql
docker compose exec -T base psql -U heimdall -d heimdall < sauvegarde.sql
```

Reprendre les bases de l'application Qt dans le conteneur :

```
docker compose cp ../Heimdall/Heimdall/donnees.db web:/tmp/donnees.db
docker compose cp ../Heimdall/Heimdall/comptes.db web:/tmp/comptes.db
docker compose exec web python manage.py reprendre_heimdall /tmp/donnees.db /tmp/comptes.db
```

### Santé

`GET /sante/` répond `200 {"ok": true}`, sans session — c'est Docker et les
répartiteurs de charge qui l'interrogent, et ils n'ont pas de compte. La base est
**réellement** interrogée : un processus Django qui répond alors que PostgreSQL
est tombé serait déclaré sain à tort et continuerait de recevoir du trafic. Dans
ce cas il renvoie `503`.

C'est ce que le `HEALTHCHECK` de l'image utilise, et ce qui fait attendre le
service `web` que la base soit prête.

---

## Équipes

Une mission se divise souvent en groupes qui partent chacun de leur côté.
Sans équipes, son matériel est un tas unique et personne ne sait qui emporte
quoi.

Une équipe appartient à sa mission : son nom n'est unique qu'à l'intérieur de
celle-ci, et deux missions peuvent chacune avoir leur « Équipe A ». Créer,
renommer, supprimer une équipe et composer ses membres sont réservés aux
administrateurs — c'est de l'organisation. **Répartir le matériel, non** :
c'est du travail courant, ouvert à tous comme emprunter.

### Deux choses de nature différente

- **Les membres** sont un état courant. Composer l'équipe, c'est dire qui en
  fait partie aujourd'hui ; rien n'est conservé de la composition d'avant, et
  un compte supprimé quitte ses équipes de lui-même.
- **Le matériel** est un historique. Chaque ligne d'emprunt garde le nom de
  l'équipe à qui elle était attribuée, y compris après son retour et y compris
  si l'équipe est supprimée — le journal doit continuer à dire ce qui est parti
  avec qui. C'est pourquoi `equipe` est une chaîne sur l'emprunt, et non une
  relation.

### Répartir

Deux voies, et la seconde compte autant que la première :

- **à l'emprunt** : les modales d'emprunt — à l'unité, en panier, ou une
  malette entière — proposent l'équipe dès qu'une mission en a. Sans équipe
  choisie, le matériel arrive au niveau de la mission ;
- **après coup** : chaque ligne de la carte de mission porte un sélecteur qui
  la déplace d'une équipe à l'autre, ou la remet au niveau de la mission. C'est
  l'ordre dans lequel on travaille réellement — on rassemble le matériel de la
  mission, puis on le divise. Sans cela, corriger une répartition demanderait
  de rendre et ressortir, ce qui laisserait deux lignes de journal pour rien.

Un déplacement laisse une ligne `AJUST.` au journal, qui dit d'où vers où.

### Restituer

« Restituer tout » rend la mission entière. Chaque équipe a son propre bouton
« Restituer », qui ne rend que le sien. Les consommables se déclarent utilisés
dans les deux cas, de la même façon.

### Ce qui est refusé

- Supprimer une équipe qui **détient encore** du matériel : rendez-le ou
  déplacez-le d'abord. Sinon du matériel se retrouverait attribué à une équipe
  qui n'existe plus, et l'écran ne saurait plus où le ranger. Ce qui est déjà
  rendu, en revanche, ne bloque rien — son nom appartient à l'historique.
- Choisir une équipe sans mission : une équipe n'a de sens que dans une
  mission.
- Changer l'équipe d'une ligne **déjà rendue** : elle appartient à
  l'historique.

---

## Vérifier que le déploiement fonctionne

Six contrôles, du moins coûteux au plus complet. Les trois premiers ne
demandent pas Docker.

### 1. Les règles métier et le contrat d'API

```
manage.py test
```

151 tests. C'est ce qui attrape une règle cassée, un champ renommé que
l'interface attendait, ou un code de retour changé.

### 2. Les réglages de production

```
DJANGO_DEBUG=0 DJANGO_SECRET_KEY=x DJANGO_ALLOWED_HOSTS=exemple.fr \
  manage.py check --deploy
```

Ne doit signaler que `security.W021` — l'inscription à la liste de préchargement
HSTS, volontairement laissée au choix.

### 3. La composition Docker, sans rien construire

```
docker compose config
```

Affiche la composition interpolée. Vérifiez que `DATABASE_URL` pointe bien sur
`base:5432`. Sans `.env` renseigné, la commande doit **échouer** en nommant la
variable manquante — c'est le garde-fou, pas une panne.

### 4. L'image se construit

```
docker compose build
```

### 5. La pile démarre et se déclare saine

```
docker compose up -d
docker compose ps
```

Le service `web` doit passer à `healthy` en moins d'une minute. S'il reste
`starting` puis devient `unhealthy`, regardez `docker compose logs web` :

| Ce que disent les journaux | Ce que ça veut dire |
|---|---|
| `la base n'a pas répondu en 60s` | PostgreSQL n'a pas démarré — voir `docker compose logs base` |
| `/bin/sh^M: no such file or directory` | `entrypoint.sh` est en CRLF ; voir `.gitattributes` |
| `DJANGO_SECRET_KEY est obligatoire` | `.env` absent ou incomplet |
| `Invalid HTTP_HOST header` | Ajoutez le nom d'hôte à `DJANGO_ALLOWED_HOSTS` |
| une erreur de migration | Le schéma et le code divergent ; le conteneur s'arrête exprès |

### 6. Le parcours complet, de bout en bout

Le mot de passe du premier compte n'est affiché **qu'une fois** :

```
docker compose logs web | grep "Mot de passe provisoire"
```

Puis, dans l'ordre :

```
curl -i http://localhost:8750/sante/          # 200 {"ok": true}
curl -i http://localhost:8750/                # 302 vers /connexion/
curl -i http://localhost:8750/api/state       # 401 : pas de session
```

Ces trois réponses sont le cœur du contrat : `/` protégée, `401` distinct du
`403` du mot de passe à changer, et la santé accessible sans compte.

Ensuite ouvrez `http://localhost:8750/` dans un navigateur, connectez-vous avec
`Admin` et le mot de passe relevé, remplacez-le, et vérifiez que le stock
s'affiche. C'est le seul contrôle qui éprouve l'interface elle-même.

Pour éprouver la résistance à une base tombée :

```
docker compose stop base
curl -i http://localhost:8750/sante/          # 503 : il ne se déclare pas sain
docker compose start base
```

### Repartir de zéro

```
docker compose down -v      # ⚠ supprime le volume, donc les données
```

### Un piège évité

`docker/entrypoint.sh` doit rester en **LF**. Ce poste a `core.autocrlf=true` :
sans les règles de `.gitattributes`, un clone sous Windows le convertirait en
CRLF, et le conteneur échouerait sur `/bin/sh^M: no such file or directory` — un
message qui ne dit pas du tout ce qui se passe.

---

## Mettre en service sans Docker

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
Dockerfile             image en deux étapes, service sous un compte sans privilèges
docker-compose.yml     l'application et PostgreSQL
docker/entrypoint.sh   attente de la base, migrations, premier compte
.dockerignore          ce qui n'a rien à faire dans l'image
.env.exemple           les variables, avec et sans Docker
.gitattributes         verrouille l'entrypoint en LF
config/
  settings.py          réglages, tout depuis l'environnement
  urls.py              /admin/, les comptes à la racine, le stock
comptes/
  models.py            Compte (AUTH_USER_MODEL), ActiviteCompte
  hashers.py           scrypt au format de Heimdall
  views.py             connexion, renouvellement imposé, déconnexion
  management/commands/
    amorcer_admin.py   le premier administrateur, idempotent
stock/
  models.py            les 17 modèles, aux noms de tables d'origine
  placement.py         attribution des casiers (repris tel quel)
  etat.py              modèles -> JSON de l'interface, complet ou différentiel
  api.py               /api/state et /api/action
  views.py             la page, et /sante/
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
  tests/               214 tests
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

214 tests : les règles métier domaine par domaine, le contrat HTTP de l'API, et
ce dont le déploiement conteneurisé dépend. Ils couvrent en particulier ce qui ne
se voit pas à l'œil nu :

- **l'atomicité** — un emprunt groupé, un lot d'exemplaires sériés ou une
  mission servie par un template n'écrivent rien s'ils refusent ;
- **le cumul de la demande** — un article réclamé par une malette *et* à
  l'unité ne doit pas passer deux fois le même contrôle de stock ;
- **la consommation** — ce qui est déclaré utilisé quitte le stock, le reste
  rentre, et le journal porte deux lignes plutôt qu'une ;
- **la traçabilité** — `identite` est recopiée au moment du mouvement, si bien
  que réétiqueter un exemplaire plus tard ne réécrit pas l'histoire ;
- **les mots de passe repris** — une empreinte au format de l'application Qt
  reste valide ;
- **le déploiement** — `/sante/` renvoie 503 quand la base est tombée au lieu de
  se déclarer sain, et l'amorçage du premier compte est idempotent, ne promeut
  pas en silence un compte existant, et n'ouvre pas `/admin/` par effet de bord.

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
