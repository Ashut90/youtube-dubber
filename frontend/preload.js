const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    // Live dubbing
    startDub:   (lang, gender) => ipcRenderer.invoke('start-dub', lang, gender),
    stopDub:    ()             => ipcRenderer.invoke('stop-dub'),
    onOutput:   (cb)           => ipcRenderer.on('dub-output',  (_e, line) => cb(line)),
    onStopped:  (cb)           => ipcRenderer.on('dub-stopped', (_e)       => cb()),

    // Video URL processing
    processVideo:   (url, lang, gender) => ipcRenderer.invoke('process-video', url, lang, gender),
    onMpvReady:     (cb) => ipcRenderer.on('mpv-ready',        (_e)      => cb()),
    onMpvTime:      (cb) => ipcRenderer.on('mpv-time',         (_e, t)   => cb(t)),
    onMpvPause:     (cb) => ipcRenderer.on('mpv-pause',        (_e, p)   => cb(p)),
    onMpvStopped:   (cb) => ipcRenderer.on('mpv-stopped',      (_e)      => cb()),
    onSegment:      (cb) => ipcRenderer.on('process-segment',  (_e, seg) => cb(seg)),
    onProgress:     (cb) => ipcRenderer.on('process-progress', (_e, msg) => cb(msg)),
    onProcessDone:  (cb) => ipcRenderer.on('process-done',     (_e)      => cb()),
    onProcessError: (cb) => ipcRenderer.on('process-error',    (_e, msg) => cb(msg)),

    setMpvVolume:   (v)              => ipcRenderer.invoke('set-mpv-volume', v),
    mpvSetPause:    (p)              => ipcRenderer.invoke('mpv-set-pause', p),
    playDub:        (id, p, off, v, segEnd) => ipcRenderer.invoke('play-dub', id, p, off, v, segEnd),
    stopDubAudio:   ()              => ipcRenderer.invoke('stop-dub-audio'),

    // File reading for dubbed audio buffers
    readFile:       (p) => ipcRenderer.invoke('read-file', p),
    readFileBinary: (p) => ipcRenderer.invoke('read-file-binary', p),
});
