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
- 반영된 우대조건과 미반영 우대조건
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
POST /api/v1/ask
        ↓
Online LangGraph Agent
        ↓
SQLite Knowledge Graph 조회
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
- 라이트·다크 테마
- 데스크톱 2열 및 모바일 1열 반응형 레이아웃

## 기술 스택

| 영역 | 기술 |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic |
| Agent workflow | LangGraph, MemorySaver checkpointer |
| LLM | Gemini Extractor / Analyzer / Writer / Reviewer |
| Database | SQLite |
| Data source | 금융감독원 금융상품 한눈에 API |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Validation | Pytest, Pydantic JSON Schema, 결정론적 계산 검증 |

## 프로젝트 구조

```text
savings_agent/
├─ backend/
│  ├─ app/
│  │  ├─ agent/          # 사용자 질의 Online LangGraph
│  │  ├─ api/routes/     # ask, evaluate, health API
│  │  ├─ db/             # SQLite 스키마·저장·조회
│  │  ├─ graph/          # 상품 추출 Offline LangGraph
│  │  ├─ integrations/   # 금융상품 한눈에 연동
│  │  ├─ schemas/        # Graph·Agent·사용자 스키마
│  │  └─ services/       # 추출·검증·계산·매칭
│  ├─ scripts/           # 상품 구축 배치
│  └─ tests/
├─ frontend/
│  └─ src/
│     ├─ components/     # 상품 카드·근거 drawer·공용 UI
│     ├─ design-system/  # 토큰·테마·타이포그래피
│     ├─ lib/            # API client
│     └─ types/          # API 타입
└─ data/
   └─ savings.db
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
```

### 2. 상품 데이터 구축

```bash
cd backend

# 소량 실행
.venv/bin/python scripts/run_savings_batch.py --limit 5 --db-path ../data/savings.db

# 전체 실행
.venv/bin/python scripts/run_savings_batch.py --db-path ../data/savings.db
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

## 테스트와 빌드

```bash
# 백엔드
cd backend
.venv/bin/python -m pytest -q

# 프론트엔드
cd frontend
npm run build
```

검증 규칙과 설계 의도는 각 서비스 모듈의 docstring에도 기록되어 있습니다.

- `backend/app/services/extractor.py`
- `backend/app/services/verification.py`
- `backend/app/services/online_agent_llm.py`
- `backend/app/agent/nodes.py`
