# Анимационные жесты: каркас (H1)

Как подключить жесты, сделанные **вручную анимацией** в Blender, вместо записи
с камеры. Это второй формат клипа рядом с landmarks MediaPipe. Каркас готов:
сервер принимает и хранит анимации, клиент умеет их грузить и проигрывать.
Когда 3D-модель и первые анимации будут готовы, останется пройти чек-лист в
конце документа.

> Контекст: ТЗ предполагает запись жестов с камеры (`/dictionary/record/`,
> landmarks + ретаргет Kalidokit). Ручная анимация — альтернативный путь
> производства, он не отменяет словарь и проверку экспертом.

## Два формата клипа

| | `landmarks` (по умолчанию) | `animation` (H1) |
| --- | --- | --- |
| Файл | `.json.gz` | `.vrma` или `.glb` |
| Что внутри | точки MediaPipe: поза 33, кисти 21+21, лицо 468 | готовые дорожки костей (glTF animation) |
| Как получают | запись с камеры, `/dictionary/record/` | Blender / Mixamo / VRoid → экспорт |
| Показ | `ClipPlayer` + Kalidokit + `vrm-rig` | `AnimationPlayer` + `THREE.AnimationMixer` |
| Модель | любая VRM с humanoid-скелетом | VRM, чьи кости совпадают с дорожками (или VRMA) |

Оба формата привязаны к глоссе через базу (`Sign.gloss` → `SignClip`), а не через
имена внутри модели. Поле `SignClip.format` (`ClipFormat`) задаёт формат.

Если у жеста есть и запись, и анимация, показ выбирает **анимацию**
(`pipeline/events.py: select_best_clip`, `Sign.best_clip`).

## Как подготовить анимации

1. Один жест — **один файл с одной анимацией**. Несколько жестов в одном `.glb`
   допустимы технически, но конвейер берёт первую анимацию.
2. Имя файла — транслит глоссы (как у landmarks): `uchebnik.glb`,
   `daktil_a.vrma`, `cifra_5.vrma`. Имя внутри модели ни на что не влияет.
3. Глоссы дактиля и чисел — по конвенции конвейера:
   `ДАКТИЛЬ_А` … `ДАКТИЛЬ_Я`, `ЦИФРА_0` … `ЦИФРА_9`.
4. Скелет модели — стандартный VRM humanoid. Код обращается к костям по именам
   `hips`, `spine`, `chest`, `neck`, `head`, `left/rightUpperArm`,
   `left/rightLowerArm`, `left/rightHand`, `left/rightUpperLeg`,
   `left/rightLowerLeg`, пальцы `*IndexProximal` и т. д. (см. `vrm-rig.ts`).
   Мимика — выражения `blinkLeft/Right`, `aa/ee/ih/oh/ou`.
5. Длительность: 0.5–2.5 с на жест, нейтральная поза в начале и конце.
6. Экспорт:
   - **GLB с анимацией** (проще всего): Blender → File → Export → glTF 2.0,
     формат `glTF Binary (.glb)`, включить Animation. Работает, если имена узлов
     совпадают с узлами VRM (обычно да, если анимируете тот же скелет).
   - **VRMA** (`@pixiv/three-vrm-animation` совместимый): привязан к humanoid-
     костям, переносится между моделями. Требует подключения пакета (см. ниже).

## Загрузка в словарь

Через API (роль `editor`/`expert`/`admin`), поле `animation`:

```bash
curl -X POST http://localhost/api/signs/ \
  -b cookies.txt \
  -H "X-CSRFToken: <token>" \
  -F "gloss=УЧЕБНИК" \
  -F "lang=rsl" \
  -F "description=Ручная анимация" \
  -F "animation=@uchebnik.vrma"
```

Ответ `201` содержит `clips[0].format = "animation"` и `url`, оканчивающийся на
`.vrma`/`.glb`. Файл проверяется (`services/clips.py: parse_animation`): сигнатура
`glTF`, версия 2, целостность длины, JSON-чанк, наличие хотя бы одной анимации,
лимит `CLIP_MAX_ANIMATION_BYTES` (20 МиБ по умолчанию). Дальше — обычный путь:
жест создаётся `draft`, эксперт проверяет и утверждает, версия словаря растёт.

