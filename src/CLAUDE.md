# Polymarket Auto-Claim Bot v2

Auto-claims winnings and closes losses on Polymarket using Firefox + Selenium.

## How it works
1. Opens `polymarket.com/portfolio` in headless Firefox
2. Checks for "Claim"/"Redeem" button → clicks → confirms modal
3. Opens `portfolio?tab=history` → checks "Close Losses" button
4. Repeats every 4 min, skips settlement windows (+/-2 min from :00/:15/:30/:45)
5. One Firefox profile covers ALL bots on the account (portfolio = whole account)

## Config (config.toml)
See `config.example.toml` for template. Real config contains Telegram token and must stay gitignored.

```toml
persistent = false
telegram_bot_token = ""  # Optional, @BotFather
telegram_chat_id = ""    # Optional, @userinfobot

[[accounts]]
name = "My Account"
firefox_profile = "claimbot.default"
```

## Commands
```bash
screen -r claimbot              # View logs
screen -S claimbot -X quit      # Stop
cd ~/claim_bot && screen -dmS claimbot python3 polymarket_claim_bot_firefox.py  # Start
python3 polymarket_claim_bot_firefox.py --gui    # GUI mode (VNC)
python3 polymarket_claim_bot_firefox.py --login  # Login mode
```

## Dependencies
- Firefox (snap or system) + standalone `/usr/local/bin/geckodriver` (NOT snap geckodriver)
- `pip3 install selenium sentry-sdk tomli`
- VNC (TigerVNC) for initial Google login

## Troubleshooting
- **"binary is not a Firefox executable"**: Snap geckodriver incompatible with `binary_location`. Use standalone geckodriver from GitHub releases.
- **"Failed to set preferences"**: Firefox profile missing (common after snap Firefox update). Recreate profile and re-login via VNC.
- **"Not logged in"**: Google session expired. Connect VNC, run `--login` mode, sign in to Google + Polymarket.
- **Snap update path**: `ls /snap/firefox/current/` - binary_location auto-detected at runtime.

## Optional monitoring (Sentry)
```bash
export SENTRY_DSN="https://..."    # from sentry.io project
```
Empty SENTRY_DSN = Sentry disabled.

## Full setup guide
See `../docs/SETUP_GUIDE.md` for from-scratch installation.

## Version
v2 - persistent Firefox drivers, periodic restart (4h), Google keepalive (30m), Telegram alerts on login failure.
