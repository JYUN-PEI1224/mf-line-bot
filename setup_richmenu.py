"""
setup_richmenu.py
LINE Bot のリッチメニューを自動セットアップするスクリプト

実行方法:
    python setup_richmenu.py

必要な環境変数:
    LINE_CHANNEL_ACCESS_TOKEN : LINE Messaging API チャンネルアクセストークン
"""

import json
import os
import sys
import requests
from pathlib import Path

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_API_BASE = "https://api.line.me/v2/bot"


def headers() -> dict:
    return {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def create_richmenu() -> str:
    """リッチメニューを作成してIDを返す"""

    # リッチメニューの定義
    # レイアウト: 2行 × 3列 = 6ボタン
    #  ┌──────────┬──────────┬──────────┐
    #  │  出勤    │  退勤    │ 休憩開始 │
    #  ├──────────┼──────────┼──────────┤
    #  │ 休憩終了 │ 状況確認 │  設定    │
    #  └──────────┴──────────┴──────────┘
    #
    # 画像サイズ: 2500 x 1686 px（LINE推奨）
    # 各セル: 幅 833px × 高さ 843px

    richmenu = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "MF勤怠メニュー",
        "chatBarText": "勤怠メニュー",
        "areas": [
            # 行1, 列1: 出勤
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "label": "出勤",
                    "text": "出勤"
                }
            },
            # 行1, 列2: 退勤
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {
                    "type": "message",
                    "label": "退勤",
                    "text": "退勤"
                }
            },
            # 行1, 列3: 休憩開始
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "label": "休憩開始",
                    "text": "休憩開始"
                }
            },
            # 行2, 列1: 休憩終了
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "label": "休憩終了",
                    "text": "休憩終了"
                }
            },
            # 行2, 列2: 状況確認
            {
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                "action": {
                    "type": "message",
                    "label": "状況確認",
                    "text": "状況確認"
                }
            },
            # 行2, 列3: 設定
            {
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "label": "設定",
                    "text": "設定"
                }
            },
        ]
    }

    resp = requests.post(
        f"{LINE_API_BASE}/richmenu",
        headers=headers(),
        json=richmenu,
        timeout=10,
    )

    if not resp.ok:
        print(f"❌ リッチメニューの作成に失敗しました: {resp.status_code}")
        print(resp.text)
        sys.exit(1)

    richmenu_id = resp.json()["richMenuId"]
    print(f"✅ リッチメニューを作成しました: {richmenu_id}")
    return richmenu_id


def upload_richmenu_image(richmenu_id: str, image_path: str):
    """リッチメニュー画像をアップロードする"""
    image_file = Path(image_path)
    if not image_file.exists():
        print(f"⚠️  画像ファイルが見つかりません: {image_path}")
        print("   リッチメニューは作成されましたが、画像なしの状態です。")
        print("   LINE Official Account Manager から手動で画像を設定してください。")
        return

    content_type = "image/png" if image_path.endswith(".png") else "image/jpeg"

    with open(image_path, "rb") as f:
        resp = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{richmenu_id}/content",
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": content_type,
            },
            data=f.read(),
            timeout=30,
        )

    if not resp.ok:
        print(f"❌ 画像のアップロードに失敗しました: {resp.status_code}")
        print(resp.text)
    else:
        print(f"✅ リッチメニュー画像をアップロードしました")


def set_default_richmenu(richmenu_id: str):
    """デフォルトのリッチメニューを設定する"""
    resp = requests.post(
        f"{LINE_API_BASE}/user/all/richmenu/{richmenu_id}",
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        timeout=10,
    )

    if not resp.ok:
        print(f"❌ デフォルトリッチメニューの設定に失敗しました: {resp.status_code}")
        print(resp.text)
    else:
        print(f"✅ デフォルトリッチメニューを設定しました")


def delete_existing_richmenus():
    """既存のリッチメニューをすべて削除する"""
    resp = requests.get(
        f"{LINE_API_BASE}/richmenu/list",
        headers=headers(),
        timeout=10,
    )
    if not resp.ok:
        return

    menus = resp.json().get("richmenus", [])
    for menu in menus:
        mid = menu["richMenuId"]
        del_resp = requests.delete(
            f"{LINE_API_BASE}/richmenu/{mid}",
            headers=headers(),
            timeout=10,
        )
        if del_resp.ok:
            print(f"🗑️  既存リッチメニューを削除しました: {mid}")


