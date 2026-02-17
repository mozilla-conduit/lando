# Copy Node.js from official image to avoid running third-party install scripts.
FROM node:20-slim AS node

# Copy Rust from official image to avoid running third-party install scripts.
FROM rust:1.84-slim AS rust

# Install Mercurial in an isolated Python 3.11 environment via pipx. Mercurial
# 6.1.4 is pinned to Python 3.11, so decoupling it from the main application
# runtime allows the app to upgrade to newer Python versions independently.
FROM python:3.11-slim AS hg
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && pip install --no-cache-dir pipx \
    && PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/opt/hg/bin pipx install mercurial==6.1.4 \
    && apt-get purge -y gcc libc6-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.11

EXPOSE 80
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN addgroup --gid 10001 app \
    && adduser \
        --disabled-password \
        --uid 10001 \
        --gid 10001 \
        --home /app \
        --gecos "app,,," \
        app

# Copy Node.js and npm from the official node image.
COPY --from=node /usr/local/bin/node /usr/local/bin/
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Copy Rust toolchain from the official rust image. Some packages do not have
# pre-built wheels (e.g. rs-parsepatch) and require this in order to compile.
COPY --from=rust /usr/local/rustup /usr/local/rustup
COPY --from=rust /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH="/usr/local/cargo/bin:${PATH}"

# Copy the pipx-installed Mercurial (venv + bin symlink) and the Python 3.11
# runtime it depends on. The `hg` script's shebang chains through the venv's
# python symlink to /usr/local/bin/python3.11. All paths are version-namespaced
# (python3.11, lib/python3.11/, libpython3.11.so) so they do not conflict with
# the main application's Python version.
COPY --from=hg /opt/pipx /opt/pipx
COPY --from=hg /opt/hg/bin /opt/hg/bin
COPY --from=hg /usr/local/bin/python3.11 /usr/local/bin/python3.11
COPY --from=hg /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=hg /usr/local/lib/libpython3.11* /usr/local/lib/
RUN ldconfig
ENV PATH="/opt/hg/bin:${PATH}"

# Upgrade `setuptools`.
RUN pip install --upgrade pip setuptools

# Install requirements first, so they are only re-installed when
# `requirements.txt` changes.
WORKDIR /code
COPY requirements.txt /code/requirements.txt
RUN pip install -r /code/requirements.txt

# Install npm dependencies (Bulma and Dart Sass) outside of /code so that
# the compose volume mount (./:/code) doesn't hide them.
COPY package.json package-lock.json /deps/
RUN npm install --prefix /deps

# Copy code into the container.
COPY ./ /code

RUN mkdir -p /code/.ruff_cache
RUN chown -R app /code/.ruff_cache


RUN pip install -e /code

USER app

WORKDIR /code

CMD ["bash"]
