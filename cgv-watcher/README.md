# CGV 빈자리(취소표) 감시 — 오디세이

[k-skill(daiso)](https://github.com/NomaDamas/k-skill/blob/main/docs/features/korean-cinema-search.md)의
CGV 연동 방식을 참고해 `api.cgv.co.kr`를 직접 호출하는 감시 스크립트입니다.
지정한 극장/날짜의 상영시간표를 주기적으로 조회해서, 오디세이 회차에 잔여석이
생기는 순간 소리·알림을 울리고 CGV 예매 페이지를 자동으로 엽니다.

> k-skill 문서에 명시된 대로 **예매·결제 자체는 자동화하지 않습니다.**
> 결제까지 자동화하면 CGV 이용약관 위반 소지가 있고, 부정예매로 취소될 수 있습니다.
> 이 스크립트는 "자리가 나면 사람보다 먼저 알려주는 것"까지가 역할입니다.

## 사용법

파이썬 표준 라이브러리만 사용하므로 설치할 것이 없습니다. (python3.8+)

```bash
# 1. 극장 코드 확인
python3 cgv_watcher.py --list-theaters 용산

# 2. 감시 시작 (기본값: 용산 / 오늘 / 키워드 "오디세이")
python3 cgv_watcher.py

# 예: 용산 IMAX, 7/27~28, 저녁 회차만, 20초 간격
python3 cgv_watcher.py --theater 용산 --date 20260727 20260728 \
    --screen IMAX --time-from 1700 --interval 20

# 응답 필드 구조 확인 (상영관 필터를 정확히 맞추고 싶을 때)
python3 cgv_watcher.py --once --debug
```

### 주요 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--keyword` | 영화 제목 키워드(여러 개 가능) | `오디세이 odyssey` |
| `--theater` | 극장 이름 일부 또는 코드(여러 개 가능) | `용산` |
| `--date` | 상영일 `YYYYMMDD`(여러 개 가능) | 오늘(KST) |
| `--screen` | 상영관 필터(예: `IMAX`) | 없음(전체) |
| `--time-from` / `--time-to` | 회차 시작시각 범위 `HHMM` | 없음 |
| `--min-seats` | 알림 기준 최소 잔여석 | `1` |
| `--interval` | 조회 주기(초, 지터 자동 추가) | `30` |
| `--notify-cmd` | 커스텀 알림 명령 (`{title}`, `{message}` 치환) | macOS 알림+사운드 |
| `--once` / `--debug` / `--no-open` | 1회 실행 / 원본 JSON / 브라우저 안 열기 | - |

알림이 오면 열려 있는 CGV 예매 페이지에서 **직접 로그인 상태로 빠르게 결제**하세요.
취소표는 수 초 안에 사라지므로, 미리 CGV 앱/웹에 로그인 + 결제수단 등록을 해두는 걸 권장합니다.

### 텔레그램 알림 예시

```bash
python3 cgv_watcher.py --notify-cmd \
  'curl -s "https://api.telegram.org/bot<TOKEN>/sendMessage" -d chat_id=<CHAT_ID> -d text="{title} {message}"'
```

## 동작 원리

- `GET /cnm/atkt/searchMovScnInfo` — 극장+날짜 기준 전체 회차와
  회차별 잔여석(`frSeatCnt`)/총좌석(`stcnt`)을 반환합니다.
- 요청마다 `X-TIMESTAMP`와 HMAC-SHA256 서명(`X-SIGNATURE`)이 필요하며,
  서명 방식은 daiso 패키지 구현을 따랐습니다.
- 잔여석이 0 → 기준치 이상으로 바뀌는 순간에만 알림을 보내 중복 알림을 막습니다.
- 조회 주기에 랜덤 지터를 넣고 최소 10초로 제한해 서버에 부담을 주지 않습니다.
