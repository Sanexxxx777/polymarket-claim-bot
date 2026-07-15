# Polymarket Auto-Claim Bot

Automatically claims winnings and closes losses on Polymarket, one or more accounts at a time.

## Quick Start

1. Get an Ubuntu server (22.04 recommended)
2. Follow the full walkthrough in [`../docs/SETUP_GUIDE.md`](../docs/SETUP_GUIDE.md)
3. Login to Polymarket via VNC
4. Run the bot

## How It Works

- Loops over every account in `config.toml`, each with its own Firefox profile
- Checks the portfolio page for a "Claim"/"Redeem" button, clicks and confirms it
- Checks the history tab for a "Close Losses" button, clicks and confirms it
- Repeats every 4 minutes, skipping settlement windows

## Requirements

- Ubuntu 22.04 server
- Firefox (snap version)
- VNC for initial setup
- Polymarket account with Google login

## Files

- `polymarket_claim_bot_firefox.py` - Main bot script
- `config.example.toml` - Config template (copy to `config.toml`, gitignored)
- `README.md` - This file

## Usage

```bash
# GUI mode (visible in VNC)
python3 polymarket_claim_bot_firefox.py --gui

# Headless mode (background)
python3 polymarket_claim_bot_firefox.py

# Login mode (open Firefox per account for manual login)
python3 polymarket_claim_bot_firefox.py --login
```

## Logs

Bot logs are saved to: `~/.polymarket_bot/bot.log`
