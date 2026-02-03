#!/usr/bin/env python3
"""Google Play 사전등록 게임 모니터링 시스템

Google Play 게임 페이지에서 "사전 등록" 섹션을 찾아 게임 목록을 수집합니다.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# 설정
GAMES_FILE = Path(__file__).parent / "games.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# 사전등록 게임 컬렉션 URL
PREREGISTER_URL = "https://play.google.com/store/apps/collection/promotion_3000000d51_pre_registration_games?hl=ko"


def fetch_preregister_games() -> list[dict]:
    """Google Play에서 사전등록 게임 목록을 가져옵니다."""
    games = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="ko-KR",
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # 사전등록 게임 컬렉션 페이지 로드
        print(f"사전등록 게임 페이지 로드 중...")
        print(f"URL: {PREREGISTER_URL}")
        try:
            page.goto(PREREGISTER_URL, timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeout:
            print("페이지 로드 타임아웃, 계속 진행...")

        # 페이지 스크롤하여 모든 게임 로드
        print("페이지 스크롤 중...")
        prev_height = 0
        for i in range(20):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)
            curr_height = page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                print(f"  스크롤 완료 (총 {i+1}회)")
                break
            prev_height = curr_height

        # 앱 링크 추출
        print("\n게임 목록 추출 중...")
        app_links = page.locator("a[href*='/store/apps/details']").all()
        print(f"  발견된 앱 링크: {len(app_links)}개")

        for link in app_links:
            try:
                href = link.get_attribute("href")
                if not href:
                    continue

                app_id_match = re.search(r"id=([a-zA-Z0-9_.]+)", href)
                if not app_id_match:
                    continue

                app_id = app_id_match.group(1)
                if app_id in seen_ids:
                    continue

                # 앱 이름 추출
                title = link.inner_text().strip()
                if title:
                    title = title.split("\n")[0].strip()

                if not title or len(title) < 2:
                    # 이미지 alt 텍스트에서 찾기
                    img = link.locator("img").first
                    if img.count() > 0:
                        title = img.get_attribute("alt") or app_id

                if title and len(title) >= 2:
                    seen_ids.add(app_id)
                    games.append({
                        "id": app_id,
                        "title": title,
                        "url": f"https://play.google.com/store/apps/details?id={app_id}&hl=ko",
                    })
                    print(f"  + {title}")

            except Exception as e:
                continue

        browser.close()

    print(f"\n총 {len(games)}개의 사전등록 게임 발견")
    return games


def load_saved_games() -> list[dict]:
    """저장된 게임 목록을 불러옵니다."""
    if not GAMES_FILE.exists():
        return []

    try:
        with open(GAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("games", [])
    except (json.JSONDecodeError, IOError):
        return []


def save_games(games: list[dict]) -> None:
    """게임 목록을 저장합니다."""
    data = {
        "updated_at": datetime.now().isoformat(),
        "count": len(games),
        "games": games,
    }

    with open(GAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_new_games(current: list[dict], saved: list[dict]) -> list[dict]:
    """새로 추가된 게임을 찾습니다."""
    saved_ids = {game["id"] for game in saved}
    return [game for game in current if game["id"] not in saved_ids]


def find_removed_games(current: list[dict], saved: list[dict]) -> list[dict]:
    """제거된 게임을 찾습니다."""
    current_ids = {game["id"] for game in current}
    return [game for game in saved if game["id"] not in current_ids]


def send_slack_notification(new_games: list[dict], removed_games: list[dict]) -> bool:
    """Slack으로 알림을 보냅니다."""
    import requests

    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        return False

    blocks = []

    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "🎮 Google Play 사전등록 게임 업데이트",
            "emoji": True
        }
    })

    if new_games:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🆕 신규 사전등록 게임 ({len(new_games)}개)*"
            }
        })

        for game in new_games[:10]:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• <{game['url']}|{game['title']}>"
                }
            })

        if len(new_games) > 10:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"외 {len(new_games) - 10}개 더 있음..."
                }]
            })

    if removed_games:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🚀 사전등록 종료/출시 ({len(removed_games)}개)*"
            }
        })

        for game in removed_games[:5]:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• <{game['url']}|{game['title']}>"
                }
            })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"⏰ 확인 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} KST"
        }]
    })

    try:
        response = requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks}, timeout=10)
        response.raise_for_status()
        print("Slack 알림 전송 성공")
        return True
    except requests.RequestException as e:
        print(f"Slack 알림 전송 실패: {e}")
        return False


def main():
    """메인 실행 함수"""
    print(f"{'='*50}")
    print(f"[{datetime.now().isoformat()}] 사전등록 게임 확인 시작")
    print(f"{'='*50}\n")

    current_games = fetch_preregister_games()
    print(f"\n현재 사전등록 게임: {len(current_games)}개")

    saved_games = load_saved_games()
    print(f"저장된 게임: {len(saved_games)}개")

    new_games = find_new_games(current_games, saved_games)
    removed_games = find_removed_games(current_games, saved_games)

    print(f"신규 게임: {len(new_games)}개")
    print(f"종료된 게임: {len(removed_games)}개")

    if new_games or removed_games:
        print(f"\n{'='*50}")
        print("변경사항 발견!")
        print(f"{'='*50}")

        if new_games:
            print("\n[신규 게임]")
            for game in new_games:
                print(f"  • {game['title']}")
                print(f"    {game['url']}")

        if removed_games:
            print("\n[종료된 게임]")
            for game in removed_games:
                print(f"  • {game['title']}")

        send_slack_notification(new_games, removed_games)

    else:
        print("\n변경사항이 없습니다.")

    save_games(current_games)
    print(f"\n{'='*50}")
    print("완료")
    print(f"{'='*50}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
