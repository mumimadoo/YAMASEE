const puppeteer = require('puppeteer-core');
const { spawn, execSync } = require('child_process');
const http = require('http');
const path = require('path');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 8099;
const BASE_URL = `http://127.0.0.1:${PORT}`;

const delay = ms => new Promise(r => setTimeout(r, ms));

function waitForServer(url, timeoutMs = 15000) {
    const start = Date.now();
    return new Promise((resolve, reject) => {
        const check = () => {
            http.get(url, res => {
                if (res.statusCode === 200) resolve();
                else if (Date.now() - start > timeoutMs) reject(new Error('Server timeout'));
                else setTimeout(check, 500);
            }).on('error', () => {
                if (Date.now() - start > timeoutMs) reject(new Error('Server connection timeout'));
                else setTimeout(check, 500);
            });
        };
        check();
    });
}

async function runAllThreeSourcesTest() {
    console.log('====================================================');
    console.log(' REAL BROWSER VERIFICATION — ALL THREE INPUT FLOWS ');
    console.log('====================================================');

    console.log('Seeding test user in database...');
    execSync(`python -c "from database import SessionLocal; from models.user import User; from services.auth_service import create_user, get_user_by_email; db = SessionLocal(); u = get_user_by_email(db, 'all_sources_test@example.com'); create_user(db, 'AllSourcesUser', 'all_sources_test@example.com', 'Password123!') if not u else None; db.close()"`, { cwd: 'E:\\WeFool' });

    const env = Object.assign({}, process.env, {
        APP_ENV: 'development',
        APP_SECRET_KEY: 'browser_pre_run_secret_key_999'
    });

    const serverProc = spawn('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', `--port=${PORT}`, '--workers', '1'], { env, cwd: 'E:\\WeFool' });

    const results = {};

    try {
        console.log('Starting Uvicorn test server...');
        await waitForServer(`${BASE_URL}/health`);
        console.log('Server healthy on port ' + PORT);

        const browser = await puppeteer.launch({
            executablePath: EDGE_PATH,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const page = await browser.newPage();

        // Login
        console.log('Logging in...');
        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('#email', 'all_sources_test@example.com');
        await page.type('#password', 'Password123!');
        
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('#submitBtn')
        ]);

        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle0' });
        console.log('Dashboard ready.');

        // --------------------------------------------------
        // TEST 1: YOUTUBE
        // --------------------------------------------------
        console.log('\n--- TEST 1: YOUTUBE URL ---');
        await page.evaluate(() => {
            const rad = document.querySelector('input[name="mediaMode"][value="youtube"]');
            if (rad) { rad.checked = true; rad.dispatchEvent(new Event('change')); }
            const inp = document.getElementById('youtubeUrl');
            if (inp) inp.value = '';
        });

        const newYtUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
        await page.type('#youtubeUrl', newYtUrl);
        await page.click('.btn-process');

        await page.waitForFunction(() => {
            const modal = document.getElementById('tokenEstimatorModal');
            return modal && getComputedStyle(modal).display !== 'none';
        }, { timeout: 3000 });

        // Wait up to 15s for YouTube duration to resolve
        for (let i = 0; i < 15; i++) {
            await delay(1000);
            const currentDur = await page.evaluate(() => document.getElementById('est-duration')?.innerText);
            if (currentDur && currentDur.includes(':') && !currentDur.includes('กำลัง')) {
                break;
            }
        }

        results.YOUTUBE = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            confidence: document.getElementById('est-confidence')?.innerText
        }));
        console.log('YOUTUBE RESULT:', results.YOUTUBE);

        // Test Model Dropdown Switch for YouTube
        await page.select('#estimatorModelSelect', 'gemini-3.6-flash');
        await delay(300);
        results.YOUTUBE_RECALC = await page.evaluate(() => ({
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            confidence: document.getElementById('est-confidence')?.innerText
        }));
        console.log('YOUTUBE MODEL SWITCH RECALC (Gemini 3.6 Flash):', results.YOUTUBE_RECALC);

        // Close modal
        await page.click('#btnModalCancel');
        await delay(500);

        // --------------------------------------------------
        // TEST 2: MP4 LOCAL FILE
        // --------------------------------------------------
        console.log('\n--- TEST 2: MP4 LOCAL FILE ---');
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

        results.MP4 = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            confidence: document.getElementById('est-confidence')?.innerText
        }));
        console.log('MP4 RESULT:', results.MP4);

        // Test Model Dropdown Switch for MP4
        await page.select('#estimatorModelSelect', 'gemini-2.5-flash-lite');
        await delay(300);
        results.MP4_RECALC = await page.evaluate(() => ({
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            confidence: document.getElementById('est-confidence')?.innerText
        }));
        console.log('MP4 MODEL SWITCH RECALC (Gemini 2.5 Flash-Lite):', results.MP4_RECALC);

        // Close modal
        await page.click('#btnModalCancel');
        await delay(500);

        // --------------------------------------------------
        // TEST 3: TIKTOK URL
        // --------------------------------------------------
        console.log('\n--- TEST 3: TIKTOK URL ---');
        await page.evaluate(() => {
            const rad = document.querySelector('input[name="mediaMode"][value="youtube"]');
            if (rad) { rad.checked = true; rad.dispatchEvent(new Event('change')); }
            const inp = document.getElementById('youtubeUrl');
            if (inp) inp.value = '';
        });

        const tiktokUrl = 'https://www.tiktok.com/@scout2015/video/6718335390841670917';
        await page.type('#youtubeUrl', tiktokUrl);
        await page.click('.btn-process');

        await page.waitForFunction(() => {
            const modal = document.getElementById('tokenEstimatorModal');
            return modal && getComputedStyle(modal).display !== 'none';
        }, { timeout: 3000 });

        // Wait up to 15s for TikTok to settle into READY or FAILED state
        for (let i = 0; i < 15; i++) {
            await delay(1000);
            const currentDur = await page.evaluate(() => document.getElementById('est-duration')?.innerText);
            if (currentDur && !currentDur.includes('กำลัง')) {
                break;
            }
        }

        results.TIKTOK = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            confidence: document.getElementById('est-confidence')?.innerText,
            note: document.getElementById('est-confidence-note')?.innerText
        }));
        console.log('TIKTOK RESULT:', results.TIKTOK);

        console.log('\n====================================================');
        console.log('            ALL THREE SOURCES TEST FINISHED         ');
        console.log('====================================================');

    } catch (err) {
        console.error('❌ Browser Test Error:', err);
    } finally {
        serverProc.kill();
        process.exit(0);
    }
}

runAllThreeSourcesTest();
