PYTHON ?= python
RUN = $(PYTHON) -m chinese_tutor

.PHONY: install chat list web

install:
	$(PYTHON) -m pip install -e .

chat:
	$(RUN) chat

list:
	$(RUN) list

web:
	.venv/bin/uvicorn chinese_tutor.web:app --host 0.0.0.0 --port 3000
