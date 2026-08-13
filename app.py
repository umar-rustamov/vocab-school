# -*- coding: utf-8 -*-
"""
Vocab School — приложение для заучивания слов с ролями студент / учитель / админ.

Запуск:
    pip install -r requirements.txt
    python app.py

Подробности — в README.md
"""

import json
import os
import random
import time
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

import db
from parsing import (
    parse_vocab_text,
    extract_docx_text,
    normalize,
    guess_unit_number,
    guess_unit_title,
)

app = Flask(__name__)
# На хостинге задайте переменную окружения SECRET_KEY (любая длинная случайная
# строка) — иначе сессии всех пользователей слетят при каждом перезапуске сервера.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")

# Создаём таблицы (если их ещё нет) сразу при импорте — важно для хостинга:
# там сервер запускает Flask через WSGI, а не через "python app.py", так что
# блок if __name__ == "__main__" ниже не выполнится вообще.
db.init_db()

BOX_INTERVALS_DAYS = [0, 1, 3, 7, 16, 35]
MASTER_BOX = 5  # потолок для "уровня" слова (растёт при повторных верных тестах)
LEARNED_BOX = 1  # слово считается выученным/пройденным, если тест по нему пройден верно хотя бы раз
DAY_SECONDS = 24 * 60 * 60


# ---------- auth helpers ----------

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return user


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user or user["role"] not in roles:
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    return decorator


@app.context_processor
def inject_user():
    return {"user": current_user()}


# ---------- home / auth ----------

@app.route("/")
def index():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] == "student":
        return redirect(url_for("student_dashboard"))
    if user["role"] == "teacher":
        return redirect(url_for("teacher_dashboard"))
    return redirect(url_for("admin_dashboard"))


