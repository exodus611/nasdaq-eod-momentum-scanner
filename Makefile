.PHONY: install update scan dashboard all docker run clean test

install:
	pip install -r requirements.txt
	pip install fastapi uvicorn

update:
	python src/update_universe.py

download:
	python src/download_history.py

download-inc:
	INCREMENTAL=1 python src/download_history.py

panel:
	python src/prep_panel.py

backtest:
	python src/backtest.py

scan:
	python src/scan.py

dashboard:
	python src/build_dashboard.py

all: update download-inc panel scan dashboard
	@echo "✅ Full pipeline done - check output/index.html"

test:
	python -m py_compile src/*.py
	@echo "Syntax OK"
	ls -lh data/ | tail -20
	ls -lh output/

docker:
	docker build -t nasdaq-eod-scanner .

run:
	python -m uvicorn deploy_server:app --host 0.0.0.0 --port 8000 --reload

deploy:
	./deploy/push.sh "$(msg)"

clean:
	rm -rf data/*.parquet data/history_index.json output/*.csv output/*.html
	@echo "Cleaned - run make download to refetch"

health:
	curl -s http://localhost:8000/health | python -m json.tool
