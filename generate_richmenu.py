from PIL import Image, ImageDraw, ImageFont
import math

# LINEリッチメニューの推奨サイズ（大・6分割）
WIDTH = 2500
HEIGHT = 1686

FONT_PATH_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FONT_PATH_REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

COLS = 3
ROWS = 2
BORDER = 10

cell_w = WIDTH // COLS
cell_h = HEIGHT // ROWS

# 落ち着いたアースカラー・くすみカラーパレット
BG_COLOR = "#F5F0EB"   # 背景：温かみのあるオフホワイト

# A=出勤, B=退勤, C=設定, D=休憩開始, E=休憩終了, F=状況確認
BUTTONS = [
    {"label": "出勤",     "bg": "#7BAE8F", "icon_color": "#FFFFFF", "label_color": "#FFFFFF"},  # A: セージグリーン
    {"label": "退勤",     "bg": "#C4837A", "icon_color": "#FFFFFF", "label_color": "#FFFFFF"},  # B: テラコッタ
    {"label": "設定",     "bg": "#8FAF9F", "icon_color": "#FFFFFF", "label_color": "#FFFFFF"},  # C: ミントグレー
    {"label": "休憩開始", "bg": "#D4A96A", "icon_color": "#FFFFFF", "label_color": "#FFFFFF"},  # D: ウォームサンド
    {"label": "休憩終了", "bg": "#7A9BBF", "icon_color": "#FFFFFF", "label_color": "#FFFFFF"},  # E: ダスティブルー
    {"label": "状況確認", "bg": "#9B8EC4", "icon_color": "#FFFFFF", "label_color": "#FFFFFF"},  # F: モーブパープル
]

img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
draw = ImageDraw.Draw(img)

def draw_rounded_rect_solid(draw, x0, y0, x1, y1, r, fill):
    """単色の角丸矩形"""
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    draw.ellipse([x0, y0, x0 + 2*r, y0 + 2*r], fill=fill)
    draw.ellipse([x1 - 2*r, y0, x1, y0 + 2*r], fill=fill)
    draw.ellipse([x0, y1 - 2*r, x0 + 2*r, y1], fill=fill)
    draw.ellipse([x1 - 2*r, y1 - 2*r, x1, y1], fill=fill)