@app.route("/register", methods=["GET", "POST"])
def register():
    # Самостоятельная регистрация — всегда ученик. Учителей/админов назначает
    # администратор вручную через «Пользователи» (см. admin_change_role).
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = "student"

        if not name or not email or not password:
            flash("Заполните все поля.", "error")
            return render_template("register.html")

        conn = db.get_db()
        exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            conn.close()
            flash("Пользователь с таким email уже существует.", "error")
            return render_template("register.html")

        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash(password), role),
        )
        conn.commit()
        conn.close()
        flash("Регистрация прошла успешно, войдите в систему.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = db.get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        flash("Неверный email или пароль.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- student ----------

@app.route("/student")
@role_required("student")
def student_dashboard():
    user = current_user()
    conn = db.get_db()
    units = conn.execute("SELECT * FROM units ORDER BY number").fetchall()

    unit_stats = []
    for u in units:
        words = conn.execute("SELECT id FROM words WHERE unit_id = ?", (u["id"],)).fetchall()
        word_ids = [w["id"] for w in words]
        total = len(word_ids)
        mastered = 0
        if word_ids:
            placeholders = ",".join("?" * len(word_ids))
            mastered = conn.execute(
                f"SELECT COUNT(*) c FROM progress WHERE student_id = ? AND box >= ? "
                f"AND word_id IN ({placeholders})",
                (user["id"], LEARNED_BOX, *word_ids),
            ).fetchone()["c"]
        unit_stats.append({"unit": u, "total": total, "mastered": mastered})
    conn.close()
    return render_template("student_dashboard.html", unit_stats=unit_stats)


@app.route("/student/study/<int:unit_id>")
@role_required("student")
def student_study(unit_id):
    """Материал юнита для изучения перед тестом: слово, перевод, синонимы,
    коллокации — без квиза, просто прочитать/повторить. Дальше — кнопка на тест."""
    conn = db.get_db()
    unit = conn.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
    if not unit:
        conn.close()
        abort(404)
    words = conn.execute(
        "SELECT * FROM words WHERE unit_id = ? ORDER BY word", (unit_id,)
    ).fetchall()
    conn.close()
    words = [
        dict(w, synonyms=json.loads(w["synonyms"]), collocations=json.loads(w["collocations"]))
        for w in words
    ]
    return render_template("student_study.html", unit=unit, words=words)


def _parse_synonym_candidates(words):
    """Разбирает список слов (сырые строки из БД) ОДИН РАЗ в плоский пул
    возможных отвлекающих вариантов: (word_id, текст, normalize(текст)).
    _build_synonym_options берёт пул отсюда вместо повторного json.loads()
    на каждой паре слов — важно для общего теста по всем юнитам сразу,
    где слов сотни и квадратичный повторный парсинг JSON заметно тормозит."""
    candidates = []
    for w in words:
        texts = [w["word"]] + [
            s.strip() for s in json.loads(w["synonyms"] or "[]") if s.strip()
        ]
        for t in texts:
            if t:
                candidates.append((w["id"], t, normalize(t)))
    return candidates


def _build_synonym_options(word, candidates):
    """Для режима квиза «выбери синоним»: возвращает перемешанный список из
    вариантов (один верный синоним слова + до 3 отвлекающих, взятых из пула
    _parse_synonym_candidates), либо None, если у слова нет синонимов или не
    набралось достаточно отвлекающих вариантов (нужно минимум 2)."""
    own_synonyms = [s.strip() for s in json.loads(word["synonyms"] or "[]") if s.strip()]
    if not own_synonyms:
        return None

    exclude = {normalize(word["word"])} | {normalize(s) for s in own_synonyms}
    pool = []
    seen = set()
    for wid, text, norm in candidates:
        if wid == word["id"] or norm in exclude or norm in seen:
            continue
        seen.add(norm)
        pool.append(text)

    if len(pool) < 2:
        return None

    correct = random.choice(own_synonyms)
    distractors = random.sample(pool, min(3, len(pool)))
    options = [correct] + distractors
    random.shuffle(options)
    return options


@app.route("/student/quiz/<int:unit_id>", methods=["GET", "POST"])
@role_required("student")
def student_quiz(unit_id):
    """Тренировка юнита проходит "заходами": в начале очередь — все слова юнита
    в случайном порядке. Ответил верно — слово в этом заходе больше не покажется.
    Ответил неверно — слово уходит не сразу, а в конец очереди (после остальных).
    Когда очередь и список "на повтор" опустели — каждое слово хоть раз отвечено
    верно, заход завершён. Состояние очереди хранится в сессии, поэтому если
    ученик уйдёт и вернётся — заход продолжится с того же места, а не сначала.

    У каждого слова заход случайно выбирает один из режимов:
    "en-ru" (перевести на русский), "ru-en" (напечатать слово по переводу)
    или "synonym" (выбрать из вариантов правильный синоним, см.
    _build_synonym_options) — последний доступен только если у слова есть
    синонимы и в юните нашлось достаточно отвлекающих вариантов."""
    user = current_user()
    conn = db.get_db()
    unit = conn.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
    if not unit:
        conn.close()
        abort(404)

    words = conn.execute("SELECT * FROM words WHERE unit_id = ?", (unit_id,)).fetchall()
    if not words:
        conn.close()
        flash("В этом юните пока нет слов.", "error")
        return redirect(url_for("student_dashboard"))

    word_by_id = {w["id"]: w for w in words}
    valid_ids = set(word_by_id.keys())
    total = len(words)

    queue_key = f"quiz_queue_{unit_id}"
    retry_key = f"quiz_retry_{unit_id}"
    done_key = f"quiz_done_{unit_id}"

    queue = session.get(queue_key)
    retry = session.get(retry_key, [])
    done = session.get(done_key, [])

    # свежий заход: сессии ещё нет, либо в юните поменялись слова с прошлого раза
    if queue is None or not valid_ids.issuperset(set(queue) | set(retry) | set(done)):
        queue = list(valid_ids)
        random.shuffle(queue)
        retry = []
        done = []

    result = None

    if request.method == "POST":
        word_id = int(request.form["word_id"])
        direction = request.form["direction"]
        answer = request.form.get("answer", "")
        word = word_by_id.get(word_id)

        if word:
            synonyms = json.loads(word["synonyms"] or "[]")
            matched_synonym = None
            if direction == "en-ru":
                acceptable = [normalize(t) for t in word["translation"].split(",")]
                correct = normalize(answer) in acceptable
            elif direction == "ru-en":
                typed = normalize(answer)
                main = normalize(word["word"])
                syn_norm = [normalize(s) for s in synonyms]
                correct = typed == main or typed in syn_norm
                if correct and typed != main:
                    matched_synonym = answer.strip()
            else:  # "synonym" — ученик выбирает вариант, а не печатает ответ
                syn_norm = [normalize(s) for s in synonyms]
                correct = normalize(answer) in syn_norm

            now = int(time.time())
            prog = conn.execute(
                "SELECT * FROM progress WHERE student_id = ? AND word_id = ?",
                (user["id"], word_id),
            ).fetchone()
            box = prog["box"] if prog else 0
            new_box = min(box + 1, MASTER_BOX) if correct else 0
            due = now + BOX_INTERVALS_DAYS[new_box] * DAY_SECONDS

            if prog:
                conn.execute(
                    "UPDATE progress SET box=?, due=?, seen=seen+1, correct=correct+?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (new_box, due, 1 if correct else 0, prog["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO progress (student_id, word_id, box, due, seen, correct) "
                    "VALUES (?, ?, ?, ?, 1, ?)",
                    (user["id"], word_id, new_box, due, 1 if correct else 0),
                )
            conn.commit()

            result = {
                "correct": correct,
                "word": word["word"],
                "translation": word["translation"],
                "synonyms": synonyms,
                "matched_synonym": matched_synonym,
                "direction": direction,
            }

            # обновляем очередь этого захода
            if correct:
                if word_id not in done:
                    done.append(word_id)
                if word_id in retry:
                    retry.remove(word_id)
            elif word_id not in retry:
                retry.append(word_id)

    # выбираем следующее слово захода
    if not queue:
        if retry:
            queue = retry
            random.shuffle(queue)
            retry = []
        else:
            # очередь и список "на повтор" пусты — каждое слово этого захода
            # хоть раз отвечено верно, заход пройден
            session.pop(queue_key, None)
            session.pop(retry_key, None)
            session.pop(done_key, None)
            next_unit = conn.execute(
                "SELECT * FROM units WHERE number > ? ORDER BY number LIMIT 1",
                (unit["number"],),
            ).fetchone()
            conn.close()
            return render_template(
                "unit_complete.html",
                unit=unit,
                total=total,
                result=result,
                next_unit=next_unit,
            )

    next_word_id = queue.pop(0)
    next_word = word_by_id[next_word_id]

    mode_choices = ["en-ru", "ru-en"]
    synonym_options = _build_synonym_options(next_word, _parse_synonym_candidates(words))
    if synonym_options:
        mode_choices.append("synonym")
    next_direction = random.choice(mode_choices)

    # en-ru и synonym оба показывают английское слово (в первом случае его
    # переводят, во втором — выбирают синоним), ru-en показывает перевод
    prompt = next_word["translation"] if next_direction == "ru-en" else next_word["word"]

    session[queue_key] = queue
    session[retry_key] = retry
    session[done_key] = done
    session.permanent = True

    conn.close()
    progress_pct = round(len(done) / total * 100) if total else 0

    return render_template(
        "quiz.html",
        unit=unit,
        word=next_word,
        direction=next_direction,
        prompt=prompt,
        options=synonym_options if next_direction == "synonym" else None,
        result=result,
        done_count=len(done),
        total=total,
        progress_pct=progress_pct,
    )


@app.route("/student/test", methods=["GET", "POST"])
@role_required("student")
def student_test():
    """Общий тест по словам ВСЕХ юнитов сразу (а не одного): только режим
    «выбери синоним» — показывается английское слово, ученик выбирает верный
    синоним из вариантов. Слова без синонимов в тест не попадают — их нечем
    тестировать в этом режиме. Очередь/повтор/прогресс — по той же схеме
    "заходов", что и в student_quiz, только без деления на юниты."""
    user = current_user()
    conn = db.get_db()

    all_words = conn.execute("SELECT * FROM words").fetchall()
    synonym_candidates = _parse_synonym_candidates(all_words)  # разбираем JSON один раз на все слова
    candidates = [w for w in all_words if json.loads(w["synonyms"] or "[]")]
    # отсекаем слова, для которых в принципе не набрать отвлекающие варианты
    testable = [w for w in candidates if _build_synonym_options(w, synonym_candidates)]

    if not testable:
        conn.close()
        flash("Пока нет слов с синонимами для теста.", "error")
        return redirect(url_for("student_dashboard"))

    word_by_id = {w["id"]: w for w in testable}
    valid_ids = set(word_by_id.keys())
    total = len(testable)

    queue_key = "test_queue_all"
    retry_key = "test_retry_all"
    done_key = "test_done_all"

    queue = session.get(queue_key)
    retry = session.get(retry_key, [])
    done = session.get(done_key, [])

    # свежий заход: сессии ещё нет, либо набор тестируемых слов поменялся
    # (учитель добавил/убрал слово или синонимы) с прошлого раза
    if queue is None or not valid_ids.issuperset(set(queue) | set(retry) | set(done)):
        queue = list(valid_ids)
        random.shuffle(queue)
        retry = []
        done = []

    result = None

    if request.method == "POST":
        word_id = int(request.form["word_id"])
        answer = request.form.get("answer", "")
        word = word_by_id.get(word_id)

        if word:
            synonyms = json.loads(word["synonyms"] or "[]")
            syn_norm = [normalize(s) for s in synonyms]
            correct = normalize(answer) in syn_norm

            now = int(time.time())
            prog = conn.execute(
                "SELECT * FROM progress WHERE student_id = ? AND word_id = ?",
                (user["id"], word_id),
            ).fetchone()
            box = prog["box"] if prog else 0
            new_box = min(box + 1, MASTER_BOX) if correct else 0
            due = now + BOX_INTERVALS_DAYS[new_box] * DAY_SECONDS

            if prog:
                conn.execute(
                    "UPDATE progress SET box=?, due=?, seen=seen+1, correct=correct+?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (new_box, due, 1 if correct else 0, prog["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO progress (student_id, word_id, box, due, seen, correct) "
                    "VALUES (?, ?, ?, ?, 1, ?)",
                    (user["id"], word_id, new_box, due, 1 if correct else 0),
                )
            conn.commit()

            result = {"correct": correct, "word": word["word"], "synonyms": synonyms}

            if correct:
                if word_id not in done:
                    done.append(word_id)
                if word_id in retry:
                    retry.remove(word_id)
            elif word_id not in retry:
                retry.append(word_id)

    if not queue:
        if retry:
            queue = retry
            random.shuffle(queue)
            retry = []
        else:
            session.pop(queue_key, None)
            session.pop(retry_key, None)
            session.pop(done_key, None)
            conn.close()
            return render_template("test_complete.html", total=total, result=result)

    next_word_id = queue.pop(0)
    next_word = word_by_id[next_word_id]
    options = _build_synonym_options(next_word, synonym_candidates)

    session[queue_key] = queue
    session[retry_key] = retry
    session[done_key] = done
    session.permanent = True

    conn.close()
    progress_pct = round(len(done) / total * 100) if total else 0

    return render_template(
        "test.html",
        word=next_word,
        options=options,
        result=result,
        done_count=len(done),
        total=total,
        progress_pct=progress_pct,
    )


@app.route("/student/progress")
@role_required("student")
def student_progress():
    user = current_user()
    conn = db.get_db()
    rows = conn.execute(
        """
        SELECT w.word, w.translation, u.number as unit_number, p.box, p.seen, p.correct
        FROM progress p
        JOIN words w ON w.id = p.word_id
        JOIN units u ON u.id = w.unit_id
        WHERE p.student_id = ?
        ORDER BY u.number, p.box DESC
        """,
        (user["id"],),
    ).fetchall()
    conn.close()
    return render_template(
        "student_progress.html", rows=rows, learned_box=LEARNED_BOX, master_box=MASTER_BOX
    )


# ---------- teacher ----------

@app.route("/teacher")
@role_required("teacher", "admin")
def teacher_dashboard():
    conn = db.get_db()
    units = conn.execute(
        """
        SELECT units.*, users.name as author_name,
               (SELECT COUNT(*) FROM words WHERE words.unit_id = units.id) as word_count
        FROM units LEFT JOIN users ON users.id = units.created_by
        ORDER BY units.number
        """
    ).fetchall()
    student_count = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE role = 'student'"
    ).fetchone()["c"]
    conn.close()
    return render_template("teacher_dashboard.html", units=units, student_count=student_count)


