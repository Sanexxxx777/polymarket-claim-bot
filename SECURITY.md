# Security

- **This bot clicks Claim/Redeem and Close Losses on your Polymarket portfolio
  autonomously**, every 4 minutes. Review `src/polymarket_claim_bot_firefox.py`
  before running it against a real account.
- **Secrets never go in the repo.** Telegram bot token / any credentials belong
  in environment variables or a gitignored config — never hardcoded. If you fork
  this and commit a real token by mistake, rotate it immediately at @BotFather;
  git history is not a safe place to "delete" a secret after the fact.
- **Google-login Polymarket accounts** require a one-time interactive VNC login
  per Firefox profile (see `docs/SETUP_GUIDE.md`) — there is no headless
  credential flow, by design, to avoid storing account passwords anywhere.

## Reporting an issue

Open a GitHub issue, or reach out via the contact below.

## Contact

**Aleksandr Shulgin** ([@Sanexxxx777](https://github.com/Sanexxxx777)) (@Aleksandr_NFA)
