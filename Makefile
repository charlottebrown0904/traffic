PY := PYTHONPATH=src python3

.PHONY: install synthetic demo status clean

install:
	pip install -r requirements.txt

## API 키 없이 파이프라인 검증 (심어둔 β를 되찾는지 확인)
synthetic:
	$(PY) scripts/make_synthetic.py

demo: synthetic
	$(PY) -m redt.cli link
	$(PY) -m redt.cli panel
	$(PY) -m redt.cli analyze --volume total

status:
	$(PY) -m redt.cli status

clean:
	rm -f data/processed/redt.duckdb data/processed/*.parquet data/processed/*.csv
