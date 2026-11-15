.PHONY: all offline test
all:
	python run_all.py
offline:
	python run_all.py --offline
test:
	python -m pytest -q project_a project_b
