const fs = require('fs');
const path = require('path');

console.log('=== RUNNING SECTION 2 FRONTEND VERIFICATION TESTS (CASES A-G) ===');

// Lightweight DOM mock
let innerHTMLStore = '';
const mockContainer = {
    get innerHTML() { return innerHTMLStore; },
    set innerHTML(val) { innerHTMLStore = val; }
};

const listeners = {};

const domLoadedListeners = [];
const mockDocument = {
    addEventListener: (evt, fn) => {
        if (evt === 'DOMContentLoaded') domLoadedListeners.push(fn);
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: (id) => {
        if (id === 'topicsDifferencesContainer') return mockContainer;
        return {
            addEventListener: () => {},
            set onclick(fn) { listeners[id] = fn; },
            get onclick() { return listeners[id]; },
            click: () => { if (listeners[id]) listeners[id](); }
        };
    }
};

global.window = {};
global.document = mockDocument;
global.escapeHtml = (str) => String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Read static/js/comparison.js code
const jsPath = path.join(__dirname, '../static/js/comparison.js');
const jsCode = fs.readFileSync(jsPath, 'utf8');

const mockSessionStorage = {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {}
};

const winObj = {
    location: { pathname: '/comparison', search: '' },
    sessionStorage: mockSessionStorage
};
global.window = winObj;
global.sessionStorage = mockSessionStorage;
global.document = mockDocument;
global.escapeHtml = (str) => String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Evaluate in global scope
const fn = new Function('window', 'document', 'escapeHtml', jsCode);
fn(winObj, mockDocument, global.escapeHtml);
domLoadedListeners.forEach(f => f());

const renderSection02 = winObj.renderSection02TopicsDifferences || window.renderSection02TopicsDifferences;
if (typeof renderSection02 !== 'function') {
    console.error('ERROR: renderSection02TopicsDifferences is not defined on window');
    process.exit(1);
}

function getContainerHTML() {
    return innerHTMLStore;
}

// -------------------------------------------------------------
// TEST CASE A: Completely Different Videos
// -------------------------------------------------------------
console.log('\n[CASE A] Videos talk about completely different topics...');
const contractCaseA = {
    topic_analysis: {
        video_a_topics: [{ title: "การปราบปรามเว็บพนันออนไลน์", description: "รายละเอียดคดีจับกุม" }],
        video_b_topics: [{ title: "การทำสวนทุเรียนนอกฤดู", description: "เทคนิคการให้น้ำและปุ๋ย" }],
        key_differences: [
            {
                title: "ขอบเขตและประเภทของเนื้อหาอยู่คนละสาขา",
                video_a: "เน้นปราบปรามอาชญากรรมทางเทคโนโลยี",
                video_b: "เน้นการเกษตรและการเพิ่มผลผลิต",
                significance: "สองคลิปนี้ไม่มีความเกี่ยวข้องกันในเชิงประเด็น"
            }
        ]
    }
};

renderSection02([], contractCaseA);
let htmlA = getContainerHTML();
console.log('CASE A Rendered HTML contains title:', htmlA.includes('ขอบเขตและประเภทของเนื้อหาอยู่คนละสาขา'));
console.log('CASE A Video A evidence correct:', htmlA.includes('เน้นปราบปรามอาชญากรรมทางเทคโนโลยี'));
console.log('CASE A Video B evidence correct:', htmlA.includes('เน้นการเกษตรและการเพิ่มผลผลิต'));
console.log('CASE A Significance rendered:', htmlA.includes('ทำไมความแตกต่างนี้สำคัญ'));
if (!htmlA.includes('ขอบเขตและประเภทของเนื้อหาอยู่คนละสาขา') || !htmlA.includes('🔵 VIDEO A') || !htmlA.includes('🩷 VIDEO B')) {
    throw new Error('CASE A verification failed!');
}
console.log('✅ CASE A PASS');

// -------------------------------------------------------------
// TEST CASE B: Similar Videos with Different Details
// -------------------------------------------------------------
console.log('\n[CASE B] Similar topics with differing factual details...');
const contractCaseB = {
    topic_analysis: {
        video_a_topics: [{ title: "อัตราดอกเบี้ยสินเชื่อบ้าน", description: "วิเคราะห์ดอกเบี้ยปี 2026" }],
        video_b_topics: [{ title: "อัตราดอกเบี้ยสินเชื่อบ้าน", description: "เปรียบเทียบโปรโมชั่นธนาคาร" }],
        key_differences: [
            {
                title: "ข้อมูลตัวเลขดอกเบี้ยเฉลี่ย 3 ปีแรก",
                video_a: "ระบุอัตราเฉลี่ย 2.5% ต่อปี",
                video_b: "ระบุอัตราเฉลี่ย 3.1% ต่อปี",
                significance: "ทำให้การคำนวณค่างวดรายเดือนต่างกันอย่างมีนัยสำคัญ"
            }
        ]
    }
};

renderSection02([], contractCaseB);
let htmlB = getContainerHTML();
console.log('CASE B Title:', htmlB.includes('ข้อมูลตัวเลขดอกเบี้ยเฉลี่ย 3 ปีแรก'));
console.log('CASE B Video A 2.5%:', htmlB.includes('2.5%'));
console.log('CASE B Video B 3.1%:', htmlB.includes('3.1%'));
if (!htmlB.includes('2.5%') || !htmlB.includes('3.1%')) {
    throw new Error('CASE B verification failed!');
}
console.log('✅ CASE B PASS');

// -------------------------------------------------------------
// TEST CASE C: Very Similar Videos — NO Meaningful Additional Difference
// -------------------------------------------------------------
console.log('\n[CASE C] Very similar videos with NO meaningful additional difference (Empty State)...');
const contractCaseC = {
    topic_analysis: {
        video_a_topics: [{ title: "การทำผัดไทยโบราณ", description: "สูตรน้ำซอสผัดไทย" }],
        video_b_topics: [{ title: "การทำผัดไทยโบราณ", description: "สูตรน้ำซอสผัดไทย" }],
        key_differences: [] // Empty list
    }
};

renderSection02([], contractCaseC);
let htmlC = getContainerHTML();
console.log('CASE C Contains Empty State Title:', htmlC.includes('ไม่พบความแตกต่างเพิ่มเติมที่มีนัยสำคัญ'));
console.log('CASE C Contains Empty Subtitle:', htmlC.includes('ความแตกต่างหลักของวิดีโอทั้งสองครอบคลุมอยู่ในภาพรวมการเปรียบเทียบแล้ว'));
if (!htmlC.includes('ไม่พบความแตกต่างเพิ่มเติมที่มีนัยสำคัญ') || htmlC.includes('undefined')) {
    throw new Error('CASE C verification failed!');
}
console.log('✅ CASE C PASS');

// -------------------------------------------------------------
// TEST CASE D: Old Cached Comparison Schema (Backward Compatibility)
// -------------------------------------------------------------
console.log('\n[CASE D] Legacy cached comparison schema compatibility...');
const contractCaseD = {
    key_differences: [
        {
            dimension: "จุดเน้นของเนื้อหา",
            video_a_perspective: "อธิบายทฤษฎีพื้นฐาน",
            video_b_perspective: "สาธิตการปฏิบัติจริง",
            significance: "เน้นคนละระดับการเรียนรู้"
        }
    ]
};

renderSection02([], contractCaseD);
let htmlD = getContainerHTML();
console.log('CASE D Legacy Title:', htmlD.includes('จุดเน้นของเนื้อหา') || htmlD.includes('ความแตกต่างที่ค้นพบ'));
console.log('CASE D Video A Perspective:', htmlD.includes('อธิบายทฤษฎีพื้นฐาน'));
console.log('CASE D Video B Perspective:', htmlD.includes('สาธิตการปฏิบัติจริง'));
if (!htmlD.includes('อธิบายทฤษฎีพื้นฐาน') || !htmlD.includes('สาธิตการปฏิบัติจริง')) {
    throw new Error('CASE D verification failed!');
}
console.log('✅ CASE D PASS');

// -------------------------------------------------------------
// TEST CASE E: Difference Info present in Video A, missing in Video B
// -------------------------------------------------------------
console.log('\n[CASE E] Info present in A, missing in B...');
const contractCaseE = {
    topic_analysis: {
        video_a_topics: [{ title: "รายละเอียดข้อกฎหมาย", description: "มาตรา 157" }],
        video_b_topics: [{ title: "ภาพรวมเหตุการณ์", description: "ลำดับเวลา" }],
        key_differences: [
            {
                title: "ข้อกฎหมายการปฏิบัติหน้าที่โดยมิชอบ",
                video_a: "อธิบายองค์ประกอบความผิดตามมาตรา 157 อย่างละเอียด",
                video_b: "ไม่พบการกล่าวถึงประเด็นนี้ใน Video B",
                significance: "ทำให้ Video A ให้แง่มุมทางกฎหมายที่ Video B ไม่มี"
            }
        ]
    }
};

renderSection02([], contractCaseE);
let htmlE = getContainerHTML();
console.log('CASE E Video B missing notice:', htmlE.includes('ไม่พบการกล่าวถึงประเด็นนี้ใน Video B'));
if (!htmlE.includes('ไม่พบการกล่าวถึงประเด็นนี้ใน Video B')) {
    throw new Error('CASE E verification failed!');
}
console.log('✅ CASE E PASS');

// -------------------------------------------------------------
// TEST CASE F: Difference Info present in Video B, missing in Video A
// -------------------------------------------------------------
console.log('\n[CASE F] Info present in B, missing in A...');
const contractCaseF = {
    topic_analysis: {
        video_a_topics: [{ title: "ภาพรวมคดี", description: "สรุปข่าว" }],
        video_b_topics: [{ title: "คำสัมภาษณ์ผู้เสียหาย", description: "เสียงจากเหยื่อ" }],
        key_differences: [
            {
                title: "สัมภาษณ์สดผู้ได้รับผลกระทบ",
                video_a: "ไม่พบการกล่าวถึงประเด็นนี้ใน Video A",
                video_b: "สัมภาษณ์เปิดใจแม่ของผู้เสียหายและทนายความ",
                significance: "ทำให้ Video B สะท้อนมุมมองด้านอารมณ์และผลกระทบบุคคล"
            }
        ]
    }
};

renderSection02([], contractCaseF);
let htmlF = getContainerHTML();
console.log('CASE F Video A missing notice:', htmlF.includes('ไม่พบการกล่าวถึงประเด็นนี้ใน Video A'));
if (!htmlF.includes('ไม่พบการกล่าวถึงประเด็นนี้ใน Video A')) {
    throw new Error('CASE F verification failed!');
}
console.log('✅ CASE F PASS');

// -------------------------------------------------------------
// TEST CASE G: Variable Finding Count & Toggle (> 3 Findings)
// -------------------------------------------------------------
console.log('\n[CASE G] Testing variable finding count > 3 and toggle button...');
const contractCaseG = {
    topic_analysis: {
        video_a_topics: [{ title: "Topic A", description: "Desc A" }],
        video_b_topics: [{ title: "Topic B", description: "Desc B" }],
        key_differences: [
            { title: "Finding 1", video_a: "A1", video_b: "B1", significance: "S1" },
            { title: "Finding 2", video_a: "A2", video_b: "B2", significance: "S2" },
            { title: "Finding 3", video_a: "A3", video_b: "B3", significance: "S3" },
            { title: "Finding 4", video_a: "A4", video_b: "B4", significance: "S4" },
            { title: "Finding 5", video_a: "A5", video_b: "B5", significance: "S5" }
        ]
    }
};

renderSection02([], contractCaseG);
let htmlG = getContainerHTML();
console.log('CASE G Contains Toggle Button:', htmlG.includes('btnToggleDifferences'));
console.log('CASE G Toggle Label contains remaining count (2):', htmlG.includes('ดูความแตกต่างเพิ่มเติม (2)'));
if (!htmlG.includes('ดูความแตกต่างเพิ่มเติม (2)')) {
    throw new Error('CASE G verification failed!');
}

// Simulate click on toggle button
const btnToggle = document.getElementById('btnToggleDifferences');
btnToggle.click();
let htmlGExpanded = getContainerHTML();
console.log('CASE G Expanded Contains Finding 5:', htmlGExpanded.includes('Finding 5'));
console.log('CASE G Expanded Button Label:', htmlGExpanded.includes('ซ่อนความแตกต่างเพิ่มเติม'));
if (!htmlGExpanded.includes('Finding 5') || !htmlGExpanded.includes('ซ่อนความแตกต่างเพิ่มเติม')) {
    throw new Error('CASE G expand verification failed!');
}
console.log('✅ CASE G PASS');

console.log('\nALL FRONTEND VERIFICATION TESTS (CASES A-G) PASSED SUCCESSFULLY!');
