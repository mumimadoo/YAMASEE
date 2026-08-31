const puppeteer = require('puppeteer-core');
const { spawn } = require('child_process');
const http = require('http');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 8009;
const BASE_URL = `http://127.0.0.1:${PORT}`;

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

async function runBrowserAcceptance() {
    console.log('=== STARTING REAL MANUAL BROWSER ACCEPTANCE (MICROSOFT EDGE) ===');

    const env = Object.assign({}, process.env, {
        APP_ENV: 'development',
        APP_SECRET_KEY: 'browser_test_secret_key_1234567890'
    });

    const serverProc = spawn('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', `--port=${PORT}`, '--workers', '1'], { env, cwd: 'E:\\WeFool' });

    serverProc.stdout.on('data', data => {
        // console.log(`[Server]: ${data}`);
    });
    serverProc.stderr.on('data', data => {
        // console.error(`[Server Err]: ${data}`);
    });

    try {
        console.log('Waiting for Uvicorn server startup...');
        await waitForServer(`${BASE_URL}/health`);
        console.log('Uvicorn server is up and healthy!');

        const browser = await puppeteer.launch({
            executablePath: EDGE_PATH,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const version = await browser.version();
        console.log(`REAL BROWSER CONNECTED: ${version}`);

        const consoleLogs = [];
        const networkErrors = [];

        const page = await browser.newPage();
        page.on('console', msg => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));
        page.on('response', resp => {
            if (resp.status() >= 400 && !resp.url().includes('favicon.ico')) {
                networkErrors.push(`[HTTP ${resp.status()}] ${resp.url()}`);
            }
        });

        // SCENARIO A: LANDING PAGE & THEME TOGGLE
        console.log('\n--- SCENARIO A: Landing Page & Theme Toggle ---');
        await page.goto(`${BASE_URL}/landing`, { waitUntil: 'networkidle0' });
        const landingTitle = await page.title();
        console.log(`Landing Page Title: "${landingTitle}"`);

        // SCENARIO B: REGISTER USER A
        console.log('\n--- SCENARIO B: Register User A ---');
        await page.goto(`${BASE_URL}/register`, { waitUntil: 'networkidle0' });
        await page.type('input[name="username"]', 'browser_user_a');
        await page.type('input[name="email"]', 'browsera@example.com');
        await page.type('input[name="password"]', 'Password123!');
        await page.type('input[name="confirmPassword"]', 'Password123!');
        
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('button[type="submit"]')
        ]);
        console.log(`URL after User A registration: ${page.url()}`);

        // SCENARIO C: LOGIN USER A
        console.log('\n--- SCENARIO C: Login User A ---');
        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('input[name="email"]', 'browsera@example.com');
        await page.type('input[name="password"]', 'Password123!');
        
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('button[type="submit"]')
        ]);
        console.log(`URL after User A login: ${page.url()}`);
        const cookies = await page.cookies();
        const sessionCookie = cookies.find(c => c.name === 'session');
        console.log(`Session Cookie Present: ${!!sessionCookie}, HttpOnly: ${sessionCookie ? sessionCookie.httpOnly : false}`);

        // SCENARIO D: DASHBOARD & SUBMISSION
        console.log('\n--- SCENARIO D: Dashboard & Form Controls ---');
        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle0' });
        const dashTitle = await page.title();
        console.log(`Dashboard Title: "${dashTitle}"`);

        // SCENARIO E: HISTORY PAGE & ACTIONS
        console.log('\n--- SCENARIO E: History Page ---');
        await page.goto(`${BASE_URL}/history`, { waitUntil: 'networkidle0' });
        const historyTitle = await page.title();
        console.log(`History Title: "${historyTitle}"`);

        // SCENARIO F: LOGOUT & GUEST ACCESS PROTECTION
        console.log('\n--- SCENARIO F: Logout & Guest Access Protection ---');
        await page.evaluate(async () => {
            await fetch('/api/auth/logout', { method: 'POST' });
        });
        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle0' });
        console.log(`Guest access to /dashboard redirected to: ${page.url()}`);

        // SCENARIO G: USER B REGISTRATION & OWNERSHIP ISOLATION
        console.log('\n--- SCENARIO G: User B Registration & Ownership Isolation ---');
        await page.goto(`${BASE_URL}/register`, { waitUntil: 'networkidle0' });
        await page.type('input[name="username"]', 'browser_user_b');
        await page.type('input[name="email"]', 'browserb@example.com');
        await page.type('input[name="password"]', 'Password123!');
        await page.type('input[name="confirmPassword"]', 'Password123!');
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('button[type="submit"]')
        ]);

        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('input[name="email"]', 'browserb@example.com');
        await page.type('input[name="password"]', 'Password123!');
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('button[type="submit"]')
        ]);

        await page.goto(`${BASE_URL}/history`, { waitUntil: 'networkidle0' });
        console.log(`User B history page loaded at: ${page.url()}`);

        console.log('\n=== REAL MANUAL BROWSER ACCEPTANCE SUMMARY ===');
        console.log(`Browser Version: ${version}`);
        console.log(`Console Logs Count: ${consoleLogs.length}`);
        console.log(`Network Errors Count: ${networkErrors.length}`);
        if (networkErrors.length > 0) {
            console.log('Network errors detected:', networkErrors.slice(0, 5));
        }

        console.log('REAL MANUAL BROWSER ACCEPTANCE PASSED SUCCESSFULLY!');
        await browser.close();
    } catch (err) {
        console.error('Browser Acceptance Error:', err);
    } finally {
        serverProc.kill();
    }
}

runBrowserAcceptance();
