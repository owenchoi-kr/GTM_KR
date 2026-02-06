#!/usr/bin/env python3
"""Google Play & 인벤 & 카카오 & 원스토어 & 네이버게임 사전등록 게임 모니터링 시스템"""

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
BASE_DIR = Path(__file__).parent
GAMES_FILE = BASE_DIR / "games.json"
INVEN_GAMES_FILE = BASE_DIR / "inven_games.json"
KAKAO_GAMES_FILE = BASE_DIR / "kakao_games.json"
ONESTORE_GAMES_FILE = BASE_DIR / "onestore_games.json"
NAVER_GAMES_FILE = BASE_DIR / "naver_games.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# URL
GPLAY_URL = "https://play.google.com/store/apps/collection/promotion_3000000d51_pre_registration_games?hl=ko"
INVEN_URL = "https://pick.inven.co.kr/"
KAKAO_URL = "https://game.kakao.com/pr"
ONESTORE_URL = "https://m.onestore.co.kr/v2/ko-kr/event/preregistrations"
NAVER_API_URL = "https://comm-api.game.naver.com/nng_main/v1/home/launchGameOfMonth"


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

        # 게임 카테고리 + 한국 개발사 필터링
        print(f"[Google Play] 한국 개발사 게임 필터링 중... (후보 {len(candidates)}개)")
        for app in candidates:
            try:
                page.goto(app["url"], timeout=15000)
                page.wait_for_timeout(1000)

                # 게임 카테고리 확인
                game_category = page.locator("a[href*='/store/apps/category/GAME']")
                if game_category.count() == 0:
                    print(f"  - [게임아님] {app['title']}")
                    continue

                # 한국 개발사 확인 (개발자 정보에 South Korea가 있는지)
                html = page.content()
                if 'South Korea' not in html:
                    print(f"  - [해외] {app['title']}")
                    continue

                # 개발사 이름 추출
                dev_link = page.locator("a[href*='/store/apps/dev']").first
                developer = ""
                if dev_link.count() > 0:
                    developer = dev_link.inner_text().strip()

                app["developer"] = developer
                games.append(app)
                print(f"  + {app['title']} ({developer})")
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
# 카카오게임즈 크롤링
# ──────────────────────────────────────────────

def fetch_kakao_games() -> list[dict]:
    """카카오게임즈에서 사전예약 게임 목록을 가져옵니다."""
    games = []

    print("[카카오게임즈] 페이지 로드 중...")
    try:
        response = req.get(
            "https://game.kakao.com/pr/ajax/list",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://game.kakao.com/pr",
            },
            timeout=15
        )
        response.raise_for_status()
    except req.RequestException as e:
        print(f"[카카오게임즈] 페이지 로드 실패: {e}")
        return games

    soup = BeautifulSoup(response.text, "html.parser")

    # 사전예약 항목 추출
    items = soup.select("li.js-ar-item, li.js-pr-item")

    for item in items:
        try:
            link = item.select_one("a")
            if not link:
                continue

            # ID 추출 (href에서 /ar/ID 패턴)
            href = link.get("href", "")
            game_id = link.get("data-app-master-id") or link.get("data-id") or ""
            if not game_id:
                id_match = re.search(r"/ar/(\w+)", href)
                game_id = id_match.group(1) if id_match else ""
            if not game_id:
                continue

            # 게임 이름
            name_elem = item.select_one(".tit_thumb, .name_game, .tit_reserve")
            title = name_elem.get_text(strip=True) if name_elem else ""
            if not title:
                title = link.get("data-pregname") or link.get("aria-label", "").split(" ")[0]
            if not title:
                continue

            # URL
            url = href if href.startswith("http") else f"https://game.kakao.com{href}"

            games.append({
                "id": game_id,
                "title": title,
                "url": url,
            })
            print(f"  + {title}")

        except Exception:
            continue

    print(f"[카카오게임즈] 총 {len(games)}개 게임 발견\n")
    return games


# ──────────────────────────────────────────────
# 원스토어 크롤링
# ──────────────────────────────────────────────

def fetch_onestore_games() -> list[dict]:
    """원스토어에서 사전예약 게임 목록을 가져옵니다."""
    games = []

    print("[원스토어] 페이지 로드 중...")
    try:
        response = req.get(
            ONESTORE_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15
        )
        response.raise_for_status()
    except req.RequestException as e:
        print(f"[원스토어] 페이지 로드 실패: {e}")
        return games

    import urllib.parse
    decoded = urllib.parse.unquote(response.text)
    # RSC 데이터의 이스케이프된 따옴표 처리
    cleaned = decoded.replace('\\"', '"')

    # prodId + prodName 쌍 추출
    pattern = r'"prodId":"(\d+)","prodName":"([^"]+)"'
    matches = re.findall(pattern, cleaned)

    seen_ids = set()
    for prod_id, prod_name in matches:
        if prod_id in seen_ids:
            continue
        seen_ids.add(prod_id)

        url = f"https://m.onestore.co.kr/v2/ko-kr/event/preregistrations/{prod_id}"

        games.append({
            "id": prod_id,
            "title": prod_name,
            "url": url,
        })
        print(f"  + {prod_name}")

    print(f"[원스토어] 총 {len(games)}개 게임 발견\n")
    return games


