.PHONY: install install-app test experiments experiments-quick app figures clean

install:
	python -m pip install -r requirements.txt -r requirements-dev.txt

install-app:
	python -m pip install -r requirements-app.txt

test:
	python -m pytest

experiments:
	python scripts/run_experiments.py

experiments-quick:
	python scripts/run_experiments.py --quick

figures:
	python scripts/make_figures.py

app:
	streamlit run app/wargame.py

clean:
	rm -rf __pycache__ */__pycache__ .pytest_cache
	find . -name '*.pyc' -delete
