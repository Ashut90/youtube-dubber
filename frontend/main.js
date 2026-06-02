const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('child_process');
const net  = require('net');
const path = require('path');
const fs   = require('fs');

const _origError = console.error.bind(console);
console.error = (...a) => {
    if (typeof a[0] === 'string' && a[0].startsWith('Error sending from webFrameMain')) return;
    _origError(...a);
};

let mainWindow;
let rendererReady = false;
let dubProcess    = null;
let videoProcess  = null;
let mpvProcess    = null;
let mpvIpc        = null;
let latestMpvTime = 0;   // current video playhead, updated by the time-pos observer

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 980, height: 780,
        minWidth: 680, minHeight: 560,
        backgroundColor: '#0f0f1a',
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            autoplayPolicy: 'no-user-gesture-required',
        },
    });
    mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
    mainWindow.webContents.on('did-start-loading', () => { rendererReady = false; });
    mainWindow.webContents.on('did-finish-load',   () => { rendererReady = true;  });
    mainWindow.webContents.on('destroyed',         () => { rendererReady = false; });
    let lastCrash = 0;
    mainWindow.webContents.on('render-process-gone', (_e, details) => {
        console.error('[renderer crashed]', details.reason, 'exitCode:', details.exitCode);
        rendererReady = false;
        // Kill background processes so the reloaded page isn't flooded with IPC events
        killMpv();
        if (videoProcess) { videoProcess.kill(); videoProcess = null; }
        const now = Date.now();
        if (now - lastCrash < 3000) {
            console.error('[crash loop] crashing too fast — not reloading');
            return;
        }
        lastCrash = now;
        setTimeout(() => {
            if (mainWindow && !mainWindow.isDestroyed())
                mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
        }, 500);
    });
    mainWindow.on('close',  () => { rendererReady = false; });
    mainWindow.on('closed', () => { mainWindow = null; rendererReady = false; });
}

function send(channel, ...args) {
    if (!rendererReady || !mainWindow || mainWindow.isDestroyed()) return;
    if (mainWindow.webContents.isDestroyed()) return;
    try { mainWindow.webContents.send(channel, ...args); } catch (_) {}
}

const py         = process.platform === 'win32' ? 'python' : 'python3';
const backendDir = path.join(__dirname, '..', 'backend');

// ── mpv video player ──────────────────────────────────────────────────────────
function killMpv() {
    if (mpvIpc)     { try { mpvIpc.destroy(); } catch(_){} mpvIpc = null; }
    if (mpvProcess) { try { mpvProcess.kill(); } catch(_){} mpvProcess = null; }
}

// Connect to mpv's IPC endpoint, retrying until mpv has created it (up to ~15s).
// Works for both Unix domain sockets and Windows named pipes — net.connect()
// accepts either path form; we just retry until the connection succeeds.
function connectMpvIpc(ipcPath) {
    return new Promise((resolve, reject) => {
        let attempts = 0;
        const tryConnect = () => {
            const sock = net.connect(ipcPath);
            sock.once('connect', () => resolve(sock));
            sock.once('error', () => {
                sock.destroy();
                if (++attempts > 30) { reject(new Error('mpv IPC did not become available')); return; }
                setTimeout(tryConnect, 500);
            });
        };
        setTimeout(tryConnect, 800);   // give mpv a moment to start
    });
}

