PYTHON ?= python
RUN = $(PYTHON) -m chinese_tutor

.PHONY: install chat review list

install:
	$(PYTHON) -m pip install -e .

chat:
	$(RUN) chat

review:
	$(RUN) review

list:
	$(RUN) list