def _import_words_into_unit(conn, user, number, title, entries):
    """Создаёт юнит (или использует существующий по номеру) и добавляет в него
    новые слова из entries. Дубликаты (по слову, без учёта регистра) пропускаются.
    Возвращает (unit_id, сколько слов реально добавлено)."""
    unit = conn.execute("SELECT * FROM units WHERE number = ?", (number,)).fetchone()
    if unit:
        unit_id = unit["id"]
        if title:
            conn.execute("UPDATE units SET title = ? WHERE id = ?", (title, unit_id))
    else:
        cur = conn.execute(
            "INSERT INTO units (number, title, created_by) VALUES (?, ?, ?)",
            (number, title, user["id"]),
        )
        unit_id = cur.lastrowid
        db.log_revision(conn, user["id"], "unit", unit_id, "create", f"Unit {number}: {title}")

    added = 0
    for e in entries:
        existing = conn.execute(
            "SELECT id FROM words WHERE unit_id = ? AND lower(word) = lower(?)",
            (unit_id, e["word"]),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO words (unit_id, word, translation, synonyms, collocations) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                unit_id,
                e["word"],
                e["translation"],
                json.dumps(e["synonyms"], ensure_ascii=False),
                json.dumps(e["collocations"], ensure_ascii=False),
            ),
        )
        added += 1
    return unit_id, added


@app.route("/teacher/upload", methods=["GET", "POST"])
@role_required("teacher", "admin")
def teacher_upload():
    user = current_user()
    if request.method == "POST":
        try:
            number = int(request.form.get("number", "").strip())
        except ValueError:
            flash("Номер юнита должен быть числом.", "error")
            return render_template("upload_unit.html")

        title = request.form.get("title", "").strip()
        pasted_text = request.form.get("text", "").strip()
        uploaded_file = request.files.get("docx_file")

        text = pasted_text
        if uploaded_file and uploaded_file.filename:
            try:
                text = extract_docx_text(uploaded_file.stream)
            except Exception:
                flash("Не удалось прочитать .docx файл.", "error")
                return render_template("upload_unit.html")

        entries = parse_vocab_text(text)
        if not entries:
            flash(
                "Слова не найдены. Проверьте формат: «1) Word - перевод», "
                "далее синонимы, затем строка «Collocations:».",
                "error",
            )
            return render_template("upload_unit.html")

        conn = db.get_db()
        unit_id, added = _import_words_into_unit(conn, user, number, title, entries)
        db.log_revision(
            conn, user["id"], "unit", unit_id, "upload_words",
            f"Добавлено слов: {added} (Unit {number})",
        )
        conn.commit()
        conn.close()
        flash(f"Готово: добавлено {added} новых слов в Unit {number}.", "success")
        return redirect(url_for("teacher_unit", unit_id=unit_id))

    return render_template("upload_unit.html")


