FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir fastapi pydantic sqlalchemy uvicorn

COPY src /app/src
COPY README.md pyproject.toml /app/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "ltx_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
