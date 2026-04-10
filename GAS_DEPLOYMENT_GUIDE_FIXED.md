# X-Poker 牌局轉換器 (GAS 完整修正版) - 佈署指南

這個指南提供完整的代碼，請依照以下步驟重新佈署。

## 佈署步驟

### 步驟 1：建立專案與後端代碼 (Code.gs)

1. 前往 [Google Apps Script](https://script.google.com/)，點擊「**新專案**」。
2. 將預設的 `Code.gs` 內容清空，貼上以下代碼：

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
        url = 'https://example.com/?' + src;
      }
      var match = src.match(/replay_key=([a-f0-9-]+)/i);
      if (match) return match[1];
    } catch (e) {}
    
    if (/^[0-9a-fA-F-]{36}$/.test(src)) {
      return src;
    }
    throw new Error("無法從來源解析出 replay_key，請確認網址格式。");
  }
  
  var replayKey = extractReplayKey(source);
  var url = "https://static.x-game.net/resource/replay/hand/" + replayKey + ".json";
  
  try {
    // 加入 User-Agent 模擬瀏覽器，避免被伺服器阻擋
    var response = UrlFetchApp.fetch(url, {
      muteHttpExceptions: true,
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
      }
    });
    
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

### 步驟 2：新增前端 UI 與繪圖代碼 (Index.html)