@app.route("/teacher/upload/bulk", methods=["POST"])
@role_required("teacher", "admin")
def teacher_upload_bulk():
    user = current_user()
    files = [f for f in request.files.getlist("docx_files") if f and f.filename]

    if not files:
        flash("Файлы не выбраны.", "error")
        return redirect(url_for("teacher_upload"))

    conn = db.get_db()
    results = []

    for f in files:
        filename = f.filename

        try:
            text = extract_docx_text(f.stream)
        except Exception:
            results.append({"filename": filename, "ok": False, "error": "не удалось прочитать .docx файл"})
            continue

        number = guess_unit_number(filename, text[:200])
        if number is None:
            results.append({
                "filename": filename, "ok": False,
                "error": "не удалось определить номер юнита (нет «Unit N» в названии файла)",
            })
            continue

        entries = parse_vocab_text(text)
        if not entries:
            results.append({"filename": filename, "ok": False, "error": "слова не найдены в файле"})
            continue

        title = guess_unit_title(filename)
        unit_id, added = _import_words_into_unit(conn, user, number, title, entries)
        db.log_revision(
            conn, user["id"], "unit", unit_id, "upload_words",
            f"Добавлено слов: {added} (Unit {number}, файл {filename})",
        )
        conn.commit()
        results.append({"filename": filename, "ok": True, "number": number, "added": added})

    conn.close()

    ok_results = [r for r in results if r["ok"]]
    err_results = [r for r in results if not r["ok"]]
    if ok_results:
        total_added = sum(r["added"] for r in ok_results)
        flash(
            f"Обработано файлов: {len(ok_results)}. Всего добавлено слов: {total_added}.",
            "success",
        )
    if err_results:
        details = "; ".join(f"«{r['filename']}» — {r['error']}" for r in err_results)
        flash(f"Не удалось обработать {len(err_results)} файл(ов): {details}", "error")

    return render_template("upload_bulk_result.html", results=results)


