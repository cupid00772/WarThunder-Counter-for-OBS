# War Thunder Nuke & Kill Counter (OBS Overlay)

<div align="center">
    <img width="800" height="449" alt="counter_showcase" src="https://github.com/user-attachments/assets/17459e67-179d-4f3b-8146-f6bbd5b4e1a5" />
</div>

這是一個專為 [War Thunder (戰爭雷霆)](https://warthunder.com/) 設計的 OBS 實況計數器 Overlay。利用遊戲內建的 HTTP API (`http://localhost:8111`) 即時讀取 HUD 訊息（右下角擊殺紀錄），實現自動追蹤「擊殺數 (Kills)」、「死亡數 (Deaths)」與「核彈數 (Nukes)」，並能自動計算顯示 K/D 值。

注意：擊殺數在自定義戰鬥(Custom Battles)會計算友軍擊殺 (目前無解，8111 端口不會提供擊殺者陣營資訊，若有辦法解決，請告知)。
但不知道為何一般戰鬥則不會計算友軍擊殺，請有能力的開發者告知原因。

## 專案架構與檔案說明

本專案採用 **Python 後端 + 前端分離** 的架構，以解決跨網域 (CORS) 限制與狀態同步問題。

### 1. 啟動腳本 (VBScript)
*   **`Start_Tracker.vbs`**：(必備) 啟動背景計數器 `backend.py`。它會先關掉同資料夾內已存在的 tracker，再隱藏啟動一個乾淨的後端行程，避免多個後端同時寫入 `state.json`。
*   **`Start_Display.vbs`**：(選用) 如果你不想開 OBS，只需雙擊此腳本，就會自動呼叫 Chrome/Edge 開啟一個乾淨的獨立小視窗。

### 2. 前端介面 (HTML / CSS / JS)
分為兩個獨立的介面，可依個人需求加入 OBS 中：
*   **`index.html`**：顯示 **總計 (Total)** 數據。包含「總 K/D」、「Total Kills」、「Total Nukes」。
*   **`today.html`**：顯示 **今日 (Today)** 數據。包含「Today's K/D」、「Today Kills」、「Today Nukes」。
*   **`startdisplay.html`**：給 `Start_Display.vbs` 使用的獨立視窗版，會顯示總計資料與最近每日紀錄。
*   **`style.css`**：外觀風格，採用 Apple Glassmorphism (毛玻璃) 搭配軍武科技風格。
*   **`counter.js`**：前端核心邏輯，負責向後端 (`http://127.0.0.1:8112`) 抓取數據、觸發連殺文字疊加動畫與核彈特效。

### 3. 後端邏輯 (`backend.py`)
這是整個專案的資料核心：
*   **資料解析與儲存**：不斷向遊戲 API 索取資料，過濾出屬於你的擊殺與死亡事件，並儲存在本地的 `state.json` 中。
*   **自動換日**：內建換日機制，跨日時會自動將 `todayKills`、`todayDeaths`、`todayNukes` 歸零。
*   **每日紀錄**：每次跨日時，後端會把前一天的 `日期 + 擊殺 + 死亡` 追加到獨立的 `daily_records.json`，保留最近 60 筆；`/state` 會同時把這份資料送給前端顯示。
*   **高壓擊殺防漏抓**：主 tracker 以低延遲輪詢 `/hudmsg`，使用 `lastDmg` 回退重抓與 damage id 去重，避免短時間大量擊殺時因 War Thunder HUD feed 視窗被洗掉而漏算。
*   **試車場判定**：`/mission.json` 由獨立背景 thread 低頻讀取，只更新快取狀態；主擊殺 loop 不會等待它。偵測到試車 / 試飛 / test drive / test flight 時，該段 HUD 訊息會標記已看過但不計入正式統計。
*   **資料伺服器**：在 `http://127.0.0.1:8112` 開啟小型伺服器，讓多個前端網頁 (OBS 或獨立視窗) 可以同時讀取並保持完美的數據同步。

## 目前相對 GitHub 版的主要變更

*   **降低高壓漏算機率**：`backend.py` 的 `/hudmsg` 輪詢改為更短週期，並移除熱路徑上的 `/mission.json` 查詢。`/mission.json` 曾在遊戲中 timeout，會讓短時間大量擊殺時漏掉少數 HUD 訊息。
*   **試車場不計數**：新增 mission watcher thread。若最近成功讀到的 mission metadata 顯示為試車 / 試飛 / test drive / test flight，會跳過計數但保留 damage id 去重，避免離開試車場後補算。
*   **每日紀錄**：新增 `daily_records.json` 與前端每日紀錄列表，跨日時保存最近 60 天的擊殺 / 死亡紀錄，獨立顯示視窗會顯示最近紀錄。
*   **啟動穩定性**：`Start_Tracker.vbs` 會優先使用本機 Python runtime，並先終止同資料夾既有 tracker，避免重複後端行程。
*   **獨立顯示視窗**：新增 `startdisplay.html`，`Start_Display.vbs` 改為開啟這個頁面並調整視窗大小。

## 核心機制解析 (For Developers)

1.  **擊殺與死亡判定**：
    *   **動詞過濾 (`ACTION_KEYWORDS`)**：程式內建涵蓋多國語言的動詞陣列（如 `"destroyed"`, `"摧毀"` 等）。
    *   **過濾機制**：自殺、撞毀 (`has crashed`) 以及核彈廣播關鍵字會被排除在擊殺之外，但會被正確計入「死亡數」以供 K/D 計算。當 K/D 為 0 時，會自動顯示為 `NaN`。
    *   **玩家比對 (`extractKillerName`)**：自動切除 `(F-15E)` 等載具標籤，擷取出純粹的玩家 ID 進行比對。
2.  **連殺疊加系統 (Kill Combo System)**：
    *   當偵測到擊殺時，會浮現 `+1 KILL`。如果在接下來的 **2.5 秒內** 又偵測到擊殺，系統**不會**產生新的文字重疊，而是會將原有的文字更新為 `+N KILL` (例如 `+3 KILL`) 並重新觸發彈跳動畫。
3.  **HUD 游標與去重**：
    *   後端不會每次直接跳到最新 `lastDmg`，而是保留一段回退 margin 重抓。已處理過的 damage id 會進入 `seen_dmg_ids`，所以可重抓防漏而不重複加分。
    *   War Thunder 關閉後重新連上時，HUD id 可能從低數字重來；後端會在偵測到 8111 connection refused 後重置去重狀態，避免新場次 id 撞到舊場次 id。
4.  **試車場過濾**：
    *   `mission_loop` 以背景 thread 低頻讀 `/mission.json`，偵測 `test drive`、`test flight`、`試車`、`試飛` 等關鍵字。
    *   如果 mission 狀態逾時或讀不到，系統採取 fail-open：照常計數，避免因 metadata timeout 造成正式戰局漏抓。
5.  **手動校正 (Edit Modal)**：
    *   由於 API 無法判斷 TK (Teamkill)，或是偶爾有漏算情況，你可以在任何一個計數器畫面上 **連續點擊滑鼠兩下** 開啟隱藏的編輯視窗。可手動調整 `Today Kills`、`Today Deaths`、`Total Kills`、`Total Deaths` 與核彈數；修改完成並按下儲存後，數據會直接送回 `backend.py` 保存，並立刻同步到所有畫面上。

## 如何使用 / 開發測試

1.  **實況主使用**：
    *   **Step 1**: 在 `config.json` 裡面設定你的遊戲 ID (`player_name`)。
    *   **Step 2**: 執行 `Start_Tracker.vbs` 來啟動背景計數器 (建議加入開機自啟動)。
    *   **Step 3**: 在 OBS 中新增「瀏覽器來源」，勾選「本機檔案」。
        *   如果你想顯示總計數據，請選擇 `index.html`。
        *   如果你想顯示今日數據，請選擇 `today.html`。
        *   如果你想開獨立小視窗並看每日紀錄，請雙擊 `Start_Display.vbs`，它會開啟 `startdisplay.html`。
        *   (你可以同時加入 `index.html` 和 `today.html`，它們的數據會完美同步！)
    *   **Step 4**: (手動校正) 需自行設定數值時，請將滑鼠移至計數器畫面上，連續點擊兩下開啟修改視窗，修改儲存後即刻生效。

2.  **開發測試**：
    *   若需進行除錯，可以將 `config.json` 中的 `"debug"` 設為 `true`，後端會在 `logs/` 目錄下產生兩個檔案：`logs/8111.log` 累積保存 `http://localhost:8111/hudmsg?...` 的原始資料，`logs/debug_kills.log` 記錄程式實際判定後的擊殺/死亡結果，並會標出 `skipped=baseline_seen`、`skipped=test_drive`、`skipped=seen_before` 等跳過原因，方便對照問題發生在哪一段。
    *   `/state` 會額外回傳 `dailyRecords`、`isTestDrive`、`missionStatus`，可用來檢查每日紀錄與試車場判定是否正常。
