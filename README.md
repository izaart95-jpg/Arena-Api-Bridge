# Arena-Api-Bridge — Beta

> **Status:** Beta · ~90% complete — CAPTCHA bypass remains outstanding. Best recorded streak: 30 prompts without a CAPTCHA error (not guaranteed).

---

## Overview

Arena-Api-Bridge provides two primary methods for token harvesting:

**Method 1 — Captcha Extensions:** A stable, extension-based approach with Rektcaptcha integration for v2 CAPTCHA handling.

**Method 2 — Fallback Browser Automation:** Two options are available:
- **Camoufox** — Experimental Firefox-based automation with fingerprint randomization.
- **arena_token.py** — Recommended production approach, optimized for Brave (any Chromium-based browser is supported).

> **Note:** Captcha-Extensions is the stable recommended method. If you are frequently encountering reCAPTCHA validation failures, try the latest extension version from the main repo: [Captcha-Extension](https://github.com/izaart95-jpg/Captcha-Extension)

---

## Usage & Walkthroughs

- 📺 [Browser Automation Walkthrough (YouTube)](https://youtu.be/hPmg9oMS3e8)
- 📺 [Extension Usage Walkthrough (YouTube)](https://youtu.be/O-ssgydeuB0)

> Use the LMArena credentials from the videos to test quickly or on first run.

---

## Method 1: Captcha Extensions (Stable)

The recommended stable solution for CAPTCHA handling. Features Rektcaptcha integration for improved success rates on checkbox CAPTCHAs.

### Installation
```bash
git clone https://github.com/izaart95-jpg/Arena-Api-Bridge.git
cd Arena-Api-Bridge
pip install -r requirements.txt
```

### Extension Setup

1. Open your browser and navigate to **Manage Extensions**.
2. Enable **Developer Mode**.
3. Click **Load Unpacked**.
4. Navigate to `Arena-Api-Bridge/Captcha-Extension/extension` and select that folder.

---

## Method 2: Browser Automation (Fallback)

> **Note:** `arena_token.py` is recommended over `camoufox_harvester`. Camoufox is experimental.

### 1. Install Dependencies
```bash
git clone https://github.com/izaart95-jpg/Arena-Api-Bridge.git
cd Arena-Api-Bridge
pip install -r requirements.txt
playwright install chromium
```

### 2. Configuration

Open `arena_token.py` and edit the configuration block at the top of the file.

**Optional — Rektcaptcha Fallback:**
If you continue to receive reCAPTCHA validation failures even with the harvester running, it is recommended to install the Rektcaptcha extension, set `EXTENSIONS=True`, and configure `EXTENSIONS_DIR` to your extensions folder to enable the v2 harvester as a fallback.

**Starting the harvester:**

1. Run `arena_token.py` and wait for the browser to initialize.
2. Open `http://localhost:5000` in your browser and start v3.
3. You can now run `main.py`.

> **Recommended browser for `arena_token.py`:** Brave

---

### 3. Flags

| Flag | Description | Default |
|------|-------------|---------|
| `CUSTOM` | Use a custom browser executable specified by `PATH` | `True` |
| `N` | Number of browser windows or tabs to open | `1` |
| `EXTENSIONS` | Load extensions from `EXTENSIONS_DIR` | `True` |
| `CUS_PROFILE` | Use a custom browser profile from `PROFILE_PATH` | `False` |
| `TABS` | `False` = N separate windows · `True` = N tabs in one window | `False` |
| `AUTO_LOGIN` | `True` = automated login and cookie fetching · `False` = manual login | `True` |
| `COOKIES` | Inject stored auth cookies into each browser context | `False` |

> ⚠️ **Compatibility Note:** `AUTO_LOGIN=True` and `COOKIES=True` are mutually exclusive. An error is raised at startup if both are enabled simultaneously.

---

### 4. Parameters

| Parameter | Description |
|-----------|-------------|
| `PATH` | Browser executable path — required when `CUSTOM=True` |
| `EXTENSIONS_DIR` | Extensions folder path — required when `EXTENSIONS=True` |
| `PROFILE_PATH` | Browser profile path — required when `CUS_PROFILE=True` |
| `COOKIE_V1` | Value for `arena-auth-prod-v1.0` — required when `COOKIES=True` |
| `COOKIE_V2` | Value for `arena-auth-prod-v1.1` — required when `COOKIES=True` |

---

### 5. Parameter Reference

#### `PATH` — Browser Executable

Navigate to `chrome://version` in your browser and copy the **Executable Path** value.

> **Windows users:** Always use a raw string prefix `r"..."` to avoid backslash escape issues.
>
> - ✅ `PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"`
> - ❌ `PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"`
> - ✅ `EXTENSIONS_DIR = r"C:\Users\USERNAME\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\Extensions"`
> - ❌ `EXTENSIONS_DIR = "C:\Users\USERNAME\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\Extensions"`

**Default paths by platform:**

| Platform | Browser | Path |
|----------|---------|------|
| Linux | Brave | `/usr/bin/brave-browser` |
| Linux | Chrome | `/usr/bin/google-chrome` |
| Linux | Chromium | `/usr/bin/chromium-browser` |
| Windows | Brave | `r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"` |
| Windows | Chrome | `r"C:\Program Files\Google\Chrome\Application\chrome.exe"` |
| Windows | Edge | `r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"` |
| macOS | Brave | `/Applications/Brave Browser.app/Contents/MacOS/Brave Browser` |
| macOS | Chrome | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` |
| macOS | Chromium | `/Applications/Chromium.app/Contents/MacOS/Chromium` |

---

#### `EXTENSIONS_DIR` — Extensions Directory

Required when `EXTENSIONS=True`. To locate it:

1. Open your browser and navigate to `chrome://version`.
2. Find the **Profile Path** value.
3. Append `/Extensions` to that path.

> At least one extension must be installed for the `Extensions` directory to exist.

**Default paths by platform:**

| Platform | Browser | Path |
|----------|---------|------|
| Linux | Brave | `/root/.config/BraveSoftware/Brave-Browser/Default/Extensions` |
| Linux | Chrome | `/home/USERNAME/.config/google-chrome/Default/Extensions` |
| Linux | Chromium | `/home/USERNAME/.config/chromium/Default/Extensions` |
| Windows | Brave | `r"C:\Users\USERNAME\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\Extensions"` |
| Windows | Chrome | `r"C:\Users\USERNAME\AppData\Local\Google\Chrome\User Data\Default\Extensions"` |
| Windows | Edge | `r"C:\Users\USERNAME\AppData\Local\Microsoft\Edge\User Data\Default\Extensions"` |
| macOS | Brave | `/Users/USERNAME/Library/Application Support/BraveSoftware/Brave-Browser/Default/Extensions` |
| macOS | Chrome | `/Users/USERNAME/Library/Application Support/Google/Chrome/Default/Extensions` |
| macOS | Chromium | `/Users/USERNAME/Library/Application Support/Chromium/Default/Extensions` |

---

#### `PROFILE_PATH` — Browser Profile Directory

Required when `CUS_PROFILE=True`. All contexts will use this directory as `user_data_dir` instead of the auto-generated `harvester_profiles/` directories.

**Default paths by platform:**

| Platform | Browser | Path |
|----------|---------|------|
| Linux | Brave | `/root/.config/BraveSoftware/Brave-Browser` |
| Linux | Chrome | `/home/USERNAME/.config/google-chrome` |
| Windows | Brave | `r"C:\Users\USERNAME\AppData\Local\BraveSoftware\Brave-Browser\User Data"` |
| Windows | Chrome | `r"C:\Users\USERNAME\AppData\Local\Google\Chrome\User Data"` |
| macOS | Brave | `/Users/USERNAME/Library/Application Support/BraveSoftware/Brave-Browser` |
| macOS | Chrome | `/Users/USERNAME/Library/Application Support/Google/Chrome` |

---

#### `COOKIE_V1` / `COOKIE_V2` — Auth Cookies

Required when `COOKIES=True`. Retrieve these values from your browser's DevTools under the **Application → Cookies** tab.

> `AUTO_LOGIN=True` is the recommended alternative — it handles authentication and cookie fetching automatically.

---

## Additional Notes

- **To change models:** Select from `models.json` and update `config.json` accordingly.
- **Image upload not working:** The `next-action` header may need to be updated manually.

---

## Method 2b: Camoufox Harvester
```bash
pip install camoufox[geoip] browserforge fastapi uvicorn
camoufox fetch        # Download the Firefox binary once
python camoufox_harvester.py
```

---

## Sister Projects

| Project | Description |
|---------|-------------|
| [Deep Router](https://github.com/izaart95-jpg/DeepRouter) | Deepseek API Bridge |
| [Kimi-Bridge](https://github.com/izaart95-jpg/Kimi-Bridge) | Kimi API Bridge |
| [GLM-Bridge](https://github.com/izaart95-jpg/GLM-Bridge) | GLM API Bridge |
