# War Thunder Nuke & Kill Counter (OBS Overlay)

這是一個專為 [War Thunder (戰爭雷霆)](https://warthunder.com/) 設計的 OBS 實況計數器 Overlay。利用遊戲內建的 HTTP API (`http://localhost:8111`) 即時讀取 HUD 訊息（右下角擊殺紀錄），實現自動追蹤「擊殺數 (Kills)」與「核彈數 (Nukes)」。

注意:擊殺數會計算友軍擊殺(目前無解，8111端口不會提供擊殺者陣營資訊，若有辦法解決，請告知)。

## 專案架構與檔案說明

本專案分為後端資料抓取 (`backend.py`) 與前端顯示 (`nuke_counter.js`, `index.html`)，確保計數狀態一致並大幅降低延遲。

### 1. `backend.py` (計數大腦)
*   **唯一真實數據源 (Source of Truth)**：在背景持續向 `http://localhost:8111` 獲取擊殺資料，儲存在本機的 `state.json`，並在 `8112` port 提供給前端讀取。
*   **極低延遲輪詢**：0.1 秒高頻輪詢 8111 端口。將 `mission.json` 移出擊殺關鍵判定路徑並加上 2 秒快取，確保在激戰時避免效能卡頓。
*   **多端同步一致**：不論使用 OBS 還是獨立視窗，只要是讀取 `backend.py` 的資料，計數都能永遠保持同步。開 OBS 的瞬間會自動靜默對齊累積數字，不會產生分歧。

### 2. 前端顯示與動畫 (`index.html`, `style.css`, `nuke_counter.js`)
*   **介面佈局**：包含四個主要的資料區塊（Total Kills, Total Nukes, Today Kills, Today Nukes）。支援 Apple Glassmorphism (毛玻璃) 搭配軍武科技風格 (`Chakra Petch`)。
*   **極速反應**：前端以 100~250ms 的頻率向 `backend.py` 獲取狀態，使遊戲跳出 kill feed 到計數器 +1 的延遲壓縮至 0.25 秒以內 (<1秒)。
*   **動態 Combo 連殺系統**：
    *   第一刀會浮現 `+1 KILL`。
    *   在連殺視窗 (預設 2.5 秒) 內若再次擊殺，同一個泡泡文字會直接更新為 `+2`、`+3`...，不疊加新視窗，並重新觸發彈跳動畫。
    *   每次擊殺都會重置 2.5 秒的消失計時，只要一直殺，泡泡就一直續命。停手滿 2.5 秒才淡出消失。一發多殺 (如一發炸彈炸兩台) 會直接反應為 `+2`。
*   **手動修改視窗 (Edit Modal)**：在網頁上「連點兩下」開啟隱藏彈出視窗，方便實況主手動校正因 Teamkill (TK) 造成的誤差。

### 3. 啟動腳本 (`.vbs`)
*   `Start_Tracker.vbs`：**核心啟動器**。雙擊會在背景隱藏執行 `backend.py` (當作唯一的計數大腦)。
*   `Start_Display.vbs` (Optional)：提供一個無邊框的獨立 Chrome 小視窗顯示計數器，方便沒開 OBS 時觀看。它會直接讀取 backend 數據，所以不需要關閉 Web Security 即可繞過 CORS。

## 如何使用 / 安裝教學

1.  **實況主使用 (OBS Overlay)**：
    *   **Step 1:** 下載並解壓縮專案。
    *   **Step 2 (修改 ID):** 啟動過一次 `Start_Tracker.vbs` 後會產生 `config.json`，請開啟並將 `player_name` 修改為你的遊戲 ID。
    *   **Step 3 (啟動大腦):** 雙擊執行 `Start_Tracker.vbs` (需安裝 Python 環境)。
    *   **Step 4 (OBS 設定):** 在 OBS 新增一個「瀏覽器來源」，勾選「本機檔案」，選擇 `index.html`。
    *   **Step 5 (設定開機自啟):** 設定開機自動執行：按下 `Win + R`，輸入 `shell:startup` 進入啟動資料夾，將 `Start_Tracker.vbs` 的捷徑放入該資料夾，以後開機就會自動在背景計算 kill 數。

2.  **純顯示使用 (不開 OBS 也可看)**：
    *   確認 `Start_Tracker.vbs` 已在背景執行。
    *   雙擊 `Start_Display.vbs`，即可呼叫一個獨立的小視窗在桌面上顯示目前數字。
