(function () {
    const HOST = "http://localhost:8111";
    const TOTAL_KILL_ID = "total-kill";
    const TOTAL_NUKE_ID = "total-nuke";
    const TODAY_KILL_ID = "today-kill";
    const TODAY_NUKE_ID = "today-nuke";
    const TOTAL_DEATH_ID = "total-death";
    const TODAY_DEATH_ID = "today-death";
    const TOTAL_KD_ID = "total-kd";
    const TODAY_KD_ID = "today-kd";

    const STORAGE_STATE = "thunder_overlay.nuke_counter.state";
    const LEGACY_STORAGE_COUNT = "thunder_overlay.nuke_counter.count";
    const LEGACY_STORAGE_LAST_DMG = "thunder_overlay.nuke_counter.last_dmg";
    const STORAGE_LANG = "thunder_overlay.nuke_counter.lang";
    const STORAGE_PLAYER = "thunder_overlay.nuke_counter.player";
    const DEFAULT_PLAYER = "cupid00772";

    // 連殺視窗 (ms):距上一個擊殺超過這個時間就開新一輪 (+1 重新數);
    // 視窗內持續擊殺 → 同一泡泡累加 +2 +3 ... 並重置消失計時。可自行調整。
    const COMBO_WINDOW_MS = 2500;

    const NUKE_KEYWORDS = {
        english: "Doomsday!",
        french: "Apocalypse!",
        german: "Tag des jüngsten Gerichts!",
        russian: "Судный день!",
        chinese: "末\t日\t审\t判！",
        hchinese: "Doomsday!",
        czech: "Soudný den!",
        polish: "Dzień zagłady!",
        romanian: "Doomsday!",
        italian: "Apocalisse!",
        portuguese: "Dia do Juízo Final!",
        korean: "최후의 심판",
        serbian: "Doomsday!",
        belarusian: "Судны дзень!",
    };

    // All known War Thunder action verbs that indicate a kill/damage event
    const ACTION_KEYWORDS = [
        // English
        "destroyed", "shot down", "has crashed",
        // German
        "zerstört", "abgeschossen",
        // French
        "détruit", "abattu",
        // Russian
        "уничтожен", "сбит",
        // Chinese
        "摧毀", "擊落",
        // Czech
        "zničil", "sestřelil",
        // Polish
        "zniszczono", "zestrzelony",
        // Romanian
        "distrus", "doborât",
        // Italian
        "distrutto", "abbattuto",
        // Portuguese
        "destruído", "abatido",
        // Korean
        "격파", "격추",
        // Serbian
        "uništen", "oboren",
        // Belarusian
        "знішчаны", "збіты",
    ];

    function readNumber(rawValue, fallback) {
        const parsed = Number.parseInt(rawValue || "", 10);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function todayKey() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    function defaultState() {
        return {
            dayKey: todayKey(),
            totalNukes: 0,
            todayNukes: 0,
            totalKills: 0,
            todayKills: 0,
            totalDeaths: 0,
            todayDeaths: 0,
            lastDmg: 0,
            lastEvt: 0,
        };
    }

    function readState() {
        const raw = localStorage.getItem(STORAGE_STATE);
        if (raw) {
            try {
                const parsed = JSON.parse(raw);
                const base = defaultState();
                return {
                    ...base,
                    ...parsed,
                    dayKey: typeof parsed.dayKey === "string" ? parsed.dayKey : base.dayKey,
                    totalNukes: readNumber(String(parsed.totalNukes ?? ""), base.totalNukes),
                    todayNukes: readNumber(String(parsed.todayNukes ?? ""), base.todayNukes),
                    totalKills: readNumber(String(parsed.totalKills ?? ""), base.totalKills),
                    todayKills: readNumber(String(parsed.todayKills ?? ""), base.todayKills),
                    totalDeaths: readNumber(String(parsed.totalDeaths ?? ""), base.totalDeaths),
                    todayDeaths: readNumber(String(parsed.todayDeaths ?? ""), base.todayDeaths),
                    lastDmg: readNumber(String(parsed.lastDmg ?? ""), base.lastDmg),
                    lastEvt: readNumber(String(parsed.lastEvt ?? ""), base.lastEvt),
                };
            } catch (_e) {
                // fall through to legacy/default state
            }
        }

        // migration from legacy keys
        const migrated = defaultState();
        migrated.totalNukes = readNumber(localStorage.getItem(LEGACY_STORAGE_COUNT), 0);
        migrated.lastDmg = readNumber(localStorage.getItem(LEGACY_STORAGE_LAST_DMG), 0);
        migrated.todayNukes = migrated.totalNukes;
        return migrated;
    }

    function writeState(state) {
        localStorage.setItem(STORAGE_STATE, JSON.stringify(state));
    }

    function rotateDailyStats(state) {
        const currentDay = todayKey();
        if (state.dayKey !== currentDay) {
            state.dayKey = currentDay;
            state.todayNukes = 0;
            state.todayKills = 0;
            state.todayDeaths = 0;
        }
    }

    function getKeyword() {
        const params = new URLSearchParams(document.location.search);
        const override = params.get("keyword");
        if (override) {
            return override;
        }

        const lang = params.get("lang") || localStorage.getItem(STORAGE_LANG) || "english";
        localStorage.setItem(STORAGE_LANG, lang);
        return NUKE_KEYWORDS[lang] || NUKE_KEYWORDS.english;
    }



    function getPlayerName() {
        const params = new URLSearchParams(document.location.search);
        const override = params.get("player");
        if (override) {
            localStorage.setItem(STORAGE_PLAYER, override);
            return override;
        }

        return localStorage.getItem(STORAGE_PLAYER) || DEFAULT_PLAYER;
    }

    function normalizeText(value) {
        return value
            .normalize("NFKD")
            .replace(/[\p{Mn}\p{Me}\p{Cf}]/gu, "")
            .replace(/\s+/g, "")
            .replace(/[\p{P}\p{S}]/gu, "")
            .toLowerCase();
    }

    function extractKillerName(message) {
        for (var i = 0; i < ACTION_KEYWORDS.length; i++) {
            var keyword = ACTION_KEYWORDS[i];
            var keywordIndex = message.indexOf(keyword);
            if (keywordIndex < 0) {
                continue;
            }

            var beforeKeyword = message.slice(0, keywordIndex).trimEnd();
            // Remove vehicle tag e.g. "(F-15E)"
            var vehicleStart = beforeKeyword.lastIndexOf("(");
            if (vehicleStart < 0) {
                return beforeKeyword.trim();
            }

            return beforeKeyword.slice(0, vehicleStart).trimEnd();
        }

        return null;
    }

    function matchesPlayerName(name, playerName) {
        return normalizeText(name).endsWith(normalizeText(playerName));
    }

    function isOwnedKillEvent(entry, nukeKeyword, playerName) {
        if (typeof entry?.msg !== "string") {
            return false;
        }

        var msg = entry.msg;

        // Skip nuke messages
        if (msg.includes(nukeKeyword)) {
            return false;
        }

        // Skip "has been wrecked" / "has crashed" (self-destruct, not a kill by player)
        if (msg.includes("has been wrecked") || msg.includes("has crashed")) {
            return false;
        }

        // Check if any action keyword is present
        var hasAction = false;
        for (var i = 0; i < ACTION_KEYWORDS.length; i++) {
            if (msg.includes(ACTION_KEYWORDS[i])) {
                hasAction = true;
                break;
            }
        }
        if (!hasAction) {
            return false;
        }

        // Check sender field first
        if (typeof entry.sender === "string" && entry.sender.length > 0 && matchesPlayerName(entry.sender, playerName)) {
            return true;
        }

        // Fall back to parsing the killer name from the message text
        var killerName = extractKillerName(msg);
        return killerName !== null && matchesPlayerName(killerName, playerName);
    }

    function setTextAndScale(id, text) {
        const element = document.getElementById(id);
        if (!element) {
            return;
        }

        element.textContent = text;
        
        // Dynamically scale down font size for long numbers
        const len = text.toString().length;
        if (len <= 4) {
            element.style.fontSize = "2.8rem";
        } else if (len === 5) {
            element.style.fontSize = "2.2rem";
        } else if (len === 6) {
            element.style.fontSize = "1.8rem";
        } else if (len === 7) {
            element.style.fontSize = "1.5rem";
        } else {
            element.style.fontSize = "1.2rem";
        }
    }

    function formatValue(num) {
        return num.toString();
    }

    function render(state) {
        setTextAndScale(TOTAL_KILL_ID, formatValue(state.totalKills));
        setTextAndScale(TODAY_KILL_ID, formatValue(state.todayKills));
        setTextAndScale(TOTAL_NUKE_ID, formatValue(state.totalNukes));
        setTextAndScale(TODAY_NUKE_ID, formatValue(state.todayNukes));

        const totalDeaths = state.totalDeaths || 0;
        const todayDeaths = state.todayDeaths || 0;
        setTextAndScale(TOTAL_DEATH_ID, formatValue(totalDeaths));
        setTextAndScale(TODAY_DEATH_ID, formatValue(todayDeaths));

        const totalKD = totalDeaths > 0 ? (state.totalKills / totalDeaths).toFixed(2) : state.totalKills.toFixed(2);
        const todayKD = todayDeaths > 0 ? (state.todayKills / todayDeaths).toFixed(2) : state.todayKills.toFixed(2);
        setTextAndScale(TOTAL_KD_ID, totalKD);
        setTextAndScale(TODAY_KD_ID, todayKD);
    }

    // 動畫觸發函數 - 專門處理核彈動畫
    function triggerNukeAnimation() {
        if (typeof document === "undefined") return;
        const targetElement = document.getElementById(TODAY_NUKE_ID);
        if (!targetElement) return;
        const parent = targetElement.parentElement;

        const floatTextEl = document.createElement('div');
        floatTextEl.classList.add('floating-text', 'nuke-anim', 'nuke-text-wrap');

        const floatGifEl = document.createElement('div');
        floatGifEl.classList.add('nuke-gif-wrap');

        const gifEl = document.createElement('img');
        const t = Date.now();
        gifEl.src = `./explosion.gif?t=${t}`;
        gifEl.className = 'nuke-gif';
        gifEl.id = `nuke-gif-${t}`;
        gifEl.alt = '';
        gifEl.addEventListener('error', () => {
            gifEl.style.display = 'none';
        }, { once: true });

        const textEl = document.createElement('span');
        textEl.className = 'nuke-plus-one';
        textEl.textContent = '+1 NUKE!';

        floatGifEl.appendChild(gifEl);
        floatTextEl.appendChild(textEl);

        parent.appendChild(floatGifEl);
        parent.appendChild(floatTextEl);
        
        setTimeout(() => {
            const img = document.getElementById(`nuke-gif-${t}`);
            if (img) {
                img.style.opacity = '0';
                img.style.transition = 'opacity 0.2s';
            }
        }, 1800); 

        setTimeout(() => {
            if (parent.contains(floatGifEl)) {
                parent.removeChild(floatGifEl);
            }
            if (parent.contains(floatTextEl)) {
                parent.removeChild(floatTextEl);
            }
        }, 5000);
    }

    let activeKillAnimEl = null;
    let activeKillAnimTimeout = null;
    let comboCount = 0;

    // 動畫觸發函數 - 擊殺連殺 (Combo)
    //  1. 連殺視窗內 (距上一刀 < COMBO_WINDOW_MS) 還活著的泡泡 → 直接累加,
    //     +1 變 +2 變 +3,文字更新在「同一個」DOM 元素上,不疊字。
    //  2. 視窗已過 (泡泡已消失) → 開新一輪,comboCount 從這次的 count 重新算。
    //  3. 每次擊殺都重播彈跳動畫並重置消失計時器 → 一直殺就一直續命,
    //     停手滿 COMBO_WINDOW_MS 才淡出。
    //  4. count 支援一次多殺 (一發炸 2 台 → 直接 +2)。
    function triggerKillCombo(count) {
        if (typeof document === "undefined") return;
        const targetElement = document.getElementById(TODAY_KILL_ID);
        if (!targetElement) return;
        const parent = targetElement.parentElement;

        const comboAlive = activeKillAnimEl && parent.contains(activeKillAnimEl);
        if (comboAlive) {
            comboCount += count;          // 續殺:累加到同一個泡泡
        } else {
            comboCount = count;           // 新一輪:重新數
            activeKillAnimEl = document.createElement('div');
            activeKillAnimEl.classList.add('floating-text', 'kill-anim');
            parent.appendChild(activeKillAnimEl);
        }

        activeKillAnimEl.textContent = '+' + comboCount + ' KILL';

        // 重播彈跳動畫 (reflow trick)
        activeKillAnimEl.classList.remove('kill-anim');
        void activeKillAnimEl.offsetWidth;
        activeKillAnimEl.classList.add('kill-anim');

        // 重置消失計時器:持續擊殺就一直續命
        if (activeKillAnimTimeout) {
            clearTimeout(activeKillAnimTimeout);
        }
        activeKillAnimTimeout = setTimeout(() => {
            if (activeKillAnimEl && parent.contains(activeKillAnimEl)) {
                parent.removeChild(activeKillAnimEl);
            }
            activeKillAnimEl = null;
            activeKillAnimTimeout = null;
            comboCount = 0;
        }, COMBO_WINDOW_MS);
    }

    // 擊殺動畫排隊器:後端是「總數差值」驅動,快速連殺時一次 poll 可能 +2/+3。
    // 若直接 triggerKillCombo(diff) 泡泡會從 +1 跳成 +3 (跳號,看起來怪)。
    // 改成把 diff 排進佇列,每 KILL_ANIM_STEP_MS 平滑播一個 +1 → +1 +2 +3。
    // 數字本身 (render) 仍即時跟著後端,動畫只是視覺節奏。
    const KILL_ANIM_STEP_MS = 120;
    let pendingKillAnim = 0;
    let killAnimDrainer = null;

    function enqueueKillAnim(n) {
        if (typeof document === "undefined") return;
        pendingKillAnim += n;
        if (killAnimDrainer !== null) return;
        const drain = () => {
            if (pendingKillAnim <= 0) {
                killAnimDrainer = null;
                return;
            }
            pendingKillAnim -= 1;
            triggerKillCombo(1);
            killAnimDrainer = setTimeout(drain, KILL_ANIM_STEP_MS);
        };
        // 第一個立即播,其餘間隔播
        drain();
    }
    async function fetchHUD(seenEvent, seenDamage) {
        const response = await fetch(`${HOST}/hudmsg?lastEvt=${seenEvent}&lastDmg=${seenDamage}`, {
            method: "GET",
            headers: {
                Accept: "application/json",
            },
        });

        if (!response.ok) {
            throw new Error(`Unexpected response code: ${response.status}`);
        }

        return response.json();
    }

    // 讀取 mission.json 來判斷當前是否為試車場
    async function fetchMission() {
        try {
            const response = await fetch(`${HOST}/mission.json`, {
                method: "GET",
                headers: { Accept: "application/json" },
            });
            if (response.ok) {
                return await response.json();
            }
        } catch (e) {
            // ignore
        }
        return null;
    }



    let keyword = getKeyword();
    let playerName = getPlayerName();
    const state = readState();
    rotateDailyStats(state);

    let polling = false;

    console.log("[NukeCounter] 啟動! playerName:", playerName, "keyword:", keyword);
    console.log("[NukeCounter] state:", JSON.stringify(state));

    render(state);

    // Modal Handling Logic
    function initModal() {
        if (typeof window === "undefined") return;

        const modal = document.getElementById('edit-modal');
        const inputTodayKills = document.getElementById('input-today-kills');
        const inputTotalDeaths = document.getElementById('input-total-deaths');
        const inputTotalKills = document.getElementById('input-total-kills');
        const inputTotalNukes = document.getElementById('input-total-nukes');
        const inputTodayNukes = document.getElementById('input-today-nukes');
        const btnSave = document.getElementById('btn-save');
        const btnCancel = document.getElementById('btn-cancel');

        if (!modal) return;

        // Double click anywhere to open modal
        document.body.addEventListener('dblclick', (e) => {
            if (modal.style.display === 'flex') return; // Prevent resetting when adjusting numbers with up/down arrows
            inputTodayKills.value = state.todayKills || 0;
            inputTotalDeaths.value = state.totalDeaths || 0;
            inputTotalKills.value = state.totalKills || 0;
            inputTotalNukes.value = state.totalNukes || 0;
            inputTodayNukes.value = state.todayNukes || 0;
            modal.style.display = 'flex';
        });

        btnSave?.addEventListener('click', async () => {
            const newTodayKills = readNumber(inputTodayKills.value, state.todayKills || 0);
            const newTotalDeaths = readNumber(inputTotalDeaths.value, state.totalDeaths || 0);
            const newTotalKills = readNumber(inputTotalKills.value, state.totalKills || 0);
            const newTotalNukes = readNumber(inputTotalNukes.value, state.totalNukes || 0);
            const newTodayNukes = readNumber(inputTodayNukes.value, state.todayNukes || 0);

            try {
                await fetch("http://127.0.0.1:8112/update", {
                    method: "POST",
                    body: JSON.stringify({ 
                        todayKills: newTodayKills, 
                        totalDeaths: newTotalDeaths, 
                        totalKills: newTotalKills, 
                        totalNukes: newTotalNukes,
                        todayNukes: newTodayNukes
                    }),
                    headers: { "Content-Type": "application/json" }
                });
            } catch (e) {
                console.error("[NukeCounter] Failed to save to backend:", e);
            }

            state.todayKills = newTodayKills;
            state.totalDeaths = newTotalDeaths;
            state.totalKills = newTotalKills;
            state.totalNukes = newTotalNukes;
            state.todayNukes = newTodayNukes;
            writeState(state);
            render(state);
            modal.style.display = 'none';
        });

        btnCancel?.addEventListener('click', () => {
            modal.style.display = 'none';
        });
    }

    initModal();

    let lastNukeTime = 0;
    const NUKE_COOLDOWN_MS = 10000;

    async function fetchBackendState() {
        try {
            const response = await fetch("http://127.0.0.1:8112/state", {
                method: "GET",
                headers: { Accept: "application/json" },
            });
            if (response.ok) {
                return await response.json();
            }
        } catch (e) {
            // ignore
        }
        return null;
    }

    let firstBackendSync = true;

    async function poll() {
        try {
            const newState = await fetchBackendState();
            if (newState) {
                // 首次同步:overlay 剛開時直接吃 backend 當下的累積值,不放動畫。
                // 否則開 OBS / display 那一刻會因為「local 0 → backend 15」噴一個 +15。
                if (firstBackendSync) {
                    firstBackendSync = false;
                    Object.assign(state, {
                        totalKills: newState.totalKills,
                        todayKills: newState.todayKills,
                        totalDeaths: newState.totalDeaths || 0,
                        todayDeaths: newState.todayDeaths || 0,
                        totalNukes: newState.totalNukes,
                        todayNukes: newState.todayNukes,
                        dayKey: newState.dayKey,
                    });
                    writeState(state);
                    render(state);
                    return;
                }

                // Check if we need to trigger animations
                if (newState.todayKills > state.todayKills) {
                    const diff = newState.todayKills - state.todayKills;
                    enqueueKillAnim(diff);
                }

                if (newState.todayNukes > state.todayNukes) {
                    triggerNukeAnimation();
                }

                // Update our local state
                Object.assign(state, {
                    totalKills: newState.totalKills,
                    todayKills: newState.todayKills,
                    totalDeaths: newState.totalDeaths || 0,
                    todayDeaths: newState.todayDeaths || 0,
                    totalNukes: newState.totalNukes,
                    todayNukes: newState.todayNukes,
                    dayKey: newState.dayKey
                });

                writeState(state);
                render(state);
            }
        } catch (error) {
            console.debug("[NukeCounter] poll backend failed:", error);
        } finally {
            window.setTimeout(poll, 100);
        }
    }

    function start() {
        if (polling) {
            return;
        }

        polling = true;
        void poll();
    }

    if (typeof window !== "undefined") {
        window.NukeCounterOverlay = {
            async resetAll() {
                state.totalNukes = 0;
                state.todayNukes = 0;
                state.totalKills = 0;
                state.todayKills = 0;
                state.totalDeaths = 0;
                state.todayDeaths = 0;
                
                try {
                    await fetch("http://127.0.0.1:8112/update", {
                        method: "POST",
                        body: JSON.stringify({ totalKills: 0, totalNukes: 0, todayKills: 0, todayNukes: 0, totalDeaths: 0, todayDeaths: 0 }),
                        headers: { "Content-Type": "application/json" }
                    });
                } catch (e) { console.error("[NukeCounter] resetAll failed", e); }

                writeState(state);
                render(state);
            },
            async resetToday() {
                rotateDailyStats(state);
                state.todayNukes = 0;
                state.todayKills = 0;
                state.todayDeaths = 0;
                state.dayKey = todayKey();
                
                try {
                    await fetch("http://127.0.0.1:8112/update", {
                        method: "POST",
                        body: JSON.stringify({ todayKills: 0, todayNukes: 0, todayDeaths: 0 }),
                        headers: { "Content-Type": "application/json" }
                    });
                } catch (e) { console.error("[NukeCounter] resetToday failed", e); }

                writeState(state);
                render(state);
            },
            setKeyword(nextKeyword) {
                keyword = nextKeyword;
                localStorage.setItem(STORAGE_LANG, "custom");
            },
            setPlayerName(nextPlayerName) {
                playerName = nextPlayerName;
                localStorage.setItem(STORAGE_PLAYER, nextPlayerName);
            },
            getState() {
                return {
                    ...state,
                    keyword,
                    playerName,
                };
            },
        };
    }

    start();
})();