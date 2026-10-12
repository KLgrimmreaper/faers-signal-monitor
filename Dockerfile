# the pipeline scripts, without the database. postgres is a service, not something to
# bake into the image
FROM python:3.12-slim

WORKDIR /app

# requirements first so the dependencies are cached when only the code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py *.sql ./
COPY fixtures ./fixtures

# no database credentials in the image. PGHOST and friends come from the environment
ENV PYTHONUNBUFFERED=1

# ingest, report, publish is what the scheduled job does. depends_on and the connection
# settings are the caller's business
CMD ["python", "run.py", "--status"]
