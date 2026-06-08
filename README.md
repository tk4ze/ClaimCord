# Discord Username Availability Checker

A Python script that checks whether Discord usernames are available or taken using Discord’s public API.  
Supports proxy rotation to avoid rate limits and bulk scanning from a text file.

## Features

- ✅ Checks availability via Discord’s official endpoint (`/api/v9/unique-username/username-attempt-unauthed`)
- 🔄 Automatic proxy rotation on rate limits (429) and connection errors
- 📝 Reads usernames from a `.txt` file (one per line, supports `#` comments)
- 🧪 Validates Discord username rules (length, allowed characters, no leading/trailing dots)
- 🎨 Colored terminal output + summary of available/taken/invalid/errors
- ⚙️ Configurable request delay and retry logic
- 🌐 Supports HTTP, HTTPS, and SOCKS5 proxies (with/without authentication)

## Requirements

- Python 3.6 or higher
- No external dependencies – only the standard library

## Installation

1. Save the script as `discord_checker.py`
2. (Optional) Make it executable:
   ```bash
   chmod +x discord_checker.py

## Important Notes
1. Legal use - only check usernames for legitimate purposes. Do not abuse the service.
2. License - this script is provided as‑is for educational purposes. Use at your own risk.


