const puppeteer = require('puppeteer-core');
const { spawn } = require('child_process');
const http = require('http');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 8011;
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

async function runVerification() {
    console.log('=== STARTING REAL BROWSER VERIFICATION (PHASE 17.1) ===');

    const dbUrl = process.env.DATABASE_URL || 'sqlite:///./data/yamasee_e2e.db';
    if (dbUrl.includes('yamasee.db') && !dbUrl.endsWith('yamasee_e2e.db') && process.env.FORCE_VERIFICATION_DB !== '1') {
        console.error('ERROR: Refusing to run verification script against the real development database.');
        console.error('Please set DATABASE_URL to an isolated DB or set FORCE_VERIFICATION_DB=1');
        process.exit(1);
    }

    console.log(`Running database setup using DB URL: ${dbUrl}`);
    const { execSync } = require('child_process');
    execSync('python -m tests.helpers.setup_verification_data', {
        env: Object.assign({}, process.env, { DATABASE_URL: dbUrl }),
        stdio: 'inherit'
    });

    const env = Object.assign({}, process.env, {
        APP_ENV: 'development',
        APP_SECRET_KEY: 'browser_test_secret_key_1234567890',
        DATABASE_URL: dbUrl
    });

    const serverProc = spawn('python', ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', `--port=${PORT}`, '--workers', '1'], { env, cwd: 'E:\\WeFool' });

    try {
        console.log('Waiting for Uvicorn server startup...');
        await waitForServer(`${BASE_URL}/health`);
        console.log('Uvicorn server is up and healthy!');

        const browser = await puppeteer.launch({
            executablePath: EDGE_PATH,
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const page = await browser.newPage();

        // 1. Log in as Owner
        console.log('\n[STEP 1] Logging in as Owner...');
        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('input[name="email"]', 'owner@example.com');
        await page.type('input[name="password"]', 'OwnerPass123!');
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }),
            page.click('button[type="submit"]')
        ]);
        console.log(`Logged in successfully, current URL: ${page.url()}`);

        // Go to Admin Center
        console.log('\n[STEP 2] Navigating to Admin Center...');
        await page.goto(`${BASE_URL}/admin`, { waitUntil: 'networkidle0' });
        
        // Wait for users table to load
        await page.waitForSelector('#usersTableBody tr');

        // Locate NormalTest row and edit button
        console.log('\n[STEP 3] Editing NormalTest username and email...');
        
        // Find row that contains NormalTest
        const getRowHandle = async (username) => {
            const rows = await page.$$('#usersTableBody tr');
            for (let row of rows) {
                const text = await page.evaluate(el => el.textContent, row);
                if (text.includes(username)) {
                    return row;
                }
            }
            return null;
        };

        let normalRow = await getRowHandle('NormalTest');
        if (!normalRow) throw new Error('NormalTest user row not found!');

        // Click Manage (จัดการ) button inside this row
        const editBtn = await normalRow.$('button');
        const editBtnText = await page.evaluate(el => el.textContent, editBtn);
        console.log(`Found action button in row: "${editBtnText}"`);
        
        await editBtn.click();
        
        // Wait for management modal to open
        await page.waitForSelector('#userManagementModal', { visible: true });
        
        // Click Edit button inside the management modal
        await page.click('#mgmtActionEdit');
        
        // Wait for edit modal to open
        await page.waitForSelector('#editUserModal', { visible: true });
        console.log('Edit User modal opened!');

        // Fill in new values
        await page.evaluate(() => {
            document.getElementById('editDisplayNameInput').value = '';
            document.getElementById('editEmailInput').value = '';
        });
        await page.type('#editDisplayNameInput', 'NormalTestUpdated');
        await page.type('#editEmailInput', 'normal_updated@example.com');

        // Verify role and status are read-only
        const isRoleReadOnly = await page.evaluate(() => document.getElementById('editRoleOutput').readOnly);
        const isStatusReadOnly = await page.evaluate(() => document.getElementById('editStatusOutput').readOnly);
        console.log(`Role field readOnly: ${isRoleReadOnly}, Status field readOnly: ${isStatusReadOnly}`);

        // Click Save (บันทึกการเปลี่ยนแปลง) and listen for standard alert dialog
        console.log('Submitting changes...');
        page.once('dialog', async dialog => {
            console.log(`[ALERT RECEIVED]: "${dialog.message()}"`);
            await dialog.accept();
        });

        await page.click('#editModalConfirmBtn');

        // Wait for modal to close
        await page.waitForSelector('#editUserModal', { hidden: true });
        console.log('Edit User modal closed!');

        // Wait for async loadUsers() to finish fetching and rendering
        await page.waitForTimeout(1000);

        // 3. Confirm row updates
        console.log('\n[STEP 4] Verifying the row updated in UI immediately...');
        let updatedRow = await getRowHandle('NormalTestUpdated');
        if (updatedRow) {
            const rowText = await page.evaluate(el => el.textContent, updatedRow);
            console.log(`Updated Row Content: "${rowText}"`);
        } else {
            throw new Error('NormalTestUpdated row not found in UI!');
        }

        // 4. Refresh page and confirm values persisted
        console.log('\n[STEP 5] Refreshing page to verify persistence...');
        await page.reload({ waitUntil: 'networkidle0' });
        await page.waitForSelector('#usersTableBody tr');
        updatedRow = await getRowHandle('NormalTestUpdated');
        if (updatedRow) {
            const rowText = await page.evaluate(el => el.textContent, updatedRow);
            console.log(`Persisted Row Content: "${rowText}"`);
            if (rowText.includes('normal_updated@example.com')) {
                console.log('SUCCESS: Email update persisted in DB!');
            } else {
                throw new Error('Email update did not persist!');
            }
        }

        // 5. Attempt to use duplicate email
        console.log('\n[STEP 6] Testing duplicate email conflict...');
        updatedRow = await getRowHandle('NormalTestUpdated');
        const editBtnConflict = await updatedRow.$('button');
        await editBtnConflict.click();
        await page.waitForSelector('#userManagementModal', { visible: true });
        await page.click('#mgmtActionEdit');
        await page.waitForSelector('#editUserModal', { visible: true });

        await page.evaluate(() => {
            document.getElementById('editEmailInput').value = '';
        });
        await page.type('#editEmailInput', 'duplicate@example.com'); // email of DuplicateTest
        await page.click('#editModalConfirmBtn');

        // Wait for error message
        await page.waitForFunction(() => {
            const el = document.getElementById('editModalErrorMessage');
            return el && el.style.display === 'block' && el.textContent.includes('Email is already used');
        }, { timeout: 3000 });
        const errorText = await page.evaluate(() => document.getElementById('editModalErrorMessage').textContent);
        console.log(`Conflict Error visible in Modal: "${errorText}"`);

        // Close the modal
        await page.click('#editModalCancelBtn');
        await page.waitForSelector('#editUserModal', { hidden: true });

        // 6. Log out
        console.log('\n[STEP 7] Logging out from Owner...');
        await page.evaluate(async () => {
            await fetch('/api/auth/logout', { method: 'POST' });
        });

        // 7. Log in as Admin
        console.log('\n[STEP 8] Logging in as Admin...');
        await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle0' });
        await page.type('input[name="email"]', 'admin@example.com');
        await page.type('input[name="password"]', 'AdminPass123!');
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'networkidle0' }),
            page.click('button[type="submit"]')
        ]);

        await page.goto(`${BASE_URL}/admin`, { waitUntil: 'networkidle0' });
        await page.waitForSelector('#usersTableBody tr');

        // Confirm Admin can edit a normal user (NormalTestUpdated)
        console.log('\n[STEP 9] Confirming Admin can edit a normal user...');
        const adminNormalRow = await getRowHandle('NormalTestUpdated');
        const adminEditBtn = await adminNormalRow.$('button');
        const adminEditBtnText = await page.evaluate(el => el.textContent, adminEditBtn);
        console.log(`Admin sees button: "${adminEditBtnText}" on normal user row`);

        // Confirm Admin cannot edit Owner
        console.log('\n[STEP 10] Confirming Admin cannot edit Owner...');
        const adminOwnerRow = await getRowHandle('OwnerTest');
        const adminOwnerText = await page.evaluate(el => el.textContent, adminOwnerRow);
        console.log(`Owner row under Admin: "${adminOwnerText}"`);
        if (adminOwnerText.includes('🛡️ Protected Owner')) {
            console.log('SUCCESS: Owner account is protected and cannot be edited by Admin!');
        } else {
            throw new Error('Owner account is not protected from Admin!');
        }

        // 9. Compare System Status active user count
        console.log('\n[STEP 11] Checking System Status active user count...');
        // Switch to System Status tab first
        await page.click('button[data-tab="status"]');
        await page.waitForTimeout(200);
        await page.click('button[id="refreshStatusBtn"]');
        await page.waitForTimeout(500); // Wait briefly for fetch
        
        const activeUsersUI = await page.evaluate(() => document.getElementById('val-total-users').textContent);
        const subtextUI = await page.evaluate(() => document.getElementById('val-admin-users').textContent);
        console.log(`UI Active Users Count: ${activeUsersUI}`);
        console.log(`UI Subtext Counts: "${subtextUI}"`);

        // 10. Soft-delete a disposable user
        console.log('\n[STEP 12] Soft-deleting DisposableTest user...');
        // Switch back to Users tab
        await page.click('button[data-tab="users"]');
        await page.waitForTimeout(200);
        const disposableRow = await getRowHandle('DisposableTest');
        
        // Find Manage button
        const deleteBtn = await disposableRow.$('button');
        await deleteBtn.click();
        
        // Wait for management modal
        await page.waitForSelector('#userManagementModal', { visible: true });
        
        // Click Soft Delete button in the modal
        await page.click('#mgmtActionDelete');
        
        // Confirm soft delete modal
        await page.waitForSelector('#adminActionModal', { visible: true });
        await page.type('#confirmUsernameInput', 'DisposableTest');
        await page.click('#modalConfirmBtn');
        await page.waitForSelector('#adminActionModal', { hidden: true });
        console.log('Soft delete action completed!');

        // Confirm counts updated
        console.log('\n[STEP 13] Verifying System Status counts after soft-delete...');
        // Switch to System Status tab
        await page.click('button[data-tab="status"]');
        await page.waitForTimeout(200);
        await page.click('button[id="refreshStatusBtn"]');
        await page.waitForTimeout(500);

        const activeUsersUI2 = await page.evaluate(() => document.getElementById('val-total-users').textContent);
        const subtextUI2 = await page.evaluate(() => document.getElementById('val-admin-users').textContent);
        console.log(`UI Active Users Count after soft-delete: ${activeUsersUI2}`);
        console.log(`UI Subtext Counts after soft-delete: "${subtextUI2}"`);

        console.log('\n=== BROWSER VERIFICATION SUCCESSFUL ===');
        await browser.close();
    } catch (err) {
        console.error('\n!!! BROWSER VERIFICATION FAILED !!!');
        console.error(err);
    } finally {
        serverProc.kill();
        process.exit(0);
    }
}

// Add polyfill for wait timeout in older puppeteer versions
if (!puppeteer.Page.prototype.waitForTimeout) {
    puppeteer.Page.prototype.waitForTimeout = function (milliseconds) {
        return new Promise(resolve => setTimeout(resolve, milliseconds));
    };
}

runVerification();
