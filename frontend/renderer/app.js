'use strict';

// ── Tab switching ─────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
        tab.classList.add('active');
        document.getElementById('tab-' + tab.dataset.tab).classList.remove('hidden');
    });
});

// ── Shared badge ──────────────────────────────────────────────────────────────
const $badge = document.getElementById('badge');
function setBadge(type, text) {
    $badge.className = 'badge badge-' + type;
    $badge.textContent = text;
}

// ══════════════════════════════════════════════════════════════════
//  VIDEO URL TAB
// ══════════════════════════════════════════════════════════════════

const $urlInput     = document.getElementById('url-input');
const $btnProcess   = document.getElementById('btn-process');
const $langVideo    = document.getElementById('lang-select-video');
const $progressWrap = document.getElementById('progress-wrap');
const $progressLbl  = document.getElementById('progress-label');
const $progressFill = document.getElementById('progress-fill');
const $playerSec    = document.getElementById('player-section');
const $subOrig      = document.getElementById('sub-orig');
const $subDub       = document.getElementById('sub-dub');
const $mpvTimeDisp  = document.getElementById('mpv-time-display');

let videoGender = 'male';
let hasDubbed   = false;   // becomes true after the first Dub It

// Switching voice or language re-dubs automatically (once the video is loaded).
// Already-generated voice/lang combos load instantly from cache; new ones
// regenerate. Without this, changing the dropdown silently did nothing.
function reDubIfActive(reason) {
    const url = $urlInput.value.trim();
    if (hasDubbed && url) {
        setBadge('loading', reason);
        startProcessing(url);
    }
}

[document.getElementById('vid-btn-male'), document.getElementById('vid-btn-female')].forEach(b => {
    b.addEventListener('click', () => {
        if (b.dataset.g === videoGender) return;     // no change
        videoGender = b.dataset.g;
        document.getElementById('vid-btn-male').classList.toggle('active',   videoGender === 'male');
        document.getElementById('vid-btn-female').classList.toggle('active', videoGender === 'female');
        reDubIfActive(`Switching to ${videoGender} voice…`);
    });
});

$langVideo.addEventListener('change', () => {
    reDubIfActive(`Switching to ${$langVideo.options[$langVideo.selectedIndex].text}…`);
});

$btnProcess.addEventListener('click', () => {
    const url = $urlInput.value.trim();
    if (!url) return;
    startProcessing(url);
});
$urlInput.addEventListener('keydown', e => { if (e.key === 'Enter') $btnProcess.click(); });

function startProcessing(url) {
    hasDubbed = true;
    $progressWrap.classList.remove('hidden');
    $btnProcess.disabled = true;
    setBadge('loading', 'Launching mpv…');
    setProgress('stream', 0, 'Starting…');
    manifest = null; playedSegments = new Set();
    readyUntil = 0; syncPaused = true; processDone = false;
    window.electronAPI.stopDubAudio();
    $subOrig.textContent = ''; $subDub.textContent = '';
    window.electronAPI.processVideo(url, $langVideo.value, videoGender);
}

function setProgress(step, pct, msg) {
    const names = { stream:'Video', captions:'Captions', translate:'Translating', tts:'Dubbed audio', stretch:'Syncing' };
    $progressLbl.textContent = `${names[step] || step}: ${msg}`;
    $progressFill.style.width = Math.max(pct, 2) + '%';
}

function fmtTime(s) {
    if (!s || isNaN(s)) return '0:00';
    const m = Math.floor(s / 60), sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
}

// ── mpv events ────────────────────────────────────────────────────
let mpvTime   = 0;
let mpvPaused = false;

window.electronAPI.onMpvReady(() => {
    $playerSec.classList.remove('hidden');
    setBadge('live', '▶ Playing in mpv');
    // AudioContext created lazily in initAudio() when first segment arrives
});

window.electronAPI.onMpvTime(t => {
    // ── Seek detection ────────────────────────────────────────────────
    // If the playhead jumps (user dragged the mpv seek bar), re-sync the dub.
    if (Math.abs(t - mpvTime) > 1.2) {
        // Backward seek (rewind): re-enable every segment whose audio covers a
        // point at/after the new position so it can play again. Without this,
        // rewound segments stay flagged in playedSegments and the dub goes silent.
        if (manifest?.segments) {
            manifest.segments.forEach((s, i) => {
                if (s && s.end > t) playedSegments.delete(i);   // future-of-now again
                else if (s)        playedSegments.add(i);        // forward-seek: skip past ones
            });
        }
        window.electronAPI.stopDubAudio();   // kill whatever was mid-play
    }

    mpvTime = t;
    if ($mpvTimeDisp) $mpvTimeDisp.textContent = fmtTime(t);
    updateSubtitles();
    checkBuffer();                        // pause/resume based on production frontier
    if (!mpvPaused) playCurrentSegment();
});