@app.route("/teacher/unit/<int:unit_id>")
@role_required("teacher", "admin")
def teacher_unit(unit_id):
    conn = db.get_db()
    unit = conn.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
    if not unit:
        conn.close()
        abort(404)
    words = conn.execute(
        "SELECT * FROM words WHERE unit_id = ? ORDER BY word", (unit_id,)
    ).fetchall()
    conn.close()
    words = [dict(w, synonyms=json.loads(w["synonyms"]), collocations=json.loads(w["collocations"])) for w in words]
    return render_template("unit_words.html", unit=unit, words=words)


@app.route("/word/<int:word_id>/edit", methods=["GET", "POST"])
@role_required("teacher", "admin")
def word_edit(word_id):
    user = current_user()
    conn = db.get_db()
    word = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    if not word:
        conn.close()
        abort(404)

    if request.method == "POST":
        new_word = request.form.get("word", "").strip()
        translation = request.form.get("translation", "").strip()
        synonyms = [s.strip() for s in request.form.get("synonyms", "").split(",") if s.strip()]
        collocations = [c.strip() for c in request.form.get("collocations", "").split("\n") if c.strip()]

        conn.execute(
            "UPDATE words SET word=?, translation=?, synonyms=?, collocations=? WHERE id=?",
            (
                new_word,
                translation,
                json.dumps(synonyms, ensure_ascii=False),
                json.dumps(collocations, ensure_ascii=False),
                word_id,
            ),
        )
        db.log_revision(
            conn, user["id"], "word", word_id, "edit",
            f"'{word['word']}' -> '{new_word}' / '{translation}'",
        )
        conn.commit()
        unit_id = word["unit_id"]
        conn.close()
        flash("Слово обновлено.", "success")
        return redirect(url_for("teacher_unit", unit_id=unit_id))

    conn.close()
    word = dict(word, synonyms=json.loads(word["synonyms"]), collocations=json.loads(word["collocations"]))
    return render_template("word_edit.html", word=word)


@app.route("/word/<int:word_id>/delete", methods=["POST"])
@role_required("teacher", "admin")
def word_delete(word_id):
    user = current_user()
    conn = db.get_db()
    word = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    if not word:
        conn.close()
        abort(404)
    unit_id = word["unit_id"]
    conn.execute("DELETE FROM progress WHERE word_id = ?", (word_id,))
    conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
    db.log_revision(conn, user["id"], "word", word_id, "delete", word["word"])
    conn.commit()
    conn.close()
    flash("Слово удалено.", "success")
    return redirect(url_for("teacher_unit", unit_id=unit_id))


@app.route("/teacher/roster")
@role_required("teacher", "admin")
def teacher_roster():
    conn = db.get_db()
    students = conn.execute(
        "SELECT * FROM users WHERE role = 'student' ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template("roster.html", students=students)


@app.route("/teacher/roster/<int:student_id>")
@role_required("teacher", "admin")
def teacher_student_progress(student_id):
    conn = db.get_db()
    student = conn.execute("SELECT * FROM users WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)

    units = conn.execute("SELECT * FROM units ORDER BY number").fetchall()
    stats = []
    for u in units:
        words = conn.execute("SELECT id FROM words WHERE unit_id = ?", (u["id"],)).fetchall()
        word_ids = [w["id"] for w in words]
        total = len(word_ids)
        mastered = 0
        avg_box = 0
        if word_ids:
            placeholders = ",".join("?" * len(word_ids))
            mastered = conn.execute(
                f"SELECT COUNT(*) c FROM progress WHERE student_id=? AND box>=? AND word_id IN ({placeholders})",
                (student_id, LEARNED_BOX, *word_ids),
            ).fetchone()["c"]
            avg_row = conn.execute(
                f"SELECT AVG(box) a FROM progress WHERE student_id=? AND word_id IN ({placeholders})",
                (student_id, *word_ids),
            ).fetchone()
            avg_box = round(avg_row["a"] or 0, 1)
        stats.append({"unit": u, "total": total, "mastered": mastered, "avg_box": avg_box})

    conn.close()
    return render_template(
        "student_progress_teacher.html",
        student=student,
        stats=stats,
        master_box=MASTER_BOX,
    )


@app.route("/teacher/roster/<int:student_id>/unit/<int:unit_id>")
@role_required("teacher", "admin")
def teacher_student_unit_progress(student_id, unit_id):
    """Детальная разбивка по словам одного юнита для одного ученика —
    что видно, кликнув на юнит внутри прогресса ученика."""
    conn = db.get_db()
    student = conn.execute("SELECT * FROM users WHERE id = ?", (student_id,)).fetchone()
    unit = conn.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
    if not student or not unit:
        conn.close()
        abort(404)

    rows = conn.execute(
        """
        SELECT w.id, w.word, w.translation, w.synonyms, w.collocations,
               p.box, p.seen, p.correct
        FROM words w
        LEFT JOIN progress p ON p.word_id = w.id AND p.student_id = ?
        WHERE w.unit_id = ?
        ORDER BY
            CASE WHEN p.box IS NULL THEN -1 ELSE p.box END ASC,
            (COALESCE(p.seen, 0) - COALESCE(p.correct, 0)) DESC,
            w.word
        """,
        (student_id, unit_id),
    ).fetchall()
    conn.close()

    words = []
    for r in rows:
        seen = r["seen"] or 0
        correct = r["correct"] or 0
        words.append({
            "word": r["word"],
            "translation": r["translation"],
            "synonyms": json.loads(r["synonyms"] or "[]"),
            "collocations": json.loads(r["collocations"] or "[]"),
            "box": r["box"],
            "seen": seen,
            "correct": correct,
            "wrong": seen - correct,
            "learned": r["box"] is not None and r["box"] >= LEARNED_BOX,
            "attempted": seen > 0,
        })

    return render_template(
        "student_unit_progress_teacher.html",
        student=student,
        unit=unit,
        words=words,
        master_box=MASTER_BOX,
    )


# ---------- admin ----------

@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    conn = db.get_db()
    stats = {
        "users": conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "students": conn.execute("SELECT COUNT(*) c FROM users WHERE role='student'").fetchone()["c"],
        "teachers": conn.execute("SELECT COUNT(*) c FROM users WHERE role='teacher'").fetchone()["c"],
        "units": conn.execute("SELECT COUNT(*) c FROM units").fetchone()["c"],
        "words": conn.execute("SELECT COUNT(*) c FROM words").fetchone()["c"],
    }
    conn.close()
    return render_template("admin_dashboard.html", stats=stats)


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    conn = db.get_db()
    users = conn.execute("SELECT * FROM users ORDER BY role, name").fetchall()
    conn.close()
    return render_template("manage_users.html", users=users)


@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
@role_required("admin")
def admin_change_role(user_id):
    admin = current_user()
    new_role = request.form.get("role")
    if new_role not in ("student", "teacher", "admin"):
        abort(400)
    conn = db.get_db()
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    db.log_revision(conn, admin["id"], "user", user_id, "role_change", new_role)
    conn.commit()
    conn.close()
    flash("Роль обновлена.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def admin_delete_user(user_id):
    admin = current_user()
    if user_id == admin["id"]:
        flash("Нельзя удалить самого себя.", "error")
        return redirect(url_for("admin_users"))
    conn = db.get_db()
    conn.execute("DELETE FROM progress WHERE student_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.log_revision(conn, admin["id"], "user", user_id, "delete", "")
    conn.commit()
    conn.close()
    flash("Пользователь удалён.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/revisions")
@role_required("admin")
def admin_revisions():
    conn = db.get_db()
    rows = conn.execute(
        """
        SELECT revisions.*, users.name as editor_name
        FROM revisions LEFT JOIN users ON users.id = revisions.editor_id
        ORDER BY revisions.id DESC LIMIT 300
        """
    ).fetchall()
    conn.close()
    return render_template("revisions.html", rows=rows)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
