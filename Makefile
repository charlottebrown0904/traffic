PY := PYTHONPATH=src python3

.PHONY: install synthetic demo test test-server web serve serve-static plan progress status clean

install:
	pip install -r requirements.txt

## API 키 없이 파이프라인 검증 (심어둔 β를 되찾는지 확인)
synthetic:
	$(PY) scripts/make_synthetic.py

## 로직 검증 (API 키 불필요)
test: test-server
	$(PY) scripts/test_backfill.py
	$(PY) scripts/test_web.py

## 매물 API 인증·권한 검증
test-server:
	$(PY) scripts/test_server.py

demo: synthetic
	$(PY) -m redt.cli link
	$(PY) -m redt.cli panel
	$(PY) -m redt.cli analyze --volume total

## 웹 화면용 JSON 생성 후 로컬 서버 실행 (http://localhost:8000)
web:
	$(PY) -m redt.cli score
	$(PY) -m redt.cli export-web
	@echo ""
	@echo "  http://127.0.0.1:8000 에서 확인하세요 (Ctrl+C 로 종료)"
	$(PY) -m redt.cli serve-api

## 매물 API + 화면 (같은 포트). JSON 이 이미 있을 때
serve:
	$(PY) -m redt.cli serve-api

## 마스터 플랜 진행률 보드 (비공개 · 로컬 전용)
## 진행률 문서 재생성 (internal/tasks.json → internal/PROGRESS.md)
progress:
	$(PY) scripts/render_progress.py

plan:
	@echo ""
	@echo "  http://127.0.0.1:8900/plan.html  — 진행률 보드 (Ctrl+C 로 종료)"
	@echo ""
	@cd internal && python3 -m http.server 8900

## 정적 화면만 (API 없이)
serve-static:
	@cd public && python3 -m http.server 8000

status:
	$(PY) -m redt.cli status

clean:
	rm -f data/processed/redt.duckdb data/processed/*.parquet data/processed/*.csv
	rm -f data/processed/.synthetic public/app/data/*.json
