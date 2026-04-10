from __future__ import annotations

import argparse
import json
import math
import random
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ACTION_LABELS = {
    0: "does nothing",
    1: "posts ante",
    2: "posts SB",
    3: "posts BB",
    4: "posts dead BB",
    5: "posts straddle",
    7: "checks",
    8: "folds",
    9: "bets",
    10: "calls",
    11: "raises",
    12: "pots",
    13: "checks",
    14: "folds",
    15: "sits",
    16: "posts bomb pot",
    17: "posts voluntary straddle",
    18: "posts voluntary restraddle",
    19: "folds",
}

ROUND_LABELS = {
    1: "Preflop",
    2: "Flop",
    3: "Turn",
    4: "River",
}

POSITION_LABELS = {
    2: ["BTN/SB", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "UTG"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"],
}

RANK_MAP = {
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "T",
    11: "J",
    12: "Q",
    13: "K",
    14: "A",
}

# Verified from the replay assets:
# 1=spade, 2=heart, 3=club, 4=diamond
SUIT_MAP = {
    1: "s",
    2: "h",
    3: "c",
    4: "d",
}

SUIT_COLORS = {
    "s": "#111111",
    "h": "#d63c3c",
    "d": "#e78a20",
    "c": "#2d6cdf",
}

ACTION_BUBBLE_COLORS = {
    1: ("#274060", "#dce8ff"),
    2: ("#274060", "#dce8ff"),
    3: ("#274060", "#dce8ff"),
    4: ("#274060", "#dce8ff"),
    5: ("#274060", "#dce8ff"),
    7: ("#3a4b68", "#eef3ff"),
    8: ("#414854", "#eef3ff"),
    9: ("#f0c04d", "#251b00"),
    10: ("#6ca6ff", "#04162f"),
    11: ("#f0c04d", "#251b00"),
    12: ("#f0c04d", "#251b00"),
    13: ("#3a4b68", "#eef3ff"),
    14: ("#414854", "#eef3ff"),
    16: ("#a55d2e", "#fff4e8"),
    17: ("#7e55c7", "#f5edff"),
    18: ("#7e55c7", "#f5edff"),
    19: ("#414854", "#eef3ff"),
}

SEAT_ANGLES = {
    2: [90, -90],
    3: [90, -25, -155],
    4: [90, 10, -90, 170],
    5: [90, 40, -20, -130, 160],
    6: [90, 48, 5, -55, -132, 175],
    7: [90, 50, 15, -35, -90, -145, 180],
    8: [90, 52, 10, -33, -90, -147, 180, 130],
    9: [90, 58, 25, -10, -50, -95, -140, 180, 132],
}

FONT_REGULAR_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\arial.ttf",
]

FONT_BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\arialbd.ttf",
]


@dataclass(frozen=True)
class PlayerInfo:
    seat_id: int
    position_index: int
    position_label: str
    uid: int
    name: str
    begin_chips: int
    end_chips: int
    cards: list[int]
    shown: bool


@dataclass(frozen=True)
class ActionView:
    kind: int
    seat_id: int
    text: str
    image_text: str


@dataclass(frozen=True)
class StreetSummary:
    round_number: int
    label: str
    board: list[int]
    pot_display: int
    pot_after: int
    actions: list[ActionView]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert an X-Poker replay URL/key into txt and png hand history files."
    )
    parser.add_argument("source", help="Replay URL or replay_key")
    parser.add_argument(
        "-o",
        "--output",
        help="Output txt path. Defaults to <hand_id>.txt in the current directory.",
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="Save the fetched replay JSON next to the output txt.",
    )
    return parser.parse_args()


def extract_replay_key(source: str) -> str:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme and parsed.netloc:
        params = urllib.parse.parse_qs(parsed.query)
        replay_keys = params.get("replay_key")
        if replay_keys and replay_keys[0]:
            return replay_keys[0]
    if re.fullmatch(r"[0-9a-fA-F-]{36}", source):
        return source
    raise ValueError("Could not parse replay_key from the provided source.")


