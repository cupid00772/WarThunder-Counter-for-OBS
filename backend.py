import http.client
import json
import time
import os
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import re
import datetime

HOST_ADDR = "127.0.0.1"
HOST_PORT = 8111
STATE_FILE = "state.json"
DAILY_RECORDS_FILE = "daily_records.json"
CONFIG_FILE = "config.json"
SERVER_PORT = 8112

# Poll interval for the 8111 tracker loop (seconds). Lower = lower kill-feed
# latency, at the cost of slightly more localhost HTTP traffic.
POLL_INTERVAL = 0.05
# /mission.json is checked by a separate low-frequency watcher thread so the
# hot /hudmsg polling path never waits on mission metadata.
MISSION_POLL_INTERVAL = 1.0
MISSION_STALE_SEC = 10.0
# cursor 重抓 margin:每次把 lastDmg 留在「最大 id 往回 N」的位置,讓 WT 晚到 /
# 亂序、id 比 cursor 小的擊殺訊息有機會被重新抓到。重複的靠 _mark_seen 去重,
# 所以重抓不會多算。這是修「殺太快漏算」的核心。
DMG_REFETCH_MARGIN = 40
# === FIX (2026-05-30) ===
# 連續抓不到 /hudmsg 幾次,才把它當成「WT 真的關了 / 換場」而重置 baseline。
# 舊版只要「單次」抓不到 (poll timeout / WT 卡頓一下) 就重置 first_poll_done +
# lastDmg=0,導致重連後把「當下 kill feed 裡正在跑的擊殺」整批當成 baseline
# (skipped=baseline_seen) 吞掉 → 連殺 / 爆發擊殺漏算 (例:AH-64E 12 秒 10 殺
# 只算到 5)。改成連續失敗 N 次才重置;單次卡頓不動 baseline。
# N * 0.2s(失敗路徑 sleep) ≈ 2 秒;真的關遊戲會持續失敗,很快就會跨過門檻。
HUD_FAIL_RESET_THRESHOLD = 10
LOG_DIR = "logs"
# debug 記錄檔:config.json 設 "debug": true 時,會把 8111 原始回傳與程式
# 判定結果都寫到 logs/ 底下,方便事後比對到底哪一段出問題。
DEBUG_RAW_LOG_FILE = os.path.join(LOG_DIR, "8111.log")
DEBUG_LOG_FILE = os.path.join(LOG_DIR, "debug_kills.log")

NUKE_KEYWORDS = {
    "english": "Doomsday!",
    "french": "Apocalypse!",
    "german": "Tag des jüngsten Gerichts!",
    "russian": "Судный день!",
    "chinese": "末\t日\t审\t判！",
    "hchinese": "Doomsday!",
    "czech": "Soudný den!",
    "polish": "Dzień zagłady!",
    "romanian": "Doomsday!",
    "italian": "Apocalisse!",
    "portuguese": "Dia do Juízo Final!",
    "korean": "최후의 심판",
    "serbian": "Doomsday!",
    "belarusian": "Судны дзень!",
}

ACTION_KEYWORDS = [
    "destroyed", "shot down", "has crashed",
    "zerstört", "abgeschossen",
    "détruit", "abattu",
    "уничтожен", "сбит",
    "摧毀", "擊落",
    "zničil", "sestřelil",
    "zniszczono", "zestrzelony",
    "distrus", "doborât",
    "distrutto", "abbattuto",
    "destruído", "abatido",
    "격파", "격추",
    "uništen", "oboren",
    "знішчаны", "збіты",
]

# 這些訊息常見於「有被打掉某個子單元，但遊戲本身不算死亡」的情況。
# 先用關鍵字排除，避免 recon drone、分體防空的發射車/雷達車被誤算成死亡。
DEFAULT_IGNORED_DEATH_KEYWORDS = [
    "recon drone",
    "reconnaissance drone",
    "偵察無人機",
    "無人偵察機",
    "launcher",
    "發射車",
    "radar",
    "雷達車",
    "zala",          # ZALA 421-16 等偵察 UAV,墜毀不算死亡 (2026-05-30 神槍要求)
]

# === 分體防空 (Multi-Vehicle SAM) 死亡計數設定 (2026-05-30) ===
# 一套分體防空 = 1 台雷達車 (TADS) + 2 台發射車。被打掉時 kill feed 會噴 2~3 行
# (每個子載具各一行),若每行都算一次死亡就會多算。下表把每個子載具的「車種片段」
# 對應到「哪一套系統 + 是雷達車還是發射車」,搭配 split_spaa_state 狀態機 + latch,
# 讓同一條命只算一次死亡。
#
# 類別 (SPLIT_SPAA_CATEGORY):
#   1 = 發射車自帶追蹤雷達 (Buk-M3, Tan-SAM kai)
#       → 發射車全死 算死;或「雷達死 且 已掉至少一台發射車」也算死。
#         雷達『單獨』死、發射車都還在 → 不算 (還能用發射車打)。
#   2 = 需要雷達車才能作戰 (其餘 6 套)
#       → 雷達死 或 發射車全死 都算死。
#
# 新增系統時:在 SPLIT_SPAA_VEHICLES 補子載具車種片段、在 SPLIT_SPAA_CATEGORY 設
# 類別即可。match 是對 kill feed 訊息做「子字串」比對 (大小寫敏感,照遊戲顯示填)。
SPLIT_SPAA_LAUNCHER_TOTAL = 2
SPLIT_SPAA_VEHICLES = [
    # --- 一類 (發射車自帶雷達,雷達死不算) ---
    {"match": "9S18M3",                 "system": "buk",      "role": "radar"},
    {"match": "9A317M",                 "system": "buk",      "role": "launcher"},
    {"match": "81 Shiki (C) Sha Tō Sō", "system": "tansam",   "role": "radar"},     # ★ 角色待確認
    {"match": "81 Shiki (C) Kadaibu",   "system": "tansam",   "role": "launcher"},  # ★ 角色待確認
    # --- 二類 (雷達死 或 發射車全死 都算) ---
    {"match": "SAMP/T (MRI)",           "system": "sampt",    "role": "radar"},
    {"match": "SAMP/T (MLT)",           "system": "sampt",    "role": "launcher"},
    {"match": "Sha Rēda",               "system": "type03",   "role": "radar"},
    {"match": "Has Sō",                 "system": "type03",   "role": "launcher"},
    {"match": "Giraffe AMB",            "system": "skysabre", "role": "radar"},
    {"match": "Land Ceptor",            "system": "skysabre", "role": "launcher"},
    {"match": "Radarfahrzeug",          "system": "irist",    "role": "radar"},
    {"match": "Startfahrzeug",          "system": "irist",    "role": "launcher"},
    {"match": "AN/MPQ-64",              "system": "nasams",   "role": "radar"},   # NASAMS 3 / CLAWS 共用 Sentinel 雷達
    {"match": "NASAMS 3",               "system": "nasams",   "role": "launcher"},
    {"match": "SLAMRAAM",               "system": "nasams",   "role": "launcher"},  # M1097A2 (SLAMRAAM) = CLAWS
]
SPLIT_SPAA_CATEGORY = {
    "buk": 1, "tansam": 1,
    "sampt": 2, "type03": 2, "skysabre": 2, "irist": 2, "nasams": 2,
}

def classify_split_spaa(msg, player_name):
    """若 msg 是玩家某套分體防空子載具的死亡,回傳 (system, role);否則 None。
    只比對玩家名稱之後的車種標籤,避免誤抓擊殺者(對手)的載具。"""
    if not isinstance(msg, str) or not player_name:
        return None
    low = msg.lower()
    pidx = low.find(player_name.lower())
    scope = msg[pidx:] if pidx >= 0 else msg
    for v in SPLIT_SPAA_VEHICLES:
        if v["match"] in scope:
            return (v["system"], v["role"])
    return None

def split_unit_should_count(category, radar_dead, launchers_dead,
                            launcher_total=SPLIT_SPAA_LAUNCHER_TOTAL):
    """這套分體防空現在算不算「一次死亡」(尚未含 latch,latch 由呼叫端管)。"""
    all_launchers_dead = launchers_dead >= launcher_total
    if category == 1:
        # 一類:發射車全死才算;或「雷達死 且 已至少掉一台發射車」也算。
        # (2026-05-30 神槍回報:發射車死後雷達死要算死;但雷達『單獨』死、發射車
        #  都還在,則不算 — 因為發射車自帶雷達還能打。launchers_dead>=1 這個條件就是
        #  用來區分這兩種:雷達單獨自爆 (launchers_dead==0) → 不算。)
        return all_launchers_dead or (radar_dead and launchers_dead >= 1)
    return radar_dead or all_launchers_dead     # 二類:雷達死 或 發射車全死

def process_split_death(state, sys_key, role):
    """處理一筆分體防空子載具死亡:更新 state[sys_key] 狀態機,回傳這筆是否算一次死亡。
    tracker loop 與單元測試共用同一份邏輯(避免 loop 與 test 各寫一份漂走)。

    state: dict,system → {radarDead, launchersDead, counted}
    role : 'radar' / 'launcher'
    """
    unit = state.setdefault(
        sys_key, {"radarDead": False, "launchersDead": 0, "counted": False}
    )
    # 偵測「新的一條命」(2026-05-30 修):一套分體防空一條命只有 1 雷達 + 2 發射車。
    # 若這次死亡會超過該命容量(雷達已死又再死、或第 3 台發射車死),代表玩家已重生
    # 這套 → 重置狀態機,讓新命的死亡能重新計。原本 latch 只在換場/跳過計數時重置,
    # 同場重生再死會被永久鎖住 → 死亡不計 (神槍回報的根因)。
    is_new_life = (
        (role == "radar" and unit["radarDead"]) or
        (role == "launcher" and unit["launchersDead"] >= SPLIT_SPAA_LAUNCHER_TOTAL)
    )
    if is_new_life:
        unit["radarDead"] = False
        unit["launchersDead"] = 0
        unit["counted"] = False
    if role == "radar":
        unit["radarDead"] = True
    else:
        unit["launchersDead"] += 1
    if not unit["counted"] and split_unit_should_count(
        SPLIT_SPAA_CATEGORY.get(sys_key, 2),
        unit["radarDead"],
        unit["launchersDead"],
    ):
        unit["counted"] = True
        return True
    return False

def today_key():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def default_state():
    return {
        "dayKey": today_key(),
        "totalNukes": 0,
        "todayNukes": 0,
        "totalKills": 0,
        "todayKills": 0,
        "totalDeaths": 0,
        "todayDeaths": 0,
        "lastDmg": 0,
        "lastEvt": 0,
    }

def load_daily_records():
    if os.path.exists(DAILY_RECORDS_FILE):
        try:
            with open(DAILY_RECORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("dailyRecords", [])
            if isinstance(data, list):
                return data
        except:
            pass
    return []

def save_daily_records(records):
    cleaned = []

    def to_int(value):
        try:
            return int(value)
        except Exception:
            return 0

    for record in records[-60:]:
        if not isinstance(record, dict):
            continue
        date = record.get("date")
        if not isinstance(date, str) or not date:
            continue
        cleaned.append({
            "date": date,
            "kills": to_int(record.get("kills", 0)),
            "deaths": to_int(record.get("deaths", 0)),
        })

    with open(DAILY_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            base = default_state()
            legacy_daily_records = []
            if isinstance(data, dict):
                legacy_daily_records = data.pop("dailyRecords", [])
            base.update(data)
            if isinstance(legacy_daily_records, list) and legacy_daily_records and not os.path.exists(DAILY_RECORDS_FILE):
                save_daily_records(legacy_daily_records)
            return base
        except:
            pass
    return default_state()

def save_state(state):
    state_to_save = {k: v for k, v in state.items() if k != "dailyRecords"}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state_to_save, f, ensure_ascii=False, indent=2)

def append_daily_record(state):
    records = state.get("dailyRecords")
    if not isinstance(records, list):
        records = []
        state["dailyRecords"] = records

    def to_int(value):
        try:
            return int(value)
        except Exception:
            return 0

    day_key = state.get("dayKey")
    if not isinstance(day_key, str) or not day_key:
        day_key = today_key()

    record = {
        "date": day_key,
        "kills": to_int(state.get("todayKills", 0)),
        "deaths": to_int(state.get("todayDeaths", 0)),
    }

    if records:
        last_record = records[-1]
        if (
            isinstance(last_record, dict)
            and last_record.get("date") == record["date"]
            and to_int(last_record.get("kills", -1)) == record["kills"]
            and to_int(last_record.get("deaths", -1)) == record["deaths"]
        ):
            return

    records.append(record)
    if len(records) > 60:
        del records[:-60]
    save_daily_records(records)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    cfg = {"player_name": "cupid00772", "language": "english"}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg

def rotate_daily_stats(state):
    current = today_key()
    if state.get("dayKey") != current:
        append_daily_record(state)
        state["dayKey"] = current
        state["todayNukes"] = 0
        state["todayKills"] = 0
        state["todayDeaths"] = 0
        return True
    return False

def normalize_text(text):
    if not text:
        return ""
    # Simplified normalization (lower and remove spaces)
    return re.sub(r'\s+', '', text.lower())

def matches_player_name(name, player_name):
    return normalize_text(player_name) in normalize_text(name)

def extract_killer_name(msg):
    for keyword in ACTION_KEYWORDS:
        idx = msg.find(keyword)
        if idx >= 0:
            before = msg[:idx].strip()
            # Remove vehicle tag like "(F-15E)"
            v_start = before.rfind("(")
            if v_start >= 0:
                return before[:v_start].strip()
            return before
    return None

def extract_victim_name(msg):
    if "has been wrecked" in msg or "has crashed" in msg:
        idx = msg.find("has been wrecked")
        if idx == -1:
            idx = msg.find("has crashed")
        before = msg[:idx].strip()
        v_start = before.rfind("(")
        if v_start >= 0:
            return before[:v_start].strip()
        return before

    for keyword in ACTION_KEYWORDS:
        idx = msg.find(keyword)
        if idx >= 0:
            after = msg[idx + len(keyword):].strip()
            v_start = after.rfind("(")
            if v_start >= 0:
                return after[:v_start].strip()
            return after
    return None

def is_owned_kill_event(entry, nuke_keyword, player_name):
    msg = entry.get("msg")
    if not isinstance(msg, str):
        return False
    if nuke_keyword in msg:
        return False
    if "has been wrecked" in msg or "has crashed" in msg:
        return False

    has_action = any(k in msg for k in ACTION_KEYWORDS)
    if not has_action:
        return False

    sender = entry.get("sender")
    if isinstance(sender, str) and sender.strip() and matches_player_name(sender, player_name):
        return True

    killer = extract_killer_name(msg)
    if killer and matches_player_name(killer, player_name):
        return True

    return False

def is_owned_death_event(entry, nuke_keyword, player_name, ignored_keywords=None):
    msg = entry.get("msg")
    if not isinstance(msg, str):
        return False
    if nuke_keyword in msg:
        return False

    normalized_msg = msg.lower()
    for keyword in (ignored_keywords or []):
        if isinstance(keyword, str) and keyword.strip() and keyword.lower() in normalized_msg:
            return False

    victim = extract_victim_name(msg)
    if victim and matches_player_name(victim, player_name):
        return True

    return False

# Global state
app_state = load_state()
app_state["dailyRecords"] = load_daily_records()
rotate_daily_stats(app_state)
last_nuke_time = 0
empty_poll_count = 0
first_poll_done = False
cached_is_test_drive = False
cached_mission_status = None
cached_mission_updated_at = 0.0
last_config_load = 0.0
# 連續抓不到 /hudmsg 的次數 (FIX 2026-05-30):用來區分「WT 卡頓一下」與
# 「WT 真的關了」。只有跨過 HUD_FAIL_RESET_THRESHOLD 才重置 baseline。
# (2026-06-02 起改用 connection-refused 偵測,hud_fail_count 已不再觸發 baseline 重置)
hud_fail_count = 0
# === FIX (2026-06-02) — 漏抓 kill 根因修正 ===
# last_request_refused:上一次 fetch_json 是否因 ConnectionRefusedError 失敗。
#   8111 沒在聽 = War Thunder 真的關了;單純 timeout 則代表遊戲還開著只是卡頓。
#   兩者在 Python 是不同例外 (ConnectionRefusedError vs TimeoutError),可明確區分。
# game_was_off:是否曾偵測到遊戲關閉。連回來時代表是新一場 session、hudmsg id 已
#   reset → 需清掉 seen 去重狀態並重新 baseline 一次,否則新 id 會跟舊 session 撞號
#   被誤判成「看過」而漏算。
last_request_refused = False
game_was_off = False
# 已計分的 damage entry id,避免 cursor 重抓時同一筆擊殺被重複計數。
seen_dmg_ids = set()
seen_dmg_order = []
# 分體防空狀態機:system → {radarDead, launchersDead, counted}。一條命算一次,
# counted 為 latch;換場 (mission_status 離開 running) 時 clear,讓下一場重新計。
split_spaa_state = {}

def _mark_seen(entry_id):
    """回傳 True 代表這是新的 id (該計分);False 代表已看過 (跳過)。"""
    if entry_id in seen_dmg_ids:
        return False
    seen_dmg_ids.add(entry_id)
    seen_dmg_order.append(entry_id)
    if len(seen_dmg_order) > 1000:
        for old in seen_dmg_order[:200]:
            seen_dmg_ids.discard(old)
        del seen_dmg_order[:200]
    return True

DEBUG = False

os.makedirs(LOG_DIR, exist_ok=True)

raw_damage_by_id = {}
debug_by_id = {}

def _debug_log(line):
    # Store lines keyed by id when possible; fall back to append for non-id lines.
    if not DEBUG:
        return
    try:
        # Try to extract id=<num> at start of line
        m = None
        try:
            m = re.match(r"\s*id=(\d+)", line)
        except Exception:
            m = None
        if m:
            try:
                eid = int(m.group(1))
                # 保留每個 id「第一次」的判定 (counted/died / baseline_seen /
                # test_drive),不被之後 margin 重抓的 seen_before 覆蓋,
                # 才看得出死亡到底卡在哪一關 (2026-05-30 診斷分體防空死亡不計)。
                if eid not in debug_by_id:
                    debug_by_id[eid] = line
                    _rewrite_debug_log()
                return
            except Exception:
                pass
        # fallback: append raw line
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def _rewrite_debug_log():
    try:
        ordered = [debug_by_id[k] for k in sorted(debug_by_id)]
        with open(DEBUG_LOG_FILE, "w", encoding="utf-8") as f:
            for line in ordered:
                f.write(line + "\n")
    except Exception:
        pass

def _debug_skip_log(entry_id, reason, msg=None, extra=None):
    if not DEBUG:
        return
    parts = []
    if isinstance(entry_id, int):
        parts.append(f"id={entry_id}")
    else:
        parts.append("id=?")
    parts.append(f"skipped={reason}")
    if extra:
        parts.append(extra)
    if isinstance(msg, str) and msg:
        parts.append(f"| {msg}")
    _debug_log(" ".join(parts))

def _rewrite_raw_damage_log():
    try:
        ordered_items = [raw_damage_by_id[entry_id] for entry_id in sorted(raw_damage_by_id)]
        with open(DEBUG_RAW_LOG_FILE, "w", encoding="utf-8") as f:
            f.write('"damage":[\n')
            for index, item in enumerate(ordered_items):
                suffix = "," if index < len(ordered_items) - 1 else ""
                f.write(
                    "  "
                    + json.dumps(item, ensure_ascii=False, separators=(", ", ": "))
                    + suffix
                    + "\n"
                )
            f.write("]")
    except Exception:
        pass

def _debug_raw_log(line):
    if not DEBUG:
        return
    try:
        with open(DEBUG_RAW_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def _flatten_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_strings(item)

def is_test_drive_mission(mission_data):
    if not isinstance(mission_data, dict):
        return False
    text = " ".join(_flatten_strings(mission_data)).lower()
    test_keywords = (
        "test drive",
        "test flight",
        "test sail",
        "test_drive",
        "test_flight",
        "testdrive",
        "testflight",
        "試車",
        "試飛",
        "试车",
        "试飞",
    )
    return any(keyword in text for keyword in test_keywords)

def is_cached_test_drive_active():
    return cached_is_test_drive and (time.time() - cached_mission_updated_at) <= MISSION_STALE_SEC

def fetch_json_quiet(path, timeout=0.3):
    try:
        conn = http.client.HTTPConnection(HOST_ADDR, HOST_PORT, timeout=timeout)
        conn.request("GET", path, headers={'Accept': 'application/json'})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return json.loads(data.decode('utf-8', errors='replace'))
    except Exception:
        return None

def mission_loop():
    global cached_is_test_drive, cached_mission_status, cached_mission_updated_at
    print("[Backend] Mission watcher started in background.")
    while True:
        mission_data = fetch_json_quiet("/mission.json", timeout=0.3)
        if isinstance(mission_data, dict):
            cached_mission_status = mission_data.get("status")
            cached_is_test_drive = is_test_drive_mission(mission_data)
            cached_mission_updated_at = time.time()
        time.sleep(MISSION_POLL_INTERVAL)

def fetch_json(path):
    global last_request_refused
    last_request_refused = False
    try:
        conn = http.client.HTTPConnection(HOST_ADDR, HOST_PORT, timeout=0.15)
        conn.request("GET", path, headers={'Accept': 'application/json'})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        last_request_refused = False
        raw_text = data.decode('utf-8', errors='replace')
        if DEBUG:
            if path.startswith("/hudmsg"):
                request_url = f"http://{HOST_ADDR}:{HOST_PORT}{path}"
                try:
                    parsed = json.loads(raw_text)
                except Exception as parse_error:
                    _debug_raw_log(
                        f"url={request_url} parse_error={type(parse_error).__name__}: {parse_error} | body={raw_text}"
                    )
                    return None

                damage = parsed.get("damage", []) if isinstance(parsed, dict) else []
                raw_items = []
                if isinstance(damage, list):
                    for entry in damage:
                        if isinstance(entry, dict):
                            raw_items.append(dict(entry))
                if not raw_items:
                    return parsed
                raw_items.sort(key=lambda item: item.get("id", 0))
                new_ids = False
                for raw_item in raw_items:
                    entry_id = raw_item.get("id")
                    if not isinstance(entry_id, int):
                        continue
                    if entry_id in raw_damage_by_id:
                        continue
                    raw_damage_by_id[entry_id] = raw_item
                    new_ids = True
                _rewrite_raw_damage_log()
            else:
                parsed = json.loads(raw_text)
                _debug_raw_log(
                    f"url=http://{HOST_ADDR}:{HOST_PORT}{path}\n{json.dumps(parsed, ensure_ascii=False, indent=2)}"
                )
        else:
            parsed = json.loads(raw_text)
        return parsed
    except ConnectionRefusedError:
        # 8111 沒在聽 = War Thunder 沒開/已關閉 (與單純 timeout 卡頓區分開來)。
        last_request_refused = True
        return None
    except Exception as e:
        return None

def tracker_loop():
    global app_state, last_nuke_time, empty_poll_count, first_poll_done
    global last_config_load, DEBUG
    global hud_fail_count, game_was_off
    print("[Backend] Tracker started in background.")
    # 先載入一次 config (之後每 ~10 秒才重載,不再每個 damage poll 都讀檔)
    config = load_config()
    nuke_keyword = NUKE_KEYWORDS.get(config.get("language", "english"), NUKE_KEYWORDS["english"])
    player_name = config.get("player_name", "cupid00772")
    DEBUG = bool(config.get("debug", False))
    ignored_death_keywords = config.get("ignored_death_keywords", DEFAULT_IGNORED_DEATH_KEYWORDS)
    while True:
        try:
            now0 = time.time()
            if (now0 - last_config_load) >= 10.0:
                config = load_config()
                nuke_keyword = NUKE_KEYWORDS.get(config.get("language", "english"), NUKE_KEYWORDS["english"])
                player_name = config.get("player_name", "cupid00772")
                DEBUG = bool(config.get("debug", False))
                ignored_death_keywords = config.get("ignored_death_keywords", DEFAULT_IGNORED_DEATH_KEYWORDS)
                last_config_load = now0

            if rotate_daily_stats(app_state):
                save_state(app_state)

            last_evt = app_state.get("lastEvt", 0)
            last_dmg = app_state.get("lastDmg", 0)

            hud = fetch_json(f"/hudmsg?lastEvt={last_evt}&lastDmg={last_dmg}")
            if not hud:
                # === FIX (2026-06-02) ===
                # 只把「connection refused」(8111 沒在聽 = 遊戲真的關了) 當重置信號。
                # 單純 timeout 卡頓時遊戲還開著、hudmsg id 連續,**不動 baseline**,
                # 靠 seen_dmg_ids 去重續算,避免把卡頓期間正在跑的連殺整批當 baseline
                # 吞掉 — 這是舊版「連續 N 次任意失敗就重 baseline」的漏算根因。
                if last_request_refused:
                    game_was_off = True
                time.sleep(POLL_INTERVAL)
                continue

            # === FIX (2026-06-02) ===
            # 曾偵測到遊戲關閉 (refused) 後又連回來 → 是新的一場 session,War Thunder
            # 的 hudmsg id 會從頭 reset。舊的 seen 清單會跟新 session 的低 id 撞號 →
            # 把新擊殺誤判成「看過」而漏算。所以清掉去重狀態 + 強制重新 baseline 一次,
            # 對齊新 session。同場 timeout 卡頓不會走到這裡 (那條路徑不重置)。
            if game_was_off:
                seen_dmg_ids.clear()
                del seen_dmg_order[:]
                split_spaa_state.clear()
                first_poll_done = False
                app_state["lastDmg"] = 0
                game_was_off = False

            damage = hud.get("damage", [])

            if not first_poll_done:
                first_poll_done = True
                if damage and app_state.get("lastDmg", 0) <= 0:
                    # baseline:把目前已存在的歷史 damage 全部標記為已看過,
                    # 這樣之後 margin 重抓重新拉到它們時不會被當成新擊殺計分。
                    for e in damage:
                        eid = e.get("id")
                        if isinstance(eid, int):
                            _mark_seen(eid)
                            if DEBUG:
                                _debug_skip_log(eid, "baseline_seen", e.get("msg"))
                    max_id = max((e.get("id", 0) for e in damage if isinstance(e.get("id"), int)), default=last_dmg)
                    app_state["lastDmg"] = max_id
                    save_state(app_state)
                    time.sleep(0.2)
                    continue

            if damage:
                empty_poll_count = 0
                now = time.time()

                # cursor 取整批最大 id (不假設陣列末筆就是最大,避免 WT 回傳順序
                # 不固定時 cursor 亂跳)
                max_id = max(
                    (e.get("id", 0) for e in damage if isinstance(e.get("id"), int)),
                    default=app_state.get("lastDmg", 0),
                )

                if is_cached_test_drive_active():
                    # 試車/試飛場不計分,但仍把 id 標記已看過,避免離開試車場後
                    # margin 重抓時把試車場擊殺補算進正式統計。
                    split_spaa_state.clear()
                    for e in damage:
                        eid = e.get("id")
                        if isinstance(eid, int):
                            _mark_seen(eid)
                            if DEBUG:
                                _debug_skip_log(eid, "test_drive", e.get("msg"))
                    app_state["lastDmg"] = max_id
                    save_state(app_state)
                else:
                    nuke_triggered = False
                    for entry in damage:
                        msg = entry.get("msg")
                        if not isinstance(msg, str):
                            continue

                        # id 去重:cursor 重抓同一筆時不重複計分。沒有 int id 的就照算
                        # (寧可偶爾重複也不漏;有 id 的才 dedup)。
                        eid = entry.get("id")
                        is_new = (not isinstance(eid, int)) or _mark_seen(eid)
                        if not is_new:
                            if DEBUG:
                                _debug_skip_log(eid, "seen_before", msg)
                            continue

                        if nuke_keyword in msg:
                            if not nuke_triggered:
                                app_state["totalNukes"] += 1
                                app_state["todayNukes"] += 1
                                nuke_triggered = True
                                last_nuke_time = now

                        owned = is_owned_kill_event(entry, nuke_keyword, player_name)
                        if owned:
                            kill_count = 1
                            match = re.search(r'(?:^|\s)(\d+)x\s', msg, re.IGNORECASE)
                            if match:
                                parsed = int(match.group(1))
                                if parsed > 0:
                                    kill_count = parsed

                            app_state["totalKills"] = app_state.get("totalKills", 0) + kill_count
                            app_state["todayKills"] = app_state.get("todayKills", 0) + kill_count

                        # === 分體防空死亡計數 (2026-05-30) ===
                        # 一套分體防空被打掉會噴 2~3 行 (雷達車 + 2 發射車各一行),
                        # 舊版每行都 +1 死 → 多算。改判定:若這行是玩家某套分體防空
                        # 子載具的死亡 → 進該套狀態機,只有「整套判定死亡」第一次成立
                        # 時才 +1 (latch),後續同套子載具死亡 / 自動清場行都忽略。
                        # 不是分體防空的一般載具 → 維持原本逐筆 1:1 計死。
                        died = False
                        victim = extract_victim_name(msg)
                        victim_is_me = (
                            nuke_keyword not in msg
                            and victim is not None
                            and matches_player_name(victim, player_name)
                        )
                        split_info = classify_split_spaa(msg, player_name) if victim_is_me else None
                        if split_info is not None:
                            sys_key, role = split_info
                            died = process_split_death(split_spaa_state, sys_key, role)
                        else:
                            died = is_owned_death_event(entry, nuke_keyword, player_name, ignored_death_keywords)

                        if died:
                            app_state["totalDeaths"] = app_state.get("totalDeaths", 0) + 1
                            app_state["todayDeaths"] = app_state.get("todayDeaths", 0) + 1

                        if DEBUG:
                            _debug_log(
                                f"id={eid} counted={owned} died={died} kill_count={kill_count if owned else 0} | {msg}"
                            )

                    # cursor 留 margin:不要直接跳到 max_id,而是退回 DMG_REFETCH_MARGIN,
                    # 讓晚到/亂序、id 較小的擊殺訊息下一輪還抓得到 (去重防重複)。
                    app_state["lastDmg"] = max(0, max_id - DMG_REFETCH_MARGIN)
                    save_state(app_state)

            else:
                empty_poll_count += 1
                if empty_poll_count >= 5 and app_state.get("lastDmg", 0) > 10000:
                    app_state["lastDmg"] = 0
                    save_state(app_state)
                    empty_poll_count = 0

        except Exception as e:
            # print(f"Error in poll: {e}")
            pass

        time.sleep(POLL_INTERVAL)

class StateHandler(BaseHTTPRequestHandler):
    def address_string(self):
        # Disable reverse DNS lookup to fix massive 1-2 second blocking delays on Windows!
        return self.client_address[0]

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/state':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            payload = dict(app_state)
            payload["dailyRecords"] = load_daily_records()
            payload["isTestDrive"] = is_cached_test_drive_active()
            payload["missionStatus"] = cached_mission_status
            self.wfile.write(json.dumps(payload).encode('utf-8'))
        elif self.path == '/daily-records':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(load_daily_records()).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/update':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                new_state = json.loads(post_data.decode('utf-8'))
                if "totalKills" in new_state:
                    app_state["totalKills"] = new_state["totalKills"]
                if "totalNukes" in new_state:
                    app_state["totalNukes"] = new_state["totalNukes"]
                if "todayKills" in new_state:
                    app_state["todayKills"] = new_state["todayKills"]
                if "todayDeaths" in new_state:
                    app_state["todayDeaths"] = new_state["todayDeaths"]
                if "todayNukes" in new_state:
                    app_state["todayNukes"] = new_state["todayNukes"]
                if "totalDeaths" in new_state:
                    app_state["totalDeaths"] = new_state["totalDeaths"]
                save_state(app_state)

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Disable logging to keep console clean

def run_server():
    # ThreadingHTTPServer so the overlay's rapid /state polls never queue behind
    # one another (single-threaded HTTPServer could add jitter to the display).
    server = ThreadingHTTPServer(('', SERVER_PORT), StateHandler)
    print(f"[Backend] Server listening on port {SERVER_PORT}")
    server.serve_forever()

if __name__ == '__main__':
    threading.Thread(target=mission_loop, daemon=True).start()
    threading.Thread(target=tracker_loop, daemon=True).start()
    run_server()
