import logging

from django.db import connection

log = logging.getLogger(__name__)

LIVENESS_PATH = "/healthz"  # must match HealthCheckPath in the infra repo's application.yaml


def liveness():
    # Deliberately shallow: a database failover must not make the ALB drain every task.
    return {"status": "ok"}, 200


def readiness():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        log.exception("readiness check failed")
        return {"status": "unavailable", "database": "unreachable"}, 503
    return {"status": "ok", "database": "ok"}, 200
