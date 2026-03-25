"""
mf_attendance.py
マネーフォワード クラウド勤怠 打刻クライアント

Webセッション経由で打刻操作・勤怠状況取得を行うモジュール。
公式の打刻REST APIは非公開のため、Webフォーム送信方式を使用する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# マネーフォワード クラウド勤怠のベースURL
BASE_URL = "https://attendance.moneyforward.com"

# 日本標準時
JST = timezone(timedelta(hours=9))

# 打刻種別の定義
PUNCH_TYPES = {
    "clock_in":    "出勤",
    "clock_out":   "退勤",
    "start_break": "休憩開始",
    "end_break":   "休憩終了",
}


@dataclass
class MFSession:
    """マネーフォワード勤怠のセッション情報"""
    session_id: str
    employee_id: str
    location_id: str
    office_account_name: str
    email: str


class MFAttendanceError(Exception):
    """マネーフォワード勤怠操作エラー"""
    pass


class MFAttendanceClient:
    """
    マネーフォワード クラウド勤怠 クライアント

    使用例:
        client = MFAttendanceClient("your_company_id", "user@example.com", "password")
        success, message = client.clock_in()
        print(message)
    """

    def __init__(self, office_account_name: str, email: str, password: str):
        """
        Args:
            office_account_name: 会社ID（マネーフォワード クラウド勤怠の会社アカウント名）
            email: ログインメールアドレス（またはアカウント名）
            password: パスワード
        """
        self.office_account_name = office_account_name
        self.email = email
        self.password = password
        self._session: Optional[MFSession] = None
        self._http = requests.Session()
        self._http.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

    def _login(self) -> MFSession:
        """マネーフォワード勤怠にログインしてセッションを取得する"""
        login_url = f"{BASE_URL}/email_employee_session/new"
        post_url = f"{BASE_URL}/email_employee_session"

        # ログインページを取得してCSRFトークンを取得
        resp = self._http.get(login_url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "html.parser")
        csrf_meta = soup.find("meta", attrs={"name": "csrf-token"})
        if not csrf_meta:
            raise MFAttendanceError("CSRFトークンの取得に失敗しました")
        csrf_token = csrf_meta.attrs["content"]

        session_cookie = resp.cookies.get("_session_id", "")

        # ログインフォームを送信
        form_data = {
            "authenticity_token": csrf_token,
            "employee_session_form[office_account_name]": self.office_account_name,
            "employee_session_form[account_name_or_email]": self.email,
            "employee_session_form[password]": self.password,
        }

        login_resp = self._http.post(
            post_url,
            data=form_data,
            cookies={"_session_id": session_cookie},
            allow_redirects=False,
        )

        if login_resp.status_code not in (301, 302):
            raise MFAttendanceError(
                f"ログインに失敗しました（ステータス: {login_resp.status_code}）。"
                "会社ID・メールアドレス・パスワードを確認してください。"
            )

        # リダイレクト先（マイページ）を取得
        new_session_id = login_resp.cookies.get("_session_id", session_cookie)
        redirect_url = login_resp.headers.get("Location", f"{BASE_URL}/my_page")
        if not redirect_url.startswith("http"):
            redirect_url = BASE_URL + redirect_url

        mypage_resp = self._http.get(
            redirect_url,
            cookies={"_session_id": new_session_id},
        )
        mypage_resp.raise_for_status()

        mypage_soup = BeautifulSoup(mypage_resp.content, "html.parser")

        # 従業員IDを取得
        uid_meta = mypage_soup.find("meta", attrs={"name": "js:rollbar:uid"})
        employee_id = uid_meta.attrs["content"] if uid_meta else ""

        # 打刻フォームのロケーションIDを取得
        location_input = mypage_soup.find(
            "input", attrs={"id": "web_time_recorder_form_office_location_id"}
        )
        location_id = location_input.attrs["value"] if location_input else ""

        final_session_id = mypage_resp.cookies.get("_session_id", new_session_id)

        logger.info("ログイン成功: employee_id=%s", employee_id)

        return MFSession(
            session_id=final_session_id,
            employee_id=employee_id,
            location_id=location_id,
            office_account_name=self.office_account_name,
            email=self.email,
        )

    def _get_session(self) -> MFSession:
        """セッションを取得する（未ログインの場合はログインする）"""
        if self._session is None:
            self._session = self._login()
        return self._session

    def _punch(self, event: str) -> Tuple[bool, str]:
        """
        打刻を実行する

        Args:
            event: 打刻種別 ("clock_in", "clock_out", "start_break", "end_break")

        Returns:
            (成功フラグ, メッセージ)
        """
        sess = self._get_session()
        mypage_url = f"{BASE_URL}/my_page"
        recorder_url = f"{BASE_URL}/my_page/web_time_recorder"
        cookies = {"_session_id": sess.session_id}

        # マイページを取得してCSRFトークンと打刻ボタンの存在を確認
        mypage_resp = self._http.get(mypage_url, cookies=cookies)
        if not mypage_resp.ok:
            # セッション切れの可能性があるため再ログイン
            self._session = None
            sess = self._get_session()
            cookies = {"_session_id": sess.session_id}
            mypage_resp = self._http.get(mypage_url, cookies=cookies)
            mypage_resp.raise_for_status()

        soup = BeautifulSoup(mypage_resp.content, "html.parser")

        # 打刻ボタンの存在確認
        form_input = soup.find("input", attrs={"value": event})
        if form_input is None:
            event_name = PUNCH_TYPES.get(event, event)
            return False, f"「{event_name}」ボタンが現在利用できません。既に打刻済みか、打刻順序が正しくない可能性があります。"

        # CSRFトークンを取得
        token_input = form_input.parent.find("input", attrs={"name": "authenticity_token"})
        if not token_input:
            return False, "認証トークンの取得に失敗しました。"
        token = token_input.attrs["value"]

        # 現在時刻（UTC）
        now_utc = datetime.now(timezone.utc)

        form_data = {
            "authenticity_token": token,
            "web_time_recorder_form[event]": event,
            "web_time_recorder_form[date]": now_utc.strftime("%Y/%m/%d"),
            "web_time_recorder_form[user_time]": now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "web_time_recorder_form[office_location_id]": sess.location_id,
        }

        punch_resp = self._http.post(
            recorder_url,
            data=form_data,
            cookies=cookies,
        )

        event_name = PUNCH_TYPES.get(event, event)
        if punch_resp.ok:
            now_jst = datetime.now(JST)
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
        """
        今日の勤怠状況を取得する

        Returns:
            (成功フラグ, 勤怠状況テキスト)
        """
        sess = self._get_session()
        mypage_url = f"{BASE_URL}/my_page"
        cookies = {"_session_id": sess.session_id}

        resp = self._http.get(mypage_url, cookies=cookies)
        if not resp.ok:
            self._session = None
            sess = self._get_session()
            cookies = {"_session_id": sess.session_id}
            resp = self._http.get(mypage_url, cookies=cookies)
            if not resp.ok:
                return False, "勤怠情報の取得に失敗しました。"

        soup = BeautifulSoup(resp.content, "html.parser")

        # 今日の日付（JST）
        now_jst = datetime.now(JST)
        date_str = now_jst.strftime("%Y年%m月%d日")

        # 打刻済みの記録を取得
        records = []
        # 打刻記録テーブルを探す（マイページの打刻履歴）
        attendance_table = soup.find("table", class_=lambda c: c and "attendance" in c.lower())
        if not attendance_table:
            # 代替: 打刻ボタンの状態から現在の状態を推定
            available_buttons = []
            for event_key, event_name in PUNCH_TYPES.items():
                btn = soup.find("input", attrs={"value": event_key})
                if btn:
                    available_buttons.append(event_name)

            if "出勤" in available_buttons:
                status_text = "未出勤"
            elif "退勤" in available_buttons and "休憩開始" in available_buttons:
                status_text = "出勤中"
            elif "休憩終了" in available_buttons:
                status_text = "休憩中"
            elif not available_buttons or available_buttons == ["退勤"]:
                status_text = "出勤中（退勤待ち）"
            else:
                status_text = "退勤済み"

            return True, (
                f"📅 {date_str} の勤怠状況\n"
                f"現在の状態: {status_text}\n"
                f"利用可能な操作: {', '.join(available_buttons) if available_buttons else 'なし（退勤済み）'}"
            )

        # テーブルから打刻記録を取得
        rows = attendance_table.find_all("tr")
        for row in rows[1:]:  # ヘッダー行をスキップ
            cells = row.find_all("td")
            if len(cells) >= 2:
                records.append(f"  {cells[0].get_text(strip=True)}: {cells[1].get_text(strip=True)}")

        records_text = "\n".join(records) if records else "  記録なし"
        return True, f"📅 {date_str} の打刻記録\n{records_text}"

    def logout(self):
        """セッションをクリアする"""
        self._session = None
