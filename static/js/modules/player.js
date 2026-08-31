window.WeFoolApp = window.WeFoolApp || {};
window.WeFoolApp.player = window.WeFoolApp.player || {};

let lastActiveIndex = -1;
let activeRowElement = null;
let isUpdatingSubtitle = false;
let youtubeApiReadyPromise = null;
let playerSetupGeneration = 0;

function ensureYouTubeAPIReady() {
    if (window.YT && typeof window.YT.Player === 'function') {
        return Promise.resolve(window.YT);
    }

    if (youtubeApiReadyPromise) {
        return youtubeApiReadyPromise;
    }

    youtubeApiReadyPromise = new Promise((resolve, reject) => {
        const previousReadyHandler = window.onYouTubeIframeAPIReady;
        let settled = false;

        const finish = () => {
            if (settled) return;
            if (!window.YT || typeof window.YT.Player !== 'function') {
                settled = true;
                clearTimeout(timeoutId);
                youtubeApiReadyPromise = null;
                reject(new Error('YouTube iframe API reported ready without a Player constructor'));
                return;
            }
            settled = true;
            clearTimeout(timeoutId);
            resolve(window.YT);
        };

        window.onYouTubeIframeAPIReady = function() {
            if (typeof previousReadyHandler === 'function') {
                try {
                    previousReadyHandler();
                } catch (e) {
                    console.error('Existing YouTube API ready handler failed:', e);
                }
            }
            finish();
        };

        const timeoutId = setTimeout(() => {
            if (settled) return;
            settled = true;
            youtubeApiReadyPromise = null;
            reject(new Error('YouTube iframe API did not become ready'));
        }, 15000);

        const existingScript = document.querySelector('script[src="https://www.youtube.com/iframe_api"]');
        if (!existingScript) {
            const script = document.createElement('script');
            script.src = 'https://www.youtube.com/iframe_api';
            script.onerror = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timeoutId);
                youtubeApiReadyPromise = null;
                reject(new Error('YouTube iframe API failed to load'));
            };
            document.head.appendChild(script);
        }

        if (window.YT && typeof window.YT.Player === 'function') {
            finish();
        }
    });

    return youtubeApiReadyPromise;
}

const atmospheres = {
    storytelling: { name: 'เล่าเรื่อง', color: '#F59E0B', rgb: '245,158,11' },
    education: { name: 'ให้ความรู้', color: '#10B981', rgb: '16,185,129' },
    fact_reporting: { name: 'รายงานข้อเท็จจริง', color: '#3B82F6', rgb: '59,130,246' },
    analysis: { name: 'วิเคราะห์', color: '#06B6D4', rgb: '6,182,212' },
    persuasion: { name: 'โน้มน้าว', color: '#EC4899', rgb: '236,72,153' },
    trust: { name: 'สร้างความเชื่อมั่น', color: '#8B5CF6', rgb: '139,92,246' },
    reasoning: { name: 'ชี้แจงเหตุผล', color: '#64748B', rgb: '100,116,139' },
    criticism: { name: 'วิพากษ์วิจารณ์', color: '#EF4444', rgb: '239,68,68' },
    alert: { name: 'เตือนภัย', color: '#F97316', rgb: '249,115,22' },
    inspirational: { name: 'สร้างแรงบันดาลใจ', color: '#D946EF', rgb: '217,70,239' },
    celebration: { name: 'เฉลิมฉลอง', color: '#FCD34D', rgb: '252,211,77' },
    loss: { name: 'สะท้อนปัญหาและความสูญเสีย', color: '#6366F1', rgb: '99,102,241' },
    neutral: { name: 'เป็นกลาง', color: '#22C55E', rgb: '34,197,94' }
};

