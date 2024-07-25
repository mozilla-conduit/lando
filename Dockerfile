FROM python:3.12

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

RUN mkdir /code
COPY ./ /code

RUN mkdir -p /code/.ruff_cache
RUN chown -R app /code/.ruff_cache

RUN pip install --upgrade pip


# Install the Rust toolchain. Some packages do not have pre-built wheels (e.g.
# rs-parsepatch) and require this in order to compile.
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# Include ~/.cargo/bin in PATH.
# See: rust-lang.org/tools/install (Configuring the PATH environment variable).
ENV PATH="/root/.cargo/bin:${PATH}"

RUN pip install -r /code/requirements.txt
RUN pip install -e /code
USER app

WORKDIR /code

CMD ["bash"]