def draw_icon_clock_in(draw, cx, cy, size, color):
    """出勤：丸の中に右向き三角"""
    r = size // 2
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=size//9)
    tri = size // 3
    pts = [(cx - tri//2, cy - tri), (cx - tri//2, cy + tri), (cx + tri, cy)]
    draw.polygon(pts, fill=color)

def draw_icon_clock_out(draw, cx, cy, size, color):
    """退勤：丸の中にXマーク（退場）"""
    r = size // 2
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=size//9)
    s = size // 3
    lw = size // 9
    draw.line([(cx-s, cy-s), (cx+s, cy+s)], fill=color, width=lw)
    draw.line([(cx+s, cy-s), (cx-s, cy+s)], fill=color, width=lw)

def draw_icon_break_start(draw, cx, cy, size, color):
    """休憩開始：シンプルなコーヒーカップ（丸＋取っ手）"""
    r = size // 3
    lw = size // 9
    # カップ本体（丸）
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=lw)
    # 取っ手（右側の半円弧）
    draw.arc([cx + r - lw, cy - r//2, cx + r + r//2, cy + r//2],
             start=-90, end=90, fill=color, width=lw)
    # 湯気（2本の短い縦線）
    for dx in [-r//3, r//3]:
        draw.line([(cx+dx, cy-r-lw), (cx+dx, cy-r-lw-r//3)],
                  fill=color, width=lw)

def draw_icon_break_end(draw, cx, cy, size, color):
    """休憩終了：左向き矢印（シンプル）"""
    s = size // 2
    lw = size // 9
    # 横棒
    draw.line([(cx - s, cy), (cx + s//2, cy)], fill=color, width=lw)
    # 矢印の先端（左向き三角）
    tri = s // 2
    pts = [(cx - s, cy), (cx - s + tri, cy - tri), (cx - s + tri, cy + tri)]
    draw.polygon(pts, fill=color)

def draw_icon_check(draw, cx, cy, size, color):
    """状況確認：シンプルなクリップボード"""
    s = size // 2
    lw = size // 10
    # 外枠（角丸）
    draw_rounded_rect_solid(draw, cx-s, cy-s, cx+s, cy+s, lw*2, color)
    # 内側を背景色で塗りつぶして枠だけ残す
    inner = lw + 2
    draw_rounded_rect_solid(draw, cx-s+lw, cy-s+lw, cx+s-lw, cy+s-lw, lw, "#FFFFFF")
    # 横線3本（濃い色）
    for yoff in [-s//3, 0, s//3]:
        draw.line([(cx - s//2, cy + yoff), (cx + s//2, cy + yoff)],
                  fill=color, width=lw)
    # 上部クリップ（小さい四角）
    cw = s // 2
    draw.rectangle([cx - cw//2, cy - s - lw, cx + cw//2, cy - s + lw*2], fill=color)

def draw_icon_gear(draw, cx, cy, size, color):
    """設定：シンプルな歯車（外リング＋中心円＋歯）"""
    r_out = size // 2
    r_in  = int(size * 0.22)
    lw = size // 10
    teeth = 8
    # 外周リング
    draw.ellipse([cx-r_out, cy-r_out, cx+r_out, cy+r_out], outline=color, width=lw)
    # 歯（短い線を放射状に）
    for i in range(teeth):
        angle = 2 * math.pi * i / teeth
        x1 = cx + int((r_out - lw) * math.cos(angle))
        y1 = cy + int((r_out - lw) * math.sin(angle))
        x2 = cx + int((r_out + lw*2) * math.cos(angle))
        y2 = cy + int((r_out + lw*2) * math.sin(angle))
        draw.line([(x1, y1), (x2, y2)], fill=color, width=lw*2)
    # 中心円（塗りつぶし）
    draw.ellipse([cx-r_in, cy-r_in, cx+r_in, cy+r_in], fill=color)

# A=出勤, B=退勤, C=設定, D=休憩開始, E=休憩終了, F=状況確認
ICON_FUNCS = [
    draw_icon_clock_in,    # A: 出勤
    draw_icon_clock_out,   # B: 退勤
    draw_icon_gear,        # C: 設定
    draw_icon_break_start, # D: 休憩開始
    draw_icon_break_end,   # E: 休憩終了
    draw_icon_check,       # F: 状況確認
]

# 各セルを描画
for i, btn in enumerate(BUTTONS):
    row = i // COLS
    col = i % COLS

    pad = 18
    x0 = col * cell_w + pad
    y0 = row * cell_h + pad
    x1 = x0 + cell_w - pad * 2
    y1 = y0 + cell_h - pad * 2

    draw_rounded_rect_solid(draw, x0, y0, x1, y1, 40, btn["bg"])

    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2

    # アイコン（中央より上）
    icon_size = cell_h // 4
    ICON_FUNCS[i](draw, cx, cy - icon_size // 3, icon_size, btn["icon_color"])

    # ラベル（下部）
    try:
        font_label = ImageFont.truetype(FONT_PATH_BOLD, 130)
    except:
        font_label = ImageFont.load_default()

    label = btn["label"]
    bbox = draw.textbbox((0, 0), label, font=font_label)
    lw_text = bbox[2] - bbox[0]
    lh_text = bbox[3] - bbox[1]
    draw.text((cx - lw_text // 2, y1 - lh_text - 80), label,
              font=font_label, fill=btn["label_color"])

out_path = "/home/ubuntu/mf-line-bot/richmenu.png"
img.save(out_path, "PNG")
print(f"保存完了: {out_path}  サイズ: {img.size}")
