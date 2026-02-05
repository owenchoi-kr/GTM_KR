#!/usr/bin/env python3
"""Google Play & 인벤 사전등록 게임 모니터링 시스템"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests as req
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# 설정
GAMES_FILE = Path(__file__).parent / "games.json"
INVEN_GAMES_FILE = Path(__file__).parent / "inven_games.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# URL
GPLAY_URL = "https://play.google.com/store/apps/collection/promotion_3000000d51_pre_registration_games?hl=ko"
INVEN_URL = "https://pick.inven.co.kr/"


# ──────────────────────────────────────────────
# Google Play 크롤링
# ──────────────────────────────────────────────

def fetch_gplay_games() -> list[dict]:
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

        print(f"[Google Play] 페이지 로드 중...")
        try:
            page.goto(GPLAY_URL, timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeout:
            print("  페이지 로드 타임아웃, 계속 진행...")

        # 스크롤
        prev_height = 0
        for i in range(20):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)
            curr_height = page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break
            prev_height = curr_height

        # 앱 링크 추출
        app_links = page.locator("a[href*='/store/apps/details']").all()

        candidates = []
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

                title = link.inner_text().strip()
                if title:
                    title = title.split("\n")[0].strip()

                if not title or len(title) < 2:
                    img = link.locator("img").first
                    if img.count() > 0:
                        title = img.get_attribute("alt") or app_id

                if title and len(title) >= 2:
                    seen_ids.add(app_id)
                    candidates.append({
                        "id": app_id,
                        "title": title,
                        "url": f"https://play.google.com/store/apps/details?id={app_id}&hl=ko",
                    })
            except Exception:
                continue

        # 게임 카테고리 필터링
        print(f"[Google Play] 게임 카테고리 필터링 중... (후보 {len(candidates)}개)")
        for app in candidates:
            try:
                page.goto(app["url"], timeout=15000)
                page.wait_for_timeout(1000)

                game_category = page.locator("a[href*='/store/apps/category/GAME']")
                if game_category.count() > 0:
                    games.append(app)
                    print(f"  + {app['title']}")
                else:
                    print(f"  - [게임아님] {app['title']}")
            except Exception:
                continue

        browser.close()

    print(f"[Google Play] 총 {len(games)}개 게임 발견\n")
    return games


# ──────────────────────────────────────────────
# 인벤 사전예약 크롤링
# ──────────────────────────────────────────────

def fetch_inven_games() -> list[dict]:
    """인벤에서 사전예약 게임 목록을 가져옵니다."""
    games = []

    print(f"[인벤] 페이지 로드 중...")
    try:
        response = req.get(
            INVEN_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15
        )
        response.raise_for_status()
    except req.RequestException as e:
        print(f"[인벤] 페이지 로드 실패: {e}")
        return games

    soup = BeautifulSoup(response.text, "html.parser")

    # 사전예약 캠페인 항목 추출
    items = soup.select("li.item a[href*='/campaign/']")

    for item in items:
        try:
            href = item.get("href", "")

            # 캠페인 ID 추출
            campaign_match = re.search(r"/campaign/(\d+)/(\w+)", href)
            if not campaign_match:
                continue

            campaign_id = campaign_match.group(1)

            # URL 정규화
            if href.startswith("/"):
                url = f"https://pick.inven.co.kr{href}"
            else:
                url = href

            # 게임 이름
            name_elem = item.select_one("p.name")
            title = name_elem.get_text(strip=True) if name_elem else None

            if not title:
                img = item.find("img")
                title = img.get("alt", "") if img else ""

            if not title:
                continue

            # 출시 예정일
            day_elem = item.select_one("p.day")
            release_date = day_elem.get_text(strip=True) if day_elem else ""

            # 보상 정보
            reward_elem = item.select_one("p.sreward")
            reward = reward_elem.get_text(strip=True) if reward_elem else ""

            games.append({
                "id": campaign_id,
                "title": title,
                "url": url,
                "release_date": release_date,
                "reward": reward,
            })
            print(f"  + {title} ({release_date})")

        except Exception:
            continue

    print(f"[인벤] 총 {len(games)}개 게임 발견\n")
    return games


# ──────────────────────────────────────────────
# 공통 유틸
# ──────────────────────────────────────────────

def load_saved(filepath: Path) -> list[dict]:
    """저장된 게임 목록을 불러옵니다."""
    if not filepath.exists():
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("games", [])
    except (json.JSONDecodeError, IOError):
        return []


def save_games(filepath: Path, games: list[dict]) -> None:
    """게임 목록을 저장합니다."""
    data = {
        "updated_at": datetime.now().isoformat(),
        "count": len(games),
        "games": games,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_new(current: list[dict], saved: list[dict]) -> list[dict]:
    saved_ids = {g["id"] for g in saved}
    return [g for g in current if g["id"] not in saved_ids]


def find_removed(current: list[dict], saved: list[dict]) -> list[dict]:
    current_ids = {g["id"] for g in current}
    return [g for g in saved if g["id"] not in current_ids]


# ──────────────────────────────────────────────
# Slack 알림
# ──────────────────────────────────────────────

def send_slack_notification(
    gplay_new: list[dict], gplay_removed: list[dict],
    inven_new: list[dict], inven_removed: list[dict],
) -> bool:
    """Slack으로 알림을 보냅니다."""
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        return False

    blocks = []

    # ── Google Play 섹션 ──
    if gplay_new or gplay_removed:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "🎮 Google Play 사전등록 업데이트", "emoji": True}
        })

        if gplay_new:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🆕 신규 ({len(gplay_new)}개)*"}
            })
            for g in gplay_new[:10]:
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"• <{g['url']}|{g['title']}>"}
                })
            if len(gplay_new) > 10:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"외 {len(gplay_new) - 10}개 더 있음..."}]
                })

        if gplay_removed:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🚀 종료/출시 ({len(gplay_removed)}개)*"}
            })
            for g in gplay_removed[:5]:
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"• <{g['url']}|{g['title']}>"}
                })

    # ── 인벤 섹션 ──
    if inven_new or inven_removed:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "📋 인벤 사전예약 업데이트", "emoji": True}
        })

        if inven_new:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🆕 신규 ({len(inven_new)}개)*"}
            })
            for g in inven_new[:10]:
                release = f" | {g.get('release_date', '')}" if g.get("release_date") else ""
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"• <{g['url']}|{g['title']}>{release}"}
                })

        if inven_removed:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🚀 종료 ({len(inven_removed)}개)*"}
            })
            for g in inven_removed[:5]:
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"• <{g['url']}|{g['title']}>"}
                })

    # 시간 정보
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"⏰ 확인 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} KST"}]
    })

    try:
        response = req.post(SLACK_WEBHOOK_URL, json={"blocks": blocks}, timeout=10)
        response.raise_for_status()
        print("Slack 알림 전송 성공")
        return True
    except req.RequestException as e:
        print(f"Slack 알림 전송 실패: {e}")
        return False


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    print(f"{'='*50}")
    print(f"[{datetime.now().isoformat()}] 사전등록 게임 확인 시작")
    print(f"{'='*50}\n")

    # Google Play
    gplay_current = fetch_gplay_games()
    gplay_saved = load_saved(GAMES_FILE)
    gplay_new = find_new(gplay_current, gplay_saved)
    gplay_removed = find_removed(gplay_current, gplay_saved)

    print(f"[Google Play] 현재: {len(gplay_current)}개 | 신규: {len(gplay_new)}개 | 종료: {len(gplay_removed)}개")

    # 인벤
    inven_current = fetch_inven_games()
    inven_saved = load_saved(INVEN_GAMES_FILE)
    inven_new = find_new(inven_current, inven_saved)
    inven_removed = find_removed(inven_current, inven_saved)

    print(f"[인벤] 현재: {len(inven_current)}개 | 신규: {len(inven_new)}개 | 종료: {len(inven_removed)}개")

    # 변경사항 확인
    has_changes = gplay_new or gplay_removed or inven_new or inven_removed

    if has_changes:
        print(f"\n{'='*50}")
        print("변경사항 발견!")
        print(f"{'='*50}")

        if gplay_new:
            print("\n[Google Play 신규]")
            for g in gplay_new:
                print(f"  • {g['title']}")

        if gplay_removed:
            print("\n[Google Play 종료]")
            for g in gplay_removed:
                print(f"  • {g['title']}")

        if inven_new:
            print("\n[인벤 신규]")
            for g in inven_new:
                print(f"  • {g['title']} ({g.get('release_date', '')})")

        if inven_removed:
            print("\n[인벤 종료]")
            for g in inven_removed:
                print(f"  • {g['title']}")

        send_slack_notification(gplay_new, gplay_removed, inven_new, inven_removed)
    else:
        print("\n변경사항이 없습니다.")

    # 저장
    save_games(GAMES_FILE, gplay_current)
    save_games(INVEN_GAMES_FILE, inven_current)

    print(f"\n{'='*50}")
    print("완료")
    print(f"{'='*50}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
