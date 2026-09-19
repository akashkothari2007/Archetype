FROM python:3.12-slim-bookworm
WORKDIR /app
COPY pyproject.toml README.md ./
COPY plancheck ./plancheck
RUN pip install --no-cache-dir .
ENV PLANCHECK_DATA_DIR=/data/projects
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "plancheck.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
