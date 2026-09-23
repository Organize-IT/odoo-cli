# Odoo 20 has no Docker Hub image yet (2026-09-23). Built from source at a pinned commit.
# Delete this directory once `odoo:20.0` is published and switch the matrix to the image.
FROM python:3.12-slim-bookworm
ARG ODOO_SHA
RUN apt-get update && apt-get install -y --no-install-recommends \
      git build-essential libpq-dev libldap2-dev libsasl2-dev libxml2-dev libxslt1-dev \
      libjpeg-dev zlib1g-dev libffi-dev postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m -d /var/lib/odoo -s /bin/bash odoo
RUN git init /opt/odoo && cd /opt/odoo \
    && git remote add origin https://github.com/odoo/odoo.git \
    && git fetch --depth 1 origin "${ODOO_SHA}" && git checkout FETCH_HEAD \
    && rm -rf .git
RUN pip install --no-cache-dir -r /opt/odoo/requirements.txt && pip install --no-cache-dir -e /opt/odoo
USER odoo
EXPOSE 8069
ENTRYPOINT ["odoo"]
