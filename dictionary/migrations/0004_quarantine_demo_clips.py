from pathlib import PurePosixPath

from django.db import migrations, models
from django.db.models import Exists, Max, OuterRef

from services.clips import ClipFormatError, default_storage, glb_json, is_demo_animation


def quarantine_demo_clips(apps, schema_editor):
    alias = schema_editor.connection.alias
    Sign = apps.get_model("dictionary", "Sign")
    Clip = apps.get_model("dictionary", "SignClip")
    Version = apps.get_model("dictionary", "DictionaryVersion")

    animations = Clip.objects.using(alias).filter(format="animation")
    paths = animations.order_by().values_list("file", flat=True).distinct()
    placeholders = []
    for path in paths:
        if not path:
            continue
        try:
            demo = is_demo_animation(glb_json(default_storage.read(path)))
        except FileNotFoundError:
            # Импорт исходного пакета именует файл по префиксу его SHA-256.
            demo = path.startswith("clips/import/") and PurePosixPath(path).stem.endswith(
                "-7733597b"
            )
        except ClipFormatError:
            continue
        if demo:
            placeholders.append(path)

    if not placeholders:
        return

    demos = animations.filter(file__in=placeholders)
    affected = Sign.objects.using(alias).filter(Exists(demos.filter(sign_id=OuterRef("pk"))))
    languages = set(affected.values_list("lang", flat=True))
    demos.update(is_placeholder=True)
    playable = Clip.objects.using(alias).filter(sign_id=OuterRef("pk"), is_placeholder=False)
    affected.filter(status="verified").exclude(Exists(playable)).update(
        status="draft",
    )
    for lang in languages:
        last = Version.objects.using(alias).filter(lang=lang).aggregate(number=Max("number"))
        Version.objects.using(alias).create(lang=lang, number=(last["number"] or 0) + 1)


class Migration(migrations.Migration):
    dependencies = [("dictionary", "0003_signclip_animation_name")]
    operations = [
        migrations.AddField(
            model_name="signclip",
            name="is_placeholder",
            field=models.BooleanField(
                "демонстрационная заглушка",
                default=False,
                editable=False,
            ),
        ),
        migrations.RunPython(quarantine_demo_clips, migrations.RunPython.noop),
    ]
