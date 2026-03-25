"""
mf_attendance.py
マネーフォワード クラウド勤怠 打刻クライアント

マネーフォワードID（id.moneyforward.com）経由のOAuth認証フローを使って
ログインし、打刻操作・勤怠状況取得を行うモジュール。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# マネーフォワード クラウド勤怠のベースURL
BASE_URL = "https://attendance.moneyforward.com"

# マネーフォワードID 認証URL
MFID_BASE = "https://id.moneyforward.com"

# 日本標準時
JST = timezone(timedelta(hours=9))

# 打刻種別の定義
PUNCH_TYPES = {
    "clock_in":    "出勤",
    "clock_out":   "退勤",
    "start_break": "休憩開始",
    "end_break":   "休憩終了",
}


class MFAttendanceError(Exception):
    """マネーフォワード勤怠操作エラー"""
    pass


class MFAttendanceClient:
    """
    マネーフォワード クラウド勤怠 クライアント（マネーフォワードID認証対応版）

    使用例:
        client = MFAttendanceClient(email="user@example.com", password="password")
        success, message = client.clock_in()
        print(message)
    """

    def __init__(self, email: str, password: str, office_account_name: str = ""):
        self.email = email
        self.password = password
        self.office_account_name = office_account_name  # 互換性のため残す
        self._logged_in = False
        self._http = requests.Session()
        self._http.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

    def _login(self):
        """マネーフォワードID経由でログインする"""

        # ── Step 1: 勤怠のログインページを開いてOAuth URLを取得 ──
        login_page = self._http.get(f"{BASE_URL}/employee_session/new")
        login_page.raise_for_status()

        soup = BeautifulSoup(login_page.content, "html.parser")
        mfid_link = soup.find("a", string=lambda t: t and "マネーフォワード ID" in t)
        if not mfid_link:
            # hrefで探す
            mfid_link = soup.find("a", href=lambda h: h and "/auth/mfid" in h)
        if not mfid_link:
            raise MFAttendanceError("マネーフォワードIDログインリンクが見つかりませんでした")

        oauth_url = mfid_link["href"]
        if not oauth_url.startswith("http"):
            oauth_url = BASE_URL + oauth_url

        # ── Step 2: OAuthページ（id.moneyforward.com）に遷移 ──
        oauth_page = self._http.get(oauth_url, allow_redirects=True)
        oauth_page.raise_for_status()

        oauth_soup = BeautifulSoup(oauth_page.content, "html.parser")

        # フォームのaction URLを取得
        form = oauth_soup.find("form")
        if not form:
            raise MFAttendanceError("ログインフォームが見つかりませんでした")

        form_action = form.get("action", "")
        if not form_action.startswith("http"):
            form_action = MFID_BASE + form_action

        # hiddenフィールドをすべて取得
        hidden_fields = {}
        for inp in oauth_soup.find_all("input", type="hidden"):
            hidden_fields[inp.get("name")] = inp.get("value", "")

        # ── Step 3: メールアドレス＋パスワードでログインフォームを送信 ──
        form_data = {
            **hidden_fields,
            "mfid_user[email]": self.email,
            "mfid_user[password]": self.password,
        }

        login_resp = self._http.post(
            form_action,
            data=form_data,
            allow_redirects=True,
        )

        # ログイン失敗チェック（エラーメッセージが含まれているか）
        if login_resp.status_code == 200:
            resp_soup = BeautifulSoup(login_resp.content, "html.parser")
            # エラーメッセージを探す
            error_div = resp_soup.find(class_=lambda c: c and "error" in c.lower())
            if error_div and ("パスワード" in error_div.get_text() or
                              "メール" in error_div.get_text() or
                              "invalid" in error_div.get_text().lower()):
                raise MFAttendanceError(
                    "メールアドレスまたはパスワードが正しくありません。"
                )
            # まだid.moneyforward.comにいる場合はログイン失敗
            if "id.moneyforward.com" in login_resp.url and "sign_in" in login_resp.url:
                raise MFAttendanceError(
                    "ログインに失敗しました。メールアドレスとパスワードを確認してください。"
                )

        # ── Step 4: 勤怠マイページに到達できているか確認 ──
        # コールバック後に勤怠サービスにリダイレクトされるはず
        final_url = login_resp.url
        logger.info("ログイン後URL: %s", final_url)

        if "attendance.moneyforward.com" not in final_url:
            # office_selection ページの場合は会社を選択する
            if "office_selection" in final_url or "moneyforward.com" in final_url:
                # 会社選択ページ
                sel_soup = BeautifulSoup(login_resp.content, "html.parser")
                # 会社IDが指定されている場合は一致する会社を選択
                office_links = sel_soup.find_all("a", href=lambda h: h and "attendance.moneyforward.com" in str(h))
                if not office_links:
                    # formで会社を選択するパターン
                    office_forms = sel_soup.find_all("form")
                    for of in office_forms:
                        action = of.get("action", "")
                        if self.office_account_name and self.office_account_name in action:
                            hidden = {i.get("name"): i.get("value", "") for i in of.find_all("input", type="hidden")}
                            self._http.post(action if action.startswith("http") else MFID_BASE + action, data=hidden)
                            break
                        elif not self.office_account_name:
                            # 最初の会社を選択
                            hidden = {i.get("name"): i.get("value", "") for i in of.find_all("input", type="hidden")}
                            self._http.post(action if action.startswith("http") else MFID_BASE + action, data=hidden)
                            break

                # 勤怠マイページに移動
                mypage = self._http.get(f"{BASE_URL}/my_page")
                if not mypage.ok:
                    raise MFAttendanceError("勤怠マイページへのアクセスに失敗しました。")
            else:
                raise MFAttendanceError(
                    f"ログイン後のリダイレクト先が想定外です: {final_url[:100]}"
                )

        self._logged_in = True
        logger.info("マネーフォワード勤怠へのログイン成功")

    def _ensure_logged_in(self):
        """ログイン状態を確認し、未ログインならログインする"""
        if not self._logged_in:
            self._login()
        # セッション有効性確認
        resp = self._http.get(f"{BASE_URL}/my_page", allow_redirects=False)
        if resp.status_code in (301, 302):
            # セッション切れ → 再ログイン
            self._logged_in = False
            self._http = requests.Session()
            self._http.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            })
            self._login()

    def _get_mypage(self) -> BeautifulSoup:
        """マイページのHTMLを取得してBeautifulSoupで返す"""
        self._ensure_logged_in()
        resp = self._http.get(f"{BASE_URL}/my_page")
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser")

    def _punch(self, event: str) -> Tuple[bool, str]:
        """打刻を実行する"""
        soup = self._get_mypage()

        # 打刻ボタンの存在確認
        form_input = soup.find("input", attrs={"value": event})
        if form_input is None:
            event_name = PUNCH_TYPES.get(event, event)
            return False, (
                f"「{event_name}」ボタンが現在利用できません。\n"
                "既に打刻済みか、打刻の順序が正しくない可能性があります。"
            )

        # CSRFトークンを取得
        token_input = form_input.parent.find("input", attrs={"name": "authenticity_token"})
        if not token_input:
            # ページ全体から探す
            token_input = soup.find("meta", attrs={"name": "csrf-token"})
            token = token_input.attrs["content"] if token_input else ""
        else:
            token = token_input.attrs["value"]

        # 現在時刻（UTC）
        now_utc = datetime.now(timezone.utc)

        # ロケーションIDを取得
        location_input = soup.find(
            "input", attrs={"id": "web_time_recorder_form_office_location_id"}
        )
        location_id = location_input.attrs["value"] if location_input else ""

        form_data = {
            "authenticity_token": token,
            "web_time_recorder_form[event]": event,
            "web_time_recorder_form[date]": now_utc.strftime("%Y/%m/%d"),
            "web_time_recorder_form[user_time]": now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "web_time_recorder_form[office_location_id]": location_id,
        }

        punch_resp = self._http.post(
            f"{BASE_URL}/my_page/web_time_recorder",
            data=form_data,
        )

        event_name = PUNCH_TYPES.get(event, event)
        now_jst = datetime.now(JST)
        if punch_resp.ok:
            return True, f"✅ {event_name}しました（{now_jst.strftime('%H:%M')}）"
        else:
            return False, f"❌ {event_name}の打刻に失敗しました（ステータス: {punch_resp.status_code}）"

    def clock_in(self) -> Tuple[bool, str]:
        """出勤打刻"""
        return self._punch("clock_in")

    def clock_out(self) -> Tuple[bool, str]:
        """退勤打刻"""
        return self._punch("clock_out")

    def start_break(self) -> Tuple[bool, str]:
        """休憩開始打刻"""
        return self._punch("start_break")

    def end_break(self) -> Tuple[bool, str]:
        """休憩終了打刻"""
        return self._punch("end_break")

    def get_status(self) -> Tuple[bool, str]:
        """今日の勤怠状況を取得する"""
        soup = self._get_mypage()
        now_jst = datetime.now(JST)
        date_str = now_jst.strftime("%Y年%m月%d日")

        # 利用可能な打刻ボタンから現在の状態を推定
        available_buttons = []
        for event_key, event_name in PUNCH_TYPES.items():
            btn = soup.find("input", attrs={"value": event_key})
            if btn:
                available_buttons.append(event_name)

        if "出勤" in available_buttons:
            status_text = "未出勤"
        elif "休憩終了" in available_buttons:
            status_text = "休憩中"
        elif "退勤" in available_buttons:
            status_text = "出勤中"
        else:
            status_text = "退勤済み"

        ops = "、".join(available_buttons) if available_buttons else "なし（退勤済み）"
        return True, (
            f"📅 {date_str} の勤怠状況\n"
            f"現在の状態: {status_text}\n"
            f"利用可能な操作: {ops}"
        )

    def logout(self):
        """セッションをクリアする"""
        self._logged_in = False
