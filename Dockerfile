# build application
FROM python as builder

RUN pip install poetry==1.8.2

ENV POETRY_CACHE_DIR=/tmp/poetry_cache \
    POETRY_NO_INTERACTION=1            \
    POETRY_VIRTUALENVS_CREATE=1        \
    POETRY_VIRTUALENVS_IN_PROJECT=1

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN touch README.md

RUN poetry install --without dev --no-root

# runtime
FROM python:slim as runtime

ENV VIRTUAL_ENV=/app/.venv      \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY entrypoint.sh ./
COPY loxone ./loxone

ENTRYPOINT [ "/entrypoint.sh" ]
