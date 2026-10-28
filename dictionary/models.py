"""Модели словаря жестов: жесты, клипы, версии словаря, очередь слов."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Language(models.TextChoices):
    """Язык жестов, к которому относится запись."""

    RSL = "rsl", "Русский жестовый"
    KSL = "ksl", "Казахский жестовый"


class SignStatus(models.TextChoices):
    """Жизненный цикл жеста: черновик → ревью → проверен/отклонён."""

    DRAFT = "draft", "Черновик"
    REVIEW = "review", "На ревью"
    VERIFIED = "verified", "Проверен"
    REJECTED = "rejected", "Отклонён"


class ClipFormat(models.TextChoices):
    """Формат клипа: landmarks MediaPipe или готовая анимация.

    ``landmarks`` — запись с камеры (``.json.gz``, ретаргет через Kalidokit),
    ``animation`` — анимация, сделанная вручную (``.vrma``/``.glb``,
    проигрывается через ``AnimationMixer``). Оба формата относятся к одной
    глоссе и различаются только способом показа (``docs/ANIMATIONS.md``).
    """

    LANDMARKS = "landmarks", "Landmarks (MediaPipe)"
    ANIMATION = "animation", "Анимация (VRMA/glTF)"


class Sign(models.Model):
    """Жест словаря: глосса, язык, статус и история проверки.

    Проверенным считается жест со статусом ``verified``. Именно такие жесты
    попадают в текущую версию словаря и в промпт для глосс.
    """

    gloss = models.CharField("глосса", max_length=100)
    lang = models.CharField(
        "язык",
        max_length=10,
        choices=Language.choices,
        default=Language.RSL,
    )
    description = models.TextField("описание", blank=True)
    status = models.CharField(
        "статус",
        max_length=10,
        choices=SignStatus.choices,
        default=SignStatus.DRAFT,
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_signs",
        verbose_name="записал",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_signs",
        verbose_name="проверил",
    )
    verified_at = models.DateTimeField("проверен", null=True, blank=True)
    comment = models.TextField("комментарий", blank=True)
    created_at = models.DateTimeField("создан", auto_now_add=True)
    updated_at = models.DateTimeField("обновлён", auto_now=True)

    class Meta:
        verbose_name = "жест"
        verbose_name_plural = "жесты"
        ordering = ("gloss", "lang")
        constraints = [
            models.UniqueConstraint(
                fields=("gloss", "lang"),
                condition=Q(status="verified"),
                name="unique_verified_sign_gloss_lang",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.gloss} [{self.lang}]"

    @property
    def is_verified(self) -> bool:
        return self.status == SignStatus.VERIFIED

    @property
    def best_clip(self):
        """Лучший клип жеста: анимация важнее landmarks, затем версия и кадры."""
        clips = list(self.clips.all())
        if not clips:
            return None
        return max(clips, key=lambda clip: (clip.is_animation, clip.version, clip.frames))

    def verify(self, expert, comment: str = "") -> None:
        """Низкоуровнево пометить жест проверенным и зафиксировать проверяющего.

        Это примитив модели (админка, служебные сценарии): он помечает жест
        ``verified`` без проверки перехода и растит версию словаря языка. Поток
        редактора и эксперта идёт через ``dictionary.services.transition_sign``,
        который проверяет допустимость перехода и роль.
        """
        self.status = SignStatus.VERIFIED
        self.verified_by = expert
        self.verified_at = timezone.now()
        if comment:
            self.comment = comment
        self.save(
            update_fields=("status", "verified_by", "verified_at", "comment", "updated_at")
        )
        DictionaryVersion.bump(self.lang)


class SignClip(models.Model):
    """Клип жеста: файл с landmarks и метаданными для воспроизведения.

    Формат файла описан в ``docs/spec/clip-format.md``: gzip JSON с
    Float16-данными по кадрам (``.json.gz``).
    """

    sign = models.ForeignKey(
        Sign,
        on_delete=models.CASCADE,
        related_name="clips",
        verbose_name="жест",
    )
    file = models.FileField("файл", upload_to="clips/%Y/%m/")
    format = models.CharField(
        "формат",
        max_length=12,
        choices=ClipFormat.choices,
        default=ClipFormat.LANDMARKS,
    )
    fps = models.PositiveSmallIntegerField("кадров в секунду", default=30)
    duration_ms = models.PositiveIntegerField("длительность, мс", default=0)
    frames = models.PositiveIntegerField("кадров", default=0)
    version = models.PositiveIntegerField("версия клипа", default=1)
    size_bytes = models.PositiveBigIntegerField("размер, байт", default=0)
    created_at = models.DateTimeField("создан", auto_now_add=True)

    class Meta:
        verbose_name = "клип жеста"
        verbose_name_plural = "клипы жестов"
        ordering = ("sign", "-version", "-frames")
        indexes = [
            models.Index(fields=("sign", "-version"), name="signclip_sign_version_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.sign.gloss} v{self.version}"

    @property
    def storage_path(self) -> str:
        """Относительный путь файла в хранилище клипов."""
        return self.file.name

    @property
    def is_animation(self) -> bool:
        """Клип — готовая анимация, а не landmarks MediaPipe (H1)."""
        return self.format == ClipFormat.ANIMATION

    @property
    def file_ext(self) -> str:
        """Расширение файла клипа без точки (``json.gz``, ``vrma``, ``glb``)."""
        name = self.file.name or ""
        if name.endswith(".tar.gz"):
            return "tar.gz"
        return name.rsplit(".", 1)[-1].lower() if "." in name else ""

    def file_url(self) -> str:
        """Публичный URL клипа (раздаёт веб-сервер).

        Landmarks отдаются по историческому пути ``/media/clips/<id>.json.gz``,
        анимации — с расширением файла, чтобы браузер и Caddy понимали тип.
        """
        from django.urls import reverse

        if self.is_animation and self.file_ext:
            return reverse("clip-file-animation", args=[self.pk, self.file_ext])
        return reverse("clip-file", args=[self.pk])


class UnknownWordStatus(models.TextChoices):
    """Очередь записи нераспознанных слов."""

    NEW = "new", "Новое"
    QUEUED = "queued", "В очереди"
    RECORDED = "recorded", "Записано"


class UnknownWord(models.Model):
    """Нераспознанное слово: сколько раз встретилось и что с ним сделали.

    Повторы агрегируются по ``(lemma, lang)``: ``count`` растёт, ``last_seen_at``
    обновляется. Отсортированы по убыванию частоты — сверху самое нужное слово.
    """

    lemma = models.CharField("лемма", max_length=100)
    lang = models.CharField(
        "язык",
        max_length=10,
        choices=Language.choices,
        default=Language.RSL,
    )
    count = models.PositiveIntegerField("повторов", default=1)
    last_seen_at = models.DateTimeField("последний раз", default=timezone.now)
    status = models.CharField(
        "статус",
        max_length=10,
        choices=UnknownWordStatus.choices,
        default=UnknownWordStatus.NEW,
    )
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        verbose_name = "нераспознанное слово"
        verbose_name_plural = "нераспознанные слова"
        ordering = ("-count", "lemma")
        constraints = [
            models.UniqueConstraint(
                fields=("lemma", "lang"),
                name="unique_unknown_word_lemma_lang",
            ),
        ]
        indexes = [
            models.Index(fields=("lang", "-count"), name="unknownword_lang_count_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.lemma} [{self.lang}] x{self.count}"


class DictionaryVersion(models.Model):
    """Версия словаря языка: номер растёт при утверждении жеста.

    Глоссы в промпте строятся только по текущей версии (наибольший ``number``).
    """

    lang = models.CharField(
        "язык",
        max_length=10,
        choices=Language.choices,
    )
    number = models.PositiveIntegerField("номер версии")
    created_at = models.DateTimeField("создана", auto_now_add=True)

    class Meta:
        verbose_name = "версия словаря"
        verbose_name_plural = "версии словаря"
        ordering = ("lang", "-number")
        constraints = [
            models.UniqueConstraint(
                fields=("lang", "number"),
                name="unique_dictionary_version_lang_number",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.lang} v{self.number}"

    @classmethod
    def current(cls, lang: str) -> "DictionaryVersion | None":
        """Текущая (последняя) версия словаря языка, если она есть."""
        return cls.objects.filter(lang=lang).order_by("-number").first()

    @classmethod
    def next_number(cls, lang: str) -> int:
        """Следующий номер версии для языка (1, если версий ещё нет)."""
        last = cls.objects.filter(lang=lang).aggregate(models.Max("number"))
        return (last["number__max"] or 0) + 1

    @classmethod
    def bump(cls, lang: str) -> "DictionaryVersion":
        """Создать новую версию словаря языка (номер на единицу больше)."""
        return cls.objects.create(lang=lang, number=cls.next_number(lang))
