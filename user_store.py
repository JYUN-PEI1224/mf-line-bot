"""
user_store.py
LINEユーザーIDとマネーフォワード認証情報のマッピング管理

認証情報はJSONファイルに暗号化して保存する。
本番環境ではデータベース（SQLite/PostgreSQL等）への移行を推奨。
"""

from __future__ import annotations

import json
import logging
import os
from base64 import b64encode, b64decode
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 認証情報の保存先ファイル
STORE_FILE = Path(os.getenv("USER_STORE_FILE", "user_store.json"))


@dataclass
class UserCredentials:
    """ユーザーの認証情報"""
    line_user_id: str
    office_account_name: str  # マネーフォワード会社ID
    email: str                # ログインメールアドレス
    password: str             # パスワード（Base64エンコード保存）

    def to_dict(self) -> dict:
        d = asdict(self)
        # パスワードをBase64エンコードして保存
        d["password"] = b64encode(self.password.encode()).decode()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "UserCredentials":
        d = d.copy()
        # Base64デコード
        d["password"] = b64decode(d["password"].encode()).decode()
        return cls(**d)


class UserStore:
    """ユーザー認証情報ストア"""

    def __init__(self, store_file: Path = STORE_FILE):
        self.store_file = store_file
        self._data: Dict[str, UserCredentials] = {}
        self._load()

    def _load(self):
        """ファイルからデータを読み込む"""
        if self.store_file.exists():
            try:
                with open(self.store_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._data = {
                    uid: UserCredentials.from_dict(cred)
                    for uid, cred in raw.items()
                }
                logger.info("ユーザーストアを読み込みました: %d件", len(self._data))
            except Exception as e:
                logger.error("ユーザーストアの読み込みに失敗しました: %s", e)
                self._data = {}

    def _save(self):
        """データをファイルに保存する"""
        try:
            raw = {uid: cred.to_dict() for uid, cred in self._data.items()}
            with open(self.store_file, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("ユーザーストアの保存に失敗しました: %s", e)

    def get(self, line_user_id: str) -> Optional[UserCredentials]:
        """LINEユーザーIDから認証情報を取得する"""
        return self._data.get(line_user_id)

    def set(self, creds: UserCredentials):
        """認証情報を保存する"""
        self._data[creds.line_user_id] = creds
        self._save()
        logger.info("ユーザー認証情報を保存しました: %s", creds.line_user_id)

    def delete(self, line_user_id: str) -> bool:
        """認証情報を削除する"""
        if line_user_id in self._data:
            del self._data[line_user_id]
            self._save()
            logger.info("ユーザー認証情報を削除しました: %s", line_user_id)
            return True
        return False

    def exists(self, line_user_id: str) -> bool:
        """認証情報が存在するか確認する"""
        return line_user_id in self._data


# シングルトンインスタンス
_store: Optional[UserStore] = None


def get_store() -> UserStore:
    """グローバルユーザーストアを取得する"""
    global _store
    if _store is None:
        _store = UserStore()
    return _store
