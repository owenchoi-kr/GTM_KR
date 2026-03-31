# 게임 사전등록 모니터링

여러 게임 플랫폼의 사전등록/사전예약/출시 게임을 모니터링하고, 변경사항이 있으면 Slack으로 알림을 보내는 시스템입니다.

## 모니터링 소스

| 소스 | URL | 수집 방식 | 수집 정보 | 저장 파일 |
|------|-----|-----------|-----------|-----------|
| 🎮 Google Play | [사전등록 컬렉션](https://play.google.com/store/apps/collection/promotion_3000000d51_pre_registration_games?hl=ko) | Playwright (JS 렌더링) | 게임명, 개발사 | `games.json` |
| 📋 인벤 | [pick.inven.co.kr](https://pick.inven.co.kr/) | requests + BeautifulSoup | 게임명, 개발사, 출시일, 보상 | `inven_games.json` |
| 🟡 카카오게임즈 | [game.kakao.com/pr](https://game.kakao.com/pr) | requests (AJAX API) | 게임명 | `kakao_games.json` |
| 🟣 원스토어 | [사전예약](https://m.onestore.co.kr/v2/ko-kr/event/preregistrations) | requests (RSC 데이터 파싱) | 게임명, 개발사 | `onestore_games.json` |
| 🟢 네이버게임 | [game.naver.com](https://game.naver.com/) | requests (REST API) | 게임명, 출시일, 플랫폼 | `naver_games.json` |
| 📅 wame.is | [wame.is/ko/upcoming](https://wame.is/ko/upcoming) | Playwright (API 응답 가로채기) | 게임명, 플랫폼, 퍼블리셔, 출시일 | - (매주 월요일) |

## 기능

- 5개 플랫폼의 사전등록/출시 게임 목록 크롤링
- JSON 파일로 게임 목록 저장 및 이전 데이터와 비교
- **신규 게임이 추가되었을 때만** 해당 게임 정보를 Slack으로 알림 (게임명, 개발사 등)
- **wame.is 신작 게임 캘린더**: 매주 월요일 향후 2개월 출시 예정 게임 목록 (타이틀, 플랫폼, 퍼블리셔) 자동 전송
- 변경사항이 없으면 알림 없음
- GitHub Actions를 통한 자동 실행 (매일 오전 9시 30분 KST)

## 설정 방법

### 1. Slack Webhook 설정

1. [Slack API](https://api.slack.com/apps)에서 새 앱 생성
2. **Incoming Webhooks** 활성화
3. **Add New Webhook to Workspace** 클릭
4. 알림 받을 채널 선택
5. Webhook URL 복사

### 2. GitHub Secrets 설정

1. GitHub Repository → Settings → Secrets and variables → Actions
2. **New repository secret** 클릭
3. Name: `SLACK_WEBHOOK_URL`, Value: Slack Webhook URL
4. Name: `SLACK_BOT_TOKEN`, Value: NewGameBot Bot Token (`xoxb-...`, `chat:write` scope 필요)

> `SLACK_BOT_TOKEN`이 설정되면 `chat.postMessage` API로 전환되어 스레드 기능이 활성화됩니다.
> 설정하지 않으면 기존 Webhook 방식으로 동작합니다 (스레드 미지원).

### 3. GitHub Actions 권한 설정

1. Repository → Settings → Actions → General
2. **Workflow permissions** → **Read and write permissions** 선택
3. Save

## 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

# 환경변수 설정
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# 실행
python main.py
```

## 파일 구조

```
.
├── main.py                # 메인 크롤링 스크립트
├── games.json             # Google Play 게임 목록
├── inven_games.json       # 인벤 사전예약 목록
├── kakao_games.json       # 카카오게임즈 사전예약 목록
├── onestore_games.json    # 원스토어 사전예약 목록
├── naver_games.json       # 네이버게임 이번 달 출시 목록
├── requirements.txt       # Python 의존성
├── .github/
│   └── workflows/
│       └── check.yml      # GitHub Actions 워크플로우
└── README.md
```

## 자동 실행

GitHub Actions가 매일 오전 9:30 KST (UTC 0:30)에 자동 실행되며, 수집된 JSON 파일은 자동으로 커밋/푸시됩니다.

수동 실행: GitHub Actions 페이지 → **Run workflow** 버튼

## 주의사항

- 각 사이트의 페이지 구조나 API가 변경되면 크롤링이 실패할 수 있습니다
- Slack Webhook URL은 절대 코드에 직접 포함하지 마세요
