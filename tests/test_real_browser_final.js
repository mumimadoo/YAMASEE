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

async function runFinalAcceptanceTest() {
    console.log('====================================================');
    console.log(' REAL BROWSER ACCEPTANCE TEST — PRE-RUN DATA FLOW   ');
    console.log('====================================================');

    execSync(`python -c "from database import SessionLocal; from models.user import User; from services.auth_service import create_user, get_user_by_email; db = SessionLocal(); u = get_user_by_email(db, 'final_browser_test@example.com'); create_user(db, 'FinalBrowserUser', 'final_browser_test@example.com', 'Password123!') if not u else None; db.close()"`, { cwd: 'E:\\WeFool' });

    const env = Object.assign({}, process.env, {
        APP_ENV: 'development',
        APP_SECRET_KEY: 'browser_final_secret_key_999'
    });

    const serverProc = spawn('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', `--port=${PORT}`, '--workers', '1'], { env, cwd: 'E:\\WeFool' });

    const reportData = {};

    try {
        await waitForServer(`${BASE_URL}/health`);
        console.log('Server is healthy on port ' + PORT);

        const browser = await puppeteer.launch({
            executablePath: EDGE_PATH,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const page = await browser.newPage();

        // Login
        console.log('Logging into YAMASEE UI...');
        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('#email', 'final_browser_test@example.com');
        await page.type('#password', 'Password123!');
        
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('#submitBtn')
        ]);

        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle0' });
        console.log('Dashboard loaded successfully.');

        // --------------------------------------------------
        // TEST 1: NEW YOUTUBE URL #1
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

        // Wait for duration resolution
        for (let i = 0; i < 15; i++) {
            await delay(1000);
            const currentDur = await page.evaluate(() => document.getElementById('est-duration')?.innerText);
            if (currentDur && currentDur.includes(':') && !currentDur.includes('กำลัง')) {
                break;
            }
        }

        reportData.YOUTUBE_1 = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            cacheStatus: window.currentPreCheckData?.cache_exists ? 'HIT' : 'MISS'
        }));
        console.log('YOUTUBE #1 RESULT:', reportData.YOUTUBE_1);

        await page.click('#btnModalCancel');
        await delay(500);

        // --------------------------------------------------
        // TEST 2: NEW YOUTUBE URL #2
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

        reportData.YOUTUBE_2 = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText,
            cacheStatus: window.currentPreCheckData?.cache_exists ? 'HIT' : 'MISS'
        }));
        console.log('YOUTUBE #2 RESULT:', reportData.YOUTUBE_2);

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

        reportData.TIKTOK = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText
        }));
        console.log('TIKTOK RESULT:', reportData.TIKTOK);

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

        reportData.MP4 = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText
        }));
        console.log('MP4 RESULT:', reportData.MP4);

        console.log('\n====================================================');
        console.log('     REAL BROWSER ACCEPTANCE TEST COMPLETED         ');
        console.log('====================================================');

    } catch (e) {
        console.error('Browser Acceptance Test Error:', e);
    } finally {
        serverProc.kill();
        process.exit(0);
    }
}

runFinalAcceptanceTest();