def fetch_replay_json(replay_key: str) -> dict[str, Any]:
    url = f"https://static.x-game.net/resource/replay/hand/{replay_key}.json"
    with urllib.request.urlopen(url) as response:
        if response.status != 200:
            raise RuntimeError(f"Failed to fetch replay JSON: HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def quantize_3(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def chips_to_display(chips: int) -> str:
    value = quantize_3(Decimal(chips) / Decimal(100))
    return format(value.normalize(), "f")


def chips_to_bb(chips: int, big_blind: int) -> str:
    value = quantize_3(Decimal(chips) / Decimal(big_blind))
    return format(value.normalize(), "f")


def format_chips_bb(chips: int, big_blind: int) -> str:
    return f"{chips_to_display(chips)} ({chips_to_bb(chips, big_blind)} BB)"


def decode_card(card_code: int, use_emoji: bool = False) -> str:
    if not card_code:
        return ""
    rank = card_code % 256
    suit = card_code // 256
    try:
        suit_char = SUIT_MAP[suit]
        if use_emoji:
            if suit_char == "s": suit_char = "♠️"
            elif suit_char == "h": suit_char = "♥️"
            elif suit_char == "c": suit_char = "♣️"
            elif suit_char == "d": suit_char = "♦️"
        return f"{RANK_MAP[rank]}{suit_char}"
    except KeyError as exc:
        raise ValueError(f"Unknown card code: {card_code}") from exc


def sort_cards_for_display(cards: list[int]) -> list[int]:
    return sorted(
        [card for card in cards if card],
        key=lambda card: ((card % 256), (card // 256)),
        reverse=True,
    )


def board_for_rounds(rounds: list[dict[str, Any]], street_number: int) -> list[int]:
    cards: list[int] = []
    for round_data in rounds:
        round_id = round_data["round"]
        if round_id > street_number:
            break
        cards.extend(round_data.get("card", []))
    return cards


def build_players(data: dict[str, Any]) -> list[PlayerInfo]:
    players = data["playerHands"]
    player_count = len(players)
    labels = POSITION_LABELS.get(player_count)
    built: list[PlayerInfo] = []

    for player in players:
        position_index = int(player.get("position", -1))
        if labels and 0 <= position_index < len(labels):
            position_label = labels[position_index]
        else:
            position_label = f"POS{position_index}"

        cards = [int(player.get(f"card{i}", 0)) for i in range(1, 7)]
        built.append(
            PlayerInfo(
                seat_id=int(player["seat_id"]),
                position_index=position_index,
                position_label=position_label,
                uid=int(player["uid"]),
                name=str(player["user_name"]),
                begin_chips=int(player["begin_chips"]),
                end_chips=int(player["end_chips"]),
                cards=[card for card in cards if card],
                shown=bool(player.get("is_show_hands")),
            )
        )

    return sorted(built, key=lambda player: player.position_index)


def player_name_map(players: list[PlayerInfo]) -> dict[int, PlayerInfo]:
    return {player.seat_id: player for player in players}


def describe_action(
    kind: int,
    amount_bb: str,
    after_bb: str,
    all_in_suffix: str,
) -> str:
    if kind == 1:
        return f"posts ante {amount_bb} BB"
    if kind == 2:
        return f"posts SB {amount_bb} BB"
    if kind == 3:
        return f"posts BB {amount_bb} BB"
    if kind == 4:
        return f"posts dead BB {amount_bb} BB"
    if kind == 5:
        return f"posts straddle {amount_bb} BB"
    if kind in {7, 13}:
        return "checks"
    if kind in {8, 14, 19}:
        return "folds"
    if kind == 9:
        return f"bets {amount_bb} BB{all_in_suffix}"
    if kind == 10:
        return f"calls {amount_bb} BB{all_in_suffix}"
    if kind == 11:
        return f"raises to {after_bb} BB{all_in_suffix}"
    if kind == 12:
        return f"pots to {after_bb} BB{all_in_suffix}"
    if kind == 16:
        return f"posts bomb pot {amount_bb} BB{all_in_suffix}"
    if kind == 17:
        return f"posts voluntary straddle {amount_bb} BB{all_in_suffix}"
    if kind == 18:
        return f"posts voluntary restraddle {amount_bb} BB{all_in_suffix}"
    if kind == 15:
        return "sits"

    label = ACTION_LABELS.get(kind, f"action_{kind}")
    if amount_bb != "0":
        return f"{label} {amount_bb} BB{all_in_suffix}"
    return label


def format_action_line(
    action: dict[str, Any],
    player: PlayerInfo,
    big_blind: int,
    round_contrib: dict[int, int],
    remaining: dict[int, int],
) -> tuple[str, str]:
    kind = int(action["action_kind"])
    amount = int(action.get("action_chips", 0))
    seat_id = int(action["seat_id"])

    before = round_contrib.get(seat_id, 0)
    after = before + amount
    round_contrib[seat_id] = after
    remaining[seat_id] -= amount

    prefix = f"{player.position_label} {player.name}"
    amount_bb = chips_to_bb(amount, big_blind)
    after_bb = chips_to_bb(after, big_blind)
    all_in_suffix = " (all-in)" if remaining[seat_id] == 0 and amount > 0 else ""
    action_text = describe_action(kind, amount_bb, after_bb, all_in_suffix)
    return f"{prefix} {action_text}", f"{player.name}: {action_text}"


def build_street_summaries(data: dict[str, Any], players: list[PlayerInfo]) -> list[StreetSummary]:
    hand = data["handInfo"]
    big_blind = int(hand["big_blind"])
    players_by_seat = player_name_map(players)
    remaining = {player.seat_id: player.begin_chips for player in players}
    rounds = hand["round"]
    cumulative_pot = 0
    summaries: list[StreetSummary] = []

    for round_data in rounds:
        round_number = int(round_data["round"])
        pot_display = cumulative_pot
        if round_number == 1:
            forced_action_kinds = {1, 2, 3, 4, 5, 16, 17, 18}
            pot_display = 0
            for action in round_data.get("action", []):
                if int(action["action_kind"]) not in forced_action_kinds:
                    break
                pot_display += int(action.get("action_chips", 0))
        round_contrib: dict[int, int] = {}
        actions: list[ActionView] = []
        for action in round_data.get("action", []):
            player = players_by_seat[int(action["seat_id"])]
            line, image_line = format_action_line(
                action=action,
                player=player,
                big_blind=big_blind,
                round_contrib=round_contrib,
                remaining=remaining,
            )
            actions.append(
                ActionView(
                    kind=int(action["action_kind"]),
                    seat_id=int(action["seat_id"]),
                    text=line,
                    image_text=image_line,
                )
            )
            cumulative_pot += int(action.get("action_chips", 0))

        summaries.append(
            StreetSummary(
                round_number=round_number,
                label=ROUND_LABELS.get(round_number, f"Round {round_number}"),
                board=board_for_rounds(rounds, round_number),
                pot_display=pot_display,
                pot_after=cumulative_pot,
                actions=actions,
            )
        )

    return summaries


def build_showdown_lines(
    players: list[PlayerInfo],
    winning_info: list[dict[str, Any]],
    big_blind: int,
    use_emoji: bool = False,
) -> list[str]:
    players_by_seat = player_name_map(players)
    lines: list[str] = []
    shown_players = [player for player in players if player.shown and player.cards]
    for player in shown_players:
        display_cards = " ".join(
            decode_card(card, use_emoji) for card in sort_cards_for_display(player.cards)
        )
        lines.append(f"{player.position_label} {player.name} shows [{display_cards}]")

    for winner in winning_info:
        winner_player = players_by_seat[int(winner["seat_id"])]
        amount = int(winner["pot_chips"])
        best_five = winner.get("best_hands") or []
        best_five_text = ""
        if best_five:
            best_five_text = " with [" + " ".join(decode_card(card, use_emoji) for card in best_five) + "]"
        lines.append(
            f"{winner_player.position_label} {winner_player.name} wins "
            f"{chips_to_bb(amount, big_blind)} BB{best_five_text}"
        )

    return lines


def render_hand_history(data: dict[str, Any], replay_key: str) -> str:
    hand = data["handInfo"]
    game = data["gameSetInfo"]
    big_blind = int(hand["big_blind"])
    small_blind = int(hand["small_blind"])
    players = build_players(data)
    streets = build_street_summaries(data, players)

    lines: list[str] = []
    lines.append(f"X-Poker Hand #{hand['hand_id']}")
    lines.append(f"Replay Key: {replay_key}")
    lines.append(f"Table: {game['game_name']}")
    lines.append(f"Blinds: {chips_to_display(small_blind)}/{chips_to_display(big_blind)}")
    lines.append(f"Seats: {len(players)}")
    lines.append("")
    lines.append("Starting Stacks")
    for player in players:
        lines.append(
            f"{player.position_label} (seat {player.seat_id}) {player.name}: "
            f"{format_chips_bb(player.begin_chips, big_blind)}"
        )

    known_hands = [player for player in players if player.cards]
    if known_hands:
        lines.append("")
        lines.append("Known Hole Cards")
        for player in known_hands:
            display_cards = " ".join(
                decode_card(card, use_emoji=True) for card in sort_cards_for_display(player.cards)
            )
            reveal_label = "shown" if player.shown else "known"
            lines.append(f"{player.position_label} {player.name}: [{display_cards}] ({reveal_label})")

    for street in streets:
        lines.append("")
        pot_text = f"Pot {chips_to_bb(street.pot_display, big_blind)} BB"
        if street.round_number == 1:
            lines.append(f"{street.label} ({pot_text})")
        else:
            board_cards = " ".join(decode_card(card, use_emoji=True) for card in street.board)
            lines.append(f"{street.label} [{board_cards}] ({pot_text})")
        for action in street.actions:
            lines.append(action.text)

    winning_info = hand.get("winning_info", [])
    if winning_info:
        lines.append("")
        lines.append("Showdown")
        lines.extend(build_showdown_lines(players, winning_info, big_blind, use_emoji=True))

    fee = int(hand.get("fee", 0))
    jackpot_fee = int(hand.get("jackpot_fee", 0))
    insurance_fee = int(hand.get("insurance_fee", 0))
    evchop_fee = int(hand.get("evchop_fee", 0))
    if any((fee, jackpot_fee, insurance_fee, evchop_fee)):
        lines.append("")
        lines.append("Fees")
        if fee:
            lines.append(f"Rake: {chips_to_bb(fee, big_blind)} BB")
        if jackpot_fee:
            lines.append(f"Jackpot fee: {chips_to_bb(jackpot_fee, big_blind)} BB")
        if insurance_fee:
            lines.append(f"Insurance fee: {chips_to_bb(insurance_fee, big_blind)} BB")
        if evchop_fee:
            lines.append(f"EV Chop fee: {chips_to_bb(evchop_fee, big_blind)} BB")

    return "\n".join(lines) + "\n"


def build_numeric_aliases(players: list[PlayerInfo], hand_id: str) -> dict[int, str]:
    rng = random.Random(f"{hand_id}:anon")
    aliases: dict[int, str] = {}
    used: set[str] = set()
    for player in sorted(players, key=lambda item: item.seat_id):
        while True:
            alias = str(rng.randint(10_000_000, 99_999_999))
            if alias not in used:
                used.add(alias)
                aliases[player.seat_id] = alias
                break
    return aliases


def remap_player_names(players: list[PlayerInfo], aliases: dict[int, str]) -> list[PlayerInfo]:
    return [replace(player, name=aliases.get(player.seat_id, player.name)) for player in players]


def format_pt4_timestamp(unix_ts: int) -> str:
    dt_utc = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    year = dt_utc.year

    march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
    march_first_offset = (6 - march_first.weekday()) % 7
    second_sunday_march = 1 + march_first_offset + 7
    dst_start_utc = datetime(year, 3, second_sunday_march, 7, 0, 0, tzinfo=timezone.utc)

    november_first = datetime(year, 11, 1, tzinfo=timezone.utc)
    november_first_offset = (6 - november_first.weekday()) % 7
    first_sunday_november = 1 + november_first_offset
    dst_end_utc = datetime(year, 11, first_sunday_november, 6, 0, 0, tzinfo=timezone.utc)

    offset_hours = -4 if dst_start_utc <= dt_utc < dst_end_utc else -5
    dt_et = dt_utc + timedelta(hours=offset_hours)
    return dt_et.strftime("%Y/%m/%d %H:%M:%S ET")


def player_seat_number(player: PlayerInfo) -> int:
    return player.seat_id + 1


def format_pt4_cards(card_codes: list[int], preserve_order: bool = True) -> str:
    cards = [card for card in card_codes if card]
    if not preserve_order:
        cards = sort_cards_for_display(cards)
    return " ".join(decode_card(card) for card in cards)


def pt4_position_note(player: PlayerInfo) -> str:
    if player.position_label == "BTN/SB":
        return "button and small blind"
    if player.position_label == "BTN":
        return "button"
    if player.position_label == "SB":
        return "small blind"
    if player.position_label == "BB":
        return "big blind"
    return ""


def pt4_table_name(data: dict[str, Any]) -> str:
    game = data["gameSetInfo"]
    room_id = game.get("room_id", "table")
    return f"XGame {room_id}"


def format_pt4_action_line(
    action: dict[str, Any],
    player: PlayerInfo,
    round_contrib: dict[int, int],
    remaining: dict[int, int],
) -> str | None:
    kind = int(action["action_kind"])
    amount = int(action.get("action_chips", 0))
    seat_id = int(action["seat_id"])
    before = round_contrib.get(seat_id, 0)
    current_bet = max(round_contrib.values(), default=0)
    after = before + amount
    round_contrib[seat_id] = after
    remaining[seat_id] -= amount

    name = player.name
    amount_text = chips_to_display(amount)
    after_text = chips_to_display(after)
    all_in_suffix = " and is all-in" if remaining[seat_id] == 0 and amount > 0 else ""

    if kind == 1:
        return f"{name}: posts the ante {amount_text}"
    if kind == 2:
        return f"{name}: posts small blind {amount_text}"
    if kind in {3, 4}:
        return f"{name}: posts big blind {amount_text}"
    if kind in {5, 17, 18}:
        return f"{name}: posts straddle {amount_text}"
    if kind == 16:
        return f"{name}: posts bomb pot {amount_text}"
    if kind in {7, 13}:
        return f"{name}: checks"
    if kind in {8, 14, 19}:
        return f"{name}: folds"
    if kind == 9:
        return f"{name}: bets {amount_text}{all_in_suffix}"
    if kind == 10:
        return f"{name}: calls {amount_text}{all_in_suffix}"
    if kind in {11, 12}:
        raise_by = max(0, after - current_bet)
        return f"{name}: raises {chips_to_display(raise_by)} to {after_text}{all_in_suffix}"
    if kind == 15:
        return None

    label = ACTION_LABELS.get(kind, f"action_{kind}")
    if amount > 0:
        return f"{name}: {label} {amount_text}"
    return f"{name}: {label}"


def build_pt4_summary_lines(
    data: dict[str, Any],
    players: list[PlayerInfo],
) -> list[str]:
    hand = data["handInfo"]
    players_by_seat = player_name_map(players)
    winning_info = hand.get("winning_info", [])
    winner_amounts: dict[int, int] = {}
    for winner in winning_info:
        seat_id = int(winner["seat_id"])
        winner_amounts[seat_id] = winner_amounts.get(seat_id, 0) + int(winner["pot_chips"])

    fold_round_by_seat: dict[int, int] = {}
    for round_data in hand["round"]:
        round_number = int(round_data["round"])
        for action in round_data.get("action", []):
            kind = int(action["action_kind"])
            seat_id = int(action["seat_id"])
            if kind in {8, 14, 19} and seat_id not in fold_round_by_seat:
                fold_round_by_seat[seat_id] = round_number

    lines: list[str] = []
    for player in sorted(players, key=lambda item: item.seat_id):
        note = pt4_position_note(player)
        prefix = f"Seat {player_seat_number(player)}: {player.name}"
        if note:
            prefix += f" ({note})"

        if player.seat_id in winner_amounts:
            if player.cards and player.shown:
                lines.append(
                    f"{prefix} showed [{format_pt4_cards(player.cards)}] and won "
                    f"({chips_to_display(winner_amounts[player.seat_id])})"
                )
            else:
                lines.append(
                    f"{prefix} collected ({chips_to_display(winner_amounts[player.seat_id])})"
                )
            continue

        if player.cards and player.shown:
            lines.append(f"{prefix} showed [{format_pt4_cards(player.cards)}] and lost")
            continue

        fold_round = fold_round_by_seat.get(player.seat_id)
        if fold_round == 1:
            lines.append(f"{prefix} folded before Flop")
        elif fold_round == 2:
            lines.append(f"{prefix} folded on the Flop")
        elif fold_round == 3:
            lines.append(f"{prefix} folded on the Turn")
        elif fold_round == 4:
            lines.append(f"{prefix} folded on the River")
        else:
            lines.append(f"{prefix} did not show hand")

    return lines


def render_pt4_hand_history(
    data: dict[str, Any],
    players_override: list[PlayerInfo] | None = None,
) -> str:
    hand = data["handInfo"]
    game = data["gameSetInfo"]
    pt4_hand_id = re.sub(r"\D", "", str(hand["hand_id"]))
    players = players_override if players_override is not None else build_players(data)
    players_by_seat = player_name_map(players)
    hero_uid = int(data.get("uid", 0))
    hero = next((player for player in players if player.uid == hero_uid and player.cards), None)
    big_blind = int(hand["big_blind"])
    small_blind = int(hand["small_blind"])
    total_pot = sum(
        int(action.get("action_chips", 0))
        for round_data in hand["round"]
        for action in round_data.get("action", [])
    )
    total_rake = (
        int(hand.get("fee", 0))
        + int(hand.get("jackpot_fee", 0))
        + int(hand.get("insurance_fee", 0))
        + int(hand.get("evchop_fee", 0))
    )
    final_board = board_for_rounds(hand["round"], hand["round"][-1]["round"] if hand["round"] else 0)
    button_seat = int(hand["dealer"]) + 1
    timestamp = format_pt4_timestamp(int(hand["hand_end_time"]))
    max_seats = int(game.get("table_size") or len(players))
    remaining = {player.seat_id: player.begin_chips for player in players}
    forced_action_kinds = {1, 2, 3, 4, 5, 16, 17, 18}

    lines: list[str] = []
    lines.append(
        f"PokerStars Hand #{pt4_hand_id}: Hold'em No Limit "
        f"({chips_to_display(small_blind)}/{chips_to_display(big_blind)}) - {timestamp}"
    )
    lines.append(
        f"Table '{pt4_table_name(data)}' {max_seats}-max (Play Money) Seat #{button_seat} is the button"
    )
    for player in sorted(players, key=lambda item: item.seat_id):
        lines.append(
            f"Seat {player_seat_number(player)}: {player.name} "
            f"({chips_to_display(player.begin_chips)} in chips)"
        )

    preflop_round = next((round_data for round_data in hand["round"] if int(round_data["round"]) == 1), None)
    if preflop_round:
        preflop_contrib: dict[int, int] = {}
        preflop_actions = preflop_round.get("action", [])
        split_index = 0
        while split_index < len(preflop_actions):
            if int(preflop_actions[split_index]["action_kind"]) not in forced_action_kinds:
                break
            action = preflop_actions[split_index]
            player = players_by_seat[int(action["seat_id"])]
            line = format_pt4_action_line(action, player, preflop_contrib, remaining)
            if line:
                lines.append(line)
            split_index += 1

        lines.append("*** HOLE CARDS ***")
        if hero:
            lines.append(f"Dealt to {hero.name} [{format_pt4_cards(hero.cards)}]")

        for action in preflop_actions[split_index:]:
            player = players_by_seat[int(action["seat_id"])]
            line = format_pt4_action_line(action, player, preflop_contrib, remaining)
            if line:
                lines.append(line)

    for round_data in hand["round"]:
        round_number = int(round_data["round"])
        if round_number == 1:
            continue

        street_cards = [card for card in round_data.get("card", []) if card]
        street_text = format_pt4_cards(street_cards)
        board_before = board_for_rounds(hand["round"], round_number - 1)
        board_before_text = format_pt4_cards(board_before)

        if round_number == 2:
            lines.append(f"*** FLOP *** [{street_text}]")
        elif round_number == 3:
            lines.append(f"*** TURN *** [{board_before_text}] [{street_text}]")
        elif round_number == 4:
            lines.append(f"*** RIVER *** [{board_before_text}] [{street_text}]")
        else:
            lines.append(f"*** {ROUND_LABELS.get(round_number, f'ROUND {round_number}').upper()} ***")

        round_contrib: dict[int, int] = {}
        for action in round_data.get("action", []):
            player = players_by_seat[int(action["seat_id"])]
            line = format_pt4_action_line(action, player, round_contrib, remaining)
            if line:
                lines.append(line)

    shown_players = [player for player in players if player.shown and player.cards]
    if shown_players:
        lines.append("*** SHOW DOWN ***")
        winner_seat_ids = {int(item["seat_id"]) for item in hand.get("winning_info", [])}
        winner_amounts = {
            int(item["seat_id"]): int(item["pot_chips"])
            for item in hand.get("winning_info", [])
        }
        for player in shown_players:
            lines.append(f"{player.name}: shows [{format_pt4_cards(player.cards)}]")
            if player.seat_id in winner_seat_ids:
                lines.append(
                    f"{player.name} collected {chips_to_display(winner_amounts[player.seat_id])} from pot"
                )

    lines.append("*** SUMMARY ***")
    lines.append(f"Total pot {chips_to_display(total_pot)} | Rake {chips_to_display(total_rake)}")
    if final_board:
        lines.append(f"Board [{format_pt4_cards(final_board)}]")
    lines.extend(build_pt4_summary_lines(data, players))
    return "\n".join(lines) + "\n"


def find_font_path(candidates: list[str]) -> str | None:
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


FONT_REGULAR_PATH = find_font_path(FONT_REGULAR_CANDIDATES)
FONT_BOLD_PATH = find_font_path(FONT_BOLD_CANDIDATES) or FONT_REGULAR_PATH


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = FONT_BOLD_PATH if bold else FONT_REGULAR_PATH
    if font_path:
        return ImageFont.truetype(font_path, size=size)
    return ImageFont.load_default()


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    anchor: str = "la",
) -> None:
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    if not text:
        return 0, 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    if text_size(draw, text, font)[0] <= max_width:
        return text
    trimmed = text
    while trimmed and text_size(draw, trimmed + "…", font)[0] > max_width:
        trimmed = trimmed[:-1]
    return trimmed + "…" if trimmed else "…"


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 2,
) -> list[str]:
    if not text:
        return [""]

    words = text.split(" ")
    lines: list[str] = []
    current = ""

    def append_line(value: str) -> None:
        if value:
            lines.append(value)

    for word in words:
        test = word if not current else f"{current} {word}"
        if text_size(draw, test, font)[0] <= max_width:
            current = test
            continue

        if current:
            append_line(current)
            current = ""
            if len(lines) == max_lines:
                lines[-1] = fit_text(draw, lines[-1], font, max_width)
                return lines

        if text_size(draw, word, font)[0] <= max_width:
            current = word
            continue

        partial = ""
        for char in word:
            test_partial = partial + char
            if text_size(draw, test_partial, font)[0] <= max_width:
                partial = test_partial
            else:
                append_line(partial)
                partial = char
                if len(lines) == max_lines:
                    lines[-1] = fit_text(draw, lines[-1], font, max_width)
                    return lines
        current = partial

    append_line(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines and words:
        consumed = " ".join(lines)
        if consumed != text:
            lines[-1] = fit_text(draw, lines[-1], font, max_width)
    return lines or [""]


def bubble_colors(kind: int) -> tuple[str, str]:
    return ACTION_BUBBLE_COLORS.get(kind, ("#4b5563", "#eef3ff"))


def draw_suit_icon(
    draw: ImageDraw.ImageDraw,
    suit: str,
    center: tuple[float, float],
    size: float,
    fill: str,
) -> None:
    cx, cy = center
    size = max(8.0, size)

    if suit == "d":
        draw.polygon(
            [
                (cx, cy - size * 0.48),
                (cx + size * 0.34, cy),
                (cx, cy + size * 0.48),
                (cx - size * 0.34, cy),
            ],
            fill=fill,
        )
        return

    if suit == "h":
        draw.ellipse(
            [cx - size * 0.38, cy - size * 0.28, cx - size * 0.02, cy + size * 0.08],
            fill=fill,
        )
        draw.ellipse(
            [cx + size * 0.02, cy - size * 0.28, cx + size * 0.38, cy + size * 0.08],
            fill=fill,
        )
        draw.polygon(
            [
                (cx - size * 0.42, cy - size * 0.02),
                (cx + size * 0.42, cy - size * 0.02),
                (cx, cy + size * 0.46),
            ],
            fill=fill,
        )
        return

    if suit == "c":
        draw.ellipse(
            [cx - size * 0.34, cy - size * 0.42, cx - size * 0.02, cy - size * 0.10],
            fill=fill,
        )
        draw.ellipse(
            [cx + size * 0.02, cy - size * 0.42, cx + size * 0.34, cy - size * 0.10],
            fill=fill,
        )
        draw.ellipse(
            [cx - size * 0.20, cy - size * 0.12, cx + size * 0.20, cy + size * 0.28],
            fill=fill,
        )
        draw.rectangle(
            [cx - size * 0.08, cy + size * 0.12, cx + size * 0.08, cy + size * 0.42],
            fill=fill,
        )
        draw.polygon(
            [
                (cx - size * 0.22, cy + size * 0.34),
                (cx + size * 0.22, cy + size * 0.34),
                (cx, cy + size * 0.12),
            ],
            fill=fill,
        )
        return

    if suit == "s":
        draw.polygon(
            [
                (cx, cy - size * 0.46),
                (cx + size * 0.44, cy + size * 0.08),
                (cx - size * 0.44, cy + size * 0.08),
            ],
            fill=fill,
        )
        draw.ellipse(
            [cx - size * 0.36, cy - size * 0.10, cx - size * 0.02, cy + size * 0.24],
            fill=fill,
        )
        draw.ellipse(
            [cx + size * 0.02, cy - size * 0.10, cx + size * 0.36, cy + size * 0.24],
            fill=fill,
        )
        draw.rectangle(
            [cx - size * 0.08, cy + size * 0.10, cx + size * 0.08, cy + size * 0.40],
            fill=fill,
        )
        draw.polygon(
            [
                (cx - size * 0.22, cy + size * 0.34),
                (cx + size * 0.22, cy + size * 0.34),
                (cx, cy + size * 0.12),
            ],
            fill=fill,
        )


def draw_card(
    image: Image.Image,
    x: int,
    y: int,
    card: str,
    size: tuple[int, int],
    style: str = "standard",
) -> None:
    width, height = size
    draw = ImageDraw.Draw(image)
    rank = card[:-1]
    suit = card[-1]
    fill_color = SUIT_COLORS[suit]

    shadow_offset = max(2, width // 18)
    draw.rounded_rectangle(
        [x + shadow_offset, y + shadow_offset, x + width + shadow_offset, y + height + shadow_offset],
        radius=max(8, width // 10),
        fill="#0a0d12",
    )
    draw.rounded_rectangle(
        [x, y, x + width, y + height],
        radius=max(10, width // 10),
        fill=fill_color,
        outline="#f1f4f8",
        width=2,
    )
    corner_rank_font = load_font(max(16, width // 5), bold=True)
    center_rank_font = load_font(max(30, width // 2), bold=True)
    text_color = "#ffffff"

    if style == "street_simple":
        simple_rank_font = load_font(max(18, width // 2), bold=True)
        draw_text(draw, (x + width // 2, y + height * 0.28), rank, simple_rank_font, text_color, anchor="mm")
        draw_suit_icon(draw, suit, (x + width * 0.50, y + height * 0.72), width * 0.28, text_color)
        return

    draw_text(draw, (x + 10, y + 8), rank, corner_rank_font, text_color)
    draw_suit_icon(draw, suit, (x + width * 0.22, y + height * 0.33), width * 0.20, text_color)
    draw_text(draw, (x + width // 2, y + height // 2 - 12), rank, center_rank_font, text_color, anchor="mm")
    draw_suit_icon(draw, suit, (x + width * 0.50, y + height * 0.70), width * 0.26, text_color)


def draw_cards_row(
    image: Image.Image,
    x: int,
    y: int,
    card_codes: list[int],
    card_size: tuple[int, int],
    gap: int,
    style: str = "standard",
) -> None:
    display_cards = [decode_card(card) for card in card_codes if card]
    for index, card in enumerate(display_cards):
        draw_card(image, x + index * (card_size[0] + gap), y, card, card_size, style=style)


def row_width(card_count: int, card_size: tuple[int, int], gap: int) -> int:
    if card_count <= 0:
        return 0
    return card_count * card_size[0] + (card_count - 1) * gap


def draw_vertical_gradient(image: Image.Image, top_color: tuple[int, int, int], bottom_color: tuple[int, int, int]) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(
            int(top_color[index] + (bottom_color[index] - top_color[index]) * ratio)
            for index in range(3)
        )
        draw.line((0, y, width, y), fill=color)


def draw_table(image: Image.Image, bbox: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = bbox
    draw.ellipse([left, top, right, bottom], fill="#1d4c34", outline="#163628", width=14)
    inset = 28
    draw.ellipse(
        [left + inset, top + inset, right - inset, bottom - inset],
        fill="#276445",
        outline="#2f7b56",
        width=4,
    )
    center_y = (top + bottom) // 2
    draw.ellipse(
        [left + 110, center_y - 70, right - 110, center_y + 70],
        fill="#2a6f4d",
        outline=None,
    )


def seat_position(
    count: int,
    index: int,
    center: tuple[int, int],
    radius: tuple[int, int],
) -> tuple[int, int]:
    angles = SEAT_ANGLES.get(count)
    if not angles:
        angles = [90 - index * (360 / count) for index in range(count)]
    angle = math.radians(angles[index])
    cx, cy = center
    rx, ry = radius
    x = cx + math.cos(angle) * rx
    y = cy - math.sin(angle) * ry
    return int(x), int(y)


def stack_label_position(
    table_center: tuple[int, int],
    seat_center: tuple[int, int],
    seat_box_size: tuple[int, int],
    label_size: tuple[int, int],
    bounds_width: int,
    bounds_top: int,
    bounds_margin: int,
) -> tuple[int, int]:
    cx, cy = seat_center
    table_cx, table_cy = table_center
    dx = cx - table_cx
    dy = cy - table_cy
    seat_half_w = seat_box_size[0] // 2
    seat_half_h = seat_box_size[1] // 2
    label_w, label_h = label_size
    offset = 14

    if abs(dx) < 110:
        x = cx - label_w // 2
        y = cy + seat_half_h + offset
    elif dx > 0:
        x = cx + seat_half_w + offset
        y = cy - label_h // 2
    else:
        x = cx - seat_half_w - offset - label_w
        y = cy - label_h // 2

    max_x = bounds_width - bounds_margin - label_w
    x = max(bounds_margin, min(x, max_x))
    y = max(bounds_top, y)
    return int(x), int(y)


def street_pot_display(pot_after: int, big_blind: int) -> str:
    return f"{chips_to_bb(pot_after, big_blind)} BB"


def render_hand_chart(
    data: dict[str, Any],
    replay_key: str,
    output_path: Path,
) -> None:
    hand = data["handInfo"]
    game = data["gameSetInfo"]
    big_blind = int(hand["big_blind"])
    small_blind = int(hand["small_blind"])
    players = build_players(data)
    streets = build_street_summaries(data, players)
    final_board = board_for_rounds(hand["round"], streets[-1].round_number if streets else 0)
    winning_info = hand.get("winning_info", [])
    winner_seat_ids = {int(item["seat_id"]) for item in winning_info}

    width = 1240
    margin = 36
    panel_gap = 18
    street_width = (width - margin * 2 - panel_gap * 3) // 4
    table_bbox = (120, 150, width - 120, 620)
    table_center_x = (table_bbox[0] + table_bbox[2]) // 2
    table_center_y = (table_bbox[1] + table_bbox[3]) // 2
    center = (table_center_x, table_center_y)
    radius = (430, 285)
    seat_box_size = (216, 88)
    seat_centers = [seat_position(len(players), index, center, radius) for index, _ in enumerate(players)]
    lowest_seat_bottom = max(cy + seat_box_size[1] // 2 for _, cy in seat_centers)
    columns_top = max(720, lowest_seat_bottom + 76)
    street_board_size = (46, 66)
    street_board_gap = 8

    probe_image = Image.new("RGB", (width, 10), "black")
    probe_draw = ImageDraw.Draw(probe_image)
    action_font = load_font(22)

    street_layouts: list[list[list[str]]] = []
    street_heights: list[int] = []
    for street in streets:
        wrapped_actions: list[list[str]] = []
        has_board = street.round_number > 1 and bool(street.board)
        total_height = 154 if has_board else 92
        for action in street.actions:
            wrapped = wrap_text(
                probe_draw,
                action.image_text,
                action_font,
                street_width - 40,
                max_lines=4,
            )
            wrapped_actions.append(wrapped)
            total_height += 26 + len(wrapped) * 28 + 14
        street_layouts.append(wrapped_actions)
        street_heights.append(total_height)

    showdown_lines = build_showdown_lines(players, winning_info, big_blind)
    footer_lines = showdown_lines[:]
    fee = int(hand.get("fee", 0))
    jackpot_fee = int(hand.get("jackpot_fee", 0))
    insurance_fee = int(hand.get("insurance_fee", 0))
    evchop_fee = int(hand.get("evchop_fee", 0))
    if any((fee, jackpot_fee, insurance_fee, evchop_fee)):
        if fee:
            footer_lines.append(f"Rake: {chips_to_bb(fee, big_blind)} BB")
        if jackpot_fee:
            footer_lines.append(f"Jackpot fee: {chips_to_bb(jackpot_fee, big_blind)} BB")
        if insurance_fee:
            footer_lines.append(f"Insurance fee: {chips_to_bb(insurance_fee, big_blind)} BB")
        if evchop_fee:
            footer_lines.append(f"EV Chop fee: {chips_to_bb(evchop_fee, big_blind)} BB")

    footer_height = max(180, 88 + len(footer_lines) * 34)
    columns_height = max(street_heights) if street_heights else 200
    footer_top = columns_top + columns_height + 28
    height = footer_top + footer_height + margin

    image = Image.new("RGB", (width, height), "#0b1118")
    draw_vertical_gradient(image, (12, 18, 26), (7, 10, 14))
    draw = ImageDraw.Draw(image)

    header_font = load_font(42, bold=True)
    sub_font = load_font(22)
    strong_font = load_font(28, bold=True)
    seat_name_font = load_font(24, bold=True)
    seat_meta_font = load_font(19)
    foot_font = load_font(24)

    header_bottom = 112
    draw.rounded_rectangle(
        [margin, margin, width - margin, header_bottom],
        radius=28,
        fill="#0f1924",
        outline="#1c2d40",
        width=2,
    )
    draw_text(draw, (margin + 26, margin + 24), game["game_name"], header_font, "#f4f7fb")
    draw_text(
        draw,
        (margin + 26, margin + 70),
        f"Hand #{hand['hand_id']}   Replay {replay_key}   Blinds {chips_to_display(small_blind)}/{chips_to_display(big_blind)}",
        sub_font,
        "#9eb2c8",
    )

    draw_table(image, table_bbox)
    board_card_size = (92, 132)
    board_gap = 16
    board_row_width = row_width(len(final_board), board_card_size, board_gap)
    draw_cards_row(
        image,
        table_center_x - board_row_width // 2,
        table_bbox[1] + 78,
        final_board,
        board_card_size,
        board_gap,
    )

    pot_total = sum(int(action.get("action_chips", 0)) for round_data in hand["round"] for action in round_data.get("action", []))
    draw_text(
        draw,
        (table_center_x, table_bbox[1] + 250),
        f"Total Pot {chips_to_bb(pot_total, big_blind)} BB",
        strong_font,
        "#f7d47b",
        anchor="mm",
    )

    if winning_info:
        winner = winning_info[0]
        winner_player = player_name_map(players)[int(winner["seat_id"])]
        draw.rounded_rectangle(
            [table_center_x - 175, table_bbox[3] - 98, table_center_x + 175, table_bbox[3] - 28],
            radius=26,
            fill="#d7a53a",
            outline="#f2d27c",
            width=3,
        )
        draw_text(
            draw,
            (table_center_x, table_bbox[3] - 65),
            f"WIN  {winner_player.position_label} {winner_player.name}  +{chips_to_bb(int(winner['pot_chips']), big_blind)} BB",
            strong_font,
            "#291c00",
            anchor="mm",
        )

    for index, player in enumerate(players):
        cx, cy = seat_centers[index]
        left = cx - seat_box_size[0] // 2
        top = cy - seat_box_size[1] // 2
        right = left + seat_box_size[0]
        bottom = top + seat_box_size[1]
        is_winner = player.seat_id in winner_seat_ids

        draw.rounded_rectangle(
            [left, top, right, bottom],
            radius=22,
            fill="#132230",
            outline="#f0c04d" if is_winner else "#25384c",
            width=4 if is_winner else 2,
        )
        draw.rounded_rectangle(
            [left + 10, top + 10, left + 86, top + 34],
            radius=12,
            fill="#1d3550",
        )
        draw_text(draw, (left + 18, top + 22), player.position_label, seat_meta_font, "#c7d7ea", anchor="lm")

        dealer_label = POSITION_LABELS.get(len(players), [])[0] if POSITION_LABELS.get(len(players)) else ""
        if player.position_label.startswith("BTN") or (dealer_label and player.position_label == dealer_label):
            draw.ellipse([right - 42, top + 12, right - 12, top + 42], fill="#efc44f", outline="#ffe89f", width=2)
            draw_text(draw, (right - 27, top + 28), "D", seat_meta_font, "#3b2a00", anchor="mm")

        name_width = seat_box_size[0] - (112 if player.cards else 24)
        safe_name = fit_text(draw, player.name, seat_name_font, name_width)
        draw_text(draw, (left + 12, top + 56), safe_name, seat_name_font, "#f5f8fb")

        if player.cards:
            mini_size = (38, 56)
            draw_cards_row(
                image,
                right - 2 * mini_size[0] - 12,
                bottom - mini_size[1] - 10,
                sort_cards_for_display(player.cards),
                mini_size,
                6,
                style="street_simple",
            )

        stack_text = f"{chips_to_bb(player.end_chips, big_blind)} BB"
        stack_text_w, stack_text_h = text_size(draw, stack_text, seat_meta_font)
        stack_box_size = (stack_text_w + 22, stack_text_h + 10)
        stack_left, stack_top = stack_label_position(
            table_center=center,
            seat_center=(cx, cy),
            seat_box_size=seat_box_size,
            label_size=stack_box_size,
            bounds_width=width,
            bounds_top=header_bottom + 8,
            bounds_margin=margin,
        )
        draw.rounded_rectangle(
            [
                stack_left,
                stack_top,
                stack_left + stack_box_size[0],
                stack_top + stack_box_size[1],
            ],
            radius=14,
            fill="#0f1924",
            outline="#233649",
            width=2,
        )
        draw_text(
            draw,
            (stack_left + stack_box_size[0] // 2, stack_top + stack_box_size[1] // 2 + 1),
            stack_text,
            seat_meta_font,
            "#9fb4ca",
            anchor="mm",
        )

    title_font = load_font(26, bold=True)
    small_font = load_font(18)
    bubble_font = action_font
    for column_index, street in enumerate(streets):
        x = margin + column_index * (street_width + panel_gap)
        panel_height = street_heights[column_index]
        draw.rounded_rectangle(
            [x, columns_top, x + street_width, columns_top + panel_height],
            radius=28,
            fill="#101923",
            outline="#203144",
            width=2,
        )
        draw_text(draw, (x + 22, columns_top + 22), street.label, title_font, "#f1f4f8")
        draw_text(
            draw,
            (x + street_width - 22, columns_top + 26),
            f"Pot {street_pot_display(street.pot_display, big_blind)}",
            small_font,
            "#9eb2c8",
            anchor="ra",
        )

        if street.round_number > 1 and street.board:
            street_board_width = row_width(len(street.board), street_board_size, street_board_gap)
            draw_cards_row(
                image,
                x + (street_width - street_board_width) // 2,
                columns_top + 58,
                street.board,
                street_board_size,
                street_board_gap,
                style="street_simple",
            )
            cursor_y = columns_top + 146
        else:
            cursor_y = columns_top + 78

        for action, wrapped_lines in zip(street.actions, street_layouts[column_index]):
            fill_color, text_color = bubble_colors(action.kind)
            bubble_height = 24 + len(wrapped_lines) * 28
            draw.rounded_rectangle(
                [x + 14, cursor_y, x + street_width - 14, cursor_y + bubble_height],
                radius=20,
                fill=fill_color,
            )
            for line_index, line in enumerate(wrapped_lines):
                draw_text(
                    draw,
                    (x + 28, cursor_y + 16 + line_index * 28),
                    line,
                    bubble_font,
                    text_color,
                )
            cursor_y += bubble_height + 12

    draw.rounded_rectangle(
        [margin, footer_top, width - margin, footer_top + footer_height],
        radius=28,
        fill="#0f1924",
        outline="#1c2d40",
        width=2,
    )
    draw_text(draw, (margin + 26, footer_top + 26), "Showdown / Notes", title_font, "#f1f4f8")
    footer_y = footer_top + 70
    for line in footer_lines:
        draw_text(draw, (margin + 26, footer_y), line, foot_font, "#dce5ef")
        footer_y += 34

    image.save(output_path)


def main() -> None:
    args = parse_args()
    replay_key = extract_replay_key(args.source)
    data = fetch_replay_json(replay_key)
    players = build_players(data)

    hand_id = data["handInfo"]["hand_id"]
    txt_path = Path(args.output) if args.output else Path(f"{hand_id}.txt")
    txt_path.write_text(
        render_hand_history(data=data, replay_key=replay_key),
        encoding="utf-8",
    )

    pt4_path = txt_path.with_name(f"{txt_path.stem}-pt4{txt_path.suffix}")
    pt4_path.write_text(
        render_pt4_hand_history(data=data, players_override=players),
        encoding="utf-8",
    )

    anon_aliases = build_numeric_aliases(players, str(hand_id))
    anon_pt4_path = txt_path.with_name(f"{txt_path.stem}-pt4-anon{txt_path.suffix}")
    anon_pt4_path.write_text(
        render_pt4_hand_history(
            data=data,
            players_override=remap_player_names(players, anon_aliases),
        ),
        encoding="utf-8",
    )

    png_path = txt_path.with_suffix(".png")
    render_hand_chart(data=data, replay_key=replay_key, output_path=png_path)

    if args.save_json:
        json_path = txt_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(txt_path.resolve())
    print(pt4_path.resolve())
    print(anon_pt4_path.resolve())
    print(png_path.resolve())


if __name__ == "__main__":
    main()
