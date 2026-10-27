# Схема базы данных (Django ORM)

Источник: `TZ_django.md`, раздел(ы) 8. Копия для этапов генерации.


## 8. Схема базы данных (Django ORM)

| Модель | Поля |
| --- | --- |
| `User` | id, email, name, role (teacher/editor/expert/admin), password, created\_at |
| `Room` | id, title, owner (FK User), lang, status (open/closed), join\_code (6 символов, уникальный среди открытых комнат), demo\_mode (bool), created\_at, closed\_at |
| `Participant` | room, user (nullable) или guest\_name, session\_key, joined\_at, removed\_at |
| `Message` | id, room, participant, body, created\_at |
| `Utterance` | id, room, text, glosses (JSONField), asr\_ms, gloss\_ms, display\_lag\_ms, started\_at |
| `Sign` | id, gloss, lang, description, status (draft/review/verified/rejected), recorded\_by, verified\_by, verified\_at, comment |
| `SignClip` | id, sign (FK), file (FileField), fps, duration\_ms, frames, version, size\_bytes |
| `UnknownWord` | id, lemma, lang, count, last\_seen\_at, status (new/queued/recorded) |
| `DictionaryVersion` | id, lang, number, created\_at (версия растёт при утверждении жеста) |

Ограничения и индексы: `Sign(gloss, lang)` уникальный для проверенных (UniqueConstraint с условием), `Message(room, created_at)`, `UnknownWord(lang, -count)`. Опционально позже: расширение `pgvector` для поиска ближайшего жеста по смыслу.
