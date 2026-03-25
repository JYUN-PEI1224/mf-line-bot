"""
app.py
マネーフォワード クラウド勤怠 × LINE Bot Webhook サーバー

LINEのリッチメニューから出勤・退勤・休憩の打刻と勤怠状況確認ができる。

必要な環境変数:
    LINE_CHANNEL_SECRET   : LINE Messaging API チャンネルシークレット
    LINE_CHANNEL_ACCESS_TOKEN : LINE Messaging API チャンネルアクセストークン
    MF_OFFICE_ACCOUNT_NAME    : マネーフォワード会社ID（全社共通の場合）
    PORT                      : サーバーポート番号（デフォルト: 8000）

起動方法:
    uvicorn app:app --host 0.0.0.0 --port 8000
"""

import hashlib
import hmac
import logging
import os
from base64 import b64decode
from typing import Any, Dict, List

import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from mf_attendance import MFAttendanceClient, MFAttendanceError
from user_store import UserCredentials, get_store

# ─── ロギング設定 ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── 環境変数 ────────────────────────────────────────────────
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
MF_OFFICE_ACCOUNT_NAME = os.getenv("MF_OFFICE_ACCOUNT_NAME", "")

LINE_API_BASE = "https://api.line.me/v2/bot"

# ─── FastAPI アプリ ──────────────────────────────────────────
app = FastAPI(
    title="MF勤怠 LINE Bot",
    description="マネーフォワード クラウド勤怠をLINEから操作するWebhookサーバー",
    version="1.0.0",
)

# ─── セッションキャッシュ（メモリ内） ────────────────────────
# LINEユーザーID -> MFAttendanceClient
_client_cache: Dict[str, MFAttendanceClient] = {}

# 登録フロー中のユーザー状態管理
# LINEユーザーID -> {"step": str, "data": dict}
_registration_state: Dict[str, Dict[str, Any]] = {}


# ─── LINE API ヘルパー ───────────────────────────────────────

