# Google Play 사전등록 게임 모니터링

Google Play 스토어의 사전등록 게임을 모니터링하고 신규 게임이 추가되면 Slack으로 알림을 보내는 시스템입니다.

## 기능

- Google Play 사전등록 게임 목록 크롤링
- JSON 파일로 게임 목록 저장 및 비교
- 신규 게임 추가 시 Slack 알림
- 사전등록 종료/출시 게임 알림
- GitHub Actions를 통한 자동 실행 (매일 오전 9시 30분 KST)

## 설정 방법

### 1. Repository 생성 및 코드 푸시

```bash
cd google-play-preregister-monitor
git init
git add .
git commit -m "feat: initial commit"
git remote add origin https://github.com/YOUR_USERNAME/google-play-preregister-monitor.git
git push -u origin main
```

### 2. Slack Webhook 설정

1. [Slack API](https://api.slack.com/apps)에서 새 앱 생성
2. **Incoming Webhooks** 활성화
3. **Add New Webhook to Workspace** 클릭
4. 알림 받을 채널 선택
5. Webhook URL 복사

### 3. GitHub Secrets 설정

1. GitHub Repository → Settings → Secrets and variables → Actions
2. **New repository secret** 클릭
3. Name: `SLACK_WEBHOOK_URL`
4. Value: 복사한 Slack Webhook URL

### 4. GitHub Actions 권한 설정

1. Repository → Settings → Actions → General
2. **Workflow permissions** 섹션에서 **Read and write permissions** 선택
3. Save

## 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정 (선택)
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# 실행
python main.py
```

## 파일 구조

```
.
├── main.py              # 메인 크롤링 스크립트
├── games.json           # 저장된 게임 목록
├── requirements.txt     # Python 의존성
├── .github/
│   └── workflows/
│       └── check.yml    # GitHub Actions 워크플로우
└── README.md
```

## 알림 예시

Slack에서 다음과 같은 알림을 받게 됩니다:

```
🎮 Google Play 사전등록 게임 업데이트

🆕 신규 사전등록 게임 (3개)
• Game Title 1
• Game Title 2
• Game Title 3

🚀 사전등록 종료/출시 (1개)
• Released Game

⏰ 확인 시각: 2024-01-15 09:30:00 KST
```

## 수동 실행

GitHub Actions 페이지에서 **Run workflow** 버튼을 클릭하여 수동으로 실행할 수 있습니다.

## 주의사항

- Google Play 페이지 구조가 변경되면 크롤링이 실패할 수 있습니다
- 너무 자주 실행하면 IP가 차단될 수 있으니 주의하세요
- Slack Webhook URL은 절대 코드에 직접 포함하지 마세요
