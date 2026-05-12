"""
日本株 高値更新モニター
kabutan.jp をスクレイピングして年初来高値・52週高値の更新をSlackに通知する
"""

import json
import logging
import os
import re
import time
from datetime import date, datetime

import pytz
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

JST = pytz.timezone("Asia/Tokyo")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
STATE_FILE = "data/state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

# 監視対象ページ定義
TARGETS = [
    {
        "key": "ytd_high",
        "url": "https://kabutan.jp/warning/?mode=3_3",
        "label": "年初来高値更新",
        "emoji": ":chart_with_upwards_trend:",
        "table_class": "warning_list",
    },
    {
        "key": "w52_high",
        "url": "https://kabutan.jp/warning/record_w52_high_price",
        "label": "52週高値更新",
        "emoji": ":rocket:",
        "table_class": "table",
    },
]


# ── 市場時間チェック ─────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    now = datetime.now(JST)
    if now.weekday() >= 5:
        return False
    m = now.hour * 60 + now.minute
    # 東証: 09:00-11:30, 12:30-15:30
    return (9 * 60 <= m <= 11 * 60 + 30) or (12 * 60 + 30 <= m <= 15 * 60 + 30)


# ── 状態管理 ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    today = date.today().isoformat()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        if state.get("date") == today:
            # リスト形式から辞書形式へのマイグレーション
            for key in ("ytd_high", "w52_high"):
                if isinstance(state.get(key), list):
                    state[key] = {code: 0 for code in state[key]}
            return state
    return {"date": today, "ytd_high": {}, "w52_high": {}}


def save_state(state: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── スクレイピング ─────────────────────────────────────────────────────────────────

def parse_price(price_str: str) -> float:
    """価格文字列を数値に変換。変換失敗時は 0.0 を返す。"""
    try:
        return float(re.sub(r"[^\d.]", "", price_str))
    except (ValueError, AttributeError):
        return 0.0


def scrape_stocks(url: str, table_class: str) -> list[dict]:
    """kabutan.jp の高値更新テーブルから銘柄一覧を取得する"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"HTTP error for {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    table = soup.find("table", class_=table_class)
    if not table:
        # フォールバック: 銘柄コードリンクを含む最初のテーブル
        for t in soup.find_all("table"):
            if t.find("a", href=lambda h: h and "/stock/?code=" in h):
                table = t
                break

    if not table:
        logger.warning(f"Stock table not found at {url}")
        return []

    stocks = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        # 銘柄コードを href="/stock/?code=XXXX" から抽出
        code = None
        name = None
        price_col = None

        for i, cell in enumerate(cells):
            link = cell.find("a", href=lambda h: h and "/stock/?code=" in h)
            if link:
                m = re.search(r"code=(\d+)", link.get("href", ""))
                if not m:
                    continue
                code = m.group(1)
                # 銘柄名: 次のセルにリンクがあればそちら、なければ同セルのテキスト
                if i + 1 < len(cells):
                    next_cell = cells[i + 1]
                    next_link = next_cell.find("a")
                    if next_link:
                        name = next_link.get_text(strip=True)
                        price_col = i + 2
                    else:
                        name = link.get_text(strip=True)
                        price_col = i + 1
                else:
                    name = link.get_text(strip=True)
                    price_col = i + 1
                break

        if not code or price_col is None:
            continue

        n = len(cells)
        price = cells[price_col].get_text(strip=True) if price_col < n else ""
        change = cells[price_col + 1].get_text(strip=True) if price_col + 1 < n else ""
        change_pct = cells[price_col + 2].get_text(strip=True) if price_col + 2 < n else ""

        stocks.append({
            "code": code,
            "name": name,
            "price": price,
            "change": change,
            "change_pct": change_pct,
        })

    return stocks


# ── Slack 通知 ─────────────────────────────────────────────────────────────────

def send_slack(text: str) -> None:
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL が設定されていません")
        return
    try:
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": text},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"Slack エラー {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Slack 送信失敗: {e}")


def build_message(stock: dict, label: str, emoji: str) -> str:
    change_str = ""
    if stock["change"] or stock["change_pct"]:
        change_str = f"  変化: {stock['change']} ({stock['change_pct']})"
    return (
        f"{emoji} *{label}*\n"
        f"銘柄: `{stock['code']}` {stock['name']}\n"
        f"現在値: {stock['price']}円{change_str}\n"
        f"<https://kabutan.jp/stock/?code={stock['code']}|株探で詳細を見る>"
    )


# ── メイン ────────────────────────────────────────────────────────────────────────

def main() -> None:
    if not is_market_open():
        now_str = datetime.now(JST).strftime("%H:%M")
        logger.info(f"市場時間外 ({now_str} JST) - スキップ")
        return

    state = load_state()
    now_str = datetime.now(JST).strftime("%H:%M")
    logger.info(f"モニター実行: {now_str} JST")

    total_new = 0

    for target in TARGETS:
        key = target["key"]
        logger.info(f"チェック中: {target['label']} ({target['url']})")

        stocks = scrape_stocks(target["url"], target["table_class"])
        logger.info(f"  取得銘柄数: {len(stocks)}")

        # {コード: 最終通知価格} の辞書で管理
        notified: dict = state.get(key, {})
        if isinstance(notified, list):
            notified = {code: 0 for code in notified}

        new_stocks = []
        for stock in stocks:
            code = stock["code"]
            current_price = parse_price(stock["price"])
            last_price = float(notified.get(code, -1))

            # 未通知 or 前回通知より高い価格なら通知
            if last_price < 0 or (current_price > 0 and current_price > last_price):
                new_stocks.append(stock)
                notified[code] = current_price

        logger.info(f"  新規通知対象: {len(new_stocks)} 銘柄")

        for stock in new_stocks:
            msg = build_message(stock, target["label"], target["emoji"])
            send_slack(msg)
            logger.info(f"  通知済み: {stock['code']} {stock['name']}")
            time.sleep(0.3)  # Slack レートリミット対策

        state[key] = notified
        total_new += len(new_stocks)

    save_state(state)
    logger.info(f"完了 - 新規通知: {total_new} 件")


if __name__ == "__main__":
    main()
