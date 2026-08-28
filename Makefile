PY := PYTHONPATH=src python3

.PHONY: install synthetic demo test web serve status clean

install:
	pip install -r requirements.txt

## API 키 없이 파이프라인 검증 (심어둔 β를 되찾는지 확인)
synthetic:
	$(PY) scripts/make_synthetic.py

## 로직 검증 (API 키 불필요)
test:
	$(PY) scripts/test_backfill.py

demo: synthetic
	$(PY) -m redt.cli link
	$(PY) -m redt.cli panel
	$(PY) -m redt.cli analyze --volume total

## 웹 화면용 JSON 생성 후 로컬 서버 실행 (http://localhost:8000)
web:
	$(PY) -m redt.cli score
	$(PY) -m redt.cli export-web
	@echo ""
	@echo "  http://localhost:8000 에서 확인하세요 (Ctrl+C 로 종료)"
	@cd web && python3 -m http.server 8000

serve:
	@cd web && python3 -m http.server 8000

status:
	$(PY) -m redt.cli status

clean:
	rm -f data/processed/redt.duckdb data/processed/*.parquet data/processed/*.csv
	rm -f data/processed/.synthetic web/data/*.json
