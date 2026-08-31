window.WeFoolApp = window.WeFoolApp || {};
window.WeFoolApp.api = {};
window.WeFoolApp.time = {};
window.WeFoolApp.format = {};
window.WeFoolApp.player = {};


window.WeFoolApp.state = {
    globalTimelineData: [],
    originalThaiTextArray: [],
    globalKeywordsChartData: [],
    keywordBarChartInstance: null,
    activeYtPlayer: null,
    ytTimerInterval: null,
    globalCommunicationIntervals: [],
    activeCommunicationRow: null,
    lastCommunicationIndex: -1,
    globalCanonicalEmotion: "ไม่ระบุ"
};

// Define getter/setter on window for compatibility with any legacy scripts/tests expecting global variable access
[
    'globalTimelineData',
    'originalThaiTextArray',
    'globalKeywordsChartData',
    'keywordBarChartInstance',
    'activeYtPlayer',
    'ytTimerInterval',
    'globalCommunicationIntervals',
    'activeCommunicationRow',
    'lastCommunicationIndex',
    'globalCanonicalEmotion'
].forEach(prop => {
    Object.defineProperty(window, prop, {
        get: () => window.WeFoolApp.state[prop],
        set: (val) => { window.WeFoolApp.state[prop] = val; },
        configurable: true
    });
});
