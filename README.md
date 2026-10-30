# Vocab School

A Flask web app for learning English vocabulary in a classroom, with separate roles for students, teachers and an administrator.

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0%2B-000000?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![PWA](https://img.shields.io/badge/PWA-installable-5A0FC8?logo=pwa&logoColor=white)

## Features

**Students**
- Browse the units uploaded by teachers and read a study page for each unit (word, translation, synonyms, collocations).
- Practise a unit in rounds. Each word is asked in a randomly chosen mode:
  English → Russian, Russian → English, or "pick the correct synonym" (multiple choice).
- A wrong answer sends the word to the end of the queue; the round ends when every word has been answered correctly. Progress within a round is kept in the session, so a student can leave and come back.
- In Russian → English mode, typing a synonym instead of the headword counts as correct, and the app shows the other synonyms.
- A combined synonym test across all units.
- Personal progress page: a mastery level (0–5) per word, with attempts and correct answers.

**Teachers**
- Upload a unit by pasting text or uploading a `.docx` file in the format `1) Word - translation`, then a line of synonyms, then `Collocations:`.
- Bulk upload of several `.docx` files at once; the unit number is detected from the file name (`Unit N`).
- Edit or delete any word.
- Class roster with per-student, per-unit progress (words learned, average level) and a per-word breakdown that puts the weakest words first.

**Administrator**
- Everything a teacher can do.
- Dashboard with counts of users, students, teachers, units and words.
- User management: change roles (student / teacher / admin) or delete users. Self-registration always creates a student account.
- Revision history: who uploaded, edited or deleted words, and who changed roles.

**Other**
- Installable as a Progressive Web App (web manifest and a service worker that caches static assets only).
- Passwords are hashed with Werkzeug; access to each page is checked by role.

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Python, Flask (Jinja2 templates, sessions) |
| Database | SQLite via the standard `sqlite3` module (schema created automatically) |
| File parsing | `python-docx` for `.docx` uploads, regular expressions for the word-list format |
| Frontend | Server-rendered HTML, CSS, Web App Manifest, Service Worker |

## Project structure

```
vocab-school/
├── app.py            # Flask routes: auth, student, teacher and admin views
├── db.py             # SQLite schema, connection helper, default admin, revision log
├── parsing.py        # Parses pasted text / .docx files into word entries
├── requirements.txt
├── static/           # style.css, manifest.json, sw.js, app icons
└── templates/        # Jinja2 templates for every page
```

## Getting started

Requires Python 3.9 or newer.

```bash
git clone https://github.com/umar-rustamov/vocab-school.git
cd vocab-school

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

- The SQLite database `vocab_school.db` is created automatically on first start, so there are no migrations to run.
- A default administrator account is created on first start and its login is printed in the console (see `db.py`). Change it right after the first login.
- In production, set the `SECRET_KEY` environment variable to a long random string so sessions stay valid across restarts.
- When the app is deployed behind a WSGI server, the tables are still created because `db.init_db()` runs on import.

---

## На русском

Веб-приложение на Python (Flask) для заучивания слов классом:
ученики, учителя и главный админ — каждый со своей ролью.

### Что умеет

**Ученик**
- Видит список юнитов (Unit 1, Unit 2...), которые загрузил учитель.
- Проходит тренировку: слово случайно спрашивается то англ→рус, то рус→англ,
  с системой интервальных повторений (слова, которые плохо знаешь, попадаются чаще).
- **Если вместо основного слова написан синоним — ответ засчитывается верным**,
  и приложение показывает остальные синонимы этого слова.
- Видит свой прогресс по каждому слову (уровень 0–5, "закреплено" на уровне 5).

**Учитель**
- Загружает слова юнита: номер юнита + текст (вставить) или файл `.docx` —
  формат тот же, что в ваших файлах Essential 504:
  ```
  1) Word - перевод
  синоним, синоним
  Collocations:
  словосочетание
  ```
- Может редактировать/удалять любое слово в юните.
- Видит список учеников и прогресс каждого по каждому юниту (сколько слов
  выучено, средний уровень) — "кто как выучил, понял" видно сразу.

**Главный админ** (супер-роль, как у разработчика)
- Всё то же, что у учителя.
- Управление пользователями: менять роль (student/teacher/admin), удалять.
- **История правок (revisions)** — кто, когда и что изменил: загрузка слов,
  редактирование, удаление, смена ролей.

Регистрация как учитель требует секретный код (`TEACHER2026` в `app.py`,
поменяйте на свой), чтобы не любой мог сам себя назначить учителем.
Первый админ создаётся автоматически при первом запуске — см. ниже.

### Как запустить (на компьютере)

Нужен Python 3.9+.

```bash
cd vocab-school
pip install -r requirements.txt
python app.py
```

Откройте в браузере: **http://127.0.0.1:5000**

При первом запуске в консоли будет напечатан логин администратора:
```
admin@school.local / admin123
```
Обязательно смените этот пароль после первого входа (через "Пользователи" →
удалить и создать нового админа, либо просто держите это в секрете, если
запускаете только у себя дома).

### Как дать доступ ученикам и учителю с телефонов

Это обычное веб-приложение — им не нужно ничего "скачивать", достаточно
открыть ссылку в браузере телефона. Два варианта:

**Вариант 1 — в своей домашней/школьной сети (бесплатно, самый простой)**
1. Запустите `python app.py` на своём компьютере.
2. Узнайте IP компьютера в локальной сети (Windows: `ipconfig`, Mac/Linux: `ifconfig`).
3. На телефоне (подключённом к той же Wi-Fi), откройте `http://<IP-компьютера>:5000`.

Работает, только пока компьютер включён и все в одной сети.

**Вариант 2 — доступ из любой точки мира (нужен хостинг)**
Разместите проект на бесплатном/недорогом хостинге, например
[PythonAnywhere](https://www.pythonanywhere.com) или [Render](https://render.com).
Тогда у приложения будет постоянная ссылка вида `https://ваш-проект.onrender.com`,
и её можно просто разослать ученикам — работает в браузере на любом телефоне,
без установки.

### Про APK (важно, честно)

Файл `.apk` — это установочный пакет для **нативного** Android-приложения.
Flask/Python сам по себе `.apk` не создаёт — это веб-сервер, а не мобильное
приложение. Есть два реальных пути, если вам обязательно нужен именно `.apk`:

1. **Обернуть сайт в APK** — разместить приложение по Варианту 2 выше (чтобы
   был постоянный URL), а затем через сервис вроде WebIntoApp или
   PWABuilder сгенерировать APK-обёртку, которая просто открывает этот сайт
   внутри приложения. Быстро, но по сути это всё равно браузер внутри.
2. **Переписать на Kivy/BeeWare** — сделать по-настоящему нативное
   Android-приложение на Python (отдельный инструмент, другая архитектура
   интерфейса) — это уже большой отдельный проект, не апгрейд текущего кода.

Для школьного использования вариант с обычной ссылкой (Вариант 2 выше) обычно
удобнее APK: не надо ничего устанавливать, работает сразу в браузере, легко
обновлять.

### Структура проекта

```
vocab-school/
  app.py              — все маршруты и логика
  db.py                — схема SQLite и создание админа
  parsing.py            — разбор текста/докс в список слов
  requirements.txt
  static/style.css
  templates/            — все HTML-страницы
  vocab_school.db        — база данных (создаётся сама при первом запуске)
```

База — обычный файл SQLite, ничего дополнительно устанавливать не нужно.
