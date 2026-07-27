#!/usr/bin/env python3
"""CGV 빈자리(취소표) 감시 스크립트.

k-skill(daiso)의 CGV 연동 방식을 참고해 api.cgv.co.kr 를 직접 호출한다.
지정한 극장/날짜의 상영시간표를 주기적으로 조회해서, 키워드(기본: 오디세이)에
해당하는 회차에 잔여석이 생기면 알림을 울리고 예매 페이지를 연다.

예매/결제 자체는 자동화하지 않는다 — 자리가 나면 즉시 알려주는 것까지가 역할이다.

사용 예:
    python3 cgv_watcher.py --list-theaters 용산
    python3 cgv_watcher.py --theater 0013 --date 20260727 --keyword 오디세이
    python3 cgv_watcher.py --theater 0013 --date 20260727 20260728 \
        --screen IMAX --time-from 1000 --time-to 2300 --interval 30

표준 라이브러리만 사용한다 (python3.8+).
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone, timedelta

BASE_URL = "https://api.cgv.co.kr"
COMPANY_CODE = "A420"
SIGNING_SECRET = "ydqXY0ocnFLmJGHr_zNzFcpjwAsXq_8JcBNURAkRscg"
THEATER_LIST_PATH = "/cnm/atkt/searchRegnList"
TIMETABLE_BY_SITE_PATH = "/cnm/atkt/searchMovScnInfo"
TIMETABLE_SITE_SCOPE_CODE = "08"
BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/movieChoice"

KST = timezone(timedelta(hours=9))


def sign(path: str, timestamp: str, body: str = "") -> str:
    payload = f"{timestamp}|{path}|{body}".encode("utf-8")
    digest = hmac.new(SIGNING_SECRET.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def request_cgv(path: str, params: dict, timeout: int = 15) -> dict:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    timestamp = str(int(time.time()))
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Language": "ko-KR",
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": sign(path, timestamp),
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_theaters() -> list:
    resp = request_cgv(THEATER_LIST_PATH, {"coCd": COMPANY_CODE})
    theaters = []
    for region in resp.get("data") or []:
        for site in region.get("siteList") or []:
            if site.get("siteNo") and site.get("siteNm"):
                theaters.append(
                    {
                        "theaterCode": site["siteNo"],
                        "theaterName": site["siteNm"],
                        "regionName": region.get("regnGrpNm", ""),
                    }
                )
    return theaters


def fetch_timetable(theater_code: str, play_date: str) -> list:
    resp = request_cgv(
        TIMETABLE_BY_SITE_PATH,
        {
            "coCd": COMPANY_CODE,
            "siteNo": theater_code,
            "scnYmd": play_date,
            "rtctlScopCd": TIMETABLE_SITE_SCOPE_CODE,
        },
    )
    return resp.get("data") or []


def to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def fmt_time(value) -> str:
    s = str(value or "")
    return f"{s[:2]}:{s[2:4]}" if len(s) >= 4 else s


def item_text(item: dict) -> str:
    """회차의 모든 문자열 필드를 합쳐 검색 대상으로 만든다."""
    return " ".join(str(v) for v in item.values() if isinstance(v, str))


def matches(item: dict, keywords: list, screen_filters: list,
            time_from: str, time_to: str) -> bool:
    name = f"{item.get('movNm', '')} {item.get('prodNm', '')}".lower()
    if keywords and not any(k.lower() in name for k in keywords):
        return False
    if screen_filters:
        haystack = item_text(item).lower()
        if not any(s.lower() in haystack for s in screen_filters):
            return False
    start = str(item.get("scnsrtTm", "") or "")[:4]
    if time_from and start and start < time_from:
        return False
    if time_to and start and start > time_to:
        return False
    return True


def send_telegram(token: str, chat_id: str, text: str):
    """텔레그램 봇으로 메시지 전송 (폰 알림용)."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as r:
            r.read()
        print("텔레그램 알림 전송 완료")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"텔레그램 전송 실패: {e}")


