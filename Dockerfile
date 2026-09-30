# syntax=docker/dockerfile:1
# -----------------------------------------------------------------------------
# Heimdall-Django
#
# Deux étapes, et le partage est celui-ci : la première installe les
# dépendances, la seconde n'emporte que le résultat. Les outils de compilation
# de psycopg restent donc dans l'étape jetée, et l'image finale ne contient pas
# de compilateur — c'est moins à télécharger et moins de surface exposée.
# -----------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12-slim


# --- étape 1 : les dépendances ------------------------------------------------
FROM python:${PYTHON_VERSION} AS dependances

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Installé dans un environnement virtuel plutôt qu'en global : le copier dans
# l'étape suivante devient un seul dossier à déplacer.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Seul `requirements.txt` est copié à ce stade : la couche d'installation reste
# en cache tant que les dépendances ne changent pas, même quand le code change.
COPY requirements.txt ./
RUN pip install --requirement requirements.txt


# --- étape 2 : l'image de service --------------------------------------------
FROM python:${PYTHON_VERSION} AS service

# PYTHONUNBUFFERED : sans lui, les journaux restent bloqués dans le tampon et
# `docker logs` ne montre rien pendant les premières secondes — y compris le mot
# de passe provisoire du premier démarrage.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings

# libpq5 seul : c'est la bibliothèque dont psycopg a besoin à l'exécution.
# `curl` sert au healthcheck. Les listes d'APT sont effacées dans la même
# couche, sinon elles y resteraient malgré la suppression.
RUN apt-get update \
 && apt-get install --yes --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

# Un compte sans privilèges. Créé avant la copie pour que `--chown` fonctionne.
RUN groupadd --system heimdall \
 && useradd --system --gid heimdall --create-home --home-dir /home/heimdall heimdall

WORKDIR /app

COPY --from=dependances /opt/venv /opt/venv
COPY --chown=heimdall:heimdall . .

RUN chmod +x /app/docker/entrypoint.sh

# Les fichiers statiques sont collectés à la construction, pas au démarrage :
# c'est du travail identique à chaque lancement, et le faire ici permet de
# démarrer plusieurs conteneurs sans qu'ils se marchent dessus.
#
# Les trois variables sont des valeurs **de construction**, jamais celles du
# service : `collectstatic` exige que les réglages se chargent, et ceux-ci
# refusent de se charger sans clé secrète ni `DATABASE_URL`. Aucune ne subsiste
# dans l'image — seul le dossier `staticfiles/` en sort.
#
# `DATABASE_URL` pointe volontairement dans le vide : `collectstatic` ne touche
# pas à la base, il lui suffit que le réglage soit lisible. La base réelle
# arrive par l'environnement au démarrage.
RUN DJANGO_SECRET_KEY=construction-uniquement \
    DJANGO_DEBUG=0 \
    DATABASE_URL=postgres://construction@127.0.0.1:5432/construction \
    python manage.py collectstatic --noinput --clear \
 && chown -R heimdall:heimdall /app/staticfiles

USER heimdall

EXPOSE 8000

# `sante/` interroge réellement la base : un processus qui répond alors que
# PostgreSQL est tombé ne doit pas être déclaré sain.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl --fail --silent --output /dev/null http://127.0.0.1:8000/sante/

ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Deux workers et deux fils : de quoi servir une équipe sans réserver de la
# mémoire pour rien. `--access-logfile -` envoie les accès sur la sortie
# standard, là où Docker les collecte.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--threads", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
