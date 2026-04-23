# Setup Guide — Polymarket Claim Bot

Полная инструкция развёртывания бота с нуля на новом Ubuntu сервере (или восстановление из архива).

---

## Быстрый путь: восстановление из архива

Если у тебя есть локальная копия этого проекта на Mac со всеми Firefox профилями — разворачивание на новом сервере занимает ~10 минут.

### 1. Подготовить сервер

Ubuntu 22.04+, root доступ, 2GB+ RAM, открытый TCP 22 (SSH).

```bash
apt update && apt install -y python3-pip python3-venv firefox screen xvfb
pip3 install selenium sentry-sdk tomli
```

### 2. Установить geckodriver

Snap geckodriver **НЕ РАБОТАЕТ** с `binary_location` — нужен standalone бинарь.

```bash
# Версия 0.36.0 (проверенная стабильная)
wget https://github.com/mozilla/geckodriver/releases/download/v0.36.0/geckodriver-v0.36.0-linux64.tar.gz
tar -xzf geckodriver-v0.36.0-linux64.tar.gz
mv geckodriver /usr/local/bin/
chmod +x /usr/local/bin/geckodriver
geckodriver --version   # проверка
```

Либо скопировать бинарь из архива:
```bash
scp local_path/bin/geckodriver root@server:/usr/local/bin/
```

### 3. Залить код + Firefox профили

С локального Mac (где лежит архив):

```bash
# Код
rsync -av --exclude="__pycache__" --exclude="*.bak" \
  /Users/sasha/Projects/polymarket-claim-bot/src/ \
  root@server:/root/claim_bot/

# Firefox профили (с авторизацией в Google/Polymarket внутри)
mkdir -p /root/snap/firefox/common/.mozilla/firefox  # на сервере
rsync -av /Users/sasha/Projects/polymarket-claim-bot/firefox_profiles/ \
  root@server:/root/snap/firefox/common/.mozilla/firefox/
```

### 4. Создать `profiles.ini` в Firefox

Если Firefox ещё не запускался на сервере — ему нужен `profiles.ini`:

```bash
cat > /root/snap/firefox/common/.mozilla/firefox/profiles.ini <<EOF
[Install5C6CFEE526AD1AD3]
Default=4anxayi6.claimbot
Locked=1

[Profile0]
Name=default
IsRelative=1
Path=4anxayi6.claimbot
Default=1

[Profile1]
Name=fast-bots
IsRelative=1
Path=45ct69qx.default

[Profile2]
Name=natali
IsRelative=1
Path=natali.claimbot

[General]
StartWithLastProfile=1
Version=2
EOF
```

### 5. Запустить

```bash
cd /root/claim_bot
screen -dmS claimbot bash -c 'python3 -u polymarket_claim_bot_firefox.py >> /tmp/claim.log 2>&1'

# Проверить
tail -20 /tmp/claim.log
screen -r claimbot
```

---

## Полная установка с нуля (без архива)

Если Firefox профиль утерян / новый сервер без готовых сессий — надо залогиниться заново через VNC.

### 1. Поставить VNC

```bash
apt install -y tigervnc-standalone-server
vncpasswd                                  # задать пароль
vncserver :2 -geometry 1280x800 -depth 24
```

Пробросить порт с Mac:
```bash
ssh -L 5902:localhost:5902 root@server -N &
# подключиться VNC Viewer'ом к localhost:5902
```

### 2. Создать Firefox профиль

```bash
snap run firefox --headless -CreateProfile "claimbot /root/snap/firefox/common/.mozilla/firefox/claimbot.default"
```

Либо (если не snap):
```bash
firefox -CreateProfile "claimbot ~/.mozilla/firefox/claimbot.default"
```

Запомни имя профиля (папку).

### 3. Залогиниться в Google + Polymarket через VNC

```bash
export DISPLAY=:2
xhost +                                    # если "X-авторизация отказана"
cd /root/claim_bot
python3 polymarket_claim_bot_firefox.py --login
```

В открывшемся Firefox:
1. `accounts.google.com` → войти
2. `polymarket.com` → Connect via Google → подтвердить
3. Проверить что портфолио отображается
4. Закрыть Firefox (скрипт подхватит сессию)

### 4. Заполнить config.toml

