# Reproducible runtime for the offline data pipeline (Spark needs a JVM, and
# Hadoop on Windows needs native binaries — Linux avoids both problems).
#
#   docker build -f pipeline/Dockerfile -t cognitive-pipeline .
#   docker run --rm -v "$PWD:/work" cognitive-pipeline make all
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps make \
 && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/work

COPY requirements-data.txt /tmp/requirements-data.txt
RUN pip install --no-cache-dir -r /tmp/requirements-data.txt

WORKDIR /work
