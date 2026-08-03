# Модуль авторизации — детальная спека

Свободная регистрация, e-mail + пароль, iOS-only, без дилеров/скидок/привилегий.
Версия 0.1. Реализация — FastAPI + PostgreSQL + Redis.

---

## 1. Решения и scope

- **Логин = e-mail.** Нужен как канал восстановления пароля (без телефона другого нет).
- **Регистрация свободная**, self-service. Никаких организаций/дилер-кодов.
- **Пароль** хранится только как Argon2id-хеш.
- **Токены:** короткий access JWT + ротируемый refresh (серверный, отзываемый).
- **E-mail-верификация — мягкая:** играть можно сразу, верификация не блокирует, но нужна для надёжного сброса пароля.
- **Зависимость:** провайдер транзакционных писем (сброс + верификация). В РФ — Unisender / SendPulse / собственный SMTP / Yandex. Без него сброс пароля не работает, так что это не опционально.

Что auth-модуль **не** делает в этом MVP: никаких ролей, орг, наград, OAuth/соцсетей, 2FA. Всё это — потом.

---

## 2. Модель токенов

| | Access | Refresh |
|---|---|---|
| Формат | JWT (HS256 на MVP; RS256 если позже дробить сервисы) | Непрозрачная случайная строка (не JWT) |
| TTL | ~15 мин | ~60 дней |
| Хранение на сервере | не хранится (stateless) | хранится **хеш** (SHA-256) в БД |
| Хранение на клиенте | Keychain (iOS) | Keychain |
| Отзыв | по истечению | немедленный (revoked_at) |
| Ротация | — | при каждом refresh; старый инвалидируется |

**Claims access-JWT (минимум):** `sub` (user_id), `iat`, `exp`, `jti`, `typ:"access"`. Ничего чувствительного (ни e-mail, ни имя) в токен не кладём.

**Ротация с детекцией угона:** refresh-токены объединяются в «семью» (`family_id`). При обновлении старый помечается использованным, выдаётся новый. **Если приходит уже использованный refresh** — это признак кражи → отзываем всю семью (разлогин на всех устройствах этого юзера).

---

## 3. Правила пароля (NIST-style: длина важнее символов)

- Минимум **10 символов**, максимум **128** (защита от DoS гигантским вводом).
- Разрешены любые символы, включая пробелы и юникод. Никаких обязательных «1 заглавная + 1 цифра + 1 спецсимвол».
- Никакой принудительной ротации.
- **Проверка на утёкшие пароли** — HIBP через k-anonymity (шлётся только префикс SHA-1 хеша, сам пароль не уходит) → `[defer-ok]` можно отложить, но желательно. Офлайн-альтернатива: локальный список топ-10k паролей.

---

## 4. Эндпоинты

Базовый префикс `/api/v1/auth`. Формат — JSON. Все ответы с ошибкой — по единому конверту (раздел 5).

### 4.1 Регистрация

```
POST /register
Body: { "email": "...", "password": "...", "nickname": "..." (опц.), "device": {...} }

Логика:
  1. Валидация: формат e-mail; политика пароля; nickname (если есть).
  2. Нормализация e-mail (trim, lowercase).
  3. Проверка уникальности e-mail (см. антиэнумерацию ниже).
  4. Хеш пароля Argon2id.
  5. Создать users + user_state (стартовые: xp=0, level=1, lives=5, streak=0).
  6. Асинхронно отправить письмо-верификацию.
  7. Зарегистрировать device, выдать access + refresh.

201 → { "access_token", "refresh_token", "user": { id, email, nickname, email_verified:false } }
```

**Антиэнумерация при регистрации** (e-mail неизбежно раскрывает занятость):
- Рекомендуемо для игры: явное `409 email_taken` на клиенте — норм, НО жёсткий rate-limit регистрации по IP (иначе массовый перебор).
- Строгий режим (если важно): всегда `200`, а существующему адресу шлём письмо «кто-то пытался зарегистрироваться под вашим e-mail». Для «просто игры» это оверкилл — оставляю на выбор.

### 4.2 Вход

```
POST /login
Body: { "email": "...", "password": "...", "device": {...} }

Логика:
  1. Rate-limit по (email + IP + device). Лок после N неудач (раздел 6).
  2. Найти пользователя по нормализованному e-mail.
  3. Argon2id-verify (constant-time). Успех/провал — одинаковый ответ и тайминг.
  4. Проверить status != 'blocked'.
  5. Выдать access + refresh, обновить device, last_login_at.

200 → { "access_token", "refresh_token", "user": {...} }
401 → invalid_credentials  (одинаково для «нет юзера» и «неверный пароль»)
423 → account_locked (+ Retry-After)
```

### 4.3 Обновление токена