def telegram_print_chat_id(token: str):
    """봇에게 아무 메시지나 보낸 뒤 실행하면 chat_id를 알려준다."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    with urllib.request.urlopen(url, timeout=10) as r:
        updates = json.loads(r.read().decode("utf-8"))
    chats = {}
    for u in updates.get("result", []):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("id"):
            name = chat.get("first_name") or chat.get("title") or ""
            chats[chat["id"]] = name
    if not chats:
        print("메시지가 없습니다. 폰에서 봇에게 아무 메시지나 먼저 보낸 뒤 다시 실행하세요.")
        return
    for cid, name in chats.items():
        print(f"chat_id: {cid}  ({name})")


def notify(title: str, message: str, notify_cmd: str = ""):
    system = platform.system()
    if notify_cmd:
        subprocess.Popen(
            notify_cmd.replace("{title}", title).replace("{message}", message),
            shell=True,
        )
        return
    if system == "Darwin":
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.Popen(["osascript", "-e", script])
        for _ in range(3):
            subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
            time.sleep(0.4)
    elif shutil.which("notify-send"):
        subprocess.Popen(["notify-send", title, message])
    print("\a", end="", flush=True)


def open_booking_page():
    try:
        webbrowser.open(BOOKING_URL)
    except Exception:
        pass


def alert(hits: list, theater_names: dict, args):
    lines = []
    for item in hits:
        theater = theater_names.get(item.get("siteNo"), item.get("siteNm", ""))
        lines.append(
            f"{item.get('scnYmd')} {fmt_time(item.get('scnsrtTm'))} "
            f"{item.get('movNm') or item.get('prodNm')} @ {theater} "
            f"잔여 {to_int(item.get('frSeatCnt') or item.get('frtmpSeatCnt'))}석"
        )
    banner = "\n".join(lines)
    print("\n" + "=" * 60)
    print("🎬 빈자리 발견! 지금 바로 예매하세요!")
    print(banner)
    print(f"예매: {BOOKING_URL}")
    print("=" * 60 + "\n")
    notify("CGV 빈자리 발견!", lines[0], args.notify_cmd)
    if args.tg_token and args.tg_chat_id:
        send_telegram(args.tg_token, args.tg_chat_id,
                      f"🎬 CGV 빈자리 발견!\n{banner}\n\n바로 예매 👉 {BOOKING_URL}")
    if not args.no_open:
        open_booking_page()


def schedule_key(item: dict) -> str:
    return f"{item.get('scnYmd')}|{item.get('siteNo')}|{item.get('scnSseq') or item.get('scnsrtTm')}"


def run_watch(args):
    theaters = fetch_theaters()
    theater_names = {t["theaterCode"]: t["theaterName"] for t in theaters}
    codes = []
    for t in args.theater:
        if t.isdigit():
            codes.append(t.zfill(4))
        else:
            found = [x["theaterCode"] for x in theaters if t in x["theaterName"]]
            if not found:
                sys.exit(f"극장을 찾을 수 없습니다: {t} (--list-theaters 로 확인)")
            codes.extend(found)
    codes = list(dict.fromkeys(codes))
    names = ", ".join(theater_names.get(c, c) for c in codes)
    screens = ", ".join(s for s in args.screen if s) or "전체"
    window = f"{args.time_from or '처음'}~{args.time_to or '끝'}"
    print(f"감시 시작 — 극장: {names} | 날짜: {', '.join(args.date)} | "
          f"키워드: {', '.join(args.keyword)} | 상영관: {screens} | "
          f"시간대: {window} | 주기: {args.interval}초")
    if args.tg_token and args.tg_chat_id:
        send_telegram(args.tg_token, args.tg_chat_id,
                      f"👀 CGV 감시 시작\n극장: {names}\n날짜: {', '.join(args.date)}\n"
                      f"상영관: {screens} | {window}\n자리 나면 바로 알려드릴게요!")
    else:
        print("(텔레그램 미설정 — 폰 알림을 받으려면 README의 텔레그램 설정 참고)")

    seen = {}  # schedule_key -> 마지막 관측 잔여석 수 (0 = 매진 상태)
    alerted_at = {}  # schedule_key -> 마지막 알림 시각 (같은 회차 반복 알림 쿨다운)
    first_pass = args.baseline
    while True:
        hits = []
        status = []
        for date in args.date:
            for code in codes:
                try:
                    items = fetch_timetable(code, date)
                except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
                    print(f"[{datetime.now(KST):%H:%M:%S}] 조회 실패 ({code}/{date}): {e}")
                    continue
                for item in items:
                    if not matches(item, args.keyword, args.screen,
                                   args.time_from, args.time_to):
                        continue
                    if args.debug:
                        print(json.dumps(item, ensure_ascii=False))
                    remaining = to_int(item.get("frSeatCnt") or item.get("frtmpSeatCnt"))
                    key = schedule_key(item)
                    status.append(
                        f"{date} {fmt_time(item.get('scnsrtTm'))} "
                        f"{theater_names.get(code, code)} 잔여 {remaining}석"
                    )
                    # 잔여석이 늘어날 때마다 알림 — 첫 자리가 마음에 안 들어
                    # 패스해도, 새 취소표가 나오면 다시 울린다. 단, 같은 회차가
                    # 선점/해제로 계속 출렁일 때의 알림 폭탄은 쿨다운으로 막는다.
                    was = seen.get(key, 0)
                    cooled = time.time() - alerted_at.get(key, 0) >= args.cooldown * 60
                    if remaining >= args.min_seats and remaining > was and cooled:
                        hits.append(item)
                        alerted_at[key] = time.time()
                    seen[key] = remaining
        now = f"[{datetime.now(KST):%H:%M:%S}]"
        if first_pass:
            # 시작 시점의 잔여석은 기준선으로만 기록하고 알리지 않는다.
            first_pass = False
            print(f"{now} 기준선 기록: " + (" | ".join(status) or "회차 없음"))
            hits = []
        if hits:
            alert(hits, theater_names, args)
            if args.exit_on_hit:
                return
        elif status:
            print(f"{now} " + " | ".join(status))
        else:
            print(f"{now} 조건에 맞는 회차가 없습니다 (키워드/극장/날짜 확인, --debug 로 원본 확인)")
        if args.once:
            return
        time.sleep(args.interval + random.uniform(0, args.interval * 0.3))


def main():
    p = argparse.ArgumentParser(description="CGV 빈자리(취소표) 감시")
    p.add_argument("--keyword", nargs="+", default=["오디세이", "odyssey"],
                   help="영화 제목 키워드 (기본: 오디세이 odyssey)")
    p.add_argument("--theater", nargs="+", default=["용산"],
                   help="극장 이름 일부 또는 극장 코드 (기본: 용산)")
    p.add_argument("--date", nargs="+", default=["20260808", "20260809"],
                   help="상영 날짜 YYYYMMDD, 여러 개 가능 (기본: 20260808 20260809)")
    p.add_argument("--screen", nargs="+", default=["IMAX"],
                   help="상영관 필터 문자열 (기본: IMAX, 전체는 --screen '')")
    p.add_argument("--time-from", default="", help="이 시각(HHMM) 이후 회차만")
    p.add_argument("--time-to", default="2059",
                   help="이 시각(HHMM) 이전 시작 회차만 (기본: 2059 = 21시 전)")
    p.add_argument("--min-seats", type=int, default=1, help="알림 기준 최소 잔여석 (기본: 1)")
    p.add_argument("--cooldown", type=int, default=15,
                   help="같은 회차 재알림 최소 간격(분, 기본: 15)")
    p.add_argument("--interval", type=int, default=30, help="조회 주기 초 (기본: 30)")
    p.add_argument("--once", action="store_true", help="1회만 조회하고 종료")
    p.add_argument("--baseline", action="store_true",
                   help="시작 시점 잔여석은 알리지 않고 기준선으로만 기록 (이후 증가분만 알림)")
    p.add_argument("--exit-on-hit", action="store_true",
                   help="알림 발생 시 종료 (외부 슈퍼바이저/알림 연동용)")
    p.add_argument("--debug", action="store_true", help="매칭된 회차의 원본 JSON 출력")
    p.add_argument("--no-open", action="store_true", help="알림 시 브라우저를 열지 않음")
    p.add_argument("--notify-cmd", default="",
                   help="커스텀 알림 명령, {title} {message} 치환")
    p.add_argument("--tg-token", default=os.environ.get("CGV_TG_TOKEN", ""),
                   help="텔레그램 봇 토큰 (환경변수 CGV_TG_TOKEN 로도 지정 가능)")
    p.add_argument("--tg-chat-id", default=os.environ.get("CGV_TG_CHAT_ID", ""),
                   help="텔레그램 chat_id (환경변수 CGV_TG_CHAT_ID 로도 지정 가능)")
    p.add_argument("--tg-get-chat-id", action="store_true",
                   help="봇에게 메시지를 보낸 뒤 실행하면 내 chat_id를 알려줌")
    p.add_argument("--list-theaters", nargs="?", const="", metavar="키워드",
                   help="극장 목록 출력 (키워드로 필터 가능)")
    args = p.parse_args()

    if args.tg_get_chat_id:
        if not args.tg_token:
            sys.exit("--tg-token (또는 CGV_TG_TOKEN) 이 필요합니다.")
        telegram_print_chat_id(args.tg_token)
        return

    if args.list_theaters is not None:
        for t in fetch_theaters():
            if args.list_theaters in t["theaterName"]:
                print(f"{t['theaterCode']}  {t['theaterName']}  ({t['regionName']})")
        return

    if args.interval < 10:
        print("경고: 10초 미만 주기는 차단당할 수 있어 10초로 조정합니다.")
        args.interval = 10

    try:
        run_watch(args)
    except KeyboardInterrupt:
        print("\n감시 종료")


if __name__ == "__main__":
    main()
