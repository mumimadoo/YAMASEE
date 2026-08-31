window.WeFoolApp = window.WeFoolApp || {};
window.WeFoolApp.time = window.WeFoolApp.time || {};

function formatToExecutiveTime(totalSeconds) {
    const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
    const secs = Math.floor(totalSeconds % 60).toString().padStart(2, '0');
    return `${minutes}:${secs}`;
}

function formatTranscriptTime(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) return "--:--";
    return formatToExecutiveTime(seconds);
}

function formatSecondsToLabel(totalSeconds) {
    const totalSecInt = Math.floor(totalSeconds);
    const hours = Math.floor(totalSecInt / 3600);
    const minutes = Math.floor((totalSecInt % 3600) / 60);
    const seconds = totalSecInt % 60;
    if (hours > 0) {
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

function parseCommunicationTimeToSeconds(value) {
    if (typeof value !== "string") {
        return null;
    }

    const parts = value
        .trim()
        .split(":")
        .map(Number);

    if (
        parts.some(
            (part) => !Number.isFinite(part)
        )
    ) {
        return null;
    }

    if (parts.length === 2) {
        return parts[0] * 60 + parts[1];
    }

    if (parts.length === 3) {
        return (
            parts[0] * 3600
            + parts[1] * 60
            + parts[2]
        );
    }

    return null;
}

function formatProcessingTime(sec) {
    if (sec === null || sec === undefined) return '00:00:00';
    const num = parseFloat(sec);
    if (isNaN(num) || !isFinite(num) || num < 0) return '00:00:00';
    
    const rounded = Math.round(num);
    const h = Math.floor(rounded / 3600);
    const m = Math.floor((rounded % 3600) / 60);
    const s = rounded % 60;
    
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

window.WeFoolApp.time.formatToExecutiveTime = formatToExecutiveTime;
window.WeFoolApp.time.formatTranscriptTime = formatTranscriptTime;
window.WeFoolApp.time.formatSecondsToLabel = formatSecondsToLabel;
window.WeFoolApp.time.parseCommunicationTimeToSeconds = parseCommunicationTimeToSeconds;
window.WeFoolApp.time.formatProcessingTime = formatProcessingTime;

// Global compatibility wrappers
window.formatToExecutiveTime = formatToExecutiveTime;
window.formatTranscriptTime = formatTranscriptTime;
window.formatSecondsToLabel = formatSecondsToLabel;
window.parseCommunicationTimeToSeconds = parseCommunicationTimeToSeconds;
window.formatProcessingTime = formatProcessingTime;