function getAtmosphereFromEmotion(emotionText) {
    if (!emotionText || emotionText === "ไม่ระบุ") return "neutral";
    const text = String(emotionText).trim().toLowerCase();
    
    // Explicit cases from prompt requirements
    if (text.includes("คัดแค้น") || text.includes("น่าเกรงขาม")) return "criticism";
    if (text.includes("รุ่งเรือง") || text.includes("เสื่อมถอย")) return "storytelling";
    if (text.includes("คาดหวัง") && text.includes("มืดมน")) return "loss";
    if (text.includes("มืดมน") || text.includes("หดหู่") || text.includes("สูญเสีย") || text.includes("โศกเศร้า") || text.includes("เศร้า") || text.includes("เสียใจ")) return "loss";

    // General keyword mapping
    if (text.match(/(เล่า|นิทาน|ย้อน|อดีต|เรื่องเล่า|ประวัติ|ตำนาน|ละคร|ความเป็นมา|สตรีม|พูดถึง)/)) return "storytelling";
    if (text.match(/(สอน|ความรู้|วิชาการ|เรียน|การเรียน|แนะนำ|ธรรม|ทฤษฎี|สัมมนา)/)) return "education";
    if (text.match(/(ข้อเท็จจริง|ข่าว|รายงาน|ประกาศ|อัพเดต|สถิติ|ตัวเลข|แถลง)/)) return "fact_reporting";
    if (text.match(/(วิเคราะห์|เจาะลึก|ประเมิน|วินิจฉัย|พิสูจน์|ตรวจสอบ|ถอดรหัส|วิจัย|ถก|เปรียบเทียบ|ประเด็น)/)) return "analysis";
    if (text.match(/(โน้มน้าว|ชักชวน|ขาย|โฆษณา|ชวนเชื่อ|ปลุกระดม|จูงใจ|รณรงค์)/)) return "persuasion";
    if (text.match(/(มั่นใจ|เชื่อมั่น|รับประกัน|สัญญา|จริงใจ|โปร่งใส|เป็นกันเอง|อบอุ่น|ปลอดภัย|ปลอบโยน|ปลอบประโลม)/)) return "trust";
    if (text.match(/(ชี้แจง|อ้างอิง|บริสุทธิ์|เหตุผล|โต้แย้ง|แก้ตัว|ตอบคำถาม|สู้ความ)/)) return "reasoning";
    if (text.match(/(วิจารณ์|วิพากษ์|แฉ|โจมตี|ตำหนิ|คัดค้าน|ไม่พอใจ|เสียดสี|ประชด|โกรธ|กดดัน|ผิดหวัง)/)) return "criticism";
    if (text.match(/(เตือน|ระวัง|อันตราย|เสี่ยง|ภัย|เฝ้าระวัง|ห้าม|ร้ายแรง|ตื่นตระหนก|วุ่นวาย|กลัว|ระวังภัย)/)) return "alert";
    if (text.match(/(แรงบันดาลใจ|บันดาลใจ|ความหวัง|สู้|ฝัน|ปลุกใจ|ฮึด|พัฒนา)/)) return "inspirational";
    if (text.match(/(ฉลอง|ยินดี|สนุก|รื่นเริง|สำเร็จ|ชนะ|มีความสุข|งานเลี้ยง|ร่าเริง|ตลก|เฮฮา|ขำ)/)) return "celebration";

    // Original tones fallback
    if (text.match(/(โกรธ|กดดัน|ผิดหวัง)/)) return "criticism";
    if (text.match(/(มั่นใจ|สร้างแรงบันดาลใจ)/)) return "inspirational";
    if (text.match(/(เป็นกันเอง|สนุกสนาน|มีความสุขและสงบสุข|มีความสุข|สงบสุข)/)) return "celebration";
    if (text.match(/(ชวนคิด|สงสัย)/)) return "analysis";
    if (text.match(/(เศร้า|กังวล|เห็นอกเห็นใจ|ตื่นตระหนกตกใจกลัว|ตื่นตระหนกและวุ่นวาย)/)) return "loss";

    return "storytelling"; // default fallback for prototype
}