1. 在左側「檔案」區，點擊 **+ 號** -> 選擇 **HTML**。
2. 檔案命名為 **`Index`**。
3. 將 `Index.html` 內容清空，貼上以下完整代碼（已補全 `build_showdown_lines`）：

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
    <h2>X-Poker 牌局轉換器 (修正版)</h2>
    <input type="text" id="urlInput" placeholder="請貼上 X-Poker 牌局網址或 replay_key...">
    <button onclick="generate()">解析並生成</button>
    <span class="loader" id="loader">載入與繪製中...請稍候</span>
    
    <div class="result" id="resultArea" style="display:none;">
      <div class="text-result">
        <h3>手牌詳情</h3>
        <textarea id="txtOutput" readonly></textarea>
      </div>
      <div class="image-result">
        <h3>圖片 (右鍵 -> 另存圖片)</h3>
        <img id="imgOutput" alt="Hand Chart">
      </div>
    </div>
  </div>

  <script>
    // --- 核心資料與對應表 ---
    const ACTION_LABELS = { 1:"posts ante", 2:"posts SB", 3:"posts BB", 7:"checks", 8:"folds", 9:"bets", 10:"calls", 11:"raises", 12:"pots", 13:"checks", 14:"folds", 16:"posts bomb pot", 17:"posts straddle", 18:"posts restraddle", 19:"folds" };
    const ROUND_LABELS = { 1: "Preflop", 2: "Flop", 3: "Turn", 4: "River" };
    const RANK_MAP = { 2:"2", 3:"3", 4:"4", 5:"5", 6:"6", 7:"7", 8:"8", 9:"9", 10:"T", 11:"J", 12:"Q", 13:"K", 14:"A" };
    const SUIT_MAP = { 1: "s", 2: "h", 3: "c", 4: "d" };
    const SUIT_COLORS = { "s": "#111111", "h": "#d63c3c", "d": "#e78a20", "c": "#2d6cdf" };
    const ACTION_BUBBLE_COLORS = { 1: ["#274060", "#dce8ff"], 2: ["#274060", "#dce8ff"], 3: ["#274060", "#dce8ff"], 7: ["#3a4b68", "#eef3ff"], 8: ["#414854", "#eef3ff"], 9: ["#f0c04d", "#251b00"], 10: ["#6ca6ff", "#04162f"], 11: ["#f0c04d", "#251b00"], 12: ["#f0c04d", "#251b00"], 13: ["#3a4b68", "#eef3ff"], 14: ["#414854", "#eef3ff"], 16: ["#a55d2e", "#fff4e8"] };
    const POSITION_LABELS = { 2: ["BTN/SB", "BB"], 3: ["BTN", "SB", "BB"], 4: ["BTN", "SB", "BB", "UTG"], 5: ["BTN", "SB", "BB", "UTG", "CO"], 6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"], 7: ["BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"], 8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"], 9: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"] };
    const SEAT_ANGLES = { 2:[90,-90], 3:[90,-25,-155], 4:[90,10,-90,170], 5:[90,40,-20,-130,160], 6:[90,48,5,-55,-132,175], 7:[90,50,15,-35,-90,-145,180], 8:[90,52,10,-33,-90,-147,180,130], 9:[90,58,25,-10,-50,-95,-140,180,132] };

    // --- 輔助邏輯 ---
    function chips_to_display(c) { return parseFloat((c/100).toFixed(3)).toString(); }
    function chips_to_bb(c, bb) { return parseFloat((c/bb).toFixed(3)).toString(); }
    function decode_card(cc, emo=false) {
        if(!cc) return ""; let r=cc%256, s=Math.floor(cc/256), sc=SUIT_MAP[s];
        if(emo) { if(sc=="s") sc="♠️"; else if(sc=="h") sc="♥️"; else if(sc=="c") sc="♣️"; else if(sc=="d") sc="♦️"; }
        return `${RANK_MAP[r]}${sc}`;
    }
    function sort_cards_for_display(cs) {
        return cs.filter(c=>c).sort((a,b)=>{ let ra=a%256, rb=b%256, sa=Math.floor(a/256), sb=Math.floor(b/256); return ra!=rb?rb-ra:sb-sa; });
    }

    // --- 核心轉換函數 ---
    function build_players(data) {
        let players = data.playerHands, labels = POSITION_LABELS[players.length], built = [];
        for (let p of players) {
            let posIdx = parseInt(p.position), posLbl = labels[posIdx] || `POS${posIdx}`;
            let cs = []; for(let i=1;i<=6;i++) if(p[`card${i}`]) cs.push(parseInt(p[`card${i}`]));
            built.push({ seat_id: parseInt(p.seat_id), position_index: posIdx, position_label: posLbl, uid: parseInt(p.uid), name: String(p.user_name), begin_chips: parseInt(p.begin_chips), end_chips: parseInt(p.end_chips), cards: cs.filter(c=>c), shown: !!p.is_show_hands });
        }
        return built.sort((a, b) => a.position_index - b.position_index);
    }

    function describe_action(k, amt_bb, aft_bb, ai) {
        if(k==7||k==13) return "checks"; if(k==8||k==14||k==19) return "folds";
        let l = ACTION_LABELS[k] || `action_${k}`;
        let res = (k==11||k==12) ? `${l} to ${aft_bb} BB` : `${l} ${amt_bb} BB`;
        return res + ai;
    }

    function build_street_summaries(data, players) {
        let hand = data.handInfo, bb = parseInt(hand.big_blind), pMap = {}; players.forEach(p=>pMap[p.seat_id]=p);
        let rem = {}; players.forEach(p=>rem[p.seat_id]=p.begin_chips);
        let curPot = 0, sums = [];
        (hand.round || []).forEach(r => {
            let rNum = parseInt(r.round), pDisp = (rNum==1)?0:curPot, rCont = {}, acts = [];
            if(rNum==1) {
                let forced = new Set([1,2,3,4,5,16,17,18]);
                for(let a of (r.action||[])) { if(!forced.has(parseInt(a.action_kind))) break; pDisp += parseInt(a.action_chips||0); }
            }
            for(let a of (r.action||[])) {
                let sid = parseInt(a.seat_id), p = pMap[sid], amt = parseInt(a.action_chips||0), k = parseInt(a.action_kind);
                let bef = rCont[sid]||0, aft = bef+amt; rCont[sid] = aft; rem[sid] -= amt;
                let ai = (rem[sid]==0 && amt>0)?" (all-in)":"";
                let txt = describe_action(k, chips_to_bb(amt, bb), chips_to_bb(aft, bb), ai);
                acts.push({ kind: k, seat_id: sid, text: `${p.position_label} ${p.name} ${txt}`, image_text: `${p.name}: ${txt}` });
                curPot += amt;
            }
            let b = []; (hand.round||[]).forEach(rr => { if(parseInt(rr.round)<=rNum && rr.card) b.push(...rr.card); });
            sums.push({ round_number: rNum, label: ROUND_LABELS[rNum]||`Round ${rNum}`, board: b, pot_display: pDisp, actions: acts });
        });
        return sums;
    }

    // --- 補全原本漏掉的函數 ---
    function build_showdown_lines(players, winning_info, big_blind, anon = false) {
        let lines = [];
        let p_map = {}; players.forEach(p => p_map[p.seat_id] = p);
        players.filter(p => p.shown && p.cards.length).forEach(p => {
            let name = anon ? `Player ${p.seat_id}` : p.name;
            let cards = sort_cards_for_display(p.cards).map(c => decode_card(c, true)).join(" ");
            lines.push(`${p.position_label} ${name} shows [${cards}]`);
        });
        winning_info.forEach(w => {
            let wp = p_map[parseInt(w.seat_id)];
            if (!wp) return;
            let name = anon ? `Player ${wp.seat_id}` : wp.name;
            let b5 = w.best_hands || [];
            let line = `${wp.position_label} ${name} wins ${chips_to_bb(parseInt(w.pot_chips), big_blind)} BB`;
            if (b5.length) line += ` with [${b5.map(c => decode_card(c, true)).join(" ")}]`;
            lines.push(line);
        });
        return lines;
    }

    // --- 繪圖邏輯 ---
    function fillRoundedRect(ctx, l, t, r, b, rad, f, ol, w) {
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(l, t, r-l, b-t, rad);
        else ctx.rect(l, t, r-l, b-t); // 墊後方案
        if(f) { ctx.fillStyle = f; ctx.fill(); }
        if(ol) { ctx.strokeStyle = ol; ctx.lineWidth = w||1; ctx.stroke(); }
    }
    
    function draw_text(ctx, x, y, t, font, f, anc="la") {
        ctx.font = font; ctx.fillStyle = f;
        if(anc=="la"){ ctx.textAlign="left"; ctx.textBaseline="top"; y+=2; }
        else if(anc=="mm"){ ctx.textAlign="center"; ctx.textBaseline="middle"; }
        else if(anc=="ra"){ ctx.textAlign="right"; ctx.textBaseline="top"; y+=2; }
        ctx.fillText(t, x, y);
    }

    function fit_text(ctx, text, font, max_w) {
        ctx.font = font; if (ctx.measureText(text).width <= max_w) return text;
        let t = text; while (t && ctx.measureText(t + "…").width > max_w) t = t.slice(0, -1);
        return t ? t + "…" : "…";
    }

    function draw_suit(ctx, suit, cx, cy, sz, fill) {
        ctx.fillStyle = fill; ctx.beginPath();
        if(suit=="d") { ctx.moveTo(cx, cy-sz*0.5); ctx.lineTo(cx+sz*0.4, cy); ctx.lineTo(cx, cy+sz*0.5); ctx.lineTo(cx-sz*0.4, cy); }
        else if(suit=="h") { ctx.arc(cx-sz*0.2, cy-sz*0.15, sz*0.2, 0, 2*Math.PI); ctx.arc(cx+sz*0.2, cy-sz*0.15, sz*0.2, 0, 2*Math.PI); ctx.fill(); ctx.beginPath(); ctx.moveTo(cx-sz*0.42, cy-sz*0.02); ctx.lineTo(cx+sz*0.42, cy-sz*0.02); ctx.lineTo(cx, cy+sz*0.48); }
        else if(suit=="c" || suit=="s") { ctx.arc(cx, cy-sz*0.1, sz*0.25, 0, 2*Math.PI); ctx.fill(); ctx.beginPath(); ctx.rect(cx-sz*0.05, cy, sz*0.1, sz*0.4); }
        ctx.fill();
    }

    function draw_card(ctx, x, y, c, w, h, simple=false) {
        let r=c.slice(0,-1), s=c.slice(-1), f=SUIT_COLORS[s];
        fillRoundedRect(ctx, x, y, x+w, y+h, 8, f, "#fff", 2);
        if(simple) { draw_text(ctx, x+w/2, y+h/2, r+s, "bold 20px sans-serif", "#fff", "mm"); return; }
        draw_text(ctx, x+5, y+5, r, "bold 16px sans-serif", "#fff", "la");
        draw_suit(ctx, s, x+w*0.7, y+h*0.7, w*0.4, "#fff");
    }

    function render_hand_chart(data, rkey) {
        let hand = data.handInfo, game = data.gameSetInfo, bb = parseInt(hand.big_blind);
        let players = build_players(data), streets = build_street_summaries(data, players);
        
        let w = 1240, m = 40, gap = 20, sw = Math.floor((w - m*2 - gap*3)/4);
        let h = 1600; // 動態高度預留
        let cvs = document.createElement('canvas'); cvs.width = w; cvs.height = h; let ctx = cvs.getContext('2d');
        
        ctx.fillStyle = "#0c121a"; ctx.fillRect(0,0,w,h);
        
        // 繪製標題
        fillRoundedRect(ctx, m, m, w-m, 120, 20, "#132230");
        draw_text(ctx, m+20, m+15, game.game_name, "bold 36px sans-serif", "#fff", "la");
        draw_text(ctx, m+20, m+60, `Hand #${hand.hand_id} | Key: ${rkey}`, "20px sans-serif", "#9eb2c8", "la");

        let curY = 150;
        // 繪製每條街
        streets.forEach((s, i) => {
            let col = i % 4, row = Math.floor(i / 4);
            let x = m + col*(sw+gap), y = curY + row*400;
            fillRoundedRect(ctx, x, y, x+sw, y+380, 15, "#101923", "#233649");
            draw_text(ctx, x+15, y+15, s.label, "bold 22px sans-serif", "#fff", "la");
            draw_text(ctx, x+sw-15, y+15, `Pot: ${chips_to_bb(s.pot_display, bb)} BB`, "18px sans-serif", "#9eb2c8", "ra");
            
            if(s.board.length) {
                s.board.forEach((bc, bi) => draw_card(ctx, x+15 + bi*45, y+50, decode_card(bc), 40, 60, true));
            }
            
            let ay = y + 120;
            s.actions.forEach(a => {
                let c = ACTION_BUBBLE_COLORS[a.kind] || ["#233649", "#fff"];
                fillRoundedRect(ctx, x+10, ay, x+sw-10, ay+30, 10, c[0]);
                draw_text(ctx, x+20, ay+5, fit_text(ctx, a.image_text, "16px sans-serif", sw-40), "16px sans-serif", c[1], "la");
                ay += 35;
            });
        });

        // 結算區
        let footY = curY + Math.ceil(streets.length/4)*400 + 20;
        let footLines = build_showdown_lines(players, hand.winning_info||[], bb);
        fillRoundedRect(ctx, m, footY, w-m, footY + 200, 20, "#0f1924");
        footLines.forEach((fl, fi) => draw_text(ctx, m+20, footY+20+fi*30, fl, "20px sans-serif", "#dce5ef", "la"));

        // 裁切畫布到實際高度
        let finalCvs = document.createElement('canvas'); finalCvs.width = w; finalCvs.height = footY + 250;
        finalCvs.getContext('2d').drawImage(cvs, 0, 0);
        return finalCvs.toDataURL("image/png");
    }

    // --- 介面控制 ---
    function generate() {
        let input = document.getElementById('urlInput').value.trim();
        if (!input) return;
        document.getElementById('loader').style.display = 'inline-block';
        document.getElementById('resultArea').style.display = 'none';
        
        google.script.run.withSuccessHandler(function(res) {
            document.getElementById('loader').style.display = 'none';
            if (!res.success) { alert("錯誤: " + res.error); return; }
            try {
                let players = build_players(res.data);
                let streets = build_street_summaries(res.data, players);
                
                // 生成 TXT
                let txt = `Hand #${res.data.handInfo.hand_id}\nKey: ${res.replayKey}\n\nActions:\n`;
                streets.forEach(s => {
                    txt += `\n--- ${s.label} ---\n`;
                    s.actions.forEach(a => txt += a.text + "\n");
                });
                document.getElementById('txtOutput').value = txt;
                
                // 生成圖片
                document.getElementById('imgOutput').src = render_hand_chart(res.data, res.replayKey);
                document.getElementById('resultArea').style.display = 'flex';
            } catch (e) { alert("繪製出錯: " + e.message); console.error(e); }
        }).fetchReplayData(input);
    }
  </script>
</body>
</html>
```

### 步驟 3：發佈 (重要！)

1. 點擊右上角 **「部署」 -> 「新增部署作業」**。
2. 類型選 **「網頁應用程式」**。
3. 執行身分：**我**。
4. 誰可以存取：**所有人**。
5. **重要：** 每次修改代碼後，都必須執行「部署 -> 管理部署 -> 編輯 -> 版本選擇 **新版本**」才會生效。

現在，您的 GAS 應用程式應該就能正常解析並繪圖了。
