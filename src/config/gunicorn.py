# gunicorn settings: gunicorn -c src/config/gunicorn.py config.wsgi:application (run from the repo root).
# Sized for a 0.5 vCPU / 1 GiB Fargate task; threads suit I/O-bound S3 and DB calls.
pythonpath = "src"
bind = "0.0.0.0:8000"
workers = 2
worker_class = "gthread"
threads = 4
timeout = 60
graceful_timeout = 25          # below the ALB deregistration delay (30 s)
keepalive = 75                 # above the ALB idle timeout (60 s) to avoid 502s
worker_tmp_dir = "/dev/shm"  # noqa: S108 - read-only root fs; on Fargate /tmp is root-owned
accesslog = "-"
errorlog = "-"
access_log_format = (
    '{"level":"INFO","logger":"access","method":"%(m)s","path":"%(U)s",'
    '"status":%(s)s,"bytes":"%(B)s","ms":%(M)s}'
)