function updateMoodBadges(emotionText) {
    const activeEmotion = (emotionText && emotionText !== "ไม่ระบุ" && emotionText !== "เป็นกลาง") 
        ? emotionText 
        : (window.WeFoolApp.state.globalCanonicalEmotion || "ไม่ระบุ");

    const badge = document.getElementById("currentMoodBadge");
    const videoBadge = document.getElementById("videoCurrentMoodBadge");
    const playerBox = document.querySelector(".sticky-player-box");

    if (activeEmotion && activeEmotion !== "ไม่ระบุ") {
        const atmosKey = getAtmosphereFromEmotion(activeEmotion);
        const atmos = atmospheres[atmosKey] || atmospheres.neutral;
        
        if (badge) {
            badge.style.setProperty("--mood-color", atmos.color);
            badge.style.setProperty("--mood-rgb", atmos.rgb);
            badge.textContent = `บรรยากาศหลัก: ${atmos.name}`;
        }
        if (videoBadge) {
            videoBadge.style.setProperty("--mood-color", atmos.color);
            videoBadge.style.setProperty("--mood-rgb", atmos.rgb);
            videoBadge.textContent = `บรรยากาศหลัก: ${atmos.name}`;
        }
        if (playerBox) {
            playerBox.style.setProperty("--mood-color", atmos.color);
            playerBox.style.setProperty("--mood-rgb", atmos.rgb);
            playerBox.classList.add("mood-glow-active");
        }
    } else {
        if (badge) {
            badge.textContent = "บรรยากาศหลัก: ไม่ระบุ";
            badge.style.removeProperty("--mood-color");
            badge.style.removeProperty("--mood-rgb");
        }
        if (videoBadge) {
            videoBadge.textContent = "บรรยากาศหลัก: ไม่ระบุ";
            videoBadge.style.removeProperty("--mood-color");
            videoBadge.style.removeProperty("--mood-rgb");
        }
        if (playerBox) {
            playerBox.classList.remove("mood-glow-active");
        }
    }
}

function findActiveIndex(currentTime) {
    const timelineData = window.WeFoolApp.state.globalTimelineData;
    let low = 0;
    let high = timelineData.length - 1;
    while (low <= high) {
        let mid = Math.floor((low + high) / 2);
        let item = timelineData[mid];
        let start = Number(item.start);
        let end = Number(item.end);
        if (isNaN(start) || isNaN(end)) {
            start = mid * 4;
            end = start + 4;
        }
        if (currentTime >= start && currentTime < end) {
            return mid;
        } else if (currentTime < start) {
            high = mid - 1;
        } else {
            low = mid + 1;
        }
    }
    return -1;
}

function trackLiveSubtitle(currentTime) {
    if (isUpdatingSubtitle) return;
    
    isUpdatingSubtitle = true;
    requestAnimationFrame(() => {
        updateCommunicationMoodByTime(currentTime);
        const timeMarker = document.getElementById('timeMarker');
        if (timeMarker) {
            timeMarker.innerText = `พิกัดเวลาตรวจสอบปัจจุบัน: ${window.WeFoolApp.time.formatToExecutiveTime(currentTime)} นาที`;
        }

        const activeIndex = findActiveIndex(currentTime);
        let activeSubText = "[ ระบบกำลังตรวจสอบความเงียบหรือการประมวลสัญญาณเสียง ]";

        if (activeIndex !== -1) {
            const item = window.WeFoolApp.state.globalTimelineData[activeIndex];
            activeSubText = item.label + " " + item.text;

            if (activeIndex !== lastActiveIndex) {
                if (activeRowElement) {
                    activeRowElement.classList.remove('active-row');
                }
                
                activeRowElement = document.getElementById(`tx-row-${activeIndex}`);
                if (activeRowElement) {
                    activeRowElement.classList.add('active-row');
                    activeRowElement.scrollIntoView({ behavior: 'auto', block: 'nearest' });
                }
                lastActiveIndex = activeIndex;
            }
        } else {
            if (activeRowElement) {
                activeRowElement.classList.remove('active-row');
                activeRowElement = null;
            }
            lastActiveIndex = -1;
        }

        const liveSubBox = document.getElementById('live-sub-box');
        if (liveSubBox) {
            liveSubBox.innerText = activeSubText;
        }
        isUpdatingSubtitle = false;
    });
}

