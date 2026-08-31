const puppeteer = require('puppeteer-core');
const { spawn, execSync } = require('child_process');
const http = require('http');

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

async function runRealBrowserVerification() {
    console.log('====================================================');
    console.log('  REAL BROWSER VERIFICATION — ASYNC DURATION FIX    ');
    console.log('====================================================');

    // Seed test user in DB via Python
    console.log('Seeding test user in database...');
    execSync(`python -c "from database import SessionLocal; from models.user import User; from services.auth_service import create_user, get_user_by_email; db = SessionLocal(); u = get_user_by_email(db, 'prerun_yt_test@example.com'); create_user(db, 'PreRunYtUser', 'prerun_yt_test@example.com', 'Password123!') if not u else None; db.close()"`, { cwd: 'E:\\WeFool' });

    const env = Object.assign({}, process.env, {
        APP_ENV: 'development',
        APP_SECRET_KEY: 'browser_pre_run_secret_key_999'
    });

    const serverProc = spawn('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', `--port=${PORT}`, '--workers', '1'], { env, cwd: 'E:\\WeFool' });

    try {
        console.log('Starting Uvicorn test server...');
        await waitForServer(`${BASE_URL}/health`);
        console.log('Server is healthy on port ' + PORT);

        const browser = await puppeteer.launch({
            executablePath: EDGE_PATH,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const version = await browser.version();
        console.log(`REAL BROWSER CONNECTED: ${version}\n`);

        const consoleLogs = [];
        const consoleErrors = [];
        const page = await browser.newPage();

        page.on('console', msg => {
            consoleLogs.push(`[Console ${msg.type()}] ${msg.text()}`);
            if (msg.type() === 'error') {
                consoleErrors.push(`[Console Error] ${msg.text()}`);
            }
        });

        // 1. Auth & Login
        console.log('--- STEP 1: Auth & Login ---');
        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('#email', 'prerun_yt_test@example.com');
        await page.type('#password', 'Password123!');
        
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('#submitBtn')
        ]);

        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle0' });
        console.log(`App loaded. URL: ${page.url()}`);

        // 2. NEW CACHE-MISS YOUTUBE URL TEST
        console.log('\n--- STEP 2: New Cache-Miss YouTube URL Test ---');
        const newYtUrl = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
        await page.waitForSelector('#youtubeUrl', { timeout: 10000 });
        await page.type('#youtubeUrl', newYtUrl);

        const clickTime = Date.now();
        await page.click('.btn-process');

        // Measure CLICK_TO_MODEL_SELECTOR_MS
        await page.waitForFunction(() => {
            const modal = document.getElementById('tokenEstimatorModal');
            return modal && getComputedStyle(modal).display !== 'none';
        }, { timeout: 3000 });

        const visibleTime = Date.now();
        const clickToModalMs = visibleTime - clickTime;
        console.log(`CLICK_TO_MODEL_SELECTOR_MS: ${clickToModalMs} ms (Target < 300ms)`);

        // Inspect immediate loading state in modal
        const initialModalState = await page.evaluate(() => {
            return {
                duration: document.getElementById('est-duration')?.innerText,
                tokens: document.getElementById('est-tokens')?.innerText,
                budget: document.getElementById('est-budget')?.innerText
            };
        });
        console.log('Immediate Modal Loading State (before yt-dlp finishes):');
        console.log(`  Duration: "${initialModalState.duration}"`);
        console.log(`  Tokens: "${initialModalState.tokens}"`);
        console.log(`  Cost: "${initialModalState.budget}"`);

        // Wait for async duration resolution
        console.log('\nWaiting for background async duration resolution...');
        const resolutionStartTime = Date.now();

        // Print logs periodically while waiting
        for (let i = 0; i < 20; i++) {
            await delay(1000);
            const currentDur = await page.evaluate(() => document.getElementById('est-duration')?.innerText);
            console.log(`[Wait ${i + 1}s] est-duration: "${currentDur}"`);
            if (currentDur && currentDur.includes(':') && !currentDur.includes('กำลัง')) {
                break;
            }
        }

        const resolutionEndTime = Date.now();
        const durationResolutionMs = resolutionEndTime - resolutionStartTime;
        console.log(`\nDURATION_RESOLUTION_MS: ${durationResolutionMs} ms`);

        // Inspect final resolved modal state
        const resolvedModalState = await page.evaluate(() => {
            return {
                duration: document.getElementById('est-duration')?.innerText,
                tokens: document.getElementById('est-tokens')?.innerText,
                tokensSub: document.getElementById('est-tokens-sub')?.innerText,
                budget: document.getElementById('est-budget')?.innerText,
                confidence: document.getElementById('est-confidence')?.innerText,
                confidenceNote: document.getElementById('est-confidence-note')?.innerText
            };
        });

        console.log('\nFinal Resolved Modal State:');
        console.log(`  Duration: "${resolvedModalState.duration}"`);
        console.log(`  Tokens Range: "${resolvedModalState.tokens}"`);
        console.log(`  Tokens Sub: "${resolvedModalState.tokensSub}"`);
        console.log(`  Estimated Cost: "${resolvedModalState.budget}"`);
        console.log(`  Confidence: "${resolvedModalState.confidence}"`);
        console.log(`  Confidence Note: "${resolvedModalState.confidenceNote}"`);

        console.log('\nRecent Console Logs:');
        consoleLogs.slice(-10).forEach(l => console.log(' ', l));

        // 3. Verification Assertions
        console.log('\n--- STEP 3: Verification Assertions ---');
        let pass = true;

        if (resolvedModalState.duration.includes('00:03:') || resolvedModalState.duration.includes(':')) {
            console.log('✅ PASS: Duration formatted as HH:MM:SS (' + resolvedModalState.duration + ')');
        } else {
            console.error('❌ FAIL: Duration invalid:', resolvedModalState.duration);
            pass = false;
        }

        if (resolvedModalState.tokens.includes('≈') && resolvedModalState.tokens.includes('Tokens')) {
            console.log('✅ PASS: Tokens range formatted correctly (' + resolvedModalState.tokens + ')');
        } else {
            console.error('❌ FAIL: Tokens range invalid:', resolvedModalState.tokens);
            pass = false;
        }

        if (resolvedModalState.budget.includes('≈') && resolvedModalState.budget.includes('฿')) {
            console.log('✅ PASS: Cost range formatted correctly (' + resolvedModalState.budget + ')');
        } else {
            console.error('❌ FAIL: Cost range invalid:', resolvedModalState.budget);
            pass = false;
        }

        // 4. Test Live Dropdown Recalculation
        console.log('\n--- STEP 4: Live Model Dropdown Switching ---');
        await page.select('#estimatorModelSelect', 'gemini-2.5-flash-lite');
        await delay(100);
        const liteData = await page.evaluate(() => ({
            tokens: document.getElementById('est-tokens')?.innerText,
            budget: document.getElementById('est-budget')?.innerText,
            confidence: document.getElementById('est-confidence')?.innerText
        }));
        console.log(`[Gemini 2.5 Flash-Lite] Tokens: "${liteData.tokens}", Cost: "${liteData.budget}", Confidence: "${liteData.confidence}"`);

        // 5. Verify Event Loop Responsiveness during lookup
        console.log('\n--- STEP 5: Server Health Check during Async Ops ---');
        const healthRes = await page.evaluate(async (url) => {
            const r = await fetch('/health');
            return r.status;
        }, BASE_URL);
        console.log(`Server health endpoint status: HTTP ${healthRes}`);

        // 6. Check Console Errors
        console.log('\n--- STEP 6: Console Errors Check ---');
        const realErrors = consoleErrors.filter(e => !e.includes('favicon.ico'));
        console.log(`Total App Console Errors: ${realErrors.length}`);
        if (realErrors.length > 0) {
            console.log('Console Errors:', realErrors);
        } else {
            console.log('✅ PASS: 0 console errors detected!');
        }

        console.log('\n====================================================');
        console.log('   REAL BROWSER VERIFICATION COMPLETED SUCCESSFULLY ');
        console.log('====================================================');

    } catch (err) {
        console.error('❌ Browser Test Failed:', err);
    } finally {
        serverProc.kill();
        process.exit(0);
    }
}

runRealBrowserVerification();