```bash
cd /root/claim_bot
cp config.example.toml config.toml
nano config.toml
```

```toml
persistent = false
telegram_bot_token = ""  # опционально
telegram_chat_id = ""

[[accounts]]
name = "My Account"
firefox_profile = "claimbot.default"
```

### 5. Запустить headless

```bash
screen -dmS claimbot bash -c 'python3 -u polymarket_claim_bot_firefox.py >> /tmp/claim.log 2>&1'
sleep 30
tail -30 /tmp/claim.log
```

Если в логе есть `[Init] Started for account "..."` и `[Claim] No claim available` (или `[Claim] Clicked!`) — всё работает.

---

## Telegram alerts (опционально)

Бот шлёт уведомление если 3 попытки логина подряд провалились:

1. Создать бота через `@BotFather` → получить токен (`1234567890:AAA...`)
2. Найти свой `chat_id` через `@userinfobot`
3. Вписать в `config.toml`:
   ```toml
   telegram_bot_token = "1234567890:AAA..."
   telegram_chat_id = "12345678"
   ```
4. Рестартовать бота.

---

## Sentry (опционально)

В коде есть `sentry_sdk.init(...)` с DSN. Для своего проекта:

1. Создать проект на [sentry.io](https://sentry.io) → получить DSN
2. Опция A: env var (рекомендуется):
   ```bash
   export SENTRY_DSN="https://..."
   ```
   И поменять в коде `sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN"))`.
3. Опция B: отключить Sentry вовсе — закомментить строку `sentry_sdk.init(...)`.

---

## Troubleshooting

### "binary is not a Firefox executable"
Selenium использует snap geckodriver вместо standalone. Решение: установить standalone (шаг 2).

### "All 3 login attempts failed"
Google сессия в Firefox профиле истекла. Перелогиниться через VNC (шаги 3-4 полной установки).

### "Failed to set preferences"
Профиль удалён (обычно после snap update Firefox'а). Создать заново (шаг 2 полной установки), перелогиниться.

### Firefox не стартует на VNC
```bash
export DISPLAY=:2
xhost +
snap run firefox
```

### "Proxy/X auth rejected"
```bash
export XAUTHORITY=~/.Xauthority
xauth list $DISPLAY
```

---

## Типичные проблемы в production

### Snap Firefox обновился → сессия слетела
Snap Firefox иногда пересоздаёт конфиг при обновлении. Профиль остаётся, но `profiles.ini` сбрасывается. Решение:
1. Проверить `ls /root/snap/firefox/common/.mozilla/firefox/` — профили на месте?
2. Пересоздать `profiles.ini` (см. шаг 4 быстрого пути)
3. Если сессии Google истекли — перелогиниться через VNC

### Polymarket переименовал кнопки
Бот ищет текст `Claim` / `Redeem` / `Claim proceeds` / `Close Losses`. При редизайне UI Polymarket селекторы могут сломаться. Обновить в коде `_find_claim_button()` и `_find_close_losses_button()`.

### "No claim available" постоянно
Нормально — значит портфолио пустое (уже закрыт). Проверить на polymarket.com/portfolio вручную.

---

## Наши аккаунты (context для восстановления)

Реальные данные (email / proxy addresses / credentials) в приватной заметке на Mac,
не в git. Здесь только маппинг профиль → назначение.

| Профиль | Аккаунт | Назначение |
|---|---|---|
| `4anxayi6.claimbot` | Account 1 | Основные боты (beta, follow-delta, postclose) |
| `45ct69qx.default` | Account 3 | Fast-bots (5m/15m) |
| `natali.claimbot` | Natali-21 | MM Live (v5_natali) |

**Важно:** на один Polymarket аккаунт = **один Firefox профиль** = все боты этого аккаунта клеймятся одновременно (portfolio общий).

Приватные данные (email, приват-ключ, proxy-адрес для каждого аккаунта) хранятся в:
- `../firefox_profiles/<profile>/` — в cookies/session-хранилище Firefox (gitignored)
- Локальный `../PRIVATE_ACCOUNTS.md` (если создашь, тоже в .gitignore)

---

## Версия
- **v2** — persistent Firefox, keep-alive Google session, Telegram alerts
- Тестировано: Ubuntu 22.04, Firefox 130+, geckodriver 0.36.0, Selenium 4.40, Python 3.10
