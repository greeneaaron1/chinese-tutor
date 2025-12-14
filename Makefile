PYTHON ?= python
RUN = $(PYTHON) -m chinese_tutor

.PHONY: install chat review list web

install:
	$(PYTHON) -m pip install -e .

chat:
	$(RUN) chat

review:
	$(RUN) review

list:
	$(RUN) list

web:
	uvicorn chinese_tutor.web:app --host 0.0.0.0 --port 3000
