# Telegram registration funnel

Минимальный локальный проект: бот на aiogram, SQLite для статистики и HTML-дашборд, который можно открыть как Telegram Mini App.

## Требования

- Python 3.10+
- токен бота от [@BotFather](https://t.me/BotFather)

## Запуск локально

```bash
# После клонирования публичного репозитория:
cd telegram-registration-funnel
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

В текущем Replit-проекте папка приложения называется `telegram-funnel`, поэтому здесь используйте `cd telegram-funnel`.

Добавьте токен в `.env`:

```env
TELEGRAM_BOT_TOKEN=токен_от_BotFather
PORT=8000
```

Запустите одним процессом:

```bash
python main.py
```

Дашборд откроется в браузере на `http://localhost:8000`. Бот работает через long polling. После `/start` отправьте контакт кнопкой «Отправить номер». Два сообщения запланированы на 10 и 60 секунд после регистрации.

Для уже зарегистрированного пользователя `/start` повторно показывает кнопку дашборда без запроса телефона.

## Открытие внутри Telegram

Telegram требует HTTPS-адрес для Mini App. Для локальной демонстрации можно временно открыть порт `8000` через HTTPS-туннель, например ngrok, и добавить полученный адрес в `.env`:

```env
WEB_APP_URL=https://ваш-временный-домен
```

Перезапустите `python main.py`. После регистрации бот покажет кнопку «Открыть дашборд». Постоянный хостинг и деплой не нужны.

## Конфигурация и данные

- `config.yaml` — приветствие, запрос телефона, тексты и задержки сообщений.
- `DATABASE_PATH` — путь к SQLite (по умолчанию `data/bot.sqlite3`).
- Номера телефонов и Telegram-ники сохраняются только локально; дашборд показывает обезличенный список.
- `GET /api/stats` — статистика для страницы, `GET /health` — проверка сервера.

Не добавляйте `.env` или файл базы данных в GitHub.

