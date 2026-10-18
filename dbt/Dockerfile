FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "dbt-core>=1.10,<2" "dbt-bigquery>=1.10,<2"

WORKDIR /usr/app

ENTRYPOINT ["dbt"]