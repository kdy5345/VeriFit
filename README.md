# VeriFit — 개인 조건 기반 적금 비교 Agent

기획 배경부터 데이터·지식 그래프·에이전트 구현까지의 경험은 [프로젝트 경험 정리](docs/project-experience.md)에 기록했습니다.

적금 상품의 **광고 최고금리**가 아니라, 사용자가 실제로 충족할 수 있는 우대조건을
반영해 **예상 적용금리와 세후 이자**를 계산하는 금융상품 비교 서비스입니다.

사용자는 복잡한 입력 폼 대신 자신의 상황을 자연어로 말할 수 있습니다.

> 월 30만 원씩 1년 넣고 싶어요. 급여이체는 가능하지만 카드는 거의 사용하지 않아요.

VeriFit은 이 문장에서 납입액·기간·금융 습관을 구조화하고, 금융감독원 공시 상품의
우대조건과 대조합니다. 이후 받을 수 있는 우대만 반영해 상품별 금리와 이자를 계산하고,
왜 그런 결과가 나왔는지 공시 원문과 함께 설명합니다.

## 해결하려는 문제

적금 상품에는 기본금리와 최고금리가 함께 표시되지만, 최고금리를 받기 위한 조건은
상품마다 다릅니다.

```text
급여이체                    +0.50%p
카드 월 30만 원 이상         +0.30%p
첫 거래 고객                 +0.20%p
마케팅 수신 동의             +0.10%p
우대금리 합산 한도           최대 0.70%p
```

단순 금리 정렬 서비스는 이 모든 조건을 충족했을 때의 최고금리를 보여줍니다. VeriFit은
사용자가 충족할 수 있는 조건만 계산해 다음 질문에 답합니다.

- 내가 실제로 받을 수 있는 예상금리는 얼마인가?
- 상품별 예상 세후 이자는 얼마나 차이 나는가?
- 어떤 우대조건이 반영됐고 어떤 조건이 빠졌는가?
- 조건 하나를 바꾸면 계산 결과가 어떻게 달라지는가?
- 이 계산의 근거가 된 금융감독원 공시 문장은 무엇인가?

## 사용자 경험

### 1. 자연어로 조건 입력

```text
“월 50만 원씩 2년 넣을 거야.
급여이체와 공과금 자동이체는 가능하고 카드 실적은 어려워.”
```

Analyzer가 사용자의 말을 `UserProfile`로 변환합니다.

```json
{
  "monthly_deposit_won": 500000,
  "term_months": 24,
  "facts": {
    "salary_transfer": { "satisfied": true },
    "utility_autopay": { "satisfied": true },
    "card_usage_amount": { "satisfied": false }
  }
}
```

### 2. 사용자 조건 확인

웹 화면은 Agent가 이해한 내용을 조건 칩으로 보여줍니다.

```text
[월 500,000원] [24개월] [급여이체 가능]
[공과금 자동이체 가능] [카드 사용 안 함]
```

금액과 기간은 LLM 출력만 믿지 않고 사용자 원문의 숫자와 코드로 다시 대조합니다.

### 3. 상품별 예상 결과 비교

각 상품 카드에서 다음 정보를 한 번에 확인할 수 있습니다.

- 기본금리·예상 적용금리·공시 최고금리
- 일반과세 기준 예상 세후 이자와 만기 예상액
- 충족·미충족·미확인 우대조건과 조건부 상한
- 가입 자격 확인 여부
- 계산에 사용된 공시 원문

### 4. 근거 확인

우대조건은 저장된 `Evidence`와 직접 연결됩니다.

```text
적용 우대
급여이체 +0.50%p

공시 원문
“급여이체 실적 충족 시 연 0.5%p”
```

검색으로 비슷한 문장을 가져오는 방식이 아니라, 실제 계산에 사용된 `Bonus`가 가진
근거 문장을 그대로 보여줍니다.

### 5. 대화를 이어서 조건 변경

첫 응답에서 받은 `thread_id`를 유지하면 이전 조건을 다시 설명하지 않아도 됩니다.

```text
사용자 1: 월 30만 원씩 1년 넣고 급여이체는 가능해.
Agent: 조건에 맞는 상품을 계산했어요.
사용자 2: 월 50만 원으로 바꿔줘.
Agent: 다른 조건은 유지하고 월 50만 원 기준으로 다시 계산했어요.
```

## 핵심 기능

### 금융상품 Knowledge Graph 구축

금융감독원 `금융상품 한눈에` API에서 적금 상품과 기간별 금리를 가져옵니다. 자연어로
제공되는 우대조건은 Gemini Extractor가 구조화하고, 검증을 통과한 결과를 SQLite에
Knowledge Graph 형태로 저장합니다.

```text
Institution
  └─ Product
       ├─ Eligibility
       └─ RateOption
            └─ BonusGroup
                 └─ Bonus
                      ├─ Requirement
                      └─ Evidence
```

예를 들어 다음 원문은:

```text
월 50만 원 이상 급여이체를 6개월 이상 유지하면 연 1.0%p
```

아래처럼 계산 가능한 구조로 변환됩니다.

```json
{
  "label": "급여이체 우대",
  "rate_bps": 100,
  "requirements": [
    {
      "codes": ["salary_transfer"],
      "min_amount_won": 500000,
      "min_months": 6
    }
  ],
  "evidence": {
    "quote": "월 50만 원 이상 급여이체를 6개월 이상 유지하면 연 1.0%p"
  }
}
```

### 개인 조건 기반 금리 판정

실시간 요청에서는 LLM이 금리를 계산하지 않습니다. 저장된 Requirement와 사용자
프로필을 코드로 비교합니다.

- AND / OR / 단일 조건 판정
- 금액·개월·횟수·채널 기준 확인
- 동시에 받을 수 없는 우대조건 처리
- 우대금리 합산 한도 적용
- 기본금리와 공시 최고금리 범위 확인
- 가입 나이·공시 납입 한도 확인, 가입 불가 후보 제외
- 정보가 없는 자격은 확인 필요로 남기고 공시 근거 제시

### 추가 질문과 가정 비교

미확인 우대는 현재 적용금리에 포함하지 않습니다. 금액·실적 기간·횟수·나이 등
빠진 정보를 다음 질문으로 요청하며, 이미 불가능하다고 답한 조건은 다시 묻지 않습니다.
질문 영향도는 조건을 충족하는 가정으로 **우대 한도·중복 제한·세금까지 재계산한
한 상품의 최대 추가 세후 이자**입니다. 가입 자격 확인은 이자 증가보다 먼저 질문합니다.
복합 조건은 답변 하나만으로 이자가 늘지 않을 수 있음을 명시합니다.

결과 화면에서는 월 납입액·기간·급여이체 가정을 바꿔 기존 결과와 비교할 수 있습니다.
동일 상품의 세후 이자 차이와 순위 변화를 보여주며, 원래 사용자 프로필은 변경하지 않습니다.
기간이 다르면 총 납입원금도 달라지므로 수익률의 직접 비교로 해석하면 안 됩니다.

### 상품 갱신과 출처 버전

배치는 공시월, 가입 자격, 우대 원문, 가입 채널, 납입 한도, 단리/복리와 기간별
금리를 해시로 비교합니다. 내용이 그대로인 검증 상품만 건너뛰고 변경되면 재검증합니다.
`product_versions`에 저장한 검증 버전과 현재 공시의 해시·저장 시각을 함께 보관합니다.
같은 상품의 여러 공시월 중 최신만 조회하며, 변경 원문이 검증되지 않으면 이전 금리를
추천에서 비활성화합니다. 상품 저장 도중 실패하면 변경 전체를 롤백합니다.

### 결정론적 이자 계산

금리와 금액 계산은 `Decimal` 기반 코드가 담당합니다.

- 자유적립식·정액적립식 구분
- 단리·복리 계산
- 납입 기간별 예상 이자
- 일반과세 15.4% 기준 세후 이자
- 총 납입원금과 만기 예상액

### 근거 기반 Agent 답변

온라인 Agent는 다음 역할을 분리합니다.

```text
Analyzer LLM
  사용자 자연어 → UserProfile
        ↓
Input Validator
  금액·기간·조건 근거 대조
        ↓
Knowledge Graph + Calculator
  가입 조건·우대금리·세후 이자 계산
        ↓
Writer LLM
  검증된 계산값을 자연어로 설명
        ↓
Answer Verifier
  상품·숫자·Evidence를 코드로 재검증
        ↓
Reviewer LLM
  과장·논리 비약·사용자 의도 왜곡 검토
```

Writer가 계산 결과와 다른 숫자를 사용하면 오류 내용을 포함해 한 번 다시 작성합니다.
재검증을 통과하지 못하거나 Reviewer를 사용할 수 없으면 LLM 문장을 사용하지 않고 코드가
계산한 정형 답변으로 전환합니다.

## 시스템 구성

### 오프라인 상품 구축 파이프라인

```text
금융상품 한눈에 API
        ↓
적립 방식·기간별 금리 옵션 정규화
        ↓
Extractor LLM 3회 실행 및 self-consistency 병합
        ↓
근거 문장·우대금리 도달 가능성·가입 자격 코드 검증
        ↓
Reviewer LLM 재검토
        ↓
기간별 accept / exclude
        ↓
SQLite Knowledge Graph 저장
```

### 실시간 서비스

```text
React Web UI
        ↓
Nginx → FastAPI (POST /api/v1/ask)
        ↓
최종 결과 캐시 조회 (Redis)
        ↓
캐시 미스: Online LangGraph Agent
  ├─ 사용자 입력 분석·검증
  ├─ 상품 KG 조회 (Redis / SQLite)
  ├─ 예상금리·세후 이자 계산
  └─ 답변 작성·코드 검증·Reviewer 검토
        ↓
결과 캐싱 + SQLite 대화 체크포인트 저장
        ↓
예상금리·세후 이자·근거 반환
```

구조화된 `UserProfile`을 직접 보내는 `POST /api/v1/evaluate`도 제공합니다. 이 경로는
LLM을 호출하지 않고 Knowledge Graph 조회와 코드 계산만 수행합니다.

## 웹 UI

웹 UI는 기존 디자인 시스템의 색상·타이포그래피·간격 토큰과 공용 컴포넌트를 사용합니다.

- 자연어 조건 입력과 예시 프롬프트
- Agent 분석 진행 상태
- 인식된 조건 시각화
- 예상금리·세후 이자 기준 정렬
- 기본·예상·최고금리 비교 바
- 적용·미적용 우대조건 표시
- 공시 원문 Evidence drawer
- `thread_id` 기반 후속 대화
- 세후 이자 영향도 기반 추가 질문과 가정 비교 표
- 공시월·원문 버전·검증 저장 시각 표시
- 새로고침·서버 재시작 후 대화 복원
- 라이트·다크 테마
- 데스크톱 2열 및 모바일 1열 반응형 레이아웃

## 기술 스택

| 영역 | 기술 | 역할 |
|---|---|---|
| 프론트엔드 | React 19, TypeScript 5 | 자연어 입력, 상품 비교, 가정 변경, 대화 결과 복원 |
| 프론트 빌드 | Vite 8 | 개발 서버 및 프로덕션 정적 파일 빌드 |
| 스타일·UI | Tailwind CSS 4, Lucide React, SUIT Variable | 디자인 토큰, 반응형 화면, 아이콘, 타이포그래피 |
| 백엔드 | Python 3.11, FastAPI, Uvicorn | 대화·금융 계산·시나리오 비교 REST API, 단일 워커 실행 |
| 스키마·설정 | Pydantic 2, Pydantic Settings | 사용자 입력·LLM 출력·API 계약 검증, 환경변수 관리 |
| 에이전트 오케스트레이션 | LangGraph | 상품 추출 및 사용자 질의 그래프, 조건 분기, 검증, 재시도, fallback |
| LLM | Gemini API | Extractor, Analyzer, Writer, Reviewer 역할; 모델은 환경변수로 설정 |
| 외부 API 통신 | HTTPX | Gemini API 및 금융감독원 API 호출 |
| 금융 데이터 | 금융감독원 금융상품 한눈에 API | 적금 상품, 가입 자격, 우대조건 원문, 기간별 금리 수집 |
| 금융 계산 | Python 결정론적 계산 엔진 | 조건 충족·가입 자격 판정, 우대 한도·중복 제한, 예상금리·세후 이자 계산 |
| 상품 저장소 | SQLite | 관계형 테이블 기반 Knowledge Graph, 공시 버전, 추출 기록, 캐시 revision |
| 대화 저장소 | LangGraph SQLiteSaver | 대화 State 체크포인트, 서버 재시작 후 결과 복원 |
| 캐싱 | Redis 7.4, redis-py, Python 메모리 캐시 | 상품 KG, 계산, 시나리오, LLM 단계, 최종 결과 캐싱; TTL·LRU·장애 대체 경로 |
| 웹 서버 | Nginx | React 정적 파일 제공, API 프록시, 컨테이너 주소 재조회 |
| 컨테이너 실행 | Docker, Docker Compose | 웹·API·Redis 서비스 및 상품 구축 배치, 멀티스테이지 빌드, 상태 확인 |
| 백엔드 검증 | pytest, 수작업 정답 세트 | 금융 계산·에이전트·저장·캐시 회귀 테스트, 선택적 실제 모델 검증 |
| 프론트 검증 | Vitest, Testing Library, jsdom | API 클라이언트 및 사용자 화면 흐름 테스트 |
| 코드 품질·협업 | ESLint, TypeScript 타입 검사, Git, GitHub | 정적 검사, 소스 버전 관리 |

SQLite가 원본 저장소이며 Redis는 재생성 가능한 캐시입니다. 임베딩·벡터 DB 기반
RAG나 별도 그래프 DB는 사용하지 않고, 계산에 연결된 공시 근거를 직접 제공합니다.
현재 실행 범위는 로컬 Docker 환경이며 공개 배포용 사용자 인증은 포함하지 않습니다.

## 프로젝트 구조

```text
savings_agent/
├─ compose.yaml         # 웹·API·Redis·배치 서비스
├─ .dockerignore        # 비밀키·DB·로컬 의존성 빌드 제외
├─ backend/
│  ├─ Dockerfile        # Python API 및 테스트 이미지
│  ├─ app/
│  │  ├─ agent/          # 사용자 질의 Online LangGraph
│  │  ├─ api/routes/     # ask, evaluate, health API
│  │  ├─ core/           # 설정·Redis/메모리 캐시
│  │  ├─ db/             # SQLite 스키마·저장·조회
│  │  ├─ graph/          # 상품 추출 Offline LangGraph
│  │  ├─ integrations/   # 금융상품 한눈에 연동
│  │  ├─ schemas/        # Graph·Agent·사용자 스키마
│  │  └─ services/       # 추출·검증·계산·매칭
│  ├─ scripts/           # 상품 구축 배치
│  └─ tests/
├─ frontend/
│  ├─ Dockerfile        # Node 빌드 → Nginx 정적 웹
│  ├─ nginx.conf        # SPA·API 프록시 설정
│  └─ src/
│     ├─ components/     # 상품 카드·근거 drawer·공용 UI
│     ├─ design-system/  # 토큰·테마·타이포그래피
│     ├─ lib/            # API client
│     └─ types/          # API 타입
└─ data/
   ├─ savings.db        # 상품 Knowledge Graph
   └─ conversations.sqlite  # 대화 체크포인트
```

## 실행 방법

### 1. 백엔드 설치

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

프로젝트 루트의 `.env`에 API 키를 설정합니다.

```dotenv
FINLIFE_API_KEY=발급받은_키
GEMINI_API_KEY=발급받은_키

EXTRACTOR_MODEL=gemini-3.7-flash
REVIEWER_MODEL=gemini-3.7-flash
ONLINE_AGENT_MODEL=gemini-3.7-flash
# 선택: 기본값은 data/conversations.sqlite
CHECKPOINT_PATH=/절대경로/savings_agent/data/conversations.sqlite
```

### 2. 상품 데이터 구축

```bash
cd backend

# 소량 실행
.venv/bin/python scripts/run_savings_batch.py --limit 5 --db-path ../data/savings.db

# 전체 실행
.venv/bin/python scripts/run_savings_batch.py --db-path ../data/savings.db

# 실행 중 하루 간격으로 갱신 (중지: Ctrl+C)
.venv/bin/python scripts/run_savings_batch.py --db-path ../data/savings.db --interval-seconds 86400
```

### 3. API 서버 실행

```bash
cd backend
.venv/bin/python run.py
```

API 서버는 기본적으로 `http://127.0.0.1:8000`에서 실행됩니다.

### 4. 웹 UI 실행

```bash
cd frontend
npm install
npm run dev
```

웹 UI는 기본적으로 `http://127.0.0.1:5173`에서 실행됩니다. 다른 API 주소를 사용할
경우 `frontend/.env`에 다음 값을 설정합니다.

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Docker로 실행

Docker Desktop을 실행한 뒤 프로젝트 루트에서 진행합니다. 로컬 Python·Node 설치는
필요하지 않습니다. 기존 수동 실행 방식도 그대로 사용할 수 있습니다.

```bash
# 처음 실행할 때만 복사하고 두 API 키를 입력합니다. 기존 .env는 덮어쓰지 마세요.
cp -n .env.example .env

docker compose up --build -d
```

- 웹: http://localhost:3000
- API 문서: http://localhost:8000/docs
- 상태 확인: `docker compose ps`
- 로그: `docker compose logs -f backend frontend`
- 중지: `docker compose down`

React 빌드 결과는 Nginx가 제공하며 `/api` 요청을 FastAPI로 전달합니다. API의
상태 확인이 성공한 다음 웹이 시작됩니다. SQLite 체크포인트와 요청 잠금의 현재
설계에 맞춰 API는 **단일 워커**로 실행하며 공개 배포용 인증은 추가하지 않습니다.
호스트 포트는 로컬에서만 접근하도록 바인딩합니다.

상품 DB와 대화 기록은 루트 `data/` 폴더를 컨테이너의 `/app/data`에 연결해 유지합니다.
컨테이너 중지·재생성으로 이 파일들이 삭제되지는 않습니다. 새 설치에는 상품이
없으므로 아래 배치를 한 번 실행해야 합니다. 기존 `savings.db`가 있다면 그대로
사용합니다. `.env`, DB, 로컬 의존성은 이미지에 포함하지 않습니다.

```bash
# 상품 수집 및 검증: FINLIFE_API_KEY, GEMINI_API_KEY 필요, Gemini 호출 비용 발생
docker compose --profile batch run --rm batch

# 하루 간격 갱신: 별도 터미널에서 실행, 중지 Ctrl+C
docker compose --profile batch run --rm batch \
  python scripts/run_savings_batch.py --db-path /app/data/savings.db --interval-seconds 86400
```

포트가 이미 사용 중이면 `.env`에 `VERIFIT_WEB_PORT=3001`, `VERIFIT_API_PORT=8001`을
설정합니다. 데이터 위치도 `VERIFIT_DATA_DIR=/절대경로/data`로 변경할 수 있습니다.
Linux에서 호스트 데이터 폴더에 쓰기 권한 오류가 나면 컨테이너 사용자 UID `10001`에
쓰기 권한을 부여해야 합니다. API 키 변경은 `docker compose up -d --force-recreate`,
코드 변경은 `docker compose up --build -d`로 반영합니다.

이미지 내부 테스트는 실제 API 키나 호스트 DB 없이 실행할 수 있습니다.

```bash
docker build -f backend/Dockerfile --target test -t verifit-backend-test .
docker run --rm verifit-backend-test
docker build -f frontend/Dockerfile --target test -t verifit-frontend-test .
docker run --rm verifit-frontend-test
```

## 캐싱

Compose는 Redis를 함께 실행하며, 수동 실행에서 `REDIS_URL`이 없으면 메모리 캐시를
사용합니다. SQLite는 상품·대화의 원본 저장소로 유지합니다.

| 대상 | 키에 포함되는 정보 | 기본 유효기간 |
|---|---|---|
| 상품 KG | DB 고유 ID + 상품 데이터 revision | 1시간 |
| 금리·이자·추가 질문 계산 | 전체 상품 스냅샷 + 정규화한 사용자 프로필 | 30분 |
| 시나리오 비교 | 상품 스냅샷 + 기준 프로필 + 변경 가정 | 30분 |
| Analyzer·Writer·Reviewer | 모델·계정 해시 + 전체 프롬프트·스키마·입력·피드백 | 10분 |
| 최종 Agent 결과 | 전체 사용자 대화 + 상품 스냅샷 + 모델·계정 해시 | 10분 |
| 대화 결과 복원 | 대화 ID + SQLite 체크포인트 ID | 10분 |
| 배치 추출·검토 | 모델·계정 해시 + 원문·금리·프롬프트·피드백 | 10분 |

모든 키에 앱 소스 버전 해시가 들어가므로 계산 코드·프롬프트·스키마가 바뀌면
기존 캐시를 재사용하지 않습니다. 상품 테이블 변경은 SQLite 트리거가 같은 트랜잭션에서
revision을 갱신합니다. 배치, 비활성화, 직접 SQL 변경도 다음 요청부터 새 KG 캐시를
사용하고, 해당 상품 스냅샷을 사용하는 계산·답변 키도 바뀝니다. 이전 캐시는 TTL로
정리됩니다. 커밋되지 않은 상품은 공유 캐시에 넣지 않습니다.

최종 결과 캐시가 적중해도 요청자의 별도 `thread_id`와 체크포인트를 저장해 후속
대화가 이어집니다. HTTP 오류·파싱 실패·거부된 검토·최종 실패 및 fallback 응답은
최종 성공 결과처럼 캐싱하지 않습니다. LLM 단계의 구조화 출력은 캐시에서 가져온
경우에도 그래프의 입력·금융 수치·근거 검증을 거칩니다. 배치의 self-consistency는
독립적인 N회 추출 결과를 **한 세트**로 캐싱해, 같은 응답을 N번 복제하지 않습니다.
금융감독원 수집, DB 쓰기, 체크포인트 쓰기와 상태 점검은 캐싱하지 않습니다.

Redis는 호스트 포트를 열지 않고 영속화를 끕니다. 사용자 입력·결과가 TTL 동안
Redis 메모리에 포함되지만 키에는 원문이나 API 키를 넣지 않습니다. Redis는 128MB
한도와 LRU 제거, 로컬 캐시는 512건·32MB 한도, 단일 값은 2MB 한도를 사용합니다.
Redis 장애 시 짧은 타임아웃 후 메모리 캐시로 전환하며 복구 시 Redis를 다시 조회합니다.
캐시가 없어도 SQLite·계산·LLM 경로로 정상 동작합니다. 동일 요청 중복 계산 억제는
현재 단일 API 프로세스 안에서만 적용됩니다.

설정은 `.env.example`의 `CACHE_*`를 참고하세요. `CACHE_ENABLED=false`로 전체 캐시를
우회하거나 대상 TTL을 `0`으로 지정해 해당 계층만 끌 수 있습니다. Compose에서 설정을
바꾸면 `docker compose up -d --force-recreate`로 반영합니다.

```bash
# 키나 사용자 내용 없이 프로세스의 계층별 hit/miss/store 확인
curl http://localhost:3000/api/v1/cache/status

# Redis 캐시 전체 비우기 (원본 SQLite DB와 대화 기록은 유지)
docker compose exec redis redis-cli FLUSHDB
```

모델 회귀·실제 모델 검증 스크립트는 캐시를 우회합니다. 과거 캐시 적중을 새 모델의
성능이나 실제 호출 결과로 기록하지 않습니다.

## API

### `POST /api/v1/ask`

자연어로 사용자 조건을 전달하는 Agent API입니다.

```json
{
  "message": "매달 30만 원씩 1년 넣고 싶고 급여이체는 가능해. 조건에 맞춰 비교해줘."
}
```

필수 정보가 부족하면 `needs_input`과 질문을 반환합니다. 후속 요청에는 응답에서 받은
`thread_id`를 함께 전달합니다.

```json
{
  "thread_id": "이전 응답에서 받은 값",
  "message": "매달 30만 원이야."
}
```

### `POST /api/v1/evaluate`

구조화된 사용자 조건을 직접 계산하는 API입니다.

```json
{
  "monthly_deposit_won": 300000,
  "term_months": 12,
  "facts": {
    "salary_transfer": {
      "satisfied": true,
      "months": 12
    },
    "card_usage_amount": {
      "satisfied": false
    }
  }
}
```

### `GET /health`

API 서버의 실행 상태를 확인합니다.

### `GET /api/v1/ask/{thread_id}`

SQLite 체크포인트의 마지막 응답을 복원합니다. 없는 대화는 404를 반환합니다.
브라우저는 현재 탭의 `sessionStorage`에 대화 ID만 보관합니다. 새 비교는 이 연결을
끊고 별도 대화로 시작합니다. 저장된 응답은 당시 공시의 스냅샷이며 후속 요청 시
최신 KG로 재계산합니다.

### `POST /api/v1/scenarios`

`baseline: UserProfile`과 `scenarios: [{name, profile}]`을 전달합니다. 최대 5개 가정을
LLM 없이 동일 계산 엔진으로 평가하고 상품별 세후 이자 증감과 순위를 반환합니다.
가입 불가 상품은 `excluded_results`로 분리됩니다. `unknown` 자격 후보는 확인 필요입니다.

## 테스트와 빌드

```bash
# 백엔드
cd backend
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_online_regression.py

# 실제 모델/프롬프트 회귀 평가: Gemini 호출 비용 발생
.venv/bin/python scripts/run_online_regression.py --live

# 기존 상품 DB 복사본으로 실제 Agent 2턴 검증 (Gemini 호출 비용 발생)
.venv/bin/python scripts/validate_live_workflow.py

# 프론트엔드
cd frontend
npm test
npm run build
npm run lint
```

검증 규칙과 설계 의도는 각 서비스 모듈의 docstring에도 기록되어 있습니다.

자동 테스트는 원문 숫자 검증, 삼상 판정, 우대 한도·중복 제한, 가입 자격,
가정 비교, 저장 롤백, 최신 공시 조회, 실제 SQLite 재시작 복원 및 화면 사용자 흐름을
포함합니다. `online_gold.json`은 수작업 정답 9건이며 `--live`를 주지 않은 실행은
정답의 계약 검증이지 모델 성능 평가가 아닙니다. 실제 호출 보고서에는 모델과
프롬프트 소스 해시가 기록됩니다.

## 운영 범위

- 현재는 인증 없는 로컬·단일 프로세스 서비스입니다. 공개 배포에는 사용자별 접근 제어와
  다중 워커용 체크포인트/잠금 설계가 별도로 필요합니다. 대화 ID를 타인에게 공유하지 마세요.
- `other` 가입 자격과 원문에 없는 세부 기준은 자동 확정하지 않습니다. 상품별 약관과
  실제 적용금리는 금융회사 확인이 필요합니다. 사용자 fact는 해당 금융회사 기준의 정보여야 합니다.
- 가정 상한은 미확인 우대의 조합 상한이지 실제 수익 약속이 아닙니다. 미확인 규칙 사이의
  상충 가능성까지 완전히 입증하는 금융상품 가입 판정기가 아닙니다.
- 갱신은 배치 실행 주기에 따릅니다. API에서 사라진 상품의 판매 종료를 자동 확정하지는
  않습니다. 일부 상품만 검증된 경우 그 옵션만 제공합니다.

- `backend/app/services/extractor.py`
- `backend/app/services/verification.py`
- `backend/app/services/online_agent_llm.py`
- `backend/app/agent/nodes.py`
