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

async function debugRealBrowser() {
    console.log('====================================================');
    console.log(' DEBUG REAL BROWSER — EXACT NETWORK & UI TRACE     ');
    console.log('====================================================');

    execSync(`python -c "from database import SessionLocal; from models.user import User; from services.auth_service import create_user, get_user_by_email; db = SessionLocal(); u = get_user_by_email(db, 'debug_user@example.com'); create_user(db, 'DebugUser', 'debug_user@example.com', 'Password123!') if not u else None; db.close()"`, { cwd: 'E:\\WeFool' });

    const env = Object.assign({}, process.env, {
        APP_ENV: 'development',
        APP_SECRET_KEY: 'browser_debug_secret_key_999'
    });

    const serverProc = spawn('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', `--port=${PORT}`, '--workers', '1'], { env, cwd: 'E:\\WeFool' });

    try {
        await waitForServer(`${BASE_URL}/health`);
        console.log('Server is healthy on port ' + PORT);

        const browser = await puppeteer.launch({
            executablePath: EDGE_PATH,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const page = await browser.newPage();

        page.on('console', msg => console.log(`[Browser Console ${msg.type()}] ${msg.text()}`));
        
        page.on('request', req => {
            if (req.url().includes('/pre_check_cache') || req.url().includes('/api/resolve_duration') || req.url().includes('/api/pre_run_estimate')) {
                console.log(`\n[NETWORK OUT] ${req.method()} ${req.url()}`);
                console.log(`  PostData:`, req.postData());
            }
        });

        page.on('response', async res => {
            if (res.url().includes('/pre_check_cache') || res.url().includes('/api/resolve_duration') || res.url().includes('/api/pre_run_estimate')) {
                console.log(`\n[NETWORK IN] ${res.status()} ${res.url()}`);
                try {
                    const text = await res.text();
                    console.log(`  ResponseBody:`, text);
                } catch (e) {
                    console.log(`  ResponseBody: <failed to read>`);
                }
            }
        });

        // Login
        console.log('\n--- Logging in ---');
        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('#email', 'debug_user@example.com');
        await page.type('#password', 'Password123!');
        
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }).catch(() => {}),
            page.click('#submitBtn')
        ]);

        await page.goto(`${BASE_URL}/dashboard`, { waitUntil: 'networkidle0' });
        console.log('Dashboard loaded.');

        // Test Uncached YouTube URL
        console.log('\n--- Testing Uncached YouTube URL ---');
        const uncachedUrl = 'https://www.youtube.com/watch?v=L_LUpnjgPso'; // Unique URL
        await page.type('#youtubeUrl', uncachedUrl);

        // Inspect URL state right before click
        const urlStateBefore = await page.evaluate(() => ({
            youtubeInputVal: document.getElementById('youtubeUrl')?.value,
            selectedMode: document.querySelector('input[name="mediaMode"]:checked')?.value
        }));
        console.log('URL State Before Click:', urlStateBefore);

        await page.click('.btn-process');

        // Wait 12 seconds to observe full network and DOM updates
        await delay(12000);

        const modalDOM = await page.evaluate(() => ({
            duration: document.getElementById('est-duration')?.innerText,
            tokens: document.getElementById('est-tokens')?.innerText,
            cost: document.getElementById('est-budget')?.innerText
        }));
        console.log('\nFinal Modal DOM State:', modalDOM);

    } catch (e) {
        console.error('Debug script error:', e);
    } finally {
        serverProc.kill();
        process.exit(0);
    }
}

debugRealBrowser();
