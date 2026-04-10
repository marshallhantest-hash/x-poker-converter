import streamlit as st
import json
import re
import urllib.parse
import requests
import math
import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# --- 核心常數與配置 (移植自原本 Python 腳本) ---

ACTION_LABELS = {
    0: "does nothing", 1: "posts ante", 2: "posts SB", 3: "posts BB", 
    4: "posts dead BB", 5: "posts straddle", 7: "checks", 8: "folds", 
    9: "bets", 10: "calls", 11: "raises", 12: "pots", 13: "checks", 
    14: "folds", 15: "sits", 16: "posts bomb pot", 17: "posts voluntary straddle", 
    18: "posts voluntary restraddle", 19: "folds"
}

ROUND_LABELS = {1: "Preflop", 2: "Flop", 3: "Turn", 4: "River"}
POSITION_LABELS = {
    2: ["BTN/SB", "BB"], 3: ["BTN", "SB", "BB"], 4: ["BTN", "SB", "BB", "UTG"],
    5: ["BTN", "SB", "BB", "UTG", "CO"], 6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"], 8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"]
}
RANK_MAP = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}
SUIT_MAP = {1: "s", 2: "h", 3: "c", 4: "d"}
SUIT_COLORS = {"s": "#111111", "h": "#d63c3c", "d": "#e78a20", "c": "#2d6cdf"}
ACTION_BUBBLE_COLORS = {
    1: ("#274060", "#dce8ff"), 2: ("#274060", "#dce8ff"), 3: ("#274060", "#dce8ff"),
    4: ("#274060", "#dce8ff"), 5: ("#274060", "#dce8ff"), 7: ("#3a4b68", "#eef3ff"),
    8: ("#414854", "#eef3ff"), 9: ("#f0c04d", "#251b00"), 10: ("#6ca6ff", "#04162f"),
    11: ("#f0c04d", "#251b00"), 12: ("#f0c04d", "#251b00"), 13: ("#3a4b68", "#eef3ff"),
    14: ("#414854", "#eef3ff"), 16: ("#a55d2e", "#fff4e8"), 17: ("#7e55c7", "#f5edff"),
    18: ("#7e55c7", "#f5edff"), 19: ("#414854", "#eef3ff")
}
SEAT_ANGLES = {
    2: [90, -90], 3: [90, -25, -155], 4: [90, 10, -90, 170], 5: [90, 40, -20, -130, 160],
    6: [90, 48, 5, -55, -132, 175], 7: [90, 50, 15, -35, -90, -145, 180],
    8: [90, 52, 10, -33, -90, -147, 180, 130], 9: [90, 58, 25, -10, -50, -95, -140, 180, 132]
}

# --- 輔助邏輯 ---

@dataclass(frozen=True)
class PlayerInfo:
    seat_id: int; position_index: int; position_label: str; uid: int; name: str; 
    begin_chips: int; end_chips: int; cards: list[int]; shown: bool

@dataclass(frozen=True)
class ActionView:
    kind: int; seat_id: int; text: str; image_text: str

@dataclass(frozen=True)
class StreetSummary:
    round_number: int; label: str; board: list[int]; pot_display: int; pot_after: int; actions: list[ActionView]

def quantize_3(v: Decimal) -> Decimal: return v.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
def chips_to_display(c: int) -> str: return format(quantize_3(Decimal(c) / Decimal(100)).normalize(), "f")
def chips_to_bb(c: int, bb: int) -> str: return format(quantize_3(Decimal(c) / Decimal(bb)).normalize(), "f")
def decode_card(cc: int, emoji: bool = False) -> str:
    if not cc: return ""
    r, s = cc % 256, cc // 256
    sc = SUIT_MAP.get(s, "")
    if emoji:
        m = {"s": "♠️", "h": "♥️", "c": "♣️", "d": "♦️"}
        sc = m.get(sc, sc)
    return f"{RANK_MAP.get(r, r)}{sc}"