window.electronAPI.onMpvPause(paused => {
    mpvPaused = paused;
    if (!paused) playCurrentSegment();
    else window.electronAPI.stopDubAudio();
});

window.electronAPI.onMpvStopped(() => {
    $btnProcess.disabled = false;
    setBadge('idle', 'Idle');
    window.electronAPI.stopDubAudio();
});

// ── Segment arrives from Python backend ───────────────────────────
window.electronAPI.onSegment(seg => {
    if (!manifest) manifest = { segments: [] };
    while (manifest.segments.length <= seg.index) manifest.segments.push(null);
    manifest.segments[seg.index] = seg;
    updateReadyUntil(seg.end);           // extend buffer frontier
    if (!mpvPaused) playCurrentSegment();
});

window.electronAPI.onProgress(({ step, pct, msg }) => setProgress(step, pct, msg));

window.electronAPI.onProcessDone(() => {
    $btnProcess.disabled = false;
    setBadge('ready', '✓ Fully dubbed!');
    $progressWrap.classList.add('hidden');
    processDone = true;                   // Python finished — never auto-pause again
    if (syncPaused) { syncPaused = false; window.electronAPI.mpvSetPause(false); }
});

window.electronAPI.onProcessError(msg => {
    $btnProcess.disabled = false;
    setBadge('error', 'Error');
    $progressLbl.textContent = '⚠ ' + msg;
});

// ── Audio engine ──────────────────────────────────────────────────
let manifest       = null;
let playedSegments = new Set();
let dubVolume      = 1.0;

// ── Buffer control ────────────────────────────────────────────────
// readyUntil = production frontier (end time of the furthest dubbed segment).
// mpv starts paused; we release it once START_BUFFER seconds are ready.
// While Python is still producing, if mpv catches up to within PAUSE_GAP of
// the frontier we pause and rebuild buffer up to RESUME_GAP, then resume.
// Once Python finishes (processDone) we never pause again.
const START_BUFFER = 6;   // seconds of dub ready before first play
const PAUSE_GAP    = 1.5; // pause if mpv gets this close to the frontier
const RESUME_GAP   = 6;   // resume once frontier is this far ahead again
let   readyUntil   = 0;
let   syncPaused   = true;
let   processDone  = false;

function updateReadyUntil(segEnd) {
    if (segEnd > readyUntil) readyUntil = segEnd;
    checkBuffer();
}

function checkBuffer() {
    if (processDone) return;                         // fully generated — let it run

    const ahead = readyUntil - mpvTime;

    if (syncPaused) {
        // Release once we have enough buffer (or at startup, START_BUFFER)
        if (ahead >= RESUME_GAP || (mpvTime < 0.5 && readyUntil >= START_BUFFER)) {
            syncPaused = false;
            window.electronAPI.mpvSetPause(false);
            setBadge('live', '▶ Playing in mpv');
        }
    } else {
        // Playing — pause if we've caught up to the production frontier
        if (ahead <= PAUSE_GAP) {
            syncPaused = true;
            window.electronAPI.mpvSetPause(true);
            setBadge('loading', 'Buffering dub…');
        }
    }
}

document.getElementById('dub-vol').addEventListener('input', e => {
    dubVolume = parseFloat(e.target.value);
});
document.getElementById('orig-vol').addEventListener('input', e => {
    window.electronAPI.setMpvVolume(parseFloat(e.target.value));
});

function playCurrentSegment() {
    if (!manifest?.segments) return;
    // 5-second grace: also catch segments that arrived late (Python rate-limiting
    // can delay first batch by 10-15s, so segments arrive after mpvTime passes them).
    const GRACE = 5;
    const idx = manifest.segments.findIndex(
        (s, i) => s?.audio_file &&
                  s.start <= mpvTime &&
                  s.end   > mpvTime - GRACE &&
                  !playedSegments.has(i)
    );
    if (idx < 0) return;
    playedSegments.add(idx);
    const seg = manifest.segments[idx];
    // Always play the full sentence from its start (offset 0) so it's never
    // clipped. The main-process queue plays clips back-to-back and drops any
    // that fall too far behind the video.
    window.electronAPI.playDub(idx, seg.audio_file, 0, dubVolume, seg.end);
}

