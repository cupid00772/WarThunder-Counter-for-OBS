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
CONFIG_FILE = "config.json"
SERVER_PORT = 8112

# Poll interval for the 8111 tracker loop (seconds). Lower = lower kill-feed
# latency, at the cost of slightly more localhost HTTP traffic.
POLL_INTERVAL = 0.1
# How long a /mission.json "test drive" determination stays cached, so it is
# NOT re-fetched on every damage-bearing poll (that round-trip used to sit on
# the critical path before each kill was counted).
MISSION_CACHE_SEC = 2.0

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

def today_key():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def default_state():
    return {
        "dayKey": today_key(),
        "totalNukes": 0,
        "todayNukes": 0,
        "totalKills": 0,
        "todayKills": 0,
        "lastDmg": 0,
        "lastEvt": 0,
    }

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            base = default_state()
            base.update(data)
            return base
        except:
            pass
    return default_state()

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

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
        state["dayKey"] = current
        state["todayNukes"] = 0
        state["todayKills"] = 0
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

# Global state
app_state = load_state()
rotate_daily_stats(app_state)
last_nuke_time = 0
empty_poll_count = 0
first_poll_done = False
last_mission_check = 0.0
cached_is_test_drive = False

def fetch_json(path):
    try:
        conn = http.client.HTTPConnection(HOST_ADDR, HOST_PORT, timeout=0.5)
        conn.request("GET", path, headers={'Accept': 'application/json'})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return json.loads(data.decode('utf-8'))
    except Exception as e:
        return None

def tracker_loop():
    global app_state, last_nuke_time, empty_poll_count, first_poll_done
    global last_mission_check, cached_is_test_drive
    print("[Backend] Tracker started in background.")
    while True:
        try:
            # Only reload config every 50 loops (~10 seconds) to save disk I/O
            if empty_poll_count % 50 == 0:
                config = load_config()
                nuke_keyword = NUKE_KEYWORDS.get(config.get("language", "english"), NUKE_KEYWORDS["english"])
                player_name = config.get("player_name", "cupid00772")

            if rotate_daily_stats(app_state):
                save_state(app_state)

            last_evt = app_state.get("lastEvt", 0)
            last_dmg = app_state.get("lastDmg", 0)

            hud = fetch_json(f"/hudmsg?lastEvt={last_evt}&lastDmg={last_dmg}")
            if not hud:
                # War Thunder is likely closed or restarting.
                # Reset baseline so we can align properly when it comes back online.
                first_poll_done = False
                if app_state.get("lastDmg", 0) != 0:
                    app_state["lastDmg"] = 0
                    save_state(app_state)
                time.sleep(0.2)
                continue

            damage = hud.get("damage", [])
            
            if not first_poll_done:
                first_poll_done = True
                if damage:
                    max_id = max((e.get("id", 0) for e in damage if isinstance(e.get("id"), int)), default=last_dmg)
                    app_state["lastDmg"] = max_id
                    save_state(app_state)
                time.sleep(0.2)
                continue

            if damage:
                empty_poll_count = 0
                now = time.time()

                # Refresh the test-drive flag at most once every MISSION_CACHE_SEC
                # instead of fetching /mission.json on every damage-bearing poll.
                # That extra round-trip used to delay every kill from being counted.
                if (now - last_mission_check) >= MISSION_CACHE_SEC:
                    mission_data = fetch_json("/mission.json")
                    if mission_data is not None:
                        cached_is_test_drive = mission_data.get("objectives") is None
                    last_mission_check = now
                is_test_drive = cached_is_test_drive

                if is_test_drive:
                    last_entry = damage[-1]
                    if isinstance(last_entry.get("id"), int):
                        app_state["lastDmg"] = last_entry["id"]
                        save_state(app_state)
                else:
                    nuke_triggered = False
                    for entry in damage:
                        msg = entry.get("msg")
                        if not isinstance(msg, str):
                            continue
                        
                        if nuke_keyword in msg:
                            if not nuke_triggered and (now - last_nuke_time) > 10.0:
                                app_state["totalNukes"] += 1
                                app_state["todayNukes"] += 1
                                nuke_triggered = True
                                last_nuke_time = now
                                
                        if is_owned_kill_event(entry, nuke_keyword, player_name):
                            kill_count = 1
                            match = re.search(r'(?:^|\s)(\d+)x\s', msg, re.IGNORECASE)
                            if match:
                                parsed = int(match.group(1))
                                if parsed > 0:
                                    kill_count = parsed
                            
                            app_state["totalKills"] += kill_count
                            app_state["todayKills"] += kill_count

                    last_entry = damage[-1]
                    if isinstance(last_entry.get("id"), int):
                        app_state["lastDmg"] = last_entry["id"]
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
            self.wfile.write(json.dumps(app_state).encode('utf-8'))
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
                if "todayNukes" in new_state:
                    app_state["todayNukes"] = new_state["todayNukes"]
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
    threading.Thread(target=tracker_loop, daemon=True).start()
    run_server()
