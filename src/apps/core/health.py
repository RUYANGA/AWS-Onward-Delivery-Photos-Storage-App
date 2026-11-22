import logging

from django.conf import settings
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
        return {"status": "unavailable", "database": "unreachable", "version": settings.APP_VERSION}, 503
    return {"status": "ok", "database": "ok", "version": settings.APP_VERSION}, 200
