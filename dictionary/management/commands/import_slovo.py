"""Импорт клипов Slovo (landmarks) из staging-папки в словарь.

Читает ``manifest.json``, который создаёт ``scripts/slovo_to_clips.py``, и для
каждой глоссы создаёт или находит ``Sign`` и прикрепляет ``SignClip`` с
landmarks. При выборе клипа демонстрационные заглушки исключаются. Остальные
версии клипов по умолчанию сохраняются.

Примеры::

    # посмотреть план, ничего не записывая
    python manage.py import_slovo /import --dry-run

    # импорт всех клипов, новые жесты сразу проверены
    python manage.py import_slovo /import --lang rsl --status verified

    # явная замена предыдущих версий клипов
    python manage.py import_slovo /import --replace-clips

    # только несколько глосс
    python manage.py import_slovo /import --only КОШКА --only ДАКТИЛЬ_А
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from dictionary.models import (
    ClipFormat,
    DictionaryVersion,
    Language,
    Sign,
    SignClip,
    SignStatus,
)
from dictionary.services import _ascii_slug
from services.clips import ClipFormatError, default_storage, parse_clip


class Command(BaseCommand):
    help = "Импортировать клипы landmarks Slovo из staging-папки (manifest.json)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Папка staging с manifest.json и clips/.")
        parser.add_argument(
            "--lang",
            default=Language.RSL,
            choices=Language.values,
            help="Язык жестов (по умолчанию rsl).",
        )
        parser.add_argument(
            "--status",
            default=SignStatus.VERIFIED,
            choices=SignStatus.values,
            help="Статус новых жестов (по умолчанию verified).",
        )
        parser.add_argument(
            "--only",
            action="append",
            default=[],
            metavar="ГЛОССА",
            help="Импортировать только указанные глоссы (можно несколько).",
        )
        parser.add_argument(
            "--replace-clips",
            action="store_true",
            help="Удалить прежние клипы глоссы, чтобы клип Slovo стал лучшим.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать план, ничего не записывая.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Перезаписать клип, даже если такой файл уже импортирован.",
        )

    def handle(self, *args, **options):
        root = Path(options["path"])
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise CommandError(f"Нет manifest.json в {root}.")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"manifest.json не разбирается: {exc}") from exc

        clips = manifest.get("clips") if isinstance(manifest, dict) else None
        if not isinstance(clips, dict):
            raise CommandError("В manifest.json нет объекта clips.")

        wanted = {item.strip().upper() for item in options["only"] if item.strip()}
        lang = options["lang"]
        status = options["status"]
        dry_run = options["dry_run"]
        replace = options["replace_clips"]
        force = options["force"]

        planned = [
            (gloss.upper(), info)
            for gloss, info in clips.items()
            if isinstance(info, dict)
            and info.get("status") in {"ok", "skipped"}
            and (not wanted or gloss.upper() in wanted)
        ]
        if not planned:
            raise CommandError("Нечего импортировать: проверьте --only и manifest.")

        self.stdout.write(
            f"Клипов к импорту: {len(planned)}; язык: {lang}; статус новых: {status}."
        )

        created_signs = 0
        created_clips = 0
        replaced_clips = 0
        skipped = 0
        errors: list[str] = []
        verified_new = 0

        for gloss, info in planned:
            file_name = str(info.get("file") or "")
            file_path = root / "clips" / file_name
            if not file_name or not file_path.is_file():
                errors.append(f"{gloss}: нет файла {file_path}")
                continue
            blob = file_path.read_bytes()
            try:
                meta = parse_clip(blob)
            except ClipFormatError as exc:
                errors.append(f"{gloss}: {exc}")
                continue
            if meta.gloss and meta.gloss.upper() != gloss:
                errors.append(f"{gloss}: внутри клипа глосса {meta.gloss!r}, ожидалась {gloss!r}")
                continue

            signs = Sign.objects.filter(gloss=gloss, lang=lang)
            sign = signs.filter(status=SignStatus.VERIFIED).first() or signs.first()
            existing = None
            if sign is not None:
                # Тот же клип уже прикреплён к жесту? Сравниваем содержимое, чтобы
                # повторный импорт не плодил версии и DictionaryVersion.
                for candidate in sign.clips.filter(format=ClipFormat.LANDMARKS, frames=meta.frames):
                    try:
                        same = default_storage.read(candidate.file.name) == blob
                    except OSError:
                        same = False
                    if same:
                        existing = candidate
                        break
            if (
                existing is not None
                and not force
                and not (status == SignStatus.VERIFIED and sign.status != status)
            ):
                skipped += 1
                self.stdout.write(f"  = {gloss} уже импортирован")
                continue
            if dry_run:
                action = (
                    "замена" if sign is not None and sign.clips.exists() and replace else "клип"
                )
                self.stdout.write(f"  + {gloss} ({action}, {meta.frames} кадров)")
                continue

            try:
                with transaction.atomic():
                    if sign is None:
                        sign = Sign.objects.create(
                            gloss=gloss,
                            lang=lang,
                            status=status,
                            description="Импорт жеста Slovo",
                        )
                        created_signs += 1
                        if status == SignStatus.VERIFIED:
                            verified_new += 1
                    elif sign.status != status and status == SignStatus.VERIFIED:
                        sign.status = status
                        sign.save(update_fields=("status", "updated_at"))
                        verified_new += 1
                    if existing is not None and not force:
                        clip = existing
                    elif replace:
                        for clip in sign.clips.all():
                            self._delete_clip_file(clip)
                            clip.delete()
                            replaced_clips += 1
                    if existing is None or force:
                        clip = self._attach_clip(sign, blob, meta)
                        created_clips += 1
            except Exception as exc:  # noqa: BLE001 — один сбой не должен рвать импорт
                errors.append(f"{gloss}: {exc}")
                continue
            self.stdout.write(f"  + {gloss} → {clip.file.name} ({clip.frames} кадров)")

        if not dry_run and (verified_new or created_clips):
            DictionaryVersion.bump(lang)

        if errors:
            self.stdout.write(self.style.WARNING(f"Ошибок: {len(errors)}"))
            for line in errors[:20]:
                self.stdout.write(f"  ! {line}")
            if len(errors) > 20:
                self.stdout.write(f"  … ещё {len(errors) - 20}")

        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: ничего не сохранено."))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: новых жестов {created_signs}, клипов {created_clips}, "
                f"заменено {replaced_clips}, пропущено {skipped}."
            )
        )
        if errors:
            raise CommandError(f"Импорт завершён с ошибками ({len(errors)}).")

    def _delete_clip_file(self, clip: SignClip) -> None:
        """Удалить файл клипа, если на него больше не ссылаются другие клипы."""
        name = clip.file.name
        if not name:
            return
        others = SignClip.objects.filter(file=name).exclude(pk=clip.pk)
        if not others.exists():
            default_storage.delete(name)

    def _attach_clip(self, sign: Sign, blob: bytes, meta) -> SignClip:
        """Сохранить файл в media и создать запись ``SignClip``."""
        version = sign.clips.count() + 1
        slug = _ascii_slug(sign.gloss) or "sign"
        name = f"{sign.pk}-{slug}-v{version}.json.gz"
        stamp = timezone.now().strftime("%Y/%m")
        path = f"clips/{stamp}/{name}"
        default_storage.save(path, blob)
        return SignClip.objects.create(
            sign=sign,
            file=path,
            format=ClipFormat.LANDMARKS,
            fps=meta.fps,
            duration_ms=meta.duration_ms,
            frames=meta.frames,
            version=version,
            size_bytes=len(blob),
        )
