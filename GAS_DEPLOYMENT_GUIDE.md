# X-Poker 牌局轉換器 (TXT + 圖) - Google Apps Script 佈署指南

這個指南將引導你將 Python 的 X-Poker 牌局解析與繪圖邏輯，完美移植到 Google Apps Script (GAS) 上，建立一個輕量級的網頁應用程式。

我們不需架設伺服器，利用後端擷取 JSON 解決 CORS 限制，並使用 HTML5 Canvas 在前端直接重現原本 Pillow 的繪圖邏輯。你可以一鍵生成 TXT 格式手牌，並且直接對著生成的圖片點擊右鍵「另存圖片」。

## 佈署步驟

### 步驟 1：建立專案與後端代碼

1. 前往 [Google Apps Script](https://script.google.com/)，點擊「**新專案**」。
2. 將預設的 `程式碼.gs` (或 `Code.gs`) 內容清空。
3. 貼上以下代碼。這段代碼負責處理網頁的載入以及繞過瀏覽器限制去抓取 X-Poker 的牌局 JSON：

```javascript
// Code.gs

function doGet(e) {
  return HtmlService.createHtmlOutputFromFile('Index')
      .setTitle('X-Poker Replay 解析器')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function fetchReplayData(source) {
  function extractReplayKey(src) {
    try {
      var url = src;
      if (!src.startsWith('http')) {
        url = 'https://example.com/?' + src; // 處理僅有參數的狀況
      }
      var match = src.match(/replay_key=([a-f0-9-]+)/i);
      if (match) return match[1];
    } catch (e) {}
    
    // 檢查是否為直接的 UUID
    if (/^[0-9a-fA-F-]{36}$/.test(src)) {
      return src;
    }
    throw new Error("無法從來源解析出 replay_key，請確認網址格式。");
  }
  
  var replayKey = extractReplayKey(source);
  var url = "https://static.x-game.net/resource/replay/hand/" + replayKey + ".json";
  
  try {
    var response = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
    if (response.getResponseCode() !== 200) {
      throw new Error("擷取 JSON 失敗，HTTP 狀態碼：" + response.getResponseCode());
    }
    var jsonText = response.getContentText();
    return {
      success: true,
      data: JSON.parse(jsonText),
      replayKey: replayKey
    };
  } catch(e) {
    return {
      success: false,
      error: e.toString()
    };
  }
}
```

### 步驟 2：新增前端 UI 與繪圖代碼

1. 在左側的「檔案」區，點擊 **+ 號** -> 選擇 **HTML**。
2. 將檔案命名為 **`Index`** (注意首字母大寫，以配合 `Code.gs` 的呼叫)。
3. 將新建立的 `Index.html` 內容清空，並貼上以下代碼（這是我們將 Python 繪圖與排版邏輯移植過來的核心）：

```html
<!DOCTYPE html>
<html>
<head>
  <base target="_top">
  <style>
    body { font-family: "Microsoft YaHei", sans-serif; padding: 20px; background: #f0f2f5; }
    .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    h2 { margin-top: 0; color: #333; }
    input[type="text"] { width: 100%; padding: 12px; margin-bottom: 15px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; font-size: 16px; }
    button { padding: 12px 24px; background: #2d6cdf; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
    button:hover { background: #1a52b8; }
    .result { margin-top: 20px; display: flex; gap: 20px; flex-wrap: wrap; }
    .text-result { flex: 1; min-width: 300px; }
    .image-result { flex: 2; min-width: 600px; }
    textarea { width: 100%; height: 600px; font-family: monospace; white-space: pre; overflow-wrap: normal; overflow-x: scroll; border: 1px solid #ccc; padding: 10px; box-sizing: border-box; border-radius: 4px;}
    img { max-width: 100%; height: auto; border: 1px solid #ccc; display: block; margin-top: 10px; border-radius: 8px;}
    .loader { display: none; margin-left: 15px; color: #666; }
  </style>
</head>
<body>
  <div class="container">
    <h2>X-Poker 牌局轉換器 (TXT + 圖)</h2>
    <input type="text" id="urlInput" placeholder="請貼上 X-Poker 牌局網址或 replay_key...">
    <button onclick="generate()">解析並生成</button>
    <span class="loader" id="loader">載入與繪製中...請稍候</span>
    
    <div class="result" id="resultArea" style="display:none;">
      <div class="text-result">
        <h3>原版 TXT 手牌詳情</h3>
        <textarea id="txtOutput" readonly></textarea>
      </div>
      <div class="image-result">
        <h3>圖片表示 (請對圖片點擊「右鍵 -> 另存圖片」)</h3>
        <img id="imgOutput" alt="Hand Chart">
      </div>
    </div>
  </div>

  <script>
    // --- 核心資料字典 ---
    const ACTION_LABELS = {
      0: "does nothing", 1: "posts ante", 2: "posts SB", 3: "posts BB", 4: "posts dead BB", 5: "posts straddle",
      7: "checks", 8: "folds", 9: "bets", 10: "calls", 11: "raises", 12: "pots", 13: "checks", 14: "folds",
      15: "sits", 16: "posts bomb pot", 17: "posts voluntary straddle", 18: "posts voluntary restraddle", 19: "folds"
    };
    const ROUND_LABELS = { 1: "Preflop", 2: "Flop", 3: "Turn", 4: "River" };
    const POSITION_LABELS = {
      2: ["BTN/SB", "BB"], 3: ["BTN", "SB", "BB"], 4: ["BTN", "SB", "BB", "UTG"],
      5: ["BTN", "SB", "BB", "UTG", "CO"], 6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
      7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"], 8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"],
      9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"]
    };
    const RANK_MAP = { 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A" };
    const SUIT_MAP = { 1: "s", 2: "h", 3: "c", 4: "d" };
    const SUIT_COLORS = { "s": "#111111", "h": "#d63c3c", "d": "#e78a20", "c": "#2d6cdf" };
    const ACTION_BUBBLE_COLORS = {
      1: ["#274060", "#dce8ff"], 2: ["#274060", "#dce8ff"], 3: ["#274060", "#dce8ff"], 4: ["#274060", "#dce8ff"],
      5: ["#274060", "#dce8ff"], 7: ["#3a4b68", "#eef3ff"], 8: ["#414854", "#eef3ff"], 9: ["#f0c04d", "#251b00"],
      10: ["#6ca6ff", "#04162f"], 11: ["#f0c04d", "#251b00"], 12: ["#f0c04d", "#251b00"], 13: ["#3a4b68", "#eef3ff"],
      14: ["#414854", "#eef3ff"], 16: ["#a55d2e", "#fff4e8"], 17: ["#7e55c7", "#f5edff"], 18: ["#7e55c7", "#f5edff"],
      19: ["#414854", "#eef3ff"]
    };
    const SEAT_ANGLES = {
      2: [90, -90], 3: [90, -25, -155], 4: [90, 10, -90, 170], 5: [90, 40, -20, -130, 160],
      6: [90, 48, 5, -55, -132, 175], 7: [90, 50, 15, -35, -90, -145, 180],
      8: [90, 52, 10, -33, -90, -147, 180, 130], 9: [90, 58, 25, -10, -50, -95, -140, 180, 132]
    };

    // --- 輔助邏輯 ---
    function chips_to_display(chips) { return parseFloat((chips / 100).toFixed(3)).toString(); }
    function chips_to_bb(chips, big_blind) { return parseFloat((chips / big_blind).toFixed(3)).toString(); }
    function format_chips_bb(chips, big_blind) { return `${chips_to_display(chips)} (${chips_to_bb(chips, big_blind)} BB)`; }
    
    function decode_card(card_code, use_emoji = false) {
        if (!card_code) return "";
        let rank = card_code % 256, suit = Math.floor(card_code / 256), suit_char = SUIT_MAP[suit];
        if (use_emoji) {
            if (suit_char === "s") suit_char = "♠️"; else if (suit_char === "h") suit_char = "♥️";
            else if (suit_char === "c") suit_char = "♣️"; else if (suit_char === "d") suit_char = "♦️";
        }
        return `${RANK_MAP[rank]}${suit_char}`;
    }

    function sort_cards_for_display(cards) {
        return cards.filter(c => c).sort((a, b) => {
            let rankA = a % 256, suitA = Math.floor(a / 256), rankB = b % 256, suitB = Math.floor(b / 256);
            return rankA !== rankB ? rankB - rankA : suitB - suitA;
        });
    }

    function board_for_rounds(rounds, street_number) {
        let cards = [];
        for (let r of rounds) {
            if (r.round > street_number) break;
            if (r.card) cards.push(...r.card);
        }
        return cards;
    }

    // --- 資料建構 (對應 Python) ---
    function build_players(data) {
        let players = data.playerHands, count = players.length, labels = POSITION_LABELS[count], built = [];
        for (let p of players) {
            let pos_idx = parseInt(p.position !== undefined ? p.position : -1);
            let pos_lbl = (labels && pos_idx >= 0 && pos_idx < labels.length) ? labels[pos_idx] : `POS${pos_idx}`;
            let cards = [];
            for (let i = 1; i <= 6; i++) if (p[`card${i}`]) cards.push(parseInt(p[`card${i}`]));
            built.push({
                seat_id: parseInt(p.seat_id), position_index: pos_idx, position_label: pos_lbl,
                uid: parseInt(p.uid), name: String(p.user_name), begin_chips: parseInt(p.begin_chips),
                end_chips: parseInt(p.end_chips), cards: cards.filter(c => c), shown: !!p.is_show_hands
            });
        }
        return built.sort((a, b) => a.position_index - b.position_index);
    }

    function describe_action(kind, amount_bb, after_bb, all_in_suffix) {
        if (kind === 1) return `posts ante ${amount_bb} BB`; if (kind === 2) return `posts SB ${amount_bb} BB`;
        if (kind === 3) return `posts BB ${amount_bb} BB`; if (kind === 4) return `posts dead BB ${amount_bb} BB`;
        if (kind === 5) return `posts straddle ${amount_bb} BB`; if (kind === 7 || kind === 13) return "checks";
        if (kind === 8 || kind === 14 || kind === 19) return "folds"; if (kind === 9) return `bets ${amount_bb} BB${all_in_suffix}`;
        if (kind === 10) return `calls ${amount_bb} BB${all_in_suffix}`; if (kind === 11) return `raises to ${after_bb} BB${all_in_suffix}`;
        if (kind === 12) return `pots to ${after_bb} BB${all_in_suffix}`; if (kind === 16) return `posts bomb pot ${amount_bb} BB${all_in_suffix}`;
        if (kind === 17) return `posts voluntary straddle ${amount_bb} BB${all_in_suffix}`; if (kind === 18) return `posts voluntary restraddle ${amount_bb} BB${all_in_suffix}`;
        if (kind === 15) return "sits";
        let label = ACTION_LABELS[kind] || `action_${kind}`;
        return amount_bb !== "0" ? `${label} ${amount_bb} BB${all_in_suffix}` : label;
    }

    function build_street_summaries(data, players) {
        let hand = data.handInfo, bb = parseInt(hand.big_blind);
        let p_map = {}; players.forEach(p => p_map[p.seat_id] = p);
        let rem = {}; players.forEach(p => rem[p.seat_id] = p.begin_chips);
        let rounds = hand.round || [], c_pot = 0, summaries = [];

        for (let r of rounds) {
            let r_num = parseInt(r.round), pot_disp = c_pot;
            if (r_num === 1) {
                let forced = new Set([1, 2, 3, 4, 5, 16, 17, 18]); pot_disp = 0;
                for (let a of (r.action || [])) {
                    if (!forced.has(parseInt(a.action_kind))) break;
                    pot_disp += parseInt(a.action_chips || 0);
                }
            }
            let r_contrib = {}, actions = [];
            for (let a of (r.action || [])) {
                let seat_id = parseInt(a.seat_id), p = p_map[seat_id];
                let amt = parseInt(a.action_chips || 0), kind = parseInt(a.action_kind);
                let before = r_contrib[seat_id] || 0, after = before + amt;
                r_contrib[seat_id] = after; rem[seat_id] -= amt;
                let all_in = (rem[seat_id] === 0 && amt > 0) ? " (all-in)" : "";
                let act_txt = describe_action(kind, chips_to_bb(amt, bb), chips_to_bb(after, bb), all_in);
                actions.push({ kind, seat_id, text: `${p.position_label} ${p.name} ${act_txt}`, image_text: `${p.name}: ${act_txt}` });
                c_pot += amt;
            }
            summaries.push({ round_number: r_num, label: ROUND_LABELS[r_num] || `Round ${r_num}`, board: board_for_rounds(rounds, r_num), pot_display: pot_disp, pot_after: c_pot, actions });
        }
        return summaries;
    }

    // --- TXT 生成 ---
    function render_hand_history(data, replay_key) {
        let hand = data.handInfo, game = data.gameSetInfo, bb = parseInt(hand.big_blind), sb = parseInt(hand.small_blind);
        let players = build_players(data), streets = build_street_summaries(data, players), lines = [];
        lines.push(`X-Poker Hand #${hand.hand_id}`, `Replay Key: ${replay_key}`, `Table: ${game.game_name}`, `Blinds: ${chips_to_display(sb)}/${chips_to_display(bb)}`, `Seats: ${players.length}`, "", "Starting Stacks");
        players.forEach(p => lines.push(`${p.position_label} (seat ${p.seat_id}) ${p.name}: ${format_chips_bb(p.begin_chips, bb)}`));

        let known = players.filter(p => p.cards.length > 0);
        if (known.length > 0) {
            lines.push("", "Known Hole Cards");
            known.forEach(p => lines.push(`${p.position_label} ${p.name}: [${sort_cards_for_display(p.cards).map(c=>decode_card(c,true)).join(" ")}] (${p.shown?"shown":"known"})`));
        }

        streets.forEach(s => {
            lines.push(""); let p_txt = `Pot ${chips_to_bb(s.pot_display, bb)} BB`;
            if (s.round_number === 1) lines.push(`${s.label} (${p_txt})`);
            else lines.push(`${s.label} [${s.board.map(c=>decode_card(c,true)).join(" ")}] (${p_txt})`);
            s.actions.forEach(a => lines.push(a.text));
        });

        if (hand.winning_info && hand.winning_info.length > 0) {
            lines.push("", "Showdown");
            players.filter(p => p.shown && p.cards.length).forEach(p => lines.push(`${p.position_label} ${p.name} shows [${sort_cards_for_display(p.cards).map(c=>decode_card(c,true)).join(" ")}]`));
            let p_map = {}; players.forEach(p => p_map[p.seat_id] = p);
            hand.winning_info.forEach(w => {
                let wp = p_map[parseInt(w.seat_id)], b5 = w.best_hands || [];
                lines.push(`${wp.position_label} ${wp.name} wins ${chips_to_bb(parseInt(w.pot_chips), bb)} BB${b5.length?" with ["+b5.map(c=>decode_card(c,true)).join(" ")+"]":""}`);
            });
        }
        
        let fee = parseInt(hand.fee||0), jp = parseInt(hand.jackpot_fee||0), ins = parseInt(hand.insurance_fee||0), ev = parseInt(hand.evchop_fee||0);
        if (fee||jp||ins||ev) {
            lines.push("", "Fees");
            if(fee) lines.push(`Rake: ${chips_to_bb(fee, bb)} BB`);
            if(jp) lines.push(`Jackpot fee: ${chips_to_bb(jp, bb)} BB`);
            if(ins) lines.push(`Insurance fee: ${chips_to_bb(ins, bb)} BB`);
            if(ev) lines.push(`EV Chop fee: ${chips_to_bb(ev, bb)} BB`);
        }
        return lines.join("\n") + "\n";
    }

    // --- HTML5 Canvas 圖片還原 ---
    function fillRoundedRect(ctx, l, t, r, b, rad, f, ol, w) {
        ctx.beginPath(); ctx.roundRect(l, t, r-l, b-t, rad);
        if(f) { ctx.fillStyle = f; ctx.fill(); }
        if(ol) { ctx.strokeStyle = ol; ctx.lineWidth = w||1; ctx.stroke(); }
    }
    
    function draw_text(ctx, x, y, t, font, f, anchor="la") {
        ctx.font = font; ctx.fillStyle = f;
        if(anchor==="la"){ ctx.textAlign="left"; ctx.textBaseline="top"; y+=2; }
        else if(anchor==="mm"){ ctx.textAlign="center"; ctx.textBaseline="middle"; }
        else if(anchor==="lm"){ ctx.textAlign="left"; ctx.textBaseline="middle"; }
        else if(anchor==="ra"){ ctx.textAlign="right"; ctx.textBaseline="top"; y+=2; }
        ctx.fillText(t, x, y);
    }
    
    function fit_text(ctx, text, font, max_w) {
        ctx.font = font; if (ctx.measureText(text).width <= max_w) return text;
        let t = text; while (t && ctx.measureText(t + "…").width > max_w) t = t.slice(0, -1);
        return t ? t + "…" : "…";
    }
    
    function wrap_text(ctx, text, font, max_w, max_l=2) {
        if (!text) return [""]; ctx.font = font;
        let words = text.split(" "), lines = [], cur = "";
        for (let w of words) {
            let test = cur ? `${cur} ${w}` : w;
            if (ctx.measureText(test).width <= max_w) cur = test;
            else {
                if (cur) { lines.push(cur); cur = w; if (lines.length === max_l) { lines[lines.length-1] = fit_text(ctx, lines[lines.length-1], font, max_w); return lines; } }
                else cur = w;
            }
        }
        if (cur) lines.push(cur);
        return (lines.length > max_l) ? lines.slice(0, max_l) : lines;
    }
    
    function draw_suit(ctx, suit, cx, cy, size, fill) {
        size = Math.max(8.0, size); ctx.fillStyle = fill; ctx.beginPath();
        if(suit === "d") { ctx.moveTo(cx, cy-size*0.48); ctx.lineTo(cx+size*0.34, cy); ctx.lineTo(cx, cy+size*0.48); ctx.lineTo(cx-size*0.34, cy); }
        else if(suit === "h") { ctx.ellipse(cx-size*0.2, cy-size*0.1, size*0.18, size*0.18, 0, 0, 2*Math.PI); ctx.ellipse(cx+size*0.2, cy-size*0.1, size*0.18, size*0.18, 0, 0, 2*Math.PI); ctx.moveTo(cx-size*0.42, cy-size*0.02); ctx.lineTo(cx+size*0.42, cy-size*0.02); ctx.lineTo(cx, cy+size*0.46); }
        else if(suit === "c") { ctx.ellipse(cx-size*0.18, cy-size*0.26, size*0.16, size*0.16, 0, 0, 2*Math.PI); ctx.ellipse(cx+size*0.18, cy-size*0.26, size*0.16, size*0.16, 0, 0, 2*Math.PI); ctx.ellipse(cx, cy+size*0.08, size*0.20, size*0.20, 0, 0, 2*Math.PI); ctx.rect(cx-size*0.08, cy+size*0.12, size*0.16, size*0.30); ctx.moveTo(cx-size*0.22, cy+size*0.34); ctx.lineTo(cx+size*0.22, cy+size*0.34); ctx.lineTo(cx, cy+size*0.12); }
        else if(suit === "s") { ctx.moveTo(cx, cy-size*0.46); ctx.lineTo(cx+size*0.44, cy+size*0.08); ctx.lineTo(cx-size*0.44, cy+size*0.08); ctx.ellipse(cx-size*0.19, cy+size*0.07, size*0.17, size*0.17, 0, 0, 2*Math.PI); ctx.ellipse(cx+size*0.19, cy+size*0.07, size*0.17, size*0.17, 0, 0, 2*Math.PI); ctx.rect(cx-size*0.08, cy+size*0.10, size*0.16, size*0.30); ctx.moveTo(cx-size*0.22, cy+size*0.34); ctx.lineTo(cx+size*0.22, cy+size*0.34); ctx.lineTo(cx, cy+size*0.12); }
        ctx.fill();
    }
    
    function draw_card(ctx, x, y, card, w, h, style="standard") {
        let rank = card.slice(0, -1), suit = card.slice(-1), fill = SUIT_COLORS[suit], sh = Math.max(2, Math.floor(w/18));
        fillRoundedRect(ctx, x+sh, y+sh, x+w+sh, y+h+sh, Math.max(8, w/10), "#0a0d12");
        fillRoundedRect(ctx, x, y, x+w, y+h, Math.max(10, w/10), fill, "#f1f4f8", 2);
        
        if (style === "street_simple") {
            draw_text(ctx, x+w/2, y+h*0.28, rank, `bold ${Math.max(18, w/2)}px sans-serif`, "#fff", "mm");
            draw_suit(ctx, suit, x+w*0.5, y+h*0.72, w*0.28, "#fff"); return;
        }
        draw_text(ctx, x+10, y+8, rank, `bold ${Math.max(16, w/5)}px sans-serif`, "#fff", "la");
        draw_suit(ctx, suit, x+w*0.22, y+h*0.33, w*0.20, "#fff");
        draw_text(ctx, x+w/2, y+h/2-12, rank, `bold ${Math.max(30, w/2)}px sans-serif`, "#fff", "mm");
        draw_suit(ctx, suit, x+w*0.5, y+h*0.70, w*0.26, "#fff");
    }

    function render_hand_chart(data, rkey) {
        let hand = data.handInfo, game = data.gameSetInfo, bb = parseInt(hand.big_blind), sb = parseInt(hand.small_blind);
        let players = build_players(data), streets = build_street_summaries(data, players);
        let final_board = board_for_rounds(hand.round||[], streets.length ? streets[streets.length-1].round_number : 0);
        let winners = new Set((hand.winning_info||[]).map(i => parseInt(i.seat_id)));
        
        let w = 1240, m = 36, gap = 18, sw = Math.floor((w - m*2 - gap*3)/4);
        let tb = [120, 150, w - 120, 620], tcx = (tb[0]+tb[2])/2, tcy = (tb[1]+tb[3])/2;
        let centers = players.map((_, i) => {
            let a = SEAT_ANGLES[players.length] ? SEAT_ANGLES[players.length][i] : 90 - i*(360/players.length);
            return [tcx + Math.cos(a*Math.PI/180)*430, tcy - Math.sin(a*Math.PI/180)*285];
        });
        
        let tmpCtx = document.createElement('canvas').getContext('2d'), act_font = "22px sans-serif";
        let layouts = [], s_heights = [];
        streets.forEach(s => {
            let acts = [], th = (s.round_number>1 && s.board.length) ? 154 : 92;
            s.actions.forEach(a => { let wr = wrap_text(tmpCtx, a.image_text, act_font, sw-40, 4); acts.push(wr); th += 26 + wr.length*28 + 14; });
            layouts.push(acts); s_heights.push(th);
        });
        
        let foot = build_showdown_lines(players, hand.winning_info||[], bb, false);
        let f1 = parseInt(hand.fee||0), f2 = parseInt(hand.jackpot_fee||0), f3 = parseInt(hand.insurance_fee||0), f4 = parseInt(hand.evchop_fee||0);
        if(f1) foot.push(`Rake: ${chips_to_bb(f1, bb)} BB`); if(f2) foot.push(`Jackpot fee: ${chips_to_bb(f2, bb)} BB`);
        if(f3) foot.push(`Insurance fee: ${chips_to_bb(f3, bb)} BB`); if(f4) foot.push(`EV Chop fee: ${chips_to_bb(f4, bb)} BB`);
        
        let lowest = Math.max(...centers.map(c => c[1] + 44)), ct = Math.max(720, lowest + 76);
        let fh = Math.max(180, 88 + foot.length*34), ft = ct + (s_heights.length ? Math.max(...s_heights) : 200) + 28, h = ft + fh + m;
        
        let cvs = document.createElement('canvas'); cvs.width = w; cvs.height = h; let ctx = cvs.getContext('2d');
        let grd = ctx.createLinearGradient(0,0,0,h); grd.addColorStop(0,"#0c121a"); grd.addColorStop(1,"#070a0e"); ctx.fillStyle=grd; ctx.fillRect(0,0,w,h);
        
        fillRoundedRect(ctx, m, m, w-m, 112, 28, "#0f1924", "#1c2d40", 2);
        draw_text(ctx, m+26, m+24, game.game_name, "bold 42px sans-serif", "#f4f7fb", "la");
        draw_text(ctx, m+26, m+70, `Hand #${hand.hand_id}   Replay ${rkey}   Blinds ${chips_to_display(sb)}/${chips_to_display(bb)}`, "22px sans-serif", "#9eb2c8", "la");

        // Table
        ctx.beginPath(); ctx.ellipse(tcx, tcy, (tb[2]-tb[0])/2, (tb[3]-tb[1])/2, 0, 0, 2*Math.PI); ctx.fillStyle="#1d4c34"; ctx.fill(); ctx.lineWidth=14; ctx.strokeStyle="#163628"; ctx.stroke();
        ctx.beginPath(); ctx.ellipse(tcx, tcy, (tb[2]-tb[0])/2 - 28, (tb[3]-tb[1])/2 - 28, 0, 0, 2*Math.PI); ctx.fillStyle="#276445"; ctx.fill(); ctx.lineWidth=4; ctx.strokeStyle="#2f7b56"; ctx.stroke();
        ctx.beginPath(); ctx.ellipse(tcx, tcy, (tb[2]-tb[0])/2 - 110, 70, 0, 0, 2*Math.PI); ctx.fillStyle="#2a6f4d"; ctx.fill();

        let b_wid = final_board.length>0 ? (final_board.length*92 + (final_board.length-1)*16) : 0;
        final_board.filter(c=>c).forEach((c,i) => draw_card(ctx, tcx - b_wid/2 + i*108, tb[1]+78, decode_card(c), 92, 132));
        
        let pot_tot = 0; (hand.round||[]).forEach(r => (r.action||[]).forEach(a => pot_tot += parseInt(a.action_chips||0)));
        draw_text(ctx, tcx, tb[1]+250, `Total Pot ${chips_to_bb(pot_tot, bb)} BB`, "bold 28px sans-serif", "#f7d47b", "mm");

        if (hand.winning_info && hand.winning_info.length) {
            let win = hand.winning_info[0], wp = players.find(p=>p.seat_id == win.seat_id);
            fillRoundedRect(ctx, tcx-175, tb[3]-98, tcx+175, tb[3]-28, 26, "#d7a53a", "#f2d27c", 3);
            draw_text(ctx, tcx, tb[3]-65, `WIN  ${wp.position_label} ${wp.name}  +${chips_to_bb(parseInt(win.pot_chips), bb)} BB`, "bold 28px sans-serif", "#291c00", "mm");
        }

        players.forEach((p, i) => {
            let cx=centers[i][0], cy=centers[i][1], is_win=winners.has(p.seat_id);
            fillRoundedRect(ctx, cx-108, cy-44, cx+108, cy+44, 22, "#132230", is_win?"#f0c04d":"#25384c", is_win?4:2);
            fillRoundedRect(ctx, cx-98, cy-34, cx-22, cy-10, 12, "#1d3550");
            draw_text(ctx, cx-90, cy-22, p.position_label, "19px sans-serif", "#c7d7ea", "lm");
            
            let d_lbl = POSITION_LABELS[players.length] ? POSITION_LABELS[players.length][0] : "";
            if (p.position_label.startsWith("BTN") || p.position_label===d_lbl) {
                ctx.beginPath(); ctx.ellipse(cx+79, cy-17, 15, 15, 0, 0, 2*Math.PI); ctx.fillStyle="#efc44f"; ctx.fill(); ctx.lineWidth=2; ctx.strokeStyle="#ffe89f"; ctx.stroke();
                draw_text(ctx, cx+79, cy-17, "D", "19px sans-serif", "#3b2a00", "mm");
            }
            draw_text(ctx, cx-96, cy+12, fit_text(ctx, p.name, "bold 24px sans-serif", 216-(p.cards.length?112:24)), "bold 24px sans-serif", "#f5f8fb", "la");
            if (p.cards.length) sort_cards_for_display(p.cards).forEach((c,ci) => draw_card(ctx, cx+108 - 2*38 - 12 + ci*44, cy+44 - 56 - 10, decode_card(c), 38, 56, "street_simple"));
            
            ctx.font="19px sans-serif"; let st_txt=`${chips_to_bb(p.end_chips, bb)} BB`, [sw, sh]=[ctx.measureText(st_txt).width+22, 33];
            let sx=cx, sy=cy;
            if(Math.abs(cx-tcx)<110) { sx = cx-sw/2; sy = cy+44+14; } else if(cx>tcx) { sx = cx+108+14; sy = cy-sh/2; } else { sx = cx-108-14-sw; sy = cy-sh/2; }
            sx=Math.max(m, Math.min(sx, w-m-sw)); sy=Math.max(120, sy);
            fillRoundedRect(ctx, sx, sy, sx+sw, sy+sh, 14, "#0f1924", "#233649", 2);
            draw_text(ctx, sx+sw/2, sy+sh/2+1, st_txt, "19px sans-serif", "#9fb4ca", "mm");
        });

        streets.forEach((s, ci) => {
            let x = m + ci*(sw+gap), py = ct+78;
            fillRoundedRect(ctx, x, ct, x+sw, ct+s_heights[ci], 28, "#101923", "#203144", 2);
            draw_text(ctx, x+22, ct+22, s.label, "bold 26px sans-serif", "#f1f4f8", "la");
            draw_text(ctx, x+sw-22, ct+26, `Pot ${chips_to_bb(s.pot_display, bb)} BB`, "18px sans-serif", "#9eb2c8", "ra");
            
            if (s.round_number>1 && s.board.length) {
                let sb_w = s.board.length*46 + (s.board.length-1)*8;
                s.board.forEach((c,i) => draw_card(ctx, x+(sw-sb_w)/2 + i*54, ct+58, decode_card(c), 46, 66, "street_simple"));
                py = ct+146;
            }
            s.actions.forEach((a, ai) => {
                let lns = layouts[ci][ai], col = ACTION_BUBBLE_COLORS[a.kind] || ["#4b5563", "#eef3ff"], bh = 24 + lns.length*28;
                fillRoundedRect(ctx, x+14, py, x+sw-14, py+bh, 20, col[0]);
                lns.forEach((l,li) => draw_text(ctx, x+28, py+16+li*28, l, act_font, col[1], "la")); py += bh+12;
            });
        });

        fillRoundedRect(ctx, m, ft, w-m, ft+fh, 28, "#0f1924", "#1c2d40", 2);
        draw_text(ctx, m+26, ft+26, "Showdown / Notes", "bold 26px sans-serif", "#f1f4f8", "la");
        let fy = ft+70; foot.forEach(l => { draw_text(ctx, m+26, fy, l, "24px sans-serif", "#dce5ef", "la"); fy+=34; });
        return cvs.toDataURL("image/png");
    }

    // --- 呼叫後端 ---
    function generate() {
        let input = document.getElementById('urlInput').value.trim();
        if (!input) { alert("請輸入網址"); return; }
        
        document.getElementById('loader').style.display = 'inline-block';
        document.getElementById('resultArea').style.display = 'none';
        
        google.script.run.withSuccessHandler(function(response) {
            document.getElementById('loader').style.display = 'none';
            if (!response.success) { alert("發生錯誤: " + response.error); return; }
            try {
                document.getElementById('txtOutput').value = render_hand_history(response.data, response.replayKey);
                document.getElementById('imgOutput').src = render_hand_chart(response.data, response.replayKey);
                document.getElementById('resultArea').style.display = 'flex';
            } catch (e) { alert("解析與繪製錯誤: " + e.message); console.error(e); }
        }).fetchReplayData(input);
    }
  </script>
</body>
</html>
```

### 步驟 3：發佈為網頁應用程式

1. 在 GAS 編輯器右上角，點擊藍色按鈕 **「部署」 -> 「新增部署作業」**。
2. 點擊左側的「選取類型 (齒輪圖示)」，選擇 **「網頁應用程式 (Web App)」**。
3. **執行身分**：選擇 `我 (你的帳號)`。
4. **誰可以存取**：選擇 `所有人 (Anyone)`。
5. 點擊 **部署**。
6. 完成後，會給你一個 **「網頁應用程式網址 (Web App URL)」**。

現在，你只需要點開這個網址，貼上你的 X-Poker Replay 連結或 Key，系統就會在網頁上立刻為你產出 TXT 格式詳情與手牌圖片！