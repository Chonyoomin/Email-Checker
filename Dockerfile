FROM python:3.14.4-slim-bookworm@sha256:fc74d22ffd0d5ac395a4b7bdda75a4539758862c49ebf3005647084631e63789
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    XDG_DATA_HOME=/data/xdg XDG_RUNTIME_DIR=/tmp/runtime \
    EMAIL_CHECK_CHECKPOINT_PATH=/models/laya EMAIL_CHECK_METADATA_DB_PATH=/data/metadata.sqlite3
RUN apt-get update && apt-get install -y --no-install-recommends dbus gnome-keyring libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app && mkdir /data && chown app:app /data
WORKDIR /app
COPY requirements-linux.lock pyproject.toml ./
RUN python -m pip install --no-deps torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install -r requirements-linux.lock
COPY src ./src
RUN python -m pip install --no-deps --no-build-isolation . && python -m pip check
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["dbus-run-session", "--", "python", "-m", "bad_email_check.container_entrypoint"]