function updateSubtitles() {
    if (!manifest?.segments) return;
    const seg = manifest.segments.find(s => s && s.start <= mpvTime && s.end > mpvTime);
    $subOrig.textContent = seg ? seg.text   : '';
    $subDub.textContent  = seg ? seg.dubbed : '';
}

// ══════════════════════════════════════════════════════════════════
//  LIVE DUB TAB
// ══════════════════════════════════════════════════════════════════

const $btnStart = document.getElementById('btn-start');
const $btnClear = document.getElementById('btn-clear');
const $feed     = document.getElementById('feed');
let gender  = 'male';
let running = false;
let pendingSrc = null;

[document.getElementById('btn-male'), document.getElementById('btn-female')].forEach(b => {
    b.addEventListener('click', () => {
        gender = b.dataset.g;
        document.getElementById('btn-male').classList.toggle('active',   gender === 'male');
        document.getElementById('btn-female').classList.toggle('active', gender === 'female');
        if (running) hotSwitch();
    });
});

document.getElementById('lang-select-live').addEventListener('change', () => {
    if (running) hotSwitch();
});

$btnStart.addEventListener('click', async () => {
    if (running) {
        await window.electronAPI.stopDub();
        setIdle();
    } else {
        const lang = document.getElementById('lang-select-live').value;
        await window.electronAPI.startDub(lang, gender);
        setLive();
    }
});

async function hotSwitch() {
    addRaw('↻ Restarting with new settings…');
    await window.electronAPI.stopDub();
    const lang = document.getElementById('lang-select-live').value;
    await window.electronAPI.startDub(lang, gender);
    setBadge('live', '● Live');
}

function setLive() {
    running = true;
    $btnStart.textContent = '■ Stop';
    $btnStart.classList.add('danger');
    setBadge('live', '● Live');
    clearFeedEmpty();
}

function setIdle() {
    running = false;
    $btnStart.textContent = '▶ Start Live Dubbing';
    $btnStart.classList.remove('danger');
    setBadge('idle', 'Idle');
}

const EMOTION_EMOJI = { excited:'😄', humorous:'😄', surprised:'😮', neutral:'😐', concerned:'😟', angry:'😠', sad:'😢' };

window.electronAPI.onOutput(raw => {
    raw.split('\n').forEach(line => {
        line = line.trim();
        if (!line) return;
        const srcM = line.match(/\[(?:stt|worker-\d+)\] (?:SRC: )?(.+)/);
        const dubM = line.match(/\[(?:translate|worker-\d+)\] (?:DUB )?\[(\w+)\]: (.+?)(?:\s+\(lag|\s+\(captured)/);
        if (srcM && !dubM) pendingSrc = srcM[1];
        else if (dubM && pendingSrc) { addEntry(pendingSrc, dubM[2], dubM[1]); pendingSrc = null; }
        else if (line.includes('failed') || line.includes('ERROR')) addRaw('⚠ ' + line);
    });
});

window.electronAPI.onStopped(() => setIdle());

function addEntry(src, dub, emotion = 'neutral') {
    clearFeedEmpty();
    const emoji = EMOTION_EMOJI[emotion] || '😐';
    const div = document.createElement('div');
    div.className = 'feed-item has-dub';
    div.innerHTML = `<div class="feed-src">${esc(src)}</div><div class="feed-dub">${emoji} ${esc(dub)}</div>`;
    $feed.appendChild(div);
    $feed.scrollTop = $feed.scrollHeight;
    while ($feed.children.length > 100) $feed.removeChild($feed.firstChild);
}

function addRaw(text) {
    clearFeedEmpty();
    const div = document.createElement('div');
    div.className = 'feed-item';
    div.innerHTML = `<div class="feed-src">${esc(text)}</div>`;
    $feed.appendChild(div);
    $feed.scrollTop = $feed.scrollHeight;
}

function clearFeedEmpty() {
    const e = $feed.querySelector('.feed-empty');
    if (e) e.remove();
}

$btnClear.addEventListener('click', () => {
    $feed.innerHTML = '<div class="feed-empty">Cleared.</div>';
});

function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
