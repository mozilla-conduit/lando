FROM python:3.11

EXPOSE 80
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE 1

RUN addgroup --gid 10001 app \
    && adduser \
        --disabled-password \
        --uid 10001 \
        --gid 10001 \
        --home /app \
        --gecos "app,,," \
        app

# Install the Rust toolchain. Some packages do not have pre-built wheels (e.g.
# rs-parsepatch) and require this in order to compile.
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# Include ~/.cargo/bin in PATH.
# See: rust-lang.org/tools/install (Configuring the PATH environment variable).
ENV PATH="/root/.cargo/bin:${PATH}"

# Install `moz-phab` via `pipx`.
ARG MOZ_PHAB_VERSION=2.7.0
ENV PIPX_HOME=/opt/pipx
ENV PIPX_BIN_DIR=/usr/local/bin
RUN python -m pip install --no-cache-dir pipx \
  && PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install --python python "MozPhab==${MOZ_PHAB_VERSION}" \
  && chmod -R a+rX /opt/pipx \
  && moz-phab --version

# Upgrade `setuptools`.
RUN pip install --upgrade pip setuptools

# Install requirements first, so they are only re-installed when
# `requirements.txt` changes.
WORKDIR /code
COPY requirements.txt /code/requirements.txt
RUN pip install -r /code/requirements.txt

# Copy code into the container.
COPY ./ /code

RUN mkdir -p /code/.ruff_cache
RUN chown -R app /code/.ruff_cache

RUN cp /code/.moz-phab-config /app/.moz-phab-config && chown app:app /app/.moz-phab-config


RUN pip install -e /code

USER app

WORKDIR /code

CMD ["bash"]