def _line_headers() -> dict:
    return {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def reply_message(reply_token: str, messages: List[dict]):
    """LINEに返信メッセージを送信する"""
    payload = {
        "replyToken": reply_token,
        "messages": messages,
    }
    resp = requests.post(
        f"{LINE_API_BASE}/message/reply",
        headers=_line_headers(),
        json=payload,
        timeout=10,
    )
    if not resp.ok:
        logger.error("LINE返信エラー: %s %s", resp.status_code, resp.text)


def push_message(user_id: str, messages: List[dict]):
    """LINEにプッシュメッセージを送信する"""
    payload = {
        "to": user_id,
        "messages": messages,
    }
    resp = requests.post(
        f"{LINE_API_BASE}/message/push",
        headers=_line_headers(),
        json=payload,
        timeout=10,
    )
    if not resp.ok:
        logger.error("LINEプッシュエラー: %s %s", resp.status_code, resp.text)


def text_message(text: str) -> dict:
    """テキストメッセージオブジェクトを生成する"""
    return {"type": "text", "text": text}


def quick_reply_message(text: str, items: List[dict]) -> dict:
    """クイックリプライ付きテキストメッセージを生成する"""
    return {
        "type": "text",
        "text": text,
        "quickReply": {"items": items},
    }


def quick_reply_item(label: str, text: str) -> dict:
    """クイックリプライアイテムを生成する"""
    return {
        "type": "action",
        "action": {
            "type": "message",
            "label": label,
            "text": text,
        },
    }


# ─── 署名検証 ────────────────────────────────────────────────

def _verify_signature(body: bytes, signature: str) -> bool:
    """LINE Webhookの署名を検証する"""
    if not LINE_CHANNEL_SECRET:
        logger.warning("LINE_CHANNEL_SECRETが未設定です。署名検証をスキップします。")
        return True
    hash_val = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    import base64
    expected = base64.b64encode(hash_val).decode("utf-8")
    return hmac.compare_digest(expected, signature)


# ─── MFクライアント管理 ──────────────────────────────────────

def _get_mf_client(line_user_id: str) -> MFAttendanceClient:
    """ユーザーのMFクライアントを取得する（キャッシュ付き）"""
    if line_user_id not in _client_cache:
        store = get_store()
        creds = store.get(line_user_id)
        if not creds:
            raise ValueError("認証情報が登録されていません")
        _client_cache[line_user_id] = MFAttendanceClient(
            office_account_name=creds.office_account_name,
            email=creds.email,
            password=creds.password,
        )
    return _client_cache[line_user_id]


# ─── メッセージハンドラー ────────────────────────────────────

def _handle_punch(user_id: str, reply_token: str, action: str):
    """打刻処理を実行する"""
    action_map = {
        "出勤": "clock_in",
        "退勤": "clock_out",
        "休憩開始": "start_break",
        "休憩終了": "end_break",
    }

    event_key = action_map.get(action)
    if not event_key:
        reply_message(reply_token, [text_message("不明な操作です。")])
        return

    try:
        client = _get_mf_client(user_id)
    except ValueError:
        reply_message(reply_token, [
            text_message(
                "⚠️ マネーフォワード勤怠の認証情報が登録されていません。\n\n"
                "「設定」と送信して認証情報を登録してください。"
            )
        ])
        return

    try:
        success, message = getattr(client, {
            "clock_in":    "clock_in",
            "clock_out":   "clock_out",
            "start_break": "start_break",
            "end_break":   "end_break",
        }[event_key])()
        reply_message(reply_token, [text_message(message)])
    except MFAttendanceError as e:
        reply_message(reply_token, [text_message(f"❌ エラーが発生しました: {e}")])
    except Exception as e:
        logger.exception("打刻処理中に予期しないエラーが発生しました")
        reply_message(reply_token, [text_message(f"❌ 予期しないエラーが発生しました: {e}")])


def _handle_status(user_id: str, reply_token: str):
    """勤怠状況を取得して返信する"""
    try:
        client = _get_mf_client(user_id)
    except ValueError:
        reply_message(reply_token, [
            text_message(
                "⚠️ マネーフォワード勤怠の認証情報が登録されていません。\n\n"
                "「設定」と送信して認証情報を登録してください。"
            )
        ])
        return

    try:
        success, message = client.get_status()
        reply_message(reply_token, [text_message(message)])
    except Exception as e:
        logger.exception("勤怠状況取得中にエラーが発生しました")
        reply_message(reply_token, [text_message(f"❌ 勤怠情報の取得に失敗しました: {e}")])


def _handle_setup_start(user_id: str, reply_token: str):
    """認証情報の登録フローを開始する"""
    # 会社IDが環境変数で設定されている場合はスキップ
    if MF_OFFICE_ACCOUNT_NAME:
        _registration_state[user_id] = {
            "step": "email",
            "data": {"office_account_name": MF_OFFICE_ACCOUNT_NAME},
        }
        reply_message(reply_token, [
            text_message(
                "🔧 マネーフォワード勤怠の認証情報を登録します。\n\n"
                "ログイン用のメールアドレスを入力してください。\n"
                "（例: user@example.com）\n\n"
                "※ このメッセージはLINEのサーバーに保存されます。\n"
                "セキュリティが心配な場合は管理者にご相談ください。"
            )
        ])
    else:
        _registration_state[user_id] = {
            "step": "office_id",
            "data": {},
        }
        reply_message(reply_token, [
            text_message(
                "🔧 マネーフォワード勤怠の認証情報を登録します。\n\n"
                "まず、会社IDを入力してください。\n"
                "（マネーフォワード クラウド勤怠のログインURLに含まれる会社IDです）\n"
                "例: https://attendance.moneyforward.com/\n"
                "　→ 会社IDは管理者にご確認ください"
            )
        ])


def _handle_registration_flow(user_id: str, reply_token: str, text: str):
    """認証情報登録フローの各ステップを処理する"""
    state = _registration_state.get(user_id)
    if not state:
        return False  # 登録フロー外

    step = state["step"]

    if step == "office_id":
        state["data"]["office_account_name"] = text.strip()
        state["step"] = "email"
        reply_message(reply_token, [
            text_message(
                "✅ 会社IDを受け付けました。\n\n"
                "次に、ログイン用のメールアドレスを入力してください。"
            )
        ])
        return True

    elif step == "email":
        state["data"]["email"] = text.strip()
        state["step"] = "password"
        reply_message(reply_token, [
            text_message(
                "✅ メールアドレスを受け付けました。\n\n"
                "次に、パスワードを入力してください。\n"
                "⚠️ パスワードは入力後すぐに処理され、暗号化して保存されます。"
            )
        ])
        return True

    elif step == "password":
        state["data"]["password"] = text.strip()

        # 認証情報を保存
        creds = UserCredentials(
            line_user_id=user_id,
            office_account_name=state["data"]["office_account_name"],
            email=state["data"]["email"],
            password=state["data"]["password"],
        )
        store = get_store()
        store.set(creds)

        # キャッシュをクリア（新しい認証情報で再ログインさせる）
        if user_id in _client_cache:
            del _client_cache[user_id]

        # 登録状態をクリア
        del _registration_state[user_id]

        reply_message(reply_token, [
            text_message(
                "✅ 認証情報を登録しました！\n\n"
                "これでLINEからマネーフォワード勤怠の打刻ができるようになりました。\n\n"
                "📌 使い方:\n"
                "・「出勤」→ 出勤打刻\n"
                "・「退勤」→ 退勤打刻\n"
                "・「休憩開始」→ 休憩開始打刻\n"
                "・「休憩終了」→ 休憩終了打刻\n"
                "・「状況確認」→ 今日の勤怠状況を確認\n\n"
                "画面下部のメニューからも操作できます。"
            )
        ])
        return True

    return False


def _handle_delete_credentials(user_id: str, reply_token: str):
    """認証情報を削除する"""
    store = get_store()
    if store.delete(user_id):
        if user_id in _client_cache:
            del _client_cache[user_id]
        reply_message(reply_token, [
            text_message("✅ 認証情報を削除しました。")
        ])
    else:
        reply_message(reply_token, [
            text_message("認証情報が見つかりませんでした。")
        ])


def _handle_help(reply_token: str):
    """ヘルプメッセージを送信する"""
    reply_message(reply_token, [
        text_message(
            "📖 MF勤怠 LINE Bot の使い方\n\n"
            "【打刻コマンド】\n"
            "・「出勤」→ 出勤打刻\n"
            "・「退勤」→ 退勤打刻\n"
            "・「休憩開始」→ 休憩開始打刻\n"
            "・「休憩終了」→ 休憩終了打刻\n\n"
            "【確認コマンド】\n"
            "・「状況確認」→ 今日の勤怠状況を確認\n\n"
            "【設定コマンド】\n"
            "・「設定」→ マネーフォワード認証情報を登録\n"
            "・「設定削除」→ 登録した認証情報を削除\n"
            "・「ヘルプ」→ この使い方を表示\n\n"
            "画面下部のリッチメニューからも操作できます。"
        )
    ])


def _process_message(user_id: str, reply_token: str, text: str):
    """受信メッセージを処理する"""
    text = text.strip()

    # 登録フロー中の場合は優先処理
    if user_id in _registration_state:
        if _handle_registration_flow(user_id, reply_token, text):
            return

    # コマンド処理
    if text in ("出勤",):
        _handle_punch(user_id, reply_token, "出勤")
    elif text in ("退勤",):
        _handle_punch(user_id, reply_token, "退勤")
    elif text in ("休憩開始", "休憩"):
        _handle_punch(user_id, reply_token, "休憩開始")
    elif text in ("休憩終了", "休憩終わり"):
        _handle_punch(user_id, reply_token, "休憩終了")
    elif text in ("状況確認", "確認", "勤怠確認", "状況"):
        _handle_status(user_id, reply_token)
    elif text in ("設定", "登録", "セットアップ"):
        _handle_setup_start(user_id, reply_token)
    elif text in ("設定削除", "削除", "リセット"):
        _handle_delete_credentials(user_id, reply_token)
    elif text in ("ヘルプ", "help", "使い方"):
        _handle_help(reply_token)
    else:
        # 未知のコマンド
        reply_message(reply_token, [
            quick_reply_message(
                "コマンドを選択してください。",
                [
                    quick_reply_item("出勤", "出勤"),
                    quick_reply_item("退勤", "退勤"),
                    quick_reply_item("休憩開始", "休憩開始"),
                    quick_reply_item("休憩終了", "休憩終了"),
                    quick_reply_item("状況確認", "状況確認"),
                    quick_reply_item("ヘルプ", "ヘルプ"),
                ],
            )
        ])


# ─── Webhook エンドポイント ──────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request):
    """LINE Messaging API Webhook エンドポイント"""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    # 署名検証
    if not _verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    events = payload.get("events", [])

    for event in events:
        event_type = event.get("type")
        reply_token = event.get("replyToken", "")
        source = event.get("source", {})
        user_id = source.get("userId", "")

        if not user_id:
            continue

        if event_type == "message":
            msg = event.get("message", {})
            if msg.get("type") == "text":
                _process_message(user_id, reply_token, msg.get("text", ""))

        elif event_type == "postback":
            data = event.get("postback", {}).get("data", "")
            _process_message(user_id, reply_token, data)

        elif event_type == "follow":
            # 友だち追加時のウェルカムメッセージ
            reply_message(reply_token, [
                text_message(
                    "🎉 マネーフォワード勤怠 LINE Bot へようこそ！\n\n"
                    "このBotを使うと、LINEからマネーフォワード クラウド勤怠の打刻ができます。\n\n"
                    "まず「設定」と送信して、マネーフォワードの認証情報を登録してください。"
                )
            ])

    return Response(content="OK", status_code=200)


@app.get("/health")
async def health():
    """ヘルスチェックエンドポイント"""
    return {"status": "ok", "service": "MF勤怠 LINE Bot"}


@app.get("/")
async def root():
    """ルートエンドポイント"""
    return {
        "service": "MF勤怠 LINE Bot",
        "description": "マネーフォワード クラウド勤怠をLINEから操作するWebhookサーバー",
        "endpoints": {
            "webhook": "POST /webhook",
            "health": "GET /health",
        },
    }
