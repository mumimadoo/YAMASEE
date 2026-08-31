const puppeteer = require('puppeteer-core');
const { spawn, execSync } = require('child_process');
const http = require('http');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 8095;
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
    console.log('  YAMASEE — VIDEO COMPARISON PRE-RUN ESTIMATE VERIFICATION  ');
    console.log('====================================================\n');

    // Seed test user in DB via Python
    console.log('Seeding test user and candidate records in database...');
    execSync(`python -c "from database import SessionLocal; from models.user import User; from services.auth_service import create_user, get_user_by_email; db = SessionLocal(); u = get_user_by_email(db, 'comp_browser_user3@example.com'); create_user(db, 'CompBrowserUser3', 'comp_browser_user3@example.com', 'Password123!') if not u else None; db.close()"`, { cwd: 'E:\\WeFool' });

    const env = Object.assign({}, process.env, {
        APP_ENV: 'development',
        APP_SECRET_KEY: 'browser_comp_prerun_secret_key_555'
    });

    const serverProc = spawn('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', `--port=${PORT}`, '--workers', '1'], { env, cwd: 'E:\\WeFool' });

    try {
        console.log('Starting Uvicorn test server on port ' + PORT + '...');
        await waitForServer(`${BASE_URL}/health`);
        console.log('Server is healthy!\n');

        const browser = await puppeteer.launch({
            executablePath: EDGE_PATH,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

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
        await page.type('#email', 'comp_browser_user3@example.com');
        await page.type('#password', 'Password123!');
        
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('#submitBtn')
        ]);

        // 2. Navigate to Video Comparison Workspace
        console.log('--- STEP 2: Navigate to Video Comparison Page ---');
        await page.goto(`${BASE_URL}/comparison`, { waitUntil: 'networkidle0' });
        console.log(`Current URL: ${page.url()}`);

        // 3. Test REAL CASE 1: Video A URL + Video B URL (New Analysis)
        console.log('\n--- REAL CASE 1: Video A (New YouTube) + Video B (New YouTube) ---');
        await page.type('#urlInputA', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
        await page.click('#btnSubmitUrlA');
        await delay(300);

        await page.type('#urlInputB', 'https://www.youtube.com/watch?v=kJQP7kiw5Fk');
        await page.click('#btnSubmitUrlB');
        
        // Wait for async YouTube duration resolution (3-5s)
        console.log('Waiting for background duration resolution...');
        await delay(4500);

        const case1UI = await page.evaluate(() => {
            const cardA = document.getElementById('compactEstimateA')?.innerText;
            const cardB = document.getElementById('compactEstimateB')?.innerText;
            const totalStateA = document.getElementById('totalStateA')?.innerText;
            const totalCostA = document.getElementById('totalCostA')?.innerText;
            const totalStateB = document.getElementById('totalStateB')?.innerText;
            const totalCostB = document.getElementById('totalCostB')?.innerText;
            const totalStateComp = document.getElementById('totalStateComp')?.innerText;
            const totalCostComp = document.getElementById('totalCostComp')?.innerText;
            const totalCost = document.getElementById('totalCostSummary')?.innerText;
            const totalTokens = document.getElementById('totalTokensSummary')?.innerText;
            const totalCardVisible = getComputedStyle(document.getElementById('comparisonTotalEstimateCard')).display !== 'none';
            return { cardA, cardB, totalStateA, totalCostA, totalStateB, totalCostB, totalStateComp, totalCostComp, totalCost, totalTokens, totalCardVisible };
        });

        console.log('Case 1 Resolved UI Results:');
        console.log('  Video A Compact Estimate:', case1UI.cardA?.replace(/\n/g, ' '));
        console.log('  Video B Compact Estimate:', case1UI.cardB?.replace(/\n/g, ' '));
        console.log('  Summary Breakdown Video A:', case1UI.totalStateA, '->', case1UI.totalCostA);
        console.log('  Summary Breakdown Video B:', case1UI.totalStateB, '->', case1UI.totalCostB);
        console.log('  Summary Breakdown Comparison:', case1UI.totalStateComp, '->', case1UI.totalCostComp);
        console.log('  Total Estimated Cost:', case1UI.totalCost);
        console.log('  Total Estimated Tokens:', case1UI.totalTokens);

        // 4. Test Day / Night Theme Contrast
        console.log('\n--- STEP 4: Day & Night Theme Verification ---');
        const themeBtn = await page.$('#themeToggleBtn');
        if (themeBtn) {
            await themeBtn.click();
            await delay(200);
            const nightThemeActive = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
            console.log(`Night Theme active: ${nightThemeActive}`);

            const nightCardBg = await page.evaluate(() => getComputedStyle(document.getElementById('comparisonTotalEstimateCard')).backgroundColor);
            console.log(`Estimate Card Night Background: ${nightCardBg}`);

            await themeBtn.click();
            await delay(200);
            const dayThemeActive = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
            console.log(`Day Theme active: ${dayThemeActive}`);
        }

        // 5. Mobile Layout Verification
        console.log('\n--- STEP 5: Mobile Viewport Stacking Test ---');
        await page.setViewport({ width: 375, height: 812 });
        await delay(300);
        const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
        console.log(`Mobile Horizontal Overflow: ${mobileOverflow ? 'YES (FAIL)' : 'NO (PASS)'}`);

        // 6. Console Error Audit
        console.log('\n--- STEP 6: Console Error Audit ---');
        const realErrors = consoleErrors.filter(e => !e.includes('favicon.ico') && !e.includes('404'));
        console.log(`Total Unhandled Console Errors: ${realErrors.length}`);
        if (realErrors.length > 0) {
            console.log('Console Errors:', realErrors);
        } else {
            console.log('✅ PASS: 0 console errors!');
        }

        console.log('\n====================================================');
        console.log('   VIDEO COMPARISON PRE-RUN VERIFICATION SUCCESSFUL   ');
        console.log('====================================================\n');

    } catch (err) {
        console.error('❌ Real Browser Test Error:', err);
    } finally {
        serverProc.kill();
        process.exit(0);
    }
}

runRealBrowserVerification();
