FROM python:3.12-slim-bookworm
WORKDIR /app
COPY pyproject.toml README.md ./
COPY plancheck ./plancheck
RUN pip install --no-cache-dir .
ENV PLANCHECK_DATA_DIR=/data/projects
ENV PYTHONUNBUFFERED=1
ENV PLANCHECK_LOG_LEVEL=INFO
EXPOSE 8000
# --log-level info keeps uvicorn + our plancheck.* loggers on stdout for
# `docker compose logs -f backend`.
CMD ["python", "-m", "uvicorn", "plancheck.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
