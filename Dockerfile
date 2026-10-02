# The AURA API. Deliberately slim: the extension collects evidence in the browser, so this image needs
# no Playwright and no browser binaries — see the lazy import in aura/browser/browser_manager.py.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Nothing is written to disk: no audit records, no screenshots, no token file.
    AURA_PERSIST=0 \
    AURA_API_HOST=0.0.0.0

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aura/ ./aura/

# Runs unprivileged and needs no writable directory.
RUN useradd --create-home --uid 10001 aura
USER aura

EXPOSE 8765
CMD ["python", "-m", "aura.api"]
