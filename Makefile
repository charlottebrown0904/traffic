PY := PYTHONPATH=src python3

# make collect 수집 범위·대상 (덮어쓰기 예: make collect START=2015-01 KIND=land)
START ?= 2021-01
END   ?= 2025-12
KIND  ?= land,factory

.PHONY: install hooks doctor collect synthetic demo test test-server check-traffic tollgate-events web serve serve-static plan progress status clean

install:
	pip install -r requirements.txt

## 키가 커밋에 섞이지 않도록 git 훅 설치 (한 번만)
hooks:
	git config core.hooksPath .githooks
	@echo "  설치됨 — 이제 키가 포함된 커밋은 차단됩니다"

## 수집 전 점검 — 키·네트워크·저장경로가 다 준비됐는지
doctor:
	$(PY) -m redt.cli doctor

## 실데이터 수집 → 분석 → 화면까지 한 번에 (파일럿 권역)
collect:
	$(PY) -m redt.cli doctor
	$(PY) -m redt.cli tollgates
	$(PY) -m redt.cli trades --kind $(KIND) --start $(START) --end $(END)
	$(PY) -m redt.cli geocode
	$(PY) -m redt.cli link
	$(PY) -m redt.cli status

## API 키 없이 파이프라인 검증 (심어둔 β를 되찾는지 확인)
synthetic:
	$(PY) scripts/make_synthetic.py

## 영업소 개통·폐쇄 시점 추출 (월별 파일에서)
tollgate-events:
	$(PY) scripts/tollgate_events.py

## 교통량 자료 정합성 검사 — 연도를 새로 넣을 때마다 돌릴 것
check-traffic: tollgate-events
	$(PY) scripts/check_traffic.py

## 로직 검증 (API 키 불필요)
test: test-server
	$(PY) scripts/test_workflows.py
	$(PY) scripts/test_privacy.py
	$(PY) scripts/test_backfill.py
	$(PY) scripts/test_trades_concurrent.py
	$(PY) scripts/test_geocode_staged.py
	$(PY) scripts/test_link_stream.py
	$(PY) scripts/test_upsert_preserve.py
	$(PY) scripts/test_geocode_quota.py
	$(PY) scripts/test_web.py
	$(PY) scripts/test_web_parcel.py
	$(PY) scripts/test_offices.py
	$(PY) scripts/test_landchar_scope.py
	$(PY) scripts/test_landprice.py
	$(PY) scripts/test_parcelscore.py
	$(PY) scripts/test_valuation.py
	$(PY) scripts/test_urban.py
	$(PY) scripts/test_analysis.py
	node scripts/test_palette.js
	node scripts/test_board.js
	node scripts/test_gate.js
	node scripts/test_rank.js
	node scripts/test_map.js
	node scripts/test_tile.js
	node scripts/test_cloudflare.js

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