# ──────────────────────────────────────────────
# 네이버게임 크롤링
# ──────────────────────────────────────────────

def fetch_naver_games() -> list[dict]:
    """네이버게임에서 이번 달 출시 게임 목록을 가져옵니다."""
    games = []

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[네이버게임] 이번 달 출시 게임 조회 중... (기준일: {today})")

    try:
        response = req.get(
            NAVER_API_URL,
            params={"count": 100, "offset": 0, "searchDate": today},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15
        )
        response.raise_for_status()
    except req.RequestException as e:
        print(f"[네이버게임] API 호출 실패: {e}")
        return games

    data = response.json()
    game_list = data.get("content", {}).get("launchGameList", [])

    for item in game_list:
        game_id = item.get("gameId", "")
        game_name = item.get("gameName", "")
        if not game_id or not game_name:
            continue

        landing_url = item.get("landingUrl", "")
        if landing_url and not landing_url.startswith("http"):
            landing_url = f"https://game.naver.com{landing_url}"

        release_type = item.get("releaseType", "")
        schedule = item.get("schedule", "")
        platform = item.get("platform", "")

        release_info = ""
        if release_type and schedule:
            release_info = f"{schedule} {release_type}"
        elif schedule:
            release_info = schedule

        games.append({
            "id": game_id,
            "title": game_name,
            "url": landing_url,
            "release_date": release_info,
            "platform": platform,
        })
        print(f"  + {game_name} ({release_info} / {platform})")

    print(f"[네이버게임] 총 {len(games)}개 게임 발견\n")
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


# ──────────────────────────────────────────────
# Slack 알림
# ──────────────────────────────────────────────

def _add_source_blocks(blocks: list, header: str, emoji: str, new: list):
    """소스별 Slack 블록을 추가합니다."""
    if not new:
        return

    if blocks:  # 이전 섹션이 있으면 구분선
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"{emoji} {header}", "emoji": True}
    })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*🆕 신규 ({len(new)}개)*"}
    })
    for g in new:
        extra_parts = []
        if g.get("developer"):
            extra_parts.append(g["developer"])
        if g.get("release_date"):
            extra_parts.append(g["release_date"])
        extra = f" | {' | '.join(extra_parts)}" if extra_parts else ""
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"• <{g['url']}|{g['title']}>{extra}"}
        })


def send_slack_notification(changes: dict) -> bool:
    """Slack으로 알림을 보냅니다."""
    if not SLACK_WEBHOOK_URL:
        print("SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        return False

    blocks = []

    sources = [
        ("Google Play 사전등록", "🎮", "gplay"),
        ("인벤 사전예약", "📋", "inven"),
        ("카카오게임즈 사전예약", "🟡", "kakao"),
        ("원스토어 사전예약", "🟣", "onestore"),
        ("네이버게임 이번 달 출시", "🟢", "naver"),
    ]

    for header, emoji, key in sources:
        new = changes.get(f"{key}_new", [])
        _add_source_blocks(blocks, header, emoji, new)

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

def check_source(name: str, fetch_fn, filepath: Path) -> dict:
    """소스별 크롤링 및 비교를 수행합니다."""
    current = fetch_fn()
    saved = load_saved(filepath)
    new = find_new(current, saved)

    print(f"[{name}] 현재: {len(current)}개 | 신규: {len(new)}개")

    return {"current": current, "new": new}


def main():
    print(f"{'='*50}")
    print(f"[{datetime.now().isoformat()}] 사전등록 게임 확인 시작")
    print(f"{'='*50}\n")

    # 각 소스 크롤링
    sources = {
        "gplay": check_source("Google Play", fetch_gplay_games, GAMES_FILE),
        "inven": check_source("인벤", fetch_inven_games, INVEN_GAMES_FILE),
        "kakao": check_source("카카오게임즈", fetch_kakao_games, KAKAO_GAMES_FILE),
        "onestore": check_source("원스토어", fetch_onestore_games, ONESTORE_GAMES_FILE),
        "naver": check_source("네이버게임", fetch_naver_games, NAVER_GAMES_FILE),
    }

    # 변경사항 확인
    changes = {}
    has_changes = False
    for key, result in sources.items():
        changes[f"{key}_new"] = result["new"]
        if result["new"]:
            has_changes = True

    if has_changes:
        print(f"\n{'='*50}")
        print("신규 게임 발견!")
        print(f"{'='*50}")

        for key, result in sources.items():
            if result["new"]:
                print(f"\n[{key} 신규]")
                for g in result["new"]:
                    extra = f" ({g.get('release_date', '')})" if g.get("release_date") else ""
                    print(f"  • {g['title']}{extra}")

        send_slack_notification(changes)
    else:
        print("\n변경사항이 없습니다.")

    # 저장
    save_games(GAMES_FILE, sources["gplay"]["current"])
    save_games(INVEN_GAMES_FILE, sources["inven"]["current"])
    save_games(KAKAO_GAMES_FILE, sources["kakao"]["current"])
    save_games(ONESTORE_GAMES_FILE, sources["onestore"]["current"])
    save_games(NAVER_GAMES_FILE, sources["naver"]["current"])

    print(f"\n{'='*50}")
    print("완료")
    print(f"{'='*50}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