Загружать `clip` (landmarks) и `animation` одновременно нельзя — ответ `400`.

## Что уже реализовано

| Слой | Файл | Что делает |
| --- | --- | --- |
| Модель | `dictionary/models.py` | `ClipFormat`, `SignClip.format`, `file_url()` с расширением, `best_clip` с приоритетом анимации |
| Валидация | `services/clips.py` | `parse_animation`, `glb_json`, `AnimationMeta`, лимит размера |
| Сервис | `dictionary/services.py` | `create_sign(animation=…, animation_name=…)`, `_attach_animation` |
| HTTP | `dictionary/api.py` | поле `animation` (multipart), `413` на превышение, `400` на оба файла |
| Отдача | `config/urls.py`, `dictionary/views.py` | `/media/clips/<id>.<ext>`, `model/gltf-binary`, ETag/304 |
| События | `pipeline/events.py` | `format` в ссылке на клип, приоритет анимации |
| Клиент | `frontend/animation-clip.ts` | разбор GLB, `loadAnimationBundle`, понятные ошибки |
| Клиент | `frontend/animation-player.ts` | очередь на `AnimationMixer`, crossfade, скорость |
| Клиент | `frontend/room-phrase.ts` | фраза целиком из анимаций играется новым плеером |
| Тесты | `tests/test_animation_clips.py`, `frontend/animation-*.test.ts` | 24 + 7 проверок |

## Что осталось (чек-лист, когда модель готова)

1. **VRMA.** Подключить пакет (это новая зависимость, версию фиксируем):
   ```bash
   npm install @pixiv/three-vrm-animation
   ```
   Затем в `frontend/animation-clip.ts`:
   - заменить заглушку `VrmaNotSupportedError` на регистрацию
     `VRMAnimationLoaderPlugin` в `GLTFLoader`;
   - для VRMA превращать `gltf.userData.vrmAnimations` в `AnimationClip` через
     `createVRMAnimationClip(vrmAnimation, vrm)` (для этого загрузчику нужен
     `vrm` — добавить параметр `vrm` в `loadAnimationBundle`);
   - в `room-phrase.ts` передать `this.avatar.model` в загрузчик.
2. **Смешанные фразы.** Сейчас фраза целиком из анимаций — новый плеер; если
   часть клипов анимации, а часть landmarks (например, дактиль с камеры) —
   играются только landmarks, в статусе предупреждение. Общий план:
   нормализовать оба источника в «поставщик кадров позы» и блендить на уровне
   костей, либо конвертировать анимации в landmarks офлайн (см. ниже).
3. **Проверка экспертом.** В карточке `/dictionary/review/<id>/` сейчас ссылка на
   файл клипа. Для анимаций полезно добавить проигрывание на `/avatar/`
   (переиспользовать `AnimationPlayer`).
4. **Дактиль.** Решить, чем делать 33 буквы и цифры: анимацией или записью с
   камеры. Конвейер поддерживает оба варианта без изменений.
5. **Кэш/версии.** Анимации участвуют в версии кэша PWA автоматически: она
   считается из `DictionaryVersion` и имён файлов сборки; клипы кэшируются
   service worker'ом по URL (`/media/clips/*`), расширение не важно.
6. **Прогон.** После подключения модели: `make check`, затем вручную — комната,
   фраза из анимаций, подсветка слов, скорость 0.6–1.3x, переподключение.

## Альтернатива: конвертировать анимации в landmarks

Если VRMA/AnimationMixer окажется неудобен для конкретных жестов, можно офлайн
«отрендерить» анимацию в landmark-клип: взять позы костей по кадрам, пересчитать
в точки MediaPipe (33 позы + 21+21 кисти), упаковать `.json.gz` (формат
`docs/spec/clip-format.md`) и загрузить как обычный `clip`. Мимика при этом
упрощается (лицо можно не передавать — `layout` гибкий). Рантайм менять не нужно.
