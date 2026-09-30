# -*- coding: utf-8 -*-
"""Réglages de Heimdall-Django.

Tout ce qui dépend du poste ou du déploiement se lit dans l'environnement, et
rien d'autre. Un réglage en dur qu'il faut éditer avant chaque mise en service
finit toujours par être committé avec la valeur de quelqu'un d'autre.

Deux bases possibles, et le choix se fait à l'exécution :

- `DATABASE_URL` absente : SQLite dans le dossier du projet. C'est le mode de
  développement, et il suffit à une personne seule ;
- `DATABASE_URL` renseignée : PostgreSQL. C'est ce que demande un vrai
  serveur — plusieurs personnes qui écrivent en même temps, ce que SQLite ne
  sait pas faire sans risquer la base.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

RACINE = Path(__file__).resolve().parent.parent


def _drapeau(nom, defaut=False):
    brut = os.environ.get(nom)
    if brut is None:
        return defaut
    return brut.strip().lower() in ("1", "true", "oui", "yes", "on")


def _liste(nom, defaut=()):
    brut = os.environ.get(nom, "")
    valeurs = [x.strip() for x in brut.split(",") if x.strip()]
    return valeurs or list(defaut)


# --------------------------------------------------------------------------
# Sécurité
# --------------------------------------------------------------------------

# En développement, une clé est tirée au démarrage : les sessions ne survivent
# pas à un redémarrage, ce qui est sans importance. En production, l'absence de
# `DJANGO_SECRET_KEY` doit être une erreur bruyante, pas un défaut silencieux
# qui invaliderait toutes les sessions à chaque déploiement.
DEBUG = _drapeau("DJANGO_DEBUG", defaut=True)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError(
            "DJANGO_SECRET_KEY est obligatoire hors développement : sans elle, "
            "les sessions et les jetons CSRF seraient invalidés à chaque "
            "redémarrage."
        )
    from django.core.management.utils import get_random_secret_key
    SECRET_KEY = get_random_secret_key()

ALLOWED_HOSTS = _liste("DJANGO_ALLOWED_HOSTS",
                       defaut=["localhost", "127.0.0.1", "[::1]"] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = _liste("DJANGO_CSRF_TRUSTED_ORIGINS")

# Derrière un reverse proxy qui termine TLS, Django doit apprendre de lui que
# la requête d'origine était en HTTPS, sinon il génère des redirections en
# clair et refuse les cookies sécurisés.
if _drapeau("DJANGO_DERRIERE_PROXY"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# Le site est-il servi en HTTPS ? C'est une question distincte de DEBUG, et les
# confondre coûte cher.
#
# Un cookie marqué `Secure` n'est pas envoyé par le navigateur sur une
# connexion en clair. En le déduisant de `not DEBUG`, un déploiement sur le
# réseau local — `http://192.168.1.50:8750` — devenait **inutilisable** :
# l'écran de connexion rebouclait sans message, parce que le cookie CSRF
# n'arrivait jamais. Le piège était invisible en essai local, les navigateurs
# traitant `http://localhost` comme un contexte sécurisé et envoyant les
# cookies `Secure` quand même.
#
# Le défaut reste sûr — HTTPS supposé hors développement — mais un déploiement
# en clair peut désormais le dire, et ce sera un choix conscient.
HTTPS = _drapeau("DJANGO_HTTPS", defaut=not DEBUG)

if not DEBUG:
    SESSION_COOKIE_SECURE = HTTPS
    CSRF_COOKIE_SECURE = HTTPS
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

    # La redirection suit HTTPS par défaut, mais reste débranchable : derrière
    # un proxy qui redirige déjà, la refaire ici est du travail en double.
    SECURE_SSL_REDIRECT = _drapeau("DJANGO_FORCE_HTTPS", defaut=HTTPS)

    # HSTS n'est jamais activé d'office : il est difficile à annuler, les
    # navigateurs s'en souviennent pendant toute la durée annoncée.
    SECURE_HSTS_SECONDS = (int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
                           if HTTPS else 0)
    if SECURE_HSTS_SECONDS:
        SECURE_HSTS_INCLUDE_SUBDOMAINS = _drapeau(
            "DJANGO_HSTS_SOUS_DOMAINES", defaut=True)
        SECURE_HSTS_PRELOAD = _drapeau("DJANGO_HSTS_PRELOAD")

# L'interface lit le jeton dans le cookie et le renvoie en en-tête : il ne doit
# donc pas être HttpOnly. C'est le fonctionnement normal du CSRF côté client de
# Django, et le jeton seul ne vaut rien sans la session.
CSRF_COOKIE_HTTPONLY = False


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "comptes",
    "stock",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise sert les fichiers statiques depuis le conteneur, ce qui évite
    # d'avoir à poser un nginx devant pour un seul dossier de CSS et d'images.
    # Il vient juste après SecurityMiddleware, comme sa documentation l'exige :
    # avant, il court-circuiterait les redirections HTTPS.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [RACINE / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ],
    },
}]


# --------------------------------------------------------------------------
# Base de données
#
# PostgreSQL, et lui seul. SQLite a servi de repli pendant le portage ; l'avoir
# gardé signifiait deux bases aux contenus différents sur le même poste, et la
# confusion que ça produit coûte plus que la commodité de développer sans
# serveur. Les tests de concurrence, en particulier, ne veulent rien dire sur
# SQLite : il ne sait pas écrire à plusieurs.
# --------------------------------------------------------------------------

def _base_depuis_url(url):
    """Traduit une URL `postgres://…` en réglage Django.

    Écrit à la main plutôt que d'ajouter `dj-database-url` : c'est vingt
    lignes, et une dépendance de moins à suivre.
    """
    morceau = urlparse(url)
    if morceau.scheme not in ("postgres", "postgresql", "psql"):
        raise RuntimeError(
            "DATABASE_URL doit désigner PostgreSQL (postgres://…), reçu : %r"
            % (morceau.scheme or url[:40])
        )
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(morceau.path.lstrip("/")),
        "USER": unquote(morceau.username or ""),
        "PASSWORD": unquote(morceau.password or ""),
        "HOST": morceau.hostname or "",
        "PORT": str(morceau.port or ""),
        "CONN_MAX_AGE": int(os.environ.get("DJANGO_CONN_MAX_AGE", "60")),
        "OPTIONS": {"connect_timeout": 10},
    }


_url = os.environ.get("DATABASE_URL", "").strip()
if not _url:
    raise RuntimeError(
        "DATABASE_URL est obligatoire. Exemple :\n"
        "  DATABASE_URL=postgres://heimdall:motdepasse@127.0.0.1:5432/heimdall\n"
        "Avec Docker, docker-compose.yml la fabrique lui-même : lancez\n"
        "  docker compose exec web python manage.py …\n"
        "Pour travailler hors conteneur, démarrez la base et pointez dessus :\n"
        "  docker compose up -d base"
    )
DATABASES = {"default": _base_depuis_url(_url)}


# --------------------------------------------------------------------------
# Comptes
# --------------------------------------------------------------------------

AUTH_USER_MODEL = "comptes.Compte"

# Le hasher maison est en tête : c'est lui qui écrit.
#
# `ScryptPasswordHasher` de Django est **volontairement absent**, et ce n'est pas
# un oubli. Il déclare le même nom d'algorithme — « scrypt » — que le nôtre, et
# Django résout une empreinte par ce nom seul : les deux inscrits, c'est le
# dernier qui gagne la résolution, et les empreintes reprises de l'application Qt
# lui seraient présentées dans un encodage qu'il ne sait pas lire.
#
# Comme aucune empreinte n'a jamais été écrite dans le format de Django ici, le
# retirer ne perd rien. Le laisser, en revanche, empêcherait toute connexion
# avec un mot de passe repris.
PASSWORD_HASHERS = [
    "comptes.hashers.ScryptHeimdall",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "connexion"
LOGIN_REDIRECT_URL = "accueil"
LOGOUT_REDIRECT_URL = "connexion"
SESSION_COOKIE_AGE = int(os.environ.get("DJANGO_SESSION_AGE", str(12 * 3600)))
SESSION_SAVE_EVERY_REQUEST = True


# --------------------------------------------------------------------------
# Localisation et fichiers
# --------------------------------------------------------------------------

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Europe/Paris")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [RACINE / "static"]
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", RACINE / "staticfiles"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # En production, WhiteNoise compresse et versionne : chaque fichier
        # reçoit un nom dérivé de son contenu, donc un cache long sans risque de
        # servir une ancienne version après un déploiement.
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG else
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"],
             "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}
