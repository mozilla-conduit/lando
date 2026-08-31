# Copy Node.js from official image to avoid running third-party install scripts.
FROM node:20-slim AS node

# Copy Rust from official image to avoid running third-party install scripts.
FROM rust:1.84-slim AS rust

FROM python:3.14-bookworm

EXPOSE 80
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install mercurial
RUN apt-get update
RUN apt-get install -y mercurial=6.3.2-1+deb12u1

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
# the compose volume mount (./:/code) doesn't hide them. Symlink to
# `/node_modules` so both CJS and ESM module resolvers find the deps when
# walking up from `/code` — `NODE_PATH` only works for CJS.
COPY package.json package-lock.json /deps/
RUN npm install --prefix /deps && ln -s /deps/node_modules /node_modules

# Add node_modules to PATH so `prettier` can be run directly.
ENV PATH="/deps/node_modules/.bin:${PATH}"

# Copy vendored static dependencies from `node_modules` into a curated location
# outside of `/code` so this layer caches with `npm install` instead of being
# invalidated on every source change. Django reads this path from
# `STATICFILES_DIRS` in `settings.py`.
RUN mkdir -p /static_vendor \
    && cp -r /deps/node_modules/font-awesome /static_vendor/font-awesome \
    && cp -r /deps/node_modules/jquery/dist /static_vendor/jquery

# Copy code into the container.
COPY ./ /code

# Build the Vue frontend bundle into the `build.outDir` directory configured in
# `vite.config.ts`, served by Django as a static asset. Resolves dependencies
# via the `/node_modules` symlink created above.
RUN cd /code && npm run build

# Create an empty directory to store version info.
RUN mkdir -p /code/src/lando/version

# Built as the caller by `compose.yaml`, so writes to the working copy stay
# editable on the host. Created here rather than at the top of the file so that
# changing the ids does not invalidate the cached dependency layers above.
ARG APP_UID=10001
ARG APP_GID=10001

RUN addgroup --gid ${APP_GID} app \
    && adduser \
        --disabled-password \
        --uid ${APP_UID} \
        --gid ${APP_GID} \
        --home /app \
        --gecos "app,,," \
        app

# Docker populates a fresh `media` volume, mounted at `/files`, from the image.
# Without this it is root-owned and unwritable by the user compose runs as.
RUN mkdir -p /files/repos /files/mozbuilds && chown -R app:app /files

RUN mkdir -p /code/.ruff_cache
RUN chown -R app /code/.ruff_cache

RUN pip install -e /code

USER app

# Make sure we can detect SSH signatures, even if we can't validate them. Run
# from `/`: git fails to find a repository under `/code` in a worktree.
RUN git -C / config --global gpg.ssh.allowedSignersFile /dev/null

WORKDIR /code

CMD ["bash"]