def generate_richmenu_image():
    """
    Pillowを使ってリッチメニュー画像を生成する
    
    ボタンレイアウト:
    ┌──────────┬──────────┬──────────┐
    │  🟢 出勤  │  🔴 退勤  │ 🟡 休憩開始│
    ├──────────┼──────────┼──────────┤
    │ 🟠 休憩終了│ 📊 状況確認│ ⚙️ 設定  │
    └──────────┴──────────┴──────────┘
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("⚠️  Pillowがインストールされていません。画像生成をスキップします。")
        return None

    W, H = 2500, 1686
    img = Image.new("RGB", (W, H), color=(245, 245, 245))
    draw = ImageDraw.Draw(img)

    # ボタン定義: (x, y, w, h, ラベル, 絵文字, 背景色)
    buttons = [
        (0,    0,    833, 843, "出勤",   "🟢", (76,  175, 80)),   # 緑
        (833,  0,    834, 843, "退勤",   "🔴", (244, 67,  54)),   # 赤
        (1667, 0,    833, 843, "休憩開始", "🟡", (255, 193, 7)),  # 黄
        (0,    843,  833, 843, "休憩終了", "🟠", (255, 152, 0)),  # オレンジ
        (833,  843,  834, 843, "状況確認", "📊", (33,  150, 243)), # 青
        (1667, 843,  833, 843, "設定",   "⚙️", (156, 39,  176)), # 紫
    ]

    # フォントの設定（日本語対応フォントを試みる）
    font_large = None
    font_small = None
    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                font_large = ImageFont.truetype(fp, 120)
                font_small = ImageFont.truetype(fp, 80)
                break
            except Exception:
                continue

    if font_large is None:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    for (x, y, w, h, label, emoji, color) in buttons:
        # 背景色
        draw.rectangle([x, y, x + w, y + h], fill=color)
        # 境界線
        draw.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 255, 255), width=4)

        # テキスト（絵文字は省略してラベルのみ）
        text = label
        try:
            bbox = draw.textbbox((0, 0), text, font=font_large)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw, th = len(text) * 60, 120

        tx = x + (w - tw) // 2
        ty = y + (h - th) // 2

        # テキストの影
        draw.text((tx + 4, ty + 4), text, fill=(0, 0, 0, 128), font=font_large)
        # テキスト本体
        draw.text((tx, ty), text, fill=(255, 255, 255), font=font_large)

    output_path = "richmenu.png"
    img.save(output_path)
    print(f"✅ リッチメニュー画像を生成しました: {output_path}")
    return output_path


def main():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません。")
        print("   export LINE_CHANNEL_ACCESS_TOKEN='your_token' を実行してください。")
        sys.exit(1)

    print("=" * 50)
    print("MF勤怠 LINE Bot リッチメニューセットアップ")
    print("=" * 50)

    # 既存のリッチメニューを削除
    print("\n1. 既存のリッチメニューを削除します...")
    delete_existing_richmenus()

    # リッチメニューを作成
    print("\n2. リッチメニューを作成します...")
    richmenu_id = create_richmenu()

    # 画像を生成してアップロード
    print("\n3. リッチメニュー画像を生成・アップロードします...")
    image_path = generate_richmenu_image()
    if image_path:
        upload_richmenu_image(richmenu_id, image_path)
    else:
        print("   画像なしでセットアップを続行します。")
        print("   LINE Official Account Manager から手動で画像を設定してください。")

    # デフォルトリッチメニューとして設定
    print("\n4. デフォルトリッチメニューとして設定します...")
    set_default_richmenu(richmenu_id)

    print("\n" + "=" * 50)
    print("✅ リッチメニューのセットアップが完了しました！")
    print(f"   リッチメニューID: {richmenu_id}")
    print("=" * 50)


if __name__ == "__main__":
    main()