function resetPlayerState() {
    lastActiveIndex = -1;
    activeRowElement = null;
    isUpdatingSubtitle = false;
}

async function setupMainPlayer(data) {
    if (!data || (!data.video_url && !data.real_youtube_url)) {
        throw new Error("Missing video_url and real_youtube_url");
    }
    const wrapper = document.getElementById('playerWrapper');
    const setupGeneration = ++playerSetupGeneration;
    const existingYtPlayer = window.WeFoolApp.state.activeYtPlayer;
    if (existingYtPlayer && typeof existingYtPlayer.destroy === 'function') {
        try {
            existingYtPlayer.destroy();
        } catch (e) {}
    }
    window.WeFoolApp.state.activeYtPlayer = null;
    const oldVideo = wrapper.querySelector('video');
    if (oldVideo) {
        try {
            oldVideo.pause();
            oldVideo.src = "";
            oldVideo.load();
        } catch (e) {}
    }
    clearInterval(window.WeFoolApp.state.ytTimerInterval);
    wrapper.innerHTML = ''; 
    resetPlayerState();

    const targetUrl = (data.real_youtube_url || "").toLowerCase();
    const isYoutubeMedia = data.is_youtube && 
                          (targetUrl.includes('youtube.com') || targetUrl.includes('youtu.be')) && 
                          !targetUrl.includes('tiktok.com');

    if (isYoutubeMedia) {
        let videoId = 'dQw4w9WgXcQ';
        try {
            if (data.real_youtube_url.includes('youtu.be/')) {
                videoId = data.real_youtube_url.split('youtu.be/')[1].split('?')[0];
            } else if (data.real_youtube_url.includes('v=')) {
                const urlObj = new URL(data.real_youtube_url);
                videoId = urlObj.searchParams.get('v');
            }
        } catch (e) {}

        await ensureYouTubeAPIReady();
        if (setupGeneration !== playerSetupGeneration) return;

        const divTarget = document.createElement('div');
        divTarget.id = 'ytActualPlayer';
        wrapper.appendChild(divTarget);

        window.WeFoolApp.state.activeYtPlayer = new window.YT.Player('ytActualPlayer', {
            height: '100%', width: '100%', videoId: videoId,
            playerVars: { 'rel': 0, 'modestbranding': 1, 'origin': window.location.origin },
            events: {
                'onReady': function() {
                    window.WeFoolApp.state.ytTimerInterval = setInterval(() => {
                        if (window.WeFoolApp.state.activeYtPlayer && typeof window.WeFoolApp.state.activeYtPlayer.getCurrentTime === 'function') {
                            trackLiveSubtitle(window.WeFoolApp.state.activeYtPlayer.getCurrentTime());
                        }
                    }, 300);
                }
            }
        });
    } else {
        window.WeFoolApp.state.activeYtPlayer = null;
        const videoTag = document.createElement('video');
        videoTag.controls = true; 
        videoTag.autoplay = true; 
        videoTag.style.width = '100%';
        videoTag.style.height = '100%';
        videoTag.style.borderRadius = '8px';
        videoTag.style.display = 'block';
        
        videoTag.onerror = function() {
            wrapper.innerHTML = `<div class="media-unavailable-notice" style="color:var(--text-secondary); padding:40px; text-align:center; background:var(--input-bg); border-radius:8px; line-height:1.6;">⚠️ ไม่พบไฟล์วิดีโอสำหรับผลการวิเคราะห์นี้<br>ข้อความถอดความและผลวิเคราะห์ยังคงใช้งานได้</div>`;
        };

        videoTag.src = data.video_url; 
        wrapper.appendChild(videoTag);
        
        videoTag.ontimeupdate = function() { 
            trackLiveSubtitle(videoTag.currentTime); 
        };
    }
}

