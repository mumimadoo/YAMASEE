const puppeteer = require('puppeteer-core');
const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 8080;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const ARTIFACT_DIR = 'C:\\Users\\PookPiK\\.gemini\\antigravity-cli\\brain\\7811d285-3140-4691-a657-1ead2a796389';

const delay = ms => new Promise(r => setTimeout(r, ms));

async function runRealUserFlowVerification8080() {
    console.log('====================================================');
    console.log(' REAL USER FLOW VERIFICATION (PORT 8080)            ');
    console.log('====================================================');

    const pythonExe = 'C:\\Users\\PookPiK\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe';

    // Seed test user in active DB
    execSync(`"${pythonExe}" -c "from database import SessionLocal; from models.user import User; from services.auth_service import create_user, get_user_by_email; db = SessionLocal(); u = get_user_by_email(db, 'real_user8080@example.com'); create_user(db, 'RealUser8080', 'real_user8080@example.com', 'Password123!') if not u else None; db.close()"`, { cwd: 'E:\\WeFool' });

    const report = {
        serverPort: PORT,
        logs: [],
        network: [],
        results: {}
    };

    try {
        console.log(`Connecting to running server on port ${PORT}...`);

        const browser = await puppeteer.launch({
            executablePath: EDGE_PATH,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const page = await browser.newPage();

        page.on('console', msg => {
            const text = msg.text();
            if (text.includes('[PRE-RUN]')) {
                console.log(`[Browser Console Log] ${text}`);
                report.logs.push(text);
            }
        });

        page.on('request', req => {
            if (req.url().includes('/api/resolve_duration')) {
                const info = `[Network OUT] ${req.method()} ${req.url()} - Body: ${req.postData()}`;
                console.log(info);
                report.network.push(info);
            }
        });

        page.on('response', async res => {
            if (res.url().includes('/api/resolve_duration')) {
                let bodyStr = '';
                try { bodyStr = await res.text(); } catch (e) {}
                const info = `[Network IN] ${res.status()} ${res.url()} - Body: ${bodyStr}`;
                console.log(info);
                report.network.push(info);
                report.lastResolveResponse = bodyStr;
            }
        });

        // 1. Login
        console.log('Logging into YAMASEE UI...');
        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('#email', 'real_user8080@example.com');
        await page.type('#password', 'Password123!');
        
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('#submitBtn')
        ]);

        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle0' });
        console.log('Dashboard loaded.');

        // 2. Verify Build Marker
        const buildMarker = await page.evaluate(() => window.YAMASEE_PRE_RUN_BUILD);
        console.log('BUILD MARKER IN BROWSER:', buildMarker);
        report.buildMarker = buildMarker;

        if (buildMarker !== 'FINAL_FIX_2026_08_23') {
            throw new Error(`Build marker mismatch! Got: ${buildMarker}`);
        }

        // --------------------------------------------------
        // TEST 1: NEW YOUTUBE URL #1 (Cache MISS)
        // --------------------------------------------------
        console.log('\n--- TEST 1: NEW YOUTUBE URL #1 ---');
        const yt1 = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
        await page.evaluate(() => {
            const rad = document.querySelector('input[name="mediaMode"][value="youtube"]');
            if (rad) { rad.checked = true; rad.dispatchEvent(new Event('change')); }
            const inp = document.getElementById('youtubeUrl');
            if (inp) inp.value = '';
        });

        await page.type('#youtubeUrl', yt1);
        await page.click('.btn-process');

        await page.waitForFunction(() => {
            const modal = document.getElementById('tokenEstimatorModal');
            return modal && getComputedStyle(modal).display !== 'none';
        }, { timeout: 3000 });

        for (let i = 0; i < 15; i++) {
            await delay(1000);
            const currentDur = await page.evaluate(() => document.getElementById('est-duration')?.innerText);
            if (currentDur && currentDur.includes(':') && !currentDur.includes('กำลัง')) {
                break;
            }
        }

        report.results.YOUTUBE_1 = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            cacheStatus: window.currentPreCheckData?.cache_exists ? 'HIT' : 'MISS'
        }));
        console.log('YOUTUBE #1 DOM:', report.results.YOUTUBE_1);

        // Screenshot modal for user evidence
        const modalElement1 = await page.$('#tokenEstimatorModal');
        if (modalElement1) {
            const ssPath1 = path.join(ARTIFACT_DIR, 'pre_run_modal_user_flow.png');
            await modalElement1.screenshot({ path: ssPath1 });
            console.log(`Saved screenshot to ${ssPath1}`);
            report.screenshot1 = ssPath1;
        }

        await page.click('#btnModalCancel');
        await delay(500);

        // --------------------------------------------------
        // TEST 2: NEW YOUTUBE URL #2 (Cache MISS)
        // --------------------------------------------------
        console.log('\n--- TEST 2: NEW YOUTUBE URL #2 ---');
        const yt2 = 'https://www.youtube.com/watch?v=L_LUpnjgPso';
        await page.evaluate(() => {
            const rad = document.querySelector('input[name="mediaMode"][value="youtube"]');
            if (rad) { rad.checked = true; rad.dispatchEvent(new Event('change')); }
            const inp = document.getElementById('youtubeUrl');
            if (inp) inp.value = '';
        });

        await page.type('#youtubeUrl', yt2);
        await page.click('.btn-process');

        await page.waitForFunction(() => {
            const modal = document.getElementById('tokenEstimatorModal');
            return modal && getComputedStyle(modal).display !== 'none';
        }, { timeout: 3000 });

        for (let i = 0; i < 15; i++) {
            await delay(1000);
            const currentDur = await page.evaluate(() => document.getElementById('est-duration')?.innerText);
            if (currentDur && currentDur.includes(':') && !currentDur.includes('กำลัง')) {
                break;
            }
        }

        report.results.YOUTUBE_2 = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            cacheStatus: window.currentPreCheckData?.cache_exists ? 'HIT' : 'MISS'
        }));
        console.log('YOUTUBE #2 DOM:', report.results.YOUTUBE_2);

        await page.click('#btnModalCancel');
        await delay(500);

        // --------------------------------------------------
        // TEST 3: TIKTOK URL
        // --------------------------------------------------
        console.log('\n--- TEST 3: TIKTOK URL ---');
        const tiktokUrl = 'https://www.tiktok.com/@scout2015/video/6718335390841670917';
        await page.evaluate(() => {
            const rad = document.querySelector('input[name="mediaMode"][value="youtube"]');
            if (rad) { rad.checked = true; rad.dispatchEvent(new Event('change')); }
            const inp = document.getElementById('youtubeUrl');
            if (inp) inp.value = '';
        });

        await page.type('#youtubeUrl', tiktokUrl);
        await page.click('.btn-process');

        await page.waitForFunction(() => {
            const modal = document.getElementById('tokenEstimatorModal');
            return modal && getComputedStyle(modal).display !== 'none';
        }, { timeout: 3000 });

        for (let i = 0; i < 15; i++) {
            await delay(1000);
            const currentDur = await page.evaluate(() => document.getElementById('est-duration')?.innerText);
            if (currentDur && !currentDur.includes('กำลัง')) {
                break;
            }
        }

        report.results.TIKTOK = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText
        }));
        console.log('TIKTOK DOM:', report.results.TIKTOK);

        await page.click('#btnModalCancel');
        await delay(500);

        // --------------------------------------------------
        // TEST 4: MP4 LOCAL FILE
        // --------------------------------------------------
        console.log('\n--- TEST 4: MP4 LOCAL FILE ---');
        await page.evaluate(() => {
            const rad = document.querySelector('input[name="mediaMode"][value="mp4"]');
            if (rad) { rad.checked = true; rad.dispatchEvent(new Event('change')); }
        });

        const mp4Path = path.join('E:\\WeFool', 'test_sample.mp4');
        const fileInputHandle = await page.$('#mediaFile');
        await fileInputHandle.uploadFile(mp4Path);
        await delay(200);

        await page.click('.btn-process');

        await page.waitForFunction(() => {
            const modal = document.getElementById('tokenEstimatorModal');
            return modal && getComputedStyle(modal).display !== 'none';
        }, { timeout: 3000 });

        await delay(1000);

        report.results.MP4 = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText
        }));
        console.log('MP4 DOM:', report.results.MP4);

        console.log('\n====================================================');
        console.log('   PORT 8080 USER FLOW VERIFICATION COMPLETED       ');
        console.log('====================================================');

    } catch (e) {
        console.error('Verification Error:', e);
        report.error = e.message;
    } finally {
        fs.writeFileSync(path.join(ARTIFACT_DIR, 'verification_report_8080.json'), JSON.stringify(report, null, 2));
        process.exit(0);
    }
}

runRealUserFlowVerification8080();
