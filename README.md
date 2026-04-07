# Arena-Api-Bridge

[![Project Status](https://img.shields.io/badge/Status-Archived-blue.svg)](https://github.com/izaart95-jpg/Arena-Api-Bridge)
[![Platform](https://img.shields.io/badge/Platform-Cross--Platform-yellow.svg)](#)

> **Note:** ~99% complete — CAPTCHA bypass remains outstanding. Best recorded streak: **30 prompts** without a CAPTCHA error *(not guaranteed)*.

---

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Method 1: Captcha Extensions](#method-1-captcha-extensions-stable)
- [Method 2: Browser Automation](#method-2-browser-automation-fallback)
- [Configuration Reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)
- [Related Projects](#related-projects)

---

## Overview

Arena-Api-Bridge provides an OpenAI-compatible API interface for [Arena](https://arena.ai), enabling developers to integrate Arena's language models into existing workflows with minimal code changes.

### Available Methods

| Method | Type | Description | Stability |
|--------|------|-------------|-----------|
| **Captcha Extensions** | Extension-based | Stable approach with Rektcaptcha integration for v2 CAPTCHA handling | ✅ Stable |
| **Browser Automation** | Script-based | Playwright/Camoufox-based automation with cookie harvesting | ⚠️ Experimental |

### Recommendations

- **Primary:** Captcha Extensions method for production use
- **Fallback:** `arena_token.py` if extension method fails frequently
- **Browser:** Brave (or any Chromium-based browser) for automation method

---

## Quick Start

### Prerequisites

- Python 3.8+
- Git
- A Chromium-based browser (recommended: Brave) or Firefox (for Camoufox)

### Installation

```bash
# Clone the repository
git clone https://github.com/izaart95-jpg/Arena-Api-Bridge.git
cd Arena-Api-Bridge

# Install dependencies
pip install -r requirements.txt

# For browser automation (Method 2)
playwright install chromium
```

---

## Method 1: Captcha Extensions (Stable)

The recommended production method using browser extensions for CAPTCHA handling.
Full Walkthrough: [CAPTCHA-EXTENSION USAGE VIDEO](https://youtu.be/O-ssgydeuB0)

### Extension Setup

1. Open your browser and navigate to **Manage Extensions**
2. Enable **Developer Mode**
3. Click **Load Unpacked**
4. Select the `Captcha-Extension/extension` directory

### Usage

```bash
# Step 1: Start the CAPTCHA server (background)
python captcha_server.py &

# Step 2: Open your browser and navigate to arena.ai

# Step 3: Start the API server
python server.py &
# Run V3 harvester from extensions window
# Note: By default extension wont work for brave browser until you turn off brave shield for arena.ai
```

The API server provides an OpenAI-compatible endpoint at:

```
http://localhost:8000/v1
```

### Interactive Chatting (Experimental)

```bash
python main.py
```

---

## Method 2: Browser Automation (Fallback)

An alternative method using Playwright for browser automation. Recommended only when the extension method is unavailable.

### Quick Start

```bash
# Start the token harvester
python arena_token.py

# In a separate terminal, open the web interface
# Navigate to http://localhost:5000 and start v3

# Run the main script
python main.py
```

### Using Camoufox (Alternative)

```bash
# Install Camoufox dependencies
pip install camoufox[geoip] browserforge fastapi uvicorn

# Download Firefox binary (one-time setup)
camoufox fetch

# Start the harvester
python camoufox_harvester.py
```

---

## Configuration Reference

### Configuration Flags

| Flag | Type | Description | Default |
|------|------|-------------|---------|
| `CUSTOM` | Boolean | Use a custom browser executable | `True` |
| `N` | Integer | Number of browser windows/tabs | `1` |
| `EXTENSIONS` | Boolean | Load browser extensions | `True` |
| `CUS_PROFILE` | Boolean | Use a custom browser profile | `False` |
| `TABS` | Boolean | `True` = tabs in one window, `False` = separate windows | `False` |
| `AUTO_LOGIN` | Boolean | Automated login and cookie fetching | `True` |
| `COOKIES` | Boolean | Inject stored auth cookies | `False` |

### Configuration Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `PATH` | When `CUSTOM=True` | Browser executable path |
| `EXTENSIONS_DIR` | When `EXTENSIONS=True` | Extensions folder path |
| `PROFILE_PATH` | When `CUS_PROFILE=True` | Browser profile directory |
| `COOKIE_V1` | When `COOKIES=True` | `arena-auth-prod-v1.0` cookie value |
| `COOKIE_V2` | When `COOKIES=True` | `arena-auth-prod-v1.1` cookie value |

### Browser Executable Paths

#### Linux

```python
PATH = "/usr/bin/brave-browser"        # Brave
PATH = "/usr/bin/google-chrome"          # Chrome
PATH = "/usr/bin/chromium-browser"       # Chromium
```

#### Windows

```python
PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

#### macOS

```python
PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PATH = "/Applications/Chromium.app/Contents/MacOS/Chromium"
```

### Important Notes

> ⚠️ **Compatibility Warning:** `AUTO_LOGIN=True` and `COOKIES=True` are mutually exclusive. The application will raise an error at startup if both are enabled simultaneously.

> 💡 **Tip:** To find your browser's executable path, navigate to `chrome://version` and copy the **Executable Path** value.

---

## Troubleshooting

### CAPTCHA Validation Failures

If you continue to receive reCAPTCHA validation failures:

1. Install the [Rektcaptcha extension](https://github.com/izaart95-jpg/Captcha-Extension)
2. Set `EXTENSIONS=True` in your configuration
3. Configure `EXTENSIONS_DIR` to point to your extensions folder

### Changing Models

1. Review available models in `models.json`
2. Update `config.json` with your selected model

### Image Upload Issues

If image uploads are not working, the `next-action` header may need to be updated manually.

---

## Related Projects

| Project | Description |
|---------|-------------|
| [Deep Router](https://github.com/izaart95-jpg/DeepRouter) | DeepSeek API Bridge |
| [Kimi-Bridge](https://github.com/izaart95-jpg/Kimi-Bridge) | Kimi API Bridge |
| [GLM-Bridge](https://github.com/izaart95-jpg/GLM-Bridge) | GLM API Bridge |

---

## License

This project is provided as-is for educational and personal use.

## Disclaimer

This software is intended for educational purposes only. Please ensure compliance with Arena's Terms of Service when using this tool.
