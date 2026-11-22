# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements/ /tmp/requirements/
RUN /opt/venv/bin/pip install --upgrade pip && /opt/venv/bin/pip install -r /tmp/requirements/prod.txt

FROM python:3.12-slim
LABEL org.opencontainers.image.title="onward-delivery-photos-app" \
      org.opencontainers.image.description="Onward Logistics delivery photo gallery (Django)"
# TMPDIR: the root filesystem is read-only and on Fargate /tmp is root-owned, so the non-root
# user writes scratch files to /dev/shm (in-memory, present in every container).
ENV PATH="/opt/venv/bin:$PATH" \
    TMPDIR=/dev/shm \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /srv
COPY --from=build /opt/venv /opt/venv
COPY manage.py ./
COPY src ./src

# At build time: ECS runs the container with a read-only root filesystem.
RUN python manage.py collectstatic --noinput --verbosity 0

USER 10001:10001
EXPOSE 8000

# Apply pending migrations (serialised by an advisory lock), then serve.
CMD ["sh", "-c", "python manage.py migrate_safely --verbosity 1 && exec gunicorn -c src/config/gunicorn.py config.wsgi:application"]
