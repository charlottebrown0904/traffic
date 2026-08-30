# PC에 아무것도 설치하지 않고 실행하기 (GitHub Codespaces)

파이썬 설치, git clone, 명령창 — 하나도 필요 없습니다.
브라우저에서 이 저장소를 열면 리눅스 개발환경이 통째로 뜨고, 거기서 수집을 돌립니다.

---

## 1단계 — 키를 Codespaces Secrets 에 넣기 (파일 아님)

**https://github.com/charlottebrown0904/traffic/settings/secrets/codespaces**

`New repository secret` 을 눌러 아래를 등록합니다.

| Name | Value |
|---|---|
| `DATA_GO_KR_KEY` | 공공데이터포털 **Decoding** 인증키 |
| `VWORLD_KEY` | 브이월드 인증키 (승인 후) |

붙여넣을 때 앞뒤 공백·줄바꿈이 딸려오지 않게 하고, 따옴표는 붙이지 마세요.
Decoding 키에 들어있는 `+` `/` `=` 는 그대로 두면 됩니다.

### ⚠️ 헷갈리기 쉬운 곳 — Secrets 저장소가 세 개입니다

저장소 `Settings` → 왼쪽 `Secrets and variables` 아래에 세 개가 나란히 있습니다.

| | 쓰이는 곳 | 여기에 키를 넣나 |
|---|---|---|
| **Actions** | 워크플로 실행 | ❌ 아니요 |
| **Codespaces** | 브라우저 개발환경 | ⭕ **여기입니다** |
| Dependabot | 의존성 업데이트 | ❌ 아니요 |

`Environment secrets` / `Repository secrets` 두 칸이 보이면 **Actions 화면**입니다.
왼쪽에서 `Codespaces` 로 옮겨가세요.

Actions 에는 넣지 마세요. 지금 Actions 에서 도는 것은 키 유출 검사뿐이라
인증키가 필요 없고, 두면 노출 경로만 늘어납니다.

> 개인 계정 전체에 걸어두려면 https://github.com/settings/codespaces 에서도
> 등록할 수 있습니다. 그때는 `Repository access` 에서 이 저장소를 선택해야 합니다.
> 저장소 한 곳에서만 쓸 것이므로 위의 저장소별 Secrets 가 더 간단합니다.

## 2단계 — Codespace 켜기

저장소 첫 화면 → 초록색 **`Code`** 버튼 → **`Codespaces`** 탭 → **`Create codespace on main`**

처음 한 번은 2~3분 걸립니다 (파이썬 패키지 설치). 그 다음부터는 몇 초입니다.
브라우저 안에 VS Code 화면이 뜨고, 아래쪽에 **터미널**이 있습니다.

## 3단계 — 점검

터미널에 이렇게 칩니다.

```bash
make doctor
```

`API 키 (읽은 곳: 환경변수)` 아래가 전부 `ok` 면 준비 완료입니다.
막힌 항목이 있으면 무엇을 하면 되는지 문장으로 나옵니다.

## 4단계 — 수집

```bash
make collect
```

경기 남부 8개 시군구의 토지·공장 실거래가를 받아 좌표를 붙이고 영업소와 잇습니다.
중간에 끊겨도 다시 실행하면 이어서 받습니다.

## 5단계 — 화면 확인

```bash
make web
```

포트 8000 알림이 뜨면 `브라우저에서 열기` 를 누릅니다.

---

## 알아두실 것

- **무료 한도** — 개인 계정은 월 60시간(2코어 기준)까지 무료입니다. 수집은 몇 시간이면
  끝나므로 충분합니다. 안 쓸 때는 `Code → Codespaces → Stop` 으로 꺼두세요.
- **자동 중지** — 30분 아무 조작이 없으면 알아서 멈춥니다. 받아둔 데이터는 남습니다.
- **데이터 보관** — 받은 데이터는 Codespace 안에 남습니다. Codespace 를 **삭제**하면
  같이 사라지니, 중요한 결과는 커밋하거나 내려받으세요.
- **키는 여기 넣지 마세요** — `config/.env.example` 은 저장소에 올라가는 서식입니다.
  값은 1단계의 Secrets 에만 넣습니다.

---

## PC에 직접 설치하고 싶다면

Codespaces 없이 로컬에서 돌리셔도 됩니다. 그때는 `config/.env` 파일을 만들어야 합니다.

```bash
git clone https://github.com/charlottebrown0904/traffic.git
cd traffic
pip install -r requirements.txt
cp config/.env.example config/.env    # 이 파일을 열어 키를 채웁니다
make hooks                            # 키가 커밋되지 않도록 차단
make doctor
```

Windows 라면 먼저 [Python](https://www.python.org/downloads/) 과
[Git](https://git-scm.com/download/win) 을 설치하고, `명령 프롬프트` 대신
`Git Bash` 에서 위 명령을 실행하세요.
