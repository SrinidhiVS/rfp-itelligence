FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin rfp \
    && mkdir -p /app/output /app/traces /home/rfp/.cache/huggingface \
    && chown -R rfp:rfp /app /home/rfp/.cache

USER rfp

ENV HF_HOME=/home/rfp/.cache/huggingface

EXPOSE 8000 8501

CMD ["python", "-m", "src.run", "--container"]
