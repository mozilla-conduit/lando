# Copy Node.js from official image to avoid running third-party install scripts.
FROM node:20-slim AS node

# Copy Rust from official image to avoid running third-party install scripts.
FROM rust:1.84-slim AS rust

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
