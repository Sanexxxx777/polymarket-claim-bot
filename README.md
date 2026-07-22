# Polymarket Auto-Claim Bot

Автоматически клеймит выигрыши и закрывает лоссы на Polymarket через Firefox + Selenium.

## Что делает

1. Открывает `polymarket.com/portfolio` в headless Firefox
2. Если есть кнопка **Claim / Redeem** — кликает, подтверждает модалку
3. Открывает `portfolio?tab=history` — проверяет **Close Losses**
4. Повторяет цикл каждые 4 минуты
5. Поддерживает несколько аккаунтов (каждый — отдельный Firefox профиль)

Один Firefox профиль покрывает весь аккаунт (все боты, любые стратегии — portfolio общий).

## Требования

- Ubuntu 22.04 (или любой Linux с Firefox)
- Python 3.10+
- Firefox (обычный, не snap рекомендуется для headless)
- Polymarket аккаунт с Google логином
- VNC (TigerVNC/TightVNC) — только для первичного логина через GUI

## Установка

Полная инструкция: [`docs/SETUP_GUIDE.md`](docs/SETUP_GUIDE.md)

```bash
# Быстрый старт
pip3 install selenium sentry-sdk tomli
cp src/config.example.toml src/config.toml
# Отредактируй config.toml — впиши firefox_profile name
python3 src/polymarket_claim_bot_firefox.py --login  # первичный логин через VNC
python3 src/polymarket_claim_bot_firefox.py          # обычный запуск (headless)
```

## Структура

```
polymarket-claim-bot/
├── src/
│   ├── polymarket_claim_bot_firefox.py   # main script
│   ├── config.toml                       # gitignored — твои секреты
│   ├── config.example.toml               # шаблон
│   ├── README.md                         # краткое описание
│   └── CLAUDE.md                         # контекст для Claude Code
├── docs/
│   └── SETUP_GUIDE.md                    # полная инструкция с нуля
├── bin/
│   └── geckodriver                       # gitignored — скачай с GitHub
├── firefox_profiles/                     # gitignored — содержат cookies
│   ├── 4anxayi6.claimbot/                # Account 1
│   ├── 45ct69qx.default/                 # Account 3
│   └── natali.claimbot/                  # Natali-21
└── .gitignore
```

## Запуск / Остановка

```bash
# Headless (фоново)
cd src && screen -dmS claimbot python3 -u polymarket_claim_bot_firefox.py

# Проверить логи
screen -r claimbot           # attach
tail -20 /tmp/claim.log

# Остановить
screen -S claimbot -X quit
```

## Безопасность

См. [SECURITY.md](SECURITY.md).

## Лицензия

MIT — см. [`LICENSE`](LICENSE).

## Контакт

**Aleksandr Shulgin** ([@Sanexxxx777](https://github.com/Sanexxxx777)) (@Aleksandr_NFA)