```
POST /refresh
Body: { "refresh_token": "..." }

Логика:
  1. Хешировать пришедший токен, найти в refresh_tokens.
  2. Проверить: не revoked, не expired, привязка к device.
  3. Если токен уже использован (revoked, но семья жива) → УГОН:
     отозвать всю family_id, вернуть 401.
  4. Иначе: ротация — пометить старый revoked, выдать новый refresh
     (та же family_id) + новый access.

200 → { "access_token", "refresh_token" }
401 → token_invalid / token_expired
```

### 4.4 Выход

```
POST /logout            (Authorization: Bearer <access>)
Body: { "refresh_token": "..." }
  → отозвать этот refresh (сессия текущего устройства). 204.
```

### 4.5 Запрос сброса пароля

```
POST /password/reset-request
Body: { "email": "..." }

Логика:
  1. Rate-limit по (email + IP).
  2. ВСЕГДА вернуть 200 (антиэнумерация — не палим наличие адреса).
  3. Если юзер есть: сгенерировать reset-токен (случайный), сохранить ХЕШ
     (Redis, TTL 30 мин, одноразовый), отправить письмо со ссылкой.

200 → { "message": "Если адрес зарегистрирован, письмо отправлено" }
```

### 4.6 Подтверждение сброса

```
POST /password/reset-confirm
Body: { "token": "...", "new_password": "..." }

Логика:
  1. Хешировать токен, найти, проверить TTL и что не использован.
  2. Валидировать новый пароль.
  3. Поставить новый Argon2id-хеш, пометить токен использованным.
  4. ОТОЗВАТЬ ВСЕ refresh-токены юзера (принудительный релогин везде).

200 → { "message": "Пароль обновлён" }
410 → token_expired
400 → token_invalid / weak_password
```

### 4.7 Смена пароля (авторизованный)

```
POST /password/change   (Authorization: Bearer <access>)
Body: { "current_password": "...", "new_password": "..." }
  → verify current, поставить новый, отозвать ОСТАЛЬНЫЕ сессии (кроме текущей). 200.
```

### 4.8 Верификация e-mail

```
GET  /verify-email?token=...        → пометить email_verified=true. 200.
POST /verify-email/resend  (auth)   → повторно отправить письмо (rate-limit). 202.
```

### 4.9 Профиль

```
GET  /me   (auth)   → { user: {...}, state: { xp, level, lives, streak_count } }
PATCH /me  (auth)   → { nickname?, region?, timezone? }
```

`[defer-ok]` Управление сессиями (`GET /sessions`, `DELETE /sessions/{id}`) — приятно, но не для первого MVP.

---

## 5. Модель ошибок

Единый конверт:

```json
{ "error": { "code": "invalid_credentials", "message": "Неверный e-mail или пароль" } }
```

Для валидации — с деталями по полям:

```json
{ "error": { "code": "validation_error", "fields": { "password": "Минимум 10 символов" } } }
```

| HTTP | code | Когда | Что делает клиент |
|---|---|---|---|
| 400 | `validation_error` | Плохой ввод (формат, длина) | Показать ошибки у полей |
| 401 | `invalid_credentials` | Неверный вход | «Неверный e-mail или пароль» |
| 401 | `token_expired` | Access протух | Тихо сделать /refresh, повторить |
| 401 | `token_invalid` | Битый/отозванный токен | Разлогин, на экран входа |
| 403 | `email_not_verified` | Действие требует верификации | Предложить подтвердить e-mail |
| 409 | `email_taken` | E-mail занят (при регистрации) | «Такой e-mail уже есть» / вход |
| 410 | `token_expired` | Reset-ссылка протухла | Запросить новую |
| 422 | `weak_password` | Пароль в утёкших / слабый | Попросить другой |
| 423 | `account_locked` | Много неудач входа | Показать таймер (Retry-After) |
| 429 | `rate_limited` | Превышен лимит запросов | Бэкофф, показать Retry-After |

Заголовок `Retry-After` — на 423 и 429.

---

## 6. Rate limiting и локаут (Redis)

| Действие | Лимит (стартовый) | Механизм |
|---|---|---|
| /login | 5 неудач / e-mail / 15 мин → лок; экспоненциальный бэкофф | счётчик по `login:fail:{email}` |
| /login | + 20 / IP / 15 мин | `login:ip:{ip}` |
| /register | 3 / IP / час | `reg:ip:{ip}` |
| /password/reset-request | 3 / e-mail / час, 10 / IP / час | `reset:{email}`, `reset:ip:{ip}` |
| /verify-email/resend | 3 / юзер / час | `verify:{user}` |

- Успешный вход сбрасывает счётчик неудач.
- Локаут — не вечный: окно с экспонентой (1 мин → 5 → 15 …), не «заблокировать навсегда».
- Всё в Redis с TTL, не в Postgres.

---

## 7. Схема БД (PostgreSQL)

```sql
CREATE EXTENSION IF NOT EXISTS citext;   -- регистронезависимый e-mail

CREATE TABLE users (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email          citext UNIQUE NOT NULL,
  email_verified boolean NOT NULL DEFAULT false,
  password_hash  text NOT NULL,           -- закодированная строка Argon2id
  nickname       text,
  region         text,
  timezone       text DEFAULT 'Europe/Moscow',
  status         text NOT NULL DEFAULT 'active',   -- active | blocked
  created_at     timestamptz NOT NULL DEFAULT now(),
  last_login_at  timestamptz
);

CREATE TABLE user_state (
  user_id        uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  xp             int NOT NULL DEFAULT 0,
  level          int NOT NULL DEFAULT 1,
  lives          int NOT NULL DEFAULT 5,
  lives_updated_at timestamptz NOT NULL DEFAULT now(),
  streak_count   int NOT NULL DEFAULT 0,
  streak_last_active date,
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE devices (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  platform       text NOT NULL DEFAULT 'ios',
  push_token     text,
  push_provider  text DEFAULT 'apns',
  app_version    text,
  last_seen_at   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id      uuid REFERENCES devices(id) ON DELETE SET NULL,
  token_hash     text NOT NULL,           -- SHA-256 от выданного токена
  family_id      uuid NOT NULL,           -- для ротации/детекции угона
  expires_at     timestamptz NOT NULL,
  revoked_at     timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_refresh_hash    ON refresh_tokens(token_hash);
CREATE INDEX idx_refresh_user    ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_family  ON refresh_tokens(family_id);

-- Verify-токены можно в таблице; reset-токены удобнее в Redis (TTL).
CREATE TABLE email_tokens (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind           text NOT NULL,           -- 'verify'
  token_hash     text NOT NULL,
  expires_at     timestamptz NOT NULL,
  used_at        timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);
```

`user_state` живёт в auth-модуле только потому, что создаётся при регистрации; дальше им владеет игровой модуль.

---

## 8. Argon2id — параметры

По OWASP Password Storage Cheat Sheet, отталкиваясь от «подобрать под ~0.5с на своём железе». Разумный старт:

```
memory      = 19 MiB (19456 KiB)   # не ниже
iterations  = 2
parallelism = 1
salt        = 16 байт, на пользователя (генерит библиотека)
```

Библиотека: `argon2-cffi` (Python). Хранить закодированную строку целиком (включает соль и параметры) — при верификации параметры берутся из неё, миграция на более сильные легко делается лениво при следующем входе.

---

## 9. Чеклист безопасности

- [ ] Только HTTPS, HSTS.
- [ ] Пароли — Argon2id, constant-time verify, никогда не логируем.
- [ ] E-mail нормализуется (trim + lowercase, citext).
- [ ] Одинаковый ответ и тайминг при неверном входе (не палим наличие юзера).
- [ ] Rate-limit + локаут на login/register/reset/resend.
- [ ] Refresh: хеш в БД, ротация, детекция повторного использования → отзыв семьи.
- [ ] Сброс/смена пароля → отзыв сессий.
- [ ] В JWT нет чувствительных данных; access короткоживущий.
- [ ] Reset-токены одноразовые, с TTL, хранится хеш.
- [ ] Лимиты на размер тела запроса; валидация content-type.
- [ ] Лог событий auth (успех/провал входа, сбросы) для аномалий — без паролей.
- [ ] PII (e-mail, имя, регион) — хранение в РФ (152-ФЗ), согласие при регистрации, политика конфиденциальности.

---

## 10. Клиент (Flutter, iOS)

- Токены — в `flutter_secure_storage` (Keychain). Не в SharedPreferences.
- HTTP-клиент (dio) с **интерсептором**: на `401 token_expired` — один тихий `/refresh` и повтор запроса; при неудаче refresh — разлогин.
- Не парсить и не доверять `exp` на клиенте для логики безопасности — сервер решает; клиент лишь оптимистично обновляет заранее.
- Экран регистрации/входа: инлайн-валидация, понятные тексты ошибок из конверта.

---

## 11. Lean-MVP: что строим первым

**Обязательно сейчас:**
- `/register`, `/login`, `/refresh`, `/logout`
- `/password/reset-request`, `/password/reset-confirm`
- Argon2id, rate-limit + локаут, refresh-ротация
- Таблицы users / user_state / devices / refresh_tokens
- Транзакционные письма (иначе сброс не работает)

**Можно отложить (`[defer-ok]`):**
- Мягкая e-mail-верификация (можно включить, но не блокирует игру)
- HIBP-проверка утёкших паролей (пока — только длина)
- Детекция угона refresh (сначала — простая ротация; семью добавить в фазу 2)
- Управление сессиями (`/sessions`)
- `/password/change` в интерфейсе (если пока некому менять — редко нужно)

Такой набор — это буквально несколько дней работы на FastAPI, и он безопасен по-взрослому, не будучи оверинжинирингом.