async function playWithMpv(videoUrl) {
    killMpv();

    // Windows uses named pipes (\\.\pipe\name); Unix uses a socket file path.
    const isWin   = process.platform === 'win32';
    const ipcPath = isWin
        ? `\\\\.\\pipe\\mpv-dubber-${process.pid}`
        : path.join(app.getPath('temp'), 'mpv-dubber.sock');
    if (!isWin) { try { fs.unlinkSync(ipcPath); } catch (_) {} }

    // Strip any &t=/?t= start-time from the URL — Python dubs sequentially from
    // t=0, so the video must also start at 0 for the dub to be in sync.
    const cleanUrl = videoUrl.replace(/([?&])t=\d+s?/g, '$1').replace(/[?&]$/, '');

    send('process-progress', { step: 'stream', pct: 10, msg: 'Starting mpv…' });

    mpvProcess = spawn('mpv', [
        cleanUrl,
        '--no-terminal',
        '--keep-open=yes',
        '--start=0',      // always begin at 0 to match sequential dub generation
        `--input-ipc-server=${ipcPath}`,
        '--title=YT Dubber — Video',
        '--ytdl-format=18/22/best[ext=mp4]/best',
        '--volume=30',    // start quiet — dubbed audio is the main track
    ]);

    mpvProcess.stderr.on('data', d => {
        const m = d.toString().trim();
        if (m) console.error('[mpv]', m);
    });
    mpvProcess.on('close', () => { mpvProcess = null; send('mpv-stopped'); });

    // Connect to mpv IPC (named pipe on Windows, socket on Unix) and observe state
    mpvIpc = await connectMpvIpc(ipcPath);
    let buf = '';
    let lastTimeSend = 0;

    // Already connected — send the initial commands now (no 'connect' event to wait for)
    mpvIpc.write(JSON.stringify({ command: ['set_property', 'pause', true]     }) + '\n');
    mpvIpc.write(JSON.stringify({ command: ['observe_property', 1, 'time-pos'] }) + '\n');
    mpvIpc.write(JSON.stringify({ command: ['observe_property', 2, 'pause']    }) + '\n');
    send('process-progress', { step: 'stream', pct: 100, msg: 'Buffering dubbed audio…' });
    send('mpv-ready');

    mpvIpc.on('data', data => {
        buf += data.toString();
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
            if (!line.trim()) continue;
            try {
                const msg = JSON.parse(line);
                if (msg.event === 'property-change') {
                    if (msg.name === 'time-pos' && msg.data != null) {
                        latestMpvTime = msg.data;   // track playhead for stale-drop logic
                        // Throttle to 10 updates/sec — mpv fires at ~30fps which floods the renderer
                        const now = Date.now();
                        if (now - lastTimeSend >= 100) {
                            send('mpv-time', msg.data);
                            lastTimeSend = now;
                        }
                    }
                    if (msg.name === 'pause') send('mpv-pause', msg.data);
                }
            } catch (_) {}
        }
    });

    mpvIpc.on('error', err => console.error('[mpv IPC]', err.message));
}

// ── Live dubbing ──────────────────────────────────────────────────────────────
ipcMain.handle('start-dub', (_e, lang, gender) => {
    // Live Dub requires PulseAudio — only available on Linux
    if (process.platform !== 'linux') {
        send('dub-output', `⚠️  Live Dub is Linux-only (requires PulseAudio).\nUse the Video URL tab instead — it works on all platforms.`);
        send('dub-stopped');
        return;
    }
    if (dubProcess) return;
    dubProcess = spawn(py, ['live_dub_v6.py', '--lang', lang, '--gender', gender], {
        cwd: backendDir, env: { ...process.env },
    });
    dubProcess.stdout.on('data', d => send('dub-output', d.toString()));
    dubProcess.stderr.on('data', d => send('dub-output', d.toString()));
    dubProcess.on('close', () => { dubProcess = null; send('dub-stopped'); });
});

ipcMain.handle('stop-dub', () => {
    if (dubProcess) { dubProcess.kill(); dubProcess = null; }
});

