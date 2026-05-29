# War Thunder Nuke & Kill Counter (OBS Overlay)

這是一個專為 [War Thunder (戰爭雷霆)](https://warthunder.com/) 設計的 OBS 實況計數器 Overlay。利用遊戲內建的 HTTP API (`http://localhost:8111`) 即時讀取 HUD 訊息（右下角擊殺紀錄），實現自動追蹤「擊殺數 (Kills)」與「核彈數 (Nukes)」。

注意:擊殺數會計算友軍擊殺(目前無解，8111端口不會提供擊殺者陣營資訊，若有辦法解決，請告知)。

## 專案架構與檔案說明

專案由三個主要檔案組成，採用純前端技術 (Vanilla JS, HTML, CSS)，不需安裝 Node.js，可直接作為 OBS 的「瀏覽器來源 (Browser Source)」使用。

### 1. `index.html` (UI 結構)
*   **介面佈局 (Shell & Grid)**：包含四個主要的資料區塊（Total Kills, Total Nukes, Today Kills, Today Nukes）。
*   **手動修改視窗 (Edit Modal)**：一個隱藏的彈出視窗。為了防範 API 偶爾無法精準判定 Teamkill (TK) 的情況，實況主可以在網頁上「連點兩下」來開啟這個視窗，手動校正目前的累積擊殺與核彈數。

### 2. `style.css` (外觀與動畫)
*   **視覺風格**：採用 Apple Glassmorphism (毛玻璃) 搭配 War Thunder 軍武科技風格 (字體使用 `Chakra Petch`)。
*   **動畫效果 (Animations)**：
    *   **Combo 動畫**：定義了 `.floating-text` 與 `@keyframes floatUp`。
    *   **Nuclear 動畫**：除了數字跳動，還支援呼叫同目錄下的 `explosion.gif` 作為核彈爆發的視覺反饋。

### 3. `nuke_counter.js` (核心邏輯)

這是整個專案的核心，負責與 War Thunder API 溝通、資料解析與本地儲存。

#### 核心機制解析 (For Developers)

1.  **狀態保存 (LocalStorage)**
    *   `state` 物件負責記錄 `totalKills`, `totalNukes`, `lastDmg` 等資訊。
    *   `rotateDailyStats(state)`: 每次輪詢時檢查日期是否跨日（`dayKey`），若跨日則自動將 `todayKills` 與 `todayNukes` 歸零。
2.  **API 輪詢與資料擷取 (Polling)**
    *   透過 `fetchHUD` 不斷向 `http://localhost:8111/hudmsg?lastEvt={X}&lastDmg={Y}` 發送 GET 請求。
    *   **防呆重置機制**：如果收到連續 5 次以上的空回應，且 `lastDmg` 的數字異常巨大（>10000），這通常是因為 Mock Server 切換或遊戲重開導致的 API ID 錯亂。此時程式會自動將 `lastDmg` 歸零以恢復正常抓取。
3.  **擊殺判定邏輯 (`isOwnedKillEvent`)**
    *   **動詞過濾 (`ACTION_KEYWORDS`)**：因為不同語系的客戶端會有不同的擊殺字眼，程式內建了涵蓋英、法、德、俄、中等多國語言的動詞陣列（如 `"destroyed"`, `"set afire"`, `"摧毀"` 等）。只要 `msg` 包含這些字眼即視為有效擊殺。
    *   **過濾自殺與核彈廣播**：自動忽略 `"has been wrecked"`, `"has crashed"`，以及觸發核彈的關鍵字（避免將核彈警報誤判為擊殺）。
    *   **玩家比對 (`extractKillerName`)**：自動切除 `(F-15E)` 等載具標籤，擷取出純粹的玩家 ID，並與 URL 參數指定的玩家名稱進行比對，藉此過濾出屬於該玩家的擊殺。
    *   *已知限制：War Thunder 的 API 並不提供擊殺的陣營資訊 (Team Data)，因此 Teamkill (殺死隊友) 依然會被判定為擊殺。若發生 TK 需依靠手動修改功能校正。*
4.  **連殺疊加系統 (Kill Combo System)**
    *   由 `triggerKillCombo(count)` 負責。
    *   **機制**：當偵測到擊殺時，會浮現 `+1 KILL`。如果在接下來的 **5 秒內** 又偵測到擊殺，系統**不會**產生新的文字重疊，而是會將原有的文字更新為 `+N KILL` (例如 `+3 KILL`)。
    *   更新文字的同時，利用 `void activeKillAnimEl.offsetWidth;` 強制觸發 CSS reflow (重繪)，讓浮動動畫可以重新播放（彈跳感），並重置 5 秒的消除計時器。

## 如何使用 / 開發測試

1.  **實況主使用**：
    * Step1: 下載專案
    * Step2: 在 OBS 新增一個「瀏覽器來源」，勾選「本機檔案」，選擇 `index.html`(其他設定預設就好)。
    * Step3: 在 `nuke.counter.js` 修改 `DEFAULT_PLAYER` 為你的遊戲ID。
2.  **開發測試**：
    開發時因為 CORS 限制與跨網域問題，建議在專案目錄下啟動一個簡易的 HTTP Server（例如：`python -m http.server 8080`），然後用瀏覽器開啟 `http://localhost:8080/index.html`，並開啟開發者工具 (F12) 觀看 `[NukeCounter]` 開頭的 Console Logs 以利除錯。