function updateCommunicationMoodByTime(currentTime) {
    const playerBox = document.querySelector(".sticky-player-box");
    if (!playerBox) return;

    let activeIndex = -1;
    let activeEmotion = "เป็นกลาง";

    const intervals = window.WeFoolApp.state.globalCommunicationIntervals;
    for (let index = 0; index < intervals.length; index += 1) {
        const item = intervals[index];
        const range = String(item.time_range || "").replace("–", "-").replace("—", "-").split("-", 2);
        if (range.length !== 2) continue;
        const start = window.WeFoolApp.time.parseCommunicationTimeToSeconds(range[0]);
        const end = window.WeFoolApp.time.parseCommunicationTimeToSeconds(range[1]);
        if (start === null || end === null) continue;
        if (currentTime >= start && currentTime < end) {
            activeIndex = index;
            activeEmotion = String(item.emotion || "เป็นกลาง");
            break;
        }
    }

    if (activeIndex !== window.WeFoolApp.state.lastCommunicationIndex) {
        if (window.WeFoolApp.state.activeCommunicationRow) {
            window.WeFoolApp.state.activeCommunicationRow.classList.remove("communication-mood-row-active");
        }

        const currentMoodVal = activeIndex !== -1 ? activeEmotion : window.WeFoolApp.state.globalCanonicalEmotion;
        updateMoodBadges(currentMoodVal);

        if (activeIndex !== -1) {
            window.WeFoolApp.state.activeCommunicationRow = document.getElementById(`communication-row-${activeIndex}`);
            if (window.WeFoolApp.state.activeCommunicationRow) {
                const atmosKey = getAtmosphereFromEmotion(activeEmotion);
                const atmos = atmospheres[atmosKey] || atmospheres.neutral;
                window.WeFoolApp.state.activeCommunicationRow.style.setProperty("--mood-color", atmos.color);
                window.WeFoolApp.state.activeCommunicationRow.style.setProperty("--mood-rgb", atmos.rgb);
                window.WeFoolApp.state.activeCommunicationRow.classList.add("communication-mood-row-active");
            }
        }
        window.WeFoolApp.state.lastCommunicationIndex = activeIndex;
    }
}

function warpToTargetTime(seconds) {
    const player = document.querySelector('video') || (window.WeFoolApp.state.activeYtPlayer ? window.WeFoolApp.state.activeYtPlayer : null);
    const wrapper = document.querySelector('.sticky-player-box');
    
    if (wrapper) {
        wrapper.style.transition = "box-shadow 0.2s ease";
        wrapper.style.boxShadow = "0 0 35px rgba(255, 87, 34, 0.8)";
        setTimeout(() => { wrapper.style.boxShadow = "0 15px 35px rgba(0,0,0,0.6)"; }, 500);
    }
    
    if (player && player.seekTo) player.seekTo(seconds, true);
    else if (player) player.currentTime = seconds;
}

window.WeFoolApp.player.setupMainPlayer = setupMainPlayer;
window.WeFoolApp.player.ensureYouTubeAPIReady = ensureYouTubeAPIReady;
window.WeFoolApp.player.warpToTargetTime = warpToTargetTime;
window.WeFoolApp.player.trackLiveSubtitle = trackLiveSubtitle;
window.WeFoolApp.player.updateMoodBadges = updateMoodBadges;
window.WeFoolApp.player.updateCommunicationMoodByTime = updateCommunicationMoodByTime;
window.WeFoolApp.player.resetPlayerState = resetPlayerState;
window.WeFoolApp.player.atmospheres = atmospheres;
window.WeFoolApp.player.getAtmosphereFromEmotion = getAtmosphereFromEmotion;

// Global compatibility wrappers
window.setupMainPlayer = setupMainPlayer;
window.warpToTargetTime = warpToTargetTime;
window.trackLiveSubtitle = trackLiveSubtitle;
window.updateMoodBadges = updateMoodBadges;
window.updateCommunicationMoodByTime = updateCommunicationMoodByTime;
window.resetPlayerState = resetPlayerState;
