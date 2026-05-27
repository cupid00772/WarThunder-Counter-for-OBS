(function () {
    const HOST = "http://localhost:8111";
    const TOTAL_KILL_ID = "total-kill";
    const TOTAL_NUKE_ID = "total-nuke";
    const TODAY_KILL_ID = "today-kill";
    const TODAY_NUKE_ID = "today-nuke";

    const STORAGE_STATE = "thunder_overlay.nuke_counter.state";
    const LEGACY_STORAGE_COUNT = "thunder_overlay.nuke_counter.count";
    const LEGACY_STORAGE_LAST_DMG = "thunder_overlay.nuke_counter.last_dmg";
    const STORAGE_LANG = "thunder_overlay.nuke_counter.lang";
    const STORAGE_PLAYER = "thunder_overlay.nuke_counter.player";
    const DEFAULT_PLAYER = "cupid00772";

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
        "destroyed", "shot down", "set afire", "has crashed",
        // German
        "zerstört", "abgeschossen", "in Brand gesetzt",
        // French
        "détruit", "abattu", "a mis le feu",
        // Russian
        "уничтожен", "сбит", "поджёг",
        // Chinese
        "摧毀", "擊落", "點燃了",
        // Czech
        "zničil", "sestřelil",
        // Polish
        "zniszczono", "zestrzelony",
        // Romanian
        "distrus", "doborât",
        // Italian
        "distrutto", "abbattuto", "incendiato",
        // Portuguese
        "destruído", "abatido", "incendiou",
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

    function setText(id, text) {
        const element = document.getElementById(id);
        if (!element) {
            return;
        }

        element.textContent = text;
    }

    function formatK(num) {
        if (num >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        }
        return num.toString();
    }

    function render(state) {
        setText(TOTAL_KILL_ID, formatK(state.totalKills));
        setText(TODAY_KILL_ID, formatK(state.todayKills));
        setText(TOTAL_NUKE_ID, formatK(state.totalNukes));
        setText(TODAY_NUKE_ID, formatK(state.todayNukes));
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
    let currentComboCount = 0;

    // 動畫觸發函數 - 專門處理擊殺連殺 (Combo)
    function triggerKillCombo(count) {
        if (typeof document === "undefined") return;
        const targetElement = document.getElementById(TODAY_KILL_ID);
        if (!targetElement) return;
        const parent = targetElement.parentElement;

        currentComboCount += count;

        if (activeKillAnimEl && parent.contains(activeKillAnimEl)) {
            activeKillAnimEl.textContent = '+' + currentComboCount + ' KILL';
            
            activeKillAnimEl.classList.remove('kill-anim');
            void activeKillAnimEl.offsetWidth; 
            activeKillAnimEl.classList.add('kill-anim');

            if (activeKillAnimTimeout) {
                clearTimeout(activeKillAnimTimeout);
            }
        } else {
            currentComboCount = count;
            activeKillAnimEl = document.createElement('div');
            activeKillAnimEl.classList.add('floating-text', 'kill-anim');
            activeKillAnimEl.textContent = '+' + currentComboCount + ' KILL';
            parent.appendChild(activeKillAnimEl);
        }

        activeKillAnimTimeout = setTimeout(() => {
            if (activeKillAnimEl && parent.contains(activeKillAnimEl)) {
                parent.removeChild(activeKillAnimEl);
            }
            activeKillAnimEl = null;
            currentComboCount = 0;
        }, 5000);
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



    let keyword = getKeyword();
    let playerName = getPlayerName();
    const state = readState();
    rotateDailyStats(state);

    let lastDmg = 0;                 // [patch A] 不從 localStorage 載入,避免 WT/OBS 重啟跨 session 殘留把新 damage 全部過濾掉
    let lastEvt = state.lastEvt;
    let polling = false;
    let firstPollDone = false;       // [patch B] 首次 poll 只對齊 baseline 不計分,避免刷新一次就 +N
    let emptyPollCount = 0;

    console.log("[NukeCounter] 啟動! playerName:", playerName, "keyword:", keyword);
    console.log("[NukeCounter] 從 localStorage 讀取 lastDmg:", lastDmg, "lastEvt:", lastEvt);
    console.log("[NukeCounter] state:", JSON.stringify(state));

    render(state);

    // Modal Handling Logic
    function initModal() {
        if (typeof window === "undefined") return;

        const modal = document.getElementById('edit-modal');
        const inputTotalKills = document.getElementById('input-total-kills');
        const inputTotalNukes = document.getElementById('input-total-nukes');
        const btnSave = document.getElementById('btn-save');
        const btnCancel = document.getElementById('btn-cancel');

        if (!modal) return;

        // Double click anywhere to open modal
        document.body.addEventListener('dblclick', () => {
            inputTotalKills.value = state.totalKills;
            inputTotalNukes.value = state.totalNukes;
            modal.style.display = 'flex';
        });

        btnSave?.addEventListener('click', () => {
            state.totalKills = readNumber(inputTotalKills.value, state.totalKills);
            state.totalNukes = readNumber(inputTotalNukes.value, state.totalNukes);
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

    async function poll() {
        try {
            const result = await fetchHUD(lastEvt, lastDmg);
            const damage = Array.isArray(result.damage) ? result.damage : [];

            // [patch B] 首次 poll 只對齊 lastDmg 到 server 當下最大 id,不計分。
            // 避免 OBS 刷新 / overlay 載入時把 server 內所有歷史 damage 全部重複加進來 (例如 +31)。
            if (!firstPollDone) {
                firstPollDone = true;
                if (damage.length > 0) {
                    let maxId = lastDmg;
                    for (const entry of damage) {
                        if (typeof entry?.id === "number" && entry.id > maxId) {
                            maxId = entry.id;
                        }
                    }
                    lastDmg = maxId;
                    console.log("[NukeCounter] 首次 poll baseline 對齊 lastDmg =", lastDmg, "(略過", damage.length, "筆歷史)");
                } else {
                    console.log("[NukeCounter] 首次 poll baseline,server 無歷史 damage");
                }
                return;
            }

            if (damage.length > 0) {
                emptyPollCount = 0;
                const now = Date.now();
                let nukeTriggeredInBatch = false;
                var batchKillCount = 0;

                for (const entry of damage) {
                    if (typeof entry?.msg !== "string") {
                        continue;
                    }

                    if (entry.msg.includes(keyword)) {
                        if (!nukeTriggeredInBatch && now - lastNukeTime > NUKE_COOLDOWN_MS) {
                            state.totalNukes += 1;
                            state.todayNukes += 1;
                            triggerNukeAnimation();
                            nukeTriggeredInBatch = true;
                            lastNukeTime = now;
                        }
                    }

                    var isOwned = isOwnedKillEvent(entry, keyword, playerName);
                    if (isOwned) {
                        var killCount = 1;
                        var match = entry.msg.match(/(?:^|\s)(\d+)x\s/i);
                        if (match) {
                            var parsed = parseInt(match[1], 10);
                            if (!isNaN(parsed) && parsed > 0) {
                                killCount = parsed;
                            }
                        }
                        
                        state.totalKills += killCount;
                        state.todayKills += killCount;
                        batchKillCount += killCount;
                    }
                }

                if (batchKillCount > 0) {
                    triggerKillCombo(batchKillCount);
                }

                const lastEntry = damage[damage.length - 1];
                if (typeof lastEntry?.id === "number") {
                    lastDmg = lastEntry.id;
                }

                state.lastDmg = lastDmg;
                state.lastEvt = lastEvt;
                rotateDailyStats(state);
                writeState(state);
                render(state);
            } else {
                // 如果連續多次收到空回應，且 lastDmg 非常大（可能是 mock server 殘留），自動重置
                emptyPollCount++;
                if (emptyPollCount >= 5 && lastDmg > 10000) {
                    console.warn("[NukeCounter] ⚠️ 連續", emptyPollCount, "次空回應，lastDmg 過大 (" + lastDmg + ")，疑似 mock server 殘留，自動重置為 0");
                    lastDmg = 0;
                    state.lastDmg = 0;
                    writeState(state);
                    emptyPollCount = 0;
                }
            }
        } catch (error) {
            console.debug("[NukeCounter] poll 失敗:", error);
        } finally {
            window.setTimeout(poll, 1000);
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
            resetAll() {
                state.totalNukes = 0;
                state.todayNukes = 0;
                state.totalKills = 0;
                state.todayKills = 0;
                lastDmg = 0;
                state.lastDmg = lastDmg;
                state.lastEvt = lastEvt;
                state.dayKey = todayKey();
                writeState(state);
                render(state);
            },
            resetToday() {
                rotateDailyStats(state);
                state.todayNukes = 0;
                state.todayKills = 0;
                state.dayKey = todayKey();
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
                    lastDmg,
                    lastEvt,
                };
            },
        };
    }

    start();
})();