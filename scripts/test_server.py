"""매물 API 검증 — 인증·소유권·공개범위.

기능이 되는지보다 **되면 안 되는 것이 막히는지**를 주로 본다.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from redt.server import app as app_module  # noqa: E402
from redt.config import band_label  # noqa: E402
from redt.server import store  # noqa: E402

BROKER_A = {
    "email": "a@example.com", "password": "verysecret123",
    "office_name": "한길공인중개사사무소", "office_address": "경기도 화성시 향남읍 1",
    "license_no": "41590-2024-00001", "agent_name": "김중개", "phone": "031-355-0001",
}
BROKER_B = {**BROKER_A, "email": "b@example.com", "office_name": "두번째공인중개사",
            "license_no": "41590-2024-00002", "agent_name": "이중개"}
LISTING = {
    "kind": "land", "deal_type": "sale", "address": "경기도 화성시 양감면 정문리 1-2",
    "area_m2": 3305.0, "price_manwon": 48000, "contact_phone": "031-355-0001",
    "lat": 37.05, "lon": 126.95, "memo": "6m 도로 접함",
}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    tmp = Path(tempfile.mkdtemp()) / "listings.sqlite"
    app_module._con = store.connect(tmp)
    app_module._tollgates = [
        {"id": "TG001", "name": "발안영업소", "lat": 37.06, "lon": 126.96},
        {"id": "TG002", "name": "먼영업소", "lat": 35.10, "lon": 128.90},
    ]
    client = TestClient(app_module.app)
    ok = []

    # 가입 / 중복 / 약한 비밀번호
    a = client.post("/api/brokers", json=BROKER_A)
    assert a.status_code == 201, a.text
    token_a = a.json()["token"]
    assert "email" not in a.json()["broker"], "응답에 이메일이 노출됨"
    assert "password_hash" not in str(a.json()), "응답에 해시가 노출됨"
    ok.append("가입 성공 · 응답에 이메일/해시 미노출")

    assert client.post("/api/brokers", json=BROKER_A).status_code == 409
    assert client.post("/api/brokers", json={**BROKER_A, "email": "c@e.com",
                                             "password": "short"}).status_code == 422
    assert client.post("/api/brokers", json={**BROKER_A, "email": "d@e.com",
                                             "license_no": "abc"}).status_code == 422
    ok.append("중복 이메일 409 · 짧은 비밀번호/잘못된 등록번호 422")

    # 로그인
    assert client.post("/api/auth/login", json={"email": "a@example.com",
                                                "password": "wrongwrong123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@example.com",
                                                "password": "verysecret123"}).status_code == 200
    ok.append("잘못된 비밀번호 401 · 올바른 비밀번호 200")

    # 무차별 대입 방어
    app_module._failures.clear()
    codes = [client.post("/api/auth/login",
                         json={"email": "a@example.com", "password": f"bad{i}pass"}).status_code
             for i in range(10)]
    assert 429 in codes, f"로그인 시도가 무제한 허용됨: {codes}"
    assert codes.index(429) >= app_module.MAX_FAILURES, codes
    app_module._failures.clear()
    ok.append(f"로그인 {app_module.MAX_FAILURES}회 실패 후 429 잠금")

    # 인증 없이 등록 차단
    assert client.post("/api/listings", json=LISTING).status_code == 401
    assert client.post("/api/listings", json=LISTING,
                       headers={"Authorization": "Bearer garbage"}).status_code == 401
    ok.append("미인증/위조토큰 등록 차단")

    # 등록 → 결제 전 상태 + 최근접 IC 계산
    created = client.post("/api/listings", json=LISTING, headers=auth(token_a))
    assert created.status_code == 201, created.text
    item = created.json()
    listing_id = item["id"]
    assert item["status"] == "pending_payment", item["status"]
    assert item["nearest_tollgate_id"] == "TG001", item
    assert item["nearest_km"] < 2, item["nearest_km"]
    # 밴드 경계는 설정에서 온다. 여기에 문자열을 박아두면 경계를 바꿀 때마다
    # 서버는 멀쩡한데 검사만 깨진다.
    assert item["band"] == band_label(item["nearest_km"]), item
    assert item["license_no"] == BROKER_A["license_no"], "표시·광고 명시사항 누락"
    ok.append(f"등록 → pending_payment · 최근접 {item['nearest_name']} "
              f"{item['nearest_km']}km ({item['band']}) · 등록번호 표시")

    # 공개 목록에는 아직 안 보임
    assert client.get("/api/listings").json() == []
    assert len(client.get("/api/listings", headers=auth(token_a)).json()) == 1
    ok.append("결제 전 매물: 공개 목록에 미노출 · 본인에게는 노출")

    # 다른 중개사는 조회·수정·삭제 불가
    token_b = client.post("/api/brokers", json=BROKER_B).json()["token"]
    assert client.get("/api/listings", headers=auth(token_b)).json() == []
    assert client.patch(f"/api/listings/{listing_id}", json={"price_manwon": 1},
                        headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/listings/{listing_id}",
                         headers=auth(token_b)).status_code == 404
    ok.append("타 중개사: 조회·수정·삭제 모두 404 (존재 사실도 미노출)")

    # 게시 → 공개
    published = client.post(f"/api/listings/{listing_id}/publish", headers=auth(token_a))
    assert published.status_code == 200 and published.json()["status"] == "active"
    assert published.json()["paid_until"]
    assert len(client.get("/api/listings").json()) == 1
    ok.append("게시 → active · 만료일 설정 · 공개 목록 노출")

    # 수정 시 좌표 변경 → 최근접 재계산
    moved = client.patch(f"/api/listings/{listing_id}",
                         json={"lat": 35.11, "lon": 128.91, "price_manwon": 52000},
                         headers=auth(token_a))
    assert moved.json()["nearest_tollgate_id"] == "TG002", moved.json()
    assert moved.json()["price_manwon"] == 52000
    ok.append("좌표 수정 → 최근접 영업소 재계산")

    # 검증 실패값 거부
    assert client.post("/api/listings", json={**LISTING, "price_manwon": -1},
                       headers=auth(token_a)).status_code == 422
    assert client.post("/api/listings", json={**LISTING, "lat": 12.0},
                       headers=auth(token_a)).status_code == 422
    ok.append("음수 가격 / 국내 범위 밖 좌표 422")

    # 삭제는 소프트 삭제
    assert client.delete(f"/api/listings/{listing_id}", headers=auth(token_a)).status_code == 204
    assert client.get("/api/listings").json() == []
    row = app_module._con.execute("SELECT status FROM listing WHERE id=?",
                                  (listing_id,)).fetchone()
    assert row["status"] == "removed", "행이 실제로 지워짐 (광고 이력 보존 실패)"
    ok.append("삭제 → 소프트 삭제 (광고 이력 보존)")

    # 로그아웃 후 토큰 무효
    assert client.post("/api/auth/logout", headers=auth(token_a)).status_code == 204
    assert client.get("/api/me", headers=auth(token_a)).status_code == 401
    ok.append("로그아웃 → 토큰 즉시 무효")

    print("\n".join(f"✅ {line}" for line in ok))
    print(f"\n{len(ok)}개 항목 통과")


if __name__ == "__main__":
    main()
