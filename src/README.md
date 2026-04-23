# Polymarket Auto-Claim Bot

Automatically claims winnings from your Polymarket portfolio.

## Quick Start

1. Get an Ubuntu server (22.04 recommended)
2. Ask Claude Code to set up the bot using instructions in `CLAUDE.md`
3. Login to Polymarket via VNC
4. Run the bot

## How It Works

- Monitors your Polymarket portfolio page
- When winnings are available, clicks "Claim" button
- Confirms the claim in the modal
- Waits 3 minutes for transaction, then checks again

## Requirements

- Ubuntu 22.04 server
- Firefox (snap version)
- VNC for initial setup
- Polymarket account with Google login

## Files

- `polymarket_claim_bot_firefox.py` - Main bot script
- `CLAUDE.md` - Setup instructions for Claude Code
- `README.md` - This file

## Usage

```bash
# GUI mode (visible in VNC)
python3 polymarket_claim_bot_firefox.py --gui

# Headless mode (background)
python3 polymarket_claim_bot_firefox.py
```

## Logs

Bot logs are saved to: `~/.polymarket_bot/bot.log`