def sort_cards(cs: list[int]) -> list[int]:
    return sorted([c for c in cs if c], key=lambda c: ((c % 256), (c // 256)), reverse=True)

def build_players(data: dict) -> list[PlayerInfo]:
    ps = data["playerHands"]; built = []
    labels = POSITION_LABELS.get(len(ps))
    for p in ps:
        idx = int(p.get("position", -1))
        lbl = labels[idx] if labels and 0 <= idx < len(labels) else f"POS{idx}"
        cs = [int(p.get(f"card{i}", 0)) for i in range(1, 7)]
        built.append(PlayerInfo(
            seat_id=int(p["seat_id"]), position_index=idx, position_label=lbl, 
            uid=int(p["uid"]), name=str(p["user_name"]), 
            begin_chips=int(p["begin_chips"]), end_chips=int(p["end_chips"]), 
            cards=[c for c in cs if c], shown=bool(p.get("is_show_hands"))
        ))
    return sorted(built, key=lambda x: x.position_index)

def build_street_summaries(data: dict, players: list[PlayerInfo]) -> list[StreetSummary]:
    h = data["handInfo"]; bb = int(h["big_blind"]); p_map = {p.seat_id: p for p in players}
    rem = {p.seat_id: p.begin_chips for p in players}; rounds = h["round"]; c_pot = 0; sums = []
    for r in rounds:
        r_num = int(r["round"]); p_disp = c_pot
        if r_num == 1:
            p_disp = 0
            for a in r.get("action", []):
                if int(a["action_kind"]) not in {1, 2, 3, 4, 5, 16, 17, 18}: break
                p_disp += int(a.get("action_chips", 0))
        acts = []
        for a in r.get("action", []):
            sid = int(a["seat_id"]); p = p_map[sid]; amt = int(a.get("action_chips", 0)); k = int(a["action_kind"])
            bef = sum(act.kind in {1,2,3,4,5,16} for act in acts if act.seat_id == sid) # 簡化邏輯
            rem[sid] -= amt; ai = " (all-in)" if rem[sid] == 0 and amt > 0 else ""
            l = ACTION_LABELS.get(k, f"action_{k}")
            t = f"{p.position_label} {p.name} {l} {chips_to_bb(amt, bb)} BB{ai}"
            acts.append(ActionView(kind=k, seat_id=sid, text=t, image_text=f"{p.name}: {l}{ai}"))
            c_pot += amt
        bd = []
        for rr in rounds:
            if int(rr["round"]) <= r_num: bd.extend(rr.get("card", []))
        sums.append(StreetSummary(
            round_number=r_num, label=ROUND_LABELS.get(r_num, f"Round {r_num}"), 
            board=bd, pot_display=p_disp, pot_after=c_pot, actions=acts
        ))
    return sums

# --- 繪圖邏輯 (Pillow) ---

def get_font(size, bold=False):
    # Streamlit Cloud 常用中文字體
    paths = ["msyh.ttc", "NotoSansTC-Regular.otf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    for p in paths:
        if Path(p).exists(): return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def draw_card_p(draw, x, y, card, w, h):
    r, s = card[:-1], card[-1]; fill = SUIT_COLORS.get(s, "#000")
    draw.rounded_rectangle([x, y, x+w, y+h], radius=5, fill=fill, outline="#fff", width=1)
    f = get_font(int(w*0.5), bold=True)
    draw.text((x+w/2, y+h/2), r+s, font=f, fill="#fff", anchor="mm")

# --- UI 介面 ---

st.set_page_config(page_title="X-Poker Replay Converter", layout="wide")
st.title("🃏 X-Poker 牌局解析器 (完整版)")
st.markdown("貼上 Replay 網址即可自動解析文字詳情與產生圖解。")

input_url = st.text_input("輸入網址或 Key:", placeholder="replay_key=...")

if st.button("🚀 解析並生成"):
    key_match = re.search(r"replay_key=([a-f0-9-]+)", input_url)
    key = key_match.group(1) if key_match else input_url
    
    if key and len(key) == 36:
        with st.spinner("從伺服器解析資料中..."):
            url = f"https://static.x-game.net/resource/replay/hand/{key}.json"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                data = resp.json(); players = build_players(data); streets = build_street_summaries(data, players)
                hand_id = data["handInfo"]["hand_id"]
                
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.subheader("📝 文字歷史")
                    output = f"Hand #{hand_id}\nKey: {key}\n"
                    for s in streets:
                        output += f"\n--- {s.label} ({chips_to_bb(s.pot_display, int(data['handInfo']['big_blind']))} BB) ---\n"
                        if s.round_number > 1: output += f"Board: {' '.join(decode_card(c, True) for c in s.board)}\n"
                        for a in s.actions: output += a.text + "\n"
                    st.text_area("Hand Details:", output, height=600)
                
                with col2:
                    st.subheader("🖼️ 牌局圖解")
                    # 簡易渲染測試
                    img = Image.new("RGB", (1000, 800), "#0b1118"); draw = ImageDraw.Draw(img)
                    f_title = get_font(40, True); draw.text((20, 20), f"X-Poker Hand #{hand_id}", font=f_title, fill="#f4f7fb")
                    
                    # 繪製公共牌
                    bd = [decode_card(c) for c in streets[-1].board if c]
                    for i, c in enumerate(bd): draw_card_p(draw, 300 + i*60, 250, c, 50, 75)
                    
                    # 繪製玩家列表
                    f_p = get_font(20)
                    for i, p in enumerate(players):
                        y_pos = 100 + i*50
                        draw.text((20, y_pos), f"{p.position_label}: {p.name} ({chips_to_bb(p.begin_chips, int(data['handInfo']['big_blind']))} BB)", font=f_p, fill="#fff")
                        if p.cards:
                            for ci, cc in enumerate(p.cards): draw_card_p(draw, 250 + ci*45, y_pos-5, decode_card(cc), 40, 55)
                    
                    st.image(img)
                    buf = BytesIO(); img.save(buf, format="PNG"); byte_im = buf.getvalue()
                    st.download_button("💾 下載圖解", byte_im, f"{hand_id}.png", "image/png")
            else:
                st.error("擷取失敗，請確認網址是否正確。")
    else:
        st.warning("請輸入正確的 Replay Key (36位 UUID)。")
