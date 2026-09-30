#!/bin/sh
# -----------------------------------------------------------------------------
# Ce qui doit être vrai avant que gunicorn accepte la première requête.
#
# `set -e` : si une migration échoue, le conteneur doit s'arrêter bruyamment.
# Démarrer quand même servirait une application dont le schéma ne correspond pas
# au code, et l'erreur n'apparaîtrait qu'au premier clic de quelqu'un.
# -----------------------------------------------------------------------------
set -e

echo "[heimdall] attente de la base de données…"

# PostgreSQL met quelques secondes à accepter les connexions, et `depends_on`
# de Compose ne garantit que le démarrage du conteneur, pas que le service
# écoute. On interroge donc Django lui-même, qui sait quelle base il visera.
attente=0
until python - <<'PY'
import sys
import django
django.setup()
from django.db import connection
try:
    connection.ensure_connection()
except Exception as souci:
    print("  pas encore : %s" % str(souci).strip().splitlines()[0][:120])
    sys.exit(1)
PY
do
    attente=$((attente + 2))
    if [ "$attente" -ge "${HEIMDALL_ATTENTE_BASE:-60}" ]; then
        echo "[heimdall] la base n'a pas répondu en ${attente}s — abandon." >&2
        exit 1
    fi
    sleep 2
done

echo "[heimdall] migrations…"
python manage.py migrate --noinput

# Idempotent : ne fait rien si un administrateur existe. C'est ce qui permet de
# l'appeler à chaque démarrage sans se demander si c'est le premier.
if [ "${HEIMDALL_AMORCER_ADMIN:-1}" = "1" ]; then
    echo "[heimdall] compte administrateur…"
    if [ -n "${HEIMDALL_ADMIN_MOTDEPASSE:-}" ]; then
        python manage.py amorcer_admin \
            --identifiant "${HEIMDALL_ADMIN_IDENTIFIANT:-Admin}" \
            --mot-de-passe "${HEIMDALL_ADMIN_MOTDEPASSE}"
    else
        python manage.py amorcer_admin \
            --identifiant "${HEIMDALL_ADMIN_IDENTIFIANT:-Admin}"
    fi
fi

echo "[heimdall] prêt."

# `exec` : gunicorn remplace ce script et devient le PID 1, si bien qu'il reçoit
# directement le SIGTERM de `docker stop` et peut terminer ses requêtes en cours.
# Sans lui, le shell garderait le PID 1 et le signal n'arriverait jamais.
exec "$@"