// ── Video URL processing ──────────────────────────────────────────────────────
ipcMain.handle('process-video', async (_e, url, lang, gender) => {
    if (videoProcess) { videoProcess.kill(); videoProcess = null; }

    send('process-progress', { step: 'stream', pct: 0, msg: 'Launching mpv…' });

    try {
        await playWithMpv(url);
    } catch (err) {
        send('process-error', 'Could not start mpv: ' + err.message);
        return;
    }

    // Python backend: captions + translate + TTS
    const outDir = path.join(app.getPath('userData'), 'dubout');
    fs.mkdirSync(outDir, { recursive: true });

    videoProcess = spawn(py, [
        'dub_video.py', '--url', url, '--lang', lang, '--gender', gender, '--out', outDir,
    ], { cwd: backendDir, env: { ...process.env } });

    videoProcess.stdout.on('data', data => {
        data.toString().split('\n').forEach(line => {
            line = line.trim();
            if (!line) return;
            try {
                const msg = JSON.parse(line);
                if      (msg.type === 'segment')  send('process-segment',  msg);
                else if (msg.type === 'progress') send('process-progress', msg);
                else if (msg.type === 'done')     { send('process-done'); videoProcess = null; }
                else if (msg.type === 'error')    { send('process-error', msg.msg); videoProcess = null; }
            } catch (_) { send('dub-output', line); }
        });
    });

    videoProcess.stderr.on('data', d => {
        const msg = d.toString().trim();
        if (msg) { console.error('[python]', msg); send('dub-output', msg); }
    });
    videoProcess.on('close', code => {
        console.log('[python] exited with code', code);
        if (videoProcess && code !== 0) send('process-error', `Processing ended (code ${code})`);
        videoProcess = null;
    });
});

// ── mpv playback control ──────────────────────────────────────────────────────
ipcMain.handle('mpv-set-pause', (_e, paused) => {
    if (mpvIpc) mpvIpc.write(JSON.stringify({ command: ['set_property', 'pause', paused] }) + '\n');
});

// ── mpv volume control ────────────────────────────────────────────────────────
ipcMain.handle('set-mpv-volume', (_e, vol) => {
    if (mpvIpc) {
        const pct = Math.round(vol * 100);
        mpvIpc.write(JSON.stringify({ command: ['set_property', 'volume', pct] }) + '\n');
    }
});

// ── Dubbed segment playback ───────────────────────────────────────────────────
// Sequential queue: each dub clip plays to completion before the next starts,
// so sentences are never cut off mid-word. If a clip falls too far behind the
// video playhead (its segment already ended >STALE_DROP s ago), it's skipped
// entirely rather than played late — keeps audio roughly in sync.
const STALE_DROP  = 4;            // seconds: drop dub if segment ended this far behind
let   dubQueue    = [];           // [{id, file, offset, volume, segEnd}]
let   dubProc     = null;         // currently playing mpv audio process
let   dubPlaying  = false;

function killAllAudio() {
    dubQueue = [];
    if (dubProc) { try { dubProc.kill('SIGKILL'); } catch(_){} dubProc = null; }
    dubPlaying = false;
}

function pumpDubQueue() {
    if (dubPlaying) return;
    // Drop stale clips whose segment already passed well behind the playhead
    while (dubQueue.length && dubQueue[0].segEnd < latestMpvTime - STALE_DROP) {
        dubQueue.shift();
    }
    if (!dubQueue.length) return;

    const item = dubQueue.shift();
    dubPlaying = true;
    dubProc = spawn('mpv', [
        item.file,
        '--no-video', '--no-terminal', '--no-loop',
        `--start=${item.offset.toFixed(2)}`,
        `--volume=${Math.round(item.volume * 100)}`,
    ]);
    dubProc.on('close', () => { dubProc = null; dubPlaying = false; pumpDubQueue(); });
    dubProc.on('error', () => { dubProc = null; dubPlaying = false; pumpDubQueue(); });
}

ipcMain.handle('play-dub', (_e, id, filePath, offset, volume, segEnd) => {
    dubQueue.push({ id, file: filePath, offset, volume, segEnd: segEnd || 0 });
    pumpDubQueue();
});

ipcMain.handle('stop-dub-audio', () => { killAllAudio(); });

// ── File access ───────────────────────────────────────────────────────────────
ipcMain.handle('read-file',        (_e, p) => fs.readFileSync(p, 'utf-8'));
ipcMain.handle('read-file-binary', (_e, p) => fs.readFileSync(p).buffer);

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(() => {
    createWindow();
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

function cleanupAll() {
    if (dubProcess)   { dubProcess.kill();   dubProcess   = null; }
    if (videoProcess) { videoProcess.kill(); videoProcess = null; }
    killMpv();
    killAllAudio();
}

app.on('window-all-closed', () => {
    cleanupAll();
    if (process.platform !== 'darwin') app.quit();
});
app.on('before-quit', () => { cleanupAll(); });
