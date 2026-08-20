# Built from the REPO ROOT, not from backend/:
#     docker build -f backend/Dockerfile .
# The API imports the pipeline modules (keyword_pipeline.py, llm.py,
# sanitize.py, ...) from the repo root, so they have to be inside the build
# context. backend/ alone would produce an image that fails on first import.
FROM python:3.12-slim

WORKDIR /app

# Both requirement sets: the root one for the pipeline's own dependencies
# (google-genai, requests, psycopg, fpdf2), the backend one for the web
# layer (fastapi, uvicorn, bcrypt, pyjwt).
#
# This pulls streamlit in too, which the API never imports -- only app.py
# does. Installed anyway rather than maintaining a second, trimmed
# requirements file: duplicated version pins drift, and the waste
# disappears on its own when app.py is retired and streamlit leaves
# requirements.txt. Correctness now, size later.
# Separate COPY lines with explicit destinations: `COPY a b ./` flattens
# both into the same directory, so backend/requirements.txt would land as
# ./requirements.txt and silently overwrite the root one.
COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r backend/requirements.txt

COPY . .

RUN useradd -m appuser
USER appuser

EXPOSE 8000
# --app-dir backend so `app.main` resolves, while the working directory stays
# at the repo root so the pipeline modules remain importable.
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
