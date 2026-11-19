"""Импорт одного GLB/VRMA с несколькими жестами (H1).

Файл сохраняется **один раз**, а на каждую запись внутри него создаётся
``SignClip`` с тем же путём и именем анимации. По умолчанию имя записи внутри
файла считается глоссой; ``--map`` позволяет задать соответствие явно.

Примеры::

    # имена анимаций = глоссы, файл с жестами из Blender
    python manage.py import_animations assets/animations/gestures.glb --lang rsl

    # явная карта и только две записи
    python manage.py import_animations assets/animations/gestures.glb \\
        --map "УЧЕБНИК=uchebnik" --map "ДАКТИЛЬ_А=daktil_a"

    # посмотреть, что будет сделано
    python manage.py import_animations assets/animations/gestures.glb --dry-run
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from dictionary.models import ClipFormat, Language, Sign, SignStatus
from dictionary.services import _ascii_slug, _attach_animation
from services.clips import ClipFormatError, default_storage, parse_animation


class Command(BaseCommand):
    help = "Импортировать жесты из одного GLB/VRMA (одна или несколько анимаций)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Путь к .glb/.vrma.")
        parser.add_argument(
            "--lang",
            default=Language.RSL,
            choices=Language.values,
            help="Язык жестов (по умолчанию rsl).",
        )
        parser.add_argument(
            "--status",
            default=SignStatus.DRAFT,
            choices=SignStatus.values,
            help="Статус новых жестов (по умолчанию draft).",
        )
        parser.add_argument(
            "--user",
            dest="email",
            default="",
            help="Email автора для поля «записал».",
        )
        parser.add_argument(
            "--map",
            action="append",
            default=[],
            metavar="ГЛОССА=АНИМАЦИЯ",
            help="Соответствие глоссы и имени анимации внутри файла (можно несколько).",
        )
        parser.add_argument(
            "--only",
            action="append",
            default=[],
            metavar="АНИМАЦИЯ",
            help="Импортировать только указанные записи (можно несколько).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать план, ничего не записывая.",
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"Файл не найден: {path}")

        blob = path.read_bytes()
        try:
            meta = parse_animation(blob, filename=path.name)
        except ClipFormatError as exc:
            raise CommandError(str(exc)) from exc

        author = self._resolve_user(options["email"])
        pairs = self._pairs(meta, options["map"], options["only"])
        self.stdout.write(
            f"Файл: {path.name}; записей: {meta.animations}; к импорту: {len(pairs)}."
        )

        stored_path = self._store(path, blob, save=not options["dry_run"])
        created_signs = 0
        created_clips = 0
        skipped = 0

        for gloss, animation in pairs:
            sign = Sign.objects.filter(gloss=gloss, lang=options["lang"]).first()
            if sign is not None and sign.clips.filter(
                format=ClipFormat.ANIMATION,
                animation_name=animation,
                file=stored_path,
            ).exists():
                skipped += 1
                self.stdout.write(f"  = {gloss} ← «{animation}» уже импортирован")
                continue
            if options["dry_run"]:
                self.stdout.write(f"  + {gloss} ← «{animation}» ({stored_path})")
                continue
            if sign is None:
                sign = Sign.objects.create(
                    gloss=gloss,
                    lang=options["lang"],
                    status=options["status"],
                    recorded_by=author,
                    description=f"Импорт анимации из {path.name}",
                )
                created_signs += 1
            _attach_animation(sign, blob, meta, clip_name=animation, path=stored_path)
            created_clips += 1
            self.stdout.write(f"  + {gloss} ← «{animation}»")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: ничего не сохранено."))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: новых жестов {created_signs}, клипов {created_clips}, "
                f"пропущено {skipped}. Файл: {stored_path}"
            )
        )

    def _resolve_user(self, email: str):
        if not email:
            return None
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"Пользователь с email {email} не найден.")
        return user

    def _pairs(self, meta, mapping: list[str], only: list[str]) -> list[tuple[str, str]]:
        """Пары «глосса, имя анимации» с проверкой имён и глосс."""
        available = list(meta.names)
        wanted = {name for name in only if name}
        pairs: list[tuple[str, str]] = []

        if mapping:
            for item in mapping:
                if "=" not in item:
                    raise CommandError(
                        f"Ожидается ГЛОССА=АНИМАЦИЯ, получено: {item!r}."
                    )
                gloss, animation = (part.strip() for part in item.split("=", 1))
                if not gloss:
                    raise CommandError(f"Пустая глосса в --map {item!r}.")
                # Пустое имя анимации — безымянная (первая) запись файла:
                # Blender-экспорт без имени дорожки. Глоссу всё равно задаём явно.
                if animation:
                    if animation not in available:
                        raise CommandError(
                            f"В файле нет анимации {animation!r}. "
                            f"Доступны: {', '.join(name or '(без имени)' for name in available)}."
                        )
                    if wanted and animation not in wanted:
                        continue
                elif "" not in available:
                    raise CommandError(
                        "В файле нет безымянной анимации: укажите имя в --map."
                    )
                pairs.append((gloss, animation))
        else:
            for animation in available:
                if wanted and animation not in wanted:
                    continue
                if not animation:
                    raise CommandError(
                        "В файле есть безымянная анимация: задайте имя через --map "
                        '"ГЛОССА=АНИМАЦИЯ" (безымянную выбрать нельзя).'
                    )
                pairs.append((animation, animation))

        if not pairs:
            raise CommandError("Нечего импортировать: проверьте --only/--map.")

        seen: set[str] = set()
        for gloss, animation in pairs:
            if len(gloss) > 100:
                raise CommandError(f"Глосса длиннее 100 символов: {gloss!r}.")
            if len(animation) > 120:
                raise CommandError(f"Имя анимации длиннее 120 символов: {animation!r}.")
            if gloss in seen:
                raise CommandError(f"Глосса указана дважды: {gloss!r}.")
            seen.add(gloss)
        return pairs

    def _store(self, path: Path, blob: bytes, *, save: bool = True) -> str:
        """Путь в хранилище: один файл на все жесты, по хешу содержимого."""
        digest = hashlib.sha256(blob).hexdigest()[:8]
        slug = _ascii_slug(path.stem) or "gestures"
        relative = f"clips/import/{slug}-{digest}.{path.suffix.lstrip('.')}"
        if save and not default_storage.exists(relative):
            default_storage.save(relative, blob)
        return relative
