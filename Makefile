# Offline data pipeline. Run natively on Linux/macOS (Python 3.12 + Java 17),
# or anywhere via Docker:  make docker-all
PY      ?= python
ROOT    ?= pipeline_data
USERS   ?= 2000
DAYS    ?= 60
IMAGE   ?= cognitive-pipeline

.PHONY: data pipeline train bandit all test docker-build docker-all

data:
	$(PY) -m pipeline.simulator.generate_events --users $(USERS) --days $(DAYS) --out $(ROOT)

pipeline:
	$(PY) -m pipeline.run_pipeline --root $(ROOT)

train:
	$(PY) -m pipeline.model.train --root $(ROOT)

bandit:
	$(PY) -m pipeline.experiments.bandit_sim

all: data pipeline train bandit

test:
	$(PY) -m pytest -q tests

docker-build:
	docker build -f pipeline/Dockerfile -t $(IMAGE) .

docker-all: docker-build
	docker run --rm -v "$(CURDIR):/work" $(IMAGE) make all USERS=$(USERS) DAYS=$(DAYS)
