# War Thunder Nuke & Kill Counter (OBS Overlay)

<div align="center">
    <img width="130" height="100" alt="image" src="https://github.com/user-attachments/assets/404c02a9-9573-4ae1-8c45-349a73e19dd4" />
</div>
這是一個專為 [War Thunder (戰爭雷霆)](https://warthunder.com/) 設計的 OBS 實況計數器 Overlay。利用遊戲內建的 HTTP API (`http://localhost:8111`) 即時讀取 HUD 訊息（右下角擊殺紀錄），實現自動追蹤「擊殺數 (Kills)」、「死亡數 (Deaths)」與「核彈數 (Nukes)」，並能自動計算顯示 K/D 值。

注意：擊殺數在自定義戰鬥(Custom Battles)會計算友軍擊殺 (目前無解，8111 端口不會提供擊殺者陣營資訊，若有辦法解決，請告知)。
但不知道為何一般戰鬥則不會計算友軍擊殺，請有能力的開發者告知原因。

## 專案架構與檔案說明

本專案採用 **Python 後端 + 前端分離** 的架構，以解決跨網域 (CORS) 限制與狀態同步問題。

### 1. 啟動腳本 (VBScript)
*   **`Start_Tracker.vbs`**：(必備) 啟動背景計數器 `backend.py`。它會隱藏視窗默默執行，負責與遊戲 API 溝通並記錄數據。建議將此捷徑加入開機自動啟動 (`shell:startup`)。
*   **`Start_Display.vbs`**：(選用) 如果你不想開 OBS，只需雙擊此腳本，就會自動呼叫 Chrome/Edge 開啟一個乾淨的獨立小視窗來顯示計數器。

### 2. 前端介面 (HTML / CSS / JS)
分為兩個獨立的介面，可依個人需求加入 OBS 中：
*   **`index.html`**：顯示 **總計 (Total)** 數據。包含「總 K/D」、「Total Kills」、「Total Nukes」。
*   **`today.html`**：顯示 **今日 (Today)** 數據。包含「Today's K/D」、「Today Kills」、「Today Nukes」。
*   **`style.css`**：外觀風格，採用 Apple Glassmorphism (毛玻璃) 搭配軍武科技風格。
*   **`counter.js`**：前端核心邏輯，負責向後端 (`http://127.0.0.1:8112`) 抓取數據、觸發連殺文字疊加動畫與核彈特效。

### 3. 後端邏輯 (`backend.py`)
這是整個專案的資料核心：
*   **資料解析與儲存**：不斷向遊戲 API 索取資料，過濾出屬於你的擊殺與死亡事件，並儲存在本地的 `state.json` 中。
*   **自動換日**：內建換日機制，跨日時會自動將 `todayKills`、`todayDeaths`、`todayNukes` 歸零。
*   **資料伺服器**：在 `http://127.0.0.1:8112` 開啟小型伺服器，讓多個前端網頁 (OBS 或獨立視窗) 可以同時讀取並保持完美的數據同步。

## 核心機制解析 (For Developers)

1.  **擊殺與死亡判定**：
    *   **動詞過濾 (`ACTION_KEYWORDS`)**：程式內建涵蓋多國語言的動詞陣列（如 `"destroyed"`, `"摧毀"` 等）。
    *   **過濾機制**：自殺、撞毀 (`has crashed`) 以及核彈廣播關鍵字會被排除在擊殺之外，但會被正確計入「死亡數」以供 K/D 計算。當 K/D 為 0 時，會自動顯示為 `NaN`。
    *   **玩家比對 (`extractKillerName`)**：自動切除 `(F-15E)` 等載具標籤，擷取出純粹的玩家 ID 進行比對。
2.  **連殺疊加系統 (Kill Combo System)**：
    *   當偵測到擊殺時，會浮現 `+1 KILL`。如果在接下來的 **5 秒內** 又偵測到擊殺，系統**不會**產生新的文字重疊，而是會將原有的文字更新為 `+N KILL` (例如 `+3 KILL`) 並重新觸發彈跳動畫。
3.  **手動校正 (Edit Modal)**：
    *   由於 API 無法判斷 TK (Teamkill)，或是偶爾有漏算情況，你可以在任何一個計數器畫面上 **連續點擊滑鼠兩下** 開啟隱藏的編輯視窗。可手動調整 `Today Kills`、`Today Deaths`、`Total Kills`、`Total Deaths` 與核彈數；修改完成並按下儲存後，數據會直接送回 `backend.py` 保存，並立刻同步到所有畫面上。

## 如何使用 / 開發測試

1.  **實況主使用**：
    *   **Step 1**: 在 `config.json` 裡面設定你的遊戲 ID (`player_name`)。
    *   **Step 2**: 執行 `Start_Tracker.vbs` 來啟動背景計數器 (建議加入開機自啟動)。
    *   **Step 3**: 在 OBS 中新增「瀏覽器來源」，勾選「本機檔案」。
        *   如果你想顯示總計數據，請選擇 `index.html`。
        *   如果你想顯示今日數據，請選擇 `today.html`。
        *   (你可以同時加入這兩個檔案，它們的數據會完美同步！)
    *   **Step 4**: (手動校正) 需自行設定數值時，請將滑鼠移至計數器畫面上，連續點擊兩下開啟修改視窗，修改儲存後即刻生效。

2.  **開發測試**：
    *   若需進行除錯，可以將 `config.json` 中的 `"debug"` 設為 `true`，後端會在 `logs/` 目錄下產生兩個檔案：`logs/8111.log` 累積保存 `http://localhost:8111/hudmsg?...` 的原始資料，`logs/debug_kills.log` 記錄程式實際判定後的擊殺/死亡結果，並會標出 `skipped=baseline_seen`、`skipped=not_running`、`skipped=seen_before` 等跳過原因，方便對照問題發生在哪一段。
