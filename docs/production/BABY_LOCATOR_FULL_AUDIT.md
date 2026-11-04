# Baby Locator — технический аудит перед исправлением production

> Обновление 03.11.2026: этот документ сохраняет исходный аудит/чеклист до исправлений. Текущий статус — [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md), актуальные шаги и ключи — [PRODUCTION_START_HERE_RU.md](PRODUCTION_START_HERE_RU.md). Lite отложен по указанию владельца.

Дата: 3 ноября 2026, Asia/Bishkek. Это аудит и план изменений, а не отчёт о завершённых исправлениях. Исходный код, платёжные продукты и production-сервер не изменялись; финансовые операции не выполнялись.

## Часть 1 — Executive Summary

**Вердикт: новый релиз пока не готов.** Найдены воспроизводимые нарушения авторизации и расчёта Premium, архитектурные причины нестабильного аудио и пробелы проверки релиза. Успешные существующие unit-тесты не подтверждают работоспособность покупок или микрофона на реальных телефонах.

Главные результаты:

1. Любой обладатель обычного DRF-токена может получить полный Lite-доступ, указав `X-App-Edition: lite`. Подпись выданного токена не делает безопасным сам процесс выдачи.
2. Сервер доверяет `is_premium`, не проверяя `premium_expires_at`. Позднее старое событие RevenueCat может отменить более новое продление. Серверной повторной синхронизации с RevenueCat нет.
3. Flutter использует настоящие `configure`, `getOfferings`, `purchase(PurchaseParams.package(...))`, `restorePurchases` и entitlement. Но экран показывает фиксированные долларовые цены, а успешная покупка на клиенте не означает готовность Premium API на backend.
4. «Звук вокруг» в основном UI использует WebRTC. Фоновый запуск микрофона не удовлетворяет ограничениям Android 14+; ошибки foreground service скрываются. Нужен пользовательский запуск/подтверждение на детском устройстве и видимое управление сессией.
5. Чужой Premium-родитель может отправить stop-команду ребёнку другой семьи. Ребёнок может удалить безопасную зону своего родителя. Оба случая воспроизведены локально.
6. FCM fallback теряет команды после выдачи без ACK. WebRTC polling допускает параллельные запросы и теряет сообщение при ошибке обработки. HTTP audio broker находится в памяти одного процесса и несовместим с рекомендованными тремя Gunicorn workers.
7. Проверка миграций не проходит. В локальном `.env` записан `IS_TEST=True`, но установленный venv не содержит python-dotenv и его автоматическая загрузка сейчас пропускается. Production GET `/api/auth/test-mode/` вернул `false`. Локальный `.env`, effective settings и production нужно различать.
8. Полный checkout Lite содержит устаревший bundled backend, tracked SQLite с 2 tokens/геопозициями/сообщениями и media. Lite analyzer/widget test не прошли; его FGS/Accessibility конфигурации расходятся с актуальным платным проектом и общей policy.

Точную единственную причину отказа оплаты в Google Play установить без Console, RevenueCat events и лога неуспешной покупки нельзя. Нельзя объявить Android SDK key неправильным только по его наличию в коде: `goog_` — публичный SDK key, а принадлежность проекту проверяется в Dashboard.

### Область и происхождение исходников

| Проект | Зафиксированный HEAD | Архитектура / назначение |
|---|---|---|
| `Baby-locator` | `4c7af2f61869d589bccce439bc3748e29d1af524` | Flutter, Riverpod, HTTP DRF, SharedPreferences, Google/Apple Maps, Geolocator, Firebase Messaging, WebRTC, RevenueCat, собственный Kotlin bridge, background service |
| `Baby-locator-backend` | `5bccf3765749bcae846fe3b272b3f7bb6484d576` | Django 5.0.6 / DRF 3.15.2, приложения accounts/tracking/subscriptions/chat, token auth, PostgreSQL по умолчанию, WSGI, Firebase Admin |
| `Baby-locator-web` | `7b1f53608a99f2bae3f17d882f54640af54e8b25` | Статический HTML/CSS/JS: лендинг, Privacy Policy, удаление аккаунта; отдельной серверной логики сайта нет |
| `Baby-locator-lite` | `985a6eb440d7932ce13f4d850d2427d9a775d2d8` | Flutter fork; RevenueCat SDK удалён, UI считает всех Premium; получает signed Lite token у того же backend. Также содержит устаревшую вложенную копию Django backend |

HEAD трёх локальных репозиториев сопоставлены с GitHub HEAD через подключённый GitHub. До начала работы уже были изменения `Baby-locator/pubspec.yaml` и backend `.DS_Store`; они сохранены. Анализ относится к рабочим файлам, а не к гарантированно воспроизводимой чистой сборке HEAD. `pubspec.yaml`: `1.0.7+23`; Lite: `1.0.1+4`.

Lite первоначально отсутствовал локально: через GitHub прочитано дерево и 41 ключевой исходный файл (`audit_evidence/lite/`). Затем получен полный checkout в `Baby-locator-lite/` с тем же HEAD; проверены дополнительные Android resources, вложенный backend и выполнены pub get/analyze/test. Полная Android release-сборка Lite не выполнялась. Flutter автоматически изменил analysis_options/lock/generated registrant; эти изменения записаны в evidence diff и восстановлены, checkout оставлен чистым. Полная построчная проверка каждого файла всех четырёх проектов и динамическая проверка каждого endpoint в этот аудит не входят.

Обязательные production-сервисы: HTTPS API + БД + защищённое хранилище файлов, Google Play Billing/RevenueCat для платной версии, Firebase FCM для push, TURN для надёжного WebRTC через ограничивающие NAT, Google Maps Android API для карты Android. Для текущего REST signaling Redis/WebSocket не обязателен. HTTP audio при нескольких workers потребует общего брокера или отдельного streaming-сервиса. Для новой reconciliation-задачи понадобится планировщик/очередь; в текущем коде такой службы не найдено.

### Какая сборка опубликована

Локально доступны AAB 22 и 23 в `Google-Play-1.0.7-22-23/`. Повторно рассчитаны SHA-256:

| Файл | SHA-256 |
|---|---|
| `baby-locator-1.0.7-v22.aab` | `3ac4f097474d0f9fd2cf16ab61e0158f1bbaf992472f59b56b319fccacf2bb9d` |
| `baby-locator-1.0.7-v23.aab` | `e4b19e25c3c2f27b4a786ba513d3394395c1609d8cd32976c14d2a03e8d7b87b` |

Существующие XML/JSON в `verification/` описывают package `com.company.familysecurity`, minSdk 24, targetSdk 36, versionName 1.0.7, codes 22/23, `isMonitoringTool=child_monitoring`, Billing 8.3.0. Старые build logs не считаются новым запуском сборки. Результат повторной проверки AAB записывается отдельно в `audit_evidence/aab-verification.log`.

**Нет доказательства, что эти AAB находятся в production, и нет привязки AAB к полному Git SHA + build inputs.** Предыдущая инструкция от 7 октября описывает старый AAB 2 в тестовых треках; текущее состояние Console не прочитано. Требуется экспорт release details всех активных треков, versionCode, upload time, сертификаты App Signing/Upload и CI build provenance. Переименование AAB не меняет versionCode. Upload certificate не равен автоматически Play App Signing certificate.

## Часть 2 — Подтверждённые ошибки

Обозначения: B = `Baby-locator-backend/`, M = `Baby-locator/`, L = snapshot `audit_evidence/lite/`, W = `Baby-locator-web/`. Номера строк относятся к проверенным файлам. P0 — прямой массовый обход платных прав; P1 — блокер безопасности/ключевой функции; P2 — важная корректность/эксплуатация. «Подтверждён кодом» не означает «эксплуатировался в production».

### F01. P0 — выдача Lite-прав без доказательства лицензии

- Репозиторий/файлы: B `subscriptions/views.py:39–68`, `accounts/authentication.py:12–59`, `subscriptions/services.py:31–55`.
- Доказательство: локальный запрос обычного пользователя с одним заголовком получает 200 и Lite-токен; Premium location API затем даёт 404 «нет геопозиции», вместо прежнего Premium 403. `backend-reproductions.log`.
- Причина: заголовок — единственное основание выдачи. HMAC защищает от подделки уже выданного токена, но любой пользователь может законно получить его у сервера. Токен переносим между клиентами, нет expiry/scope/install binding.
- Последствие: платный клиент или произвольный HTTP-клиент получает полный доступ; `is_premium` в БД при этом остаётся false.
- Исправление: серверные grants по аккаунту/семье и продуктовой политике, ограниченные scopes, срок, revoke; если edition действительно лицензионная — серверная проверка Play Integrity, package/certificate/app recognition, nonce/request binding и replay protection. Integrity не заменяет проверку покупки и не доказывает право на Premium. Для бесплатного Lite явно определить допустимые бесплатные API.
- Проверка: подмена заголовка обычным пользователем не выдаёт платные scopes; перенос/повтор attestation отвергается; реальные Lite-сценарии сохраняют разрешённый набор функций. Существующий тест `test_lite_non_premium_gets_full_access_without_db_premium_change` закрепляет уязвимое поведение и должен быть заменён.

### F02. P1 — stop-команда чужому ребёнку

- B `tracking/views.py:1394–1428`: `DeactivateMonitoringView` проверяет Premium родителя, но не его связь с `child_id` при создании команды.
- Воспроизведено: другой Premium-родитель получает 200; в БД появляется `webrtc_monitor_stop` для чужого ребёнка. Это подтверждает несанкционированную команду; фактическое прерывание конкретной активной сессии зависит от клиентской обработки.
- Исправление: child/session получать через ownership filter; несогласованный child/token отклонять; команду создавать только из проверенной сессии.
- Проверка: чужая семья получает 403/404, никаких команд/FCM; своя сессия останавливается.

### F03. P1 — ребёнок может изменять родительские safe zones

- B `tracking/views.py:141–156`: ModelViewSet даёт ребёнку queryset зон родителя и только `IsAuthenticated`, без запрета PATCH/DELETE.
- Воспроизведено: DELETE ребёнком возвращает 204, зона удалена.
- Исправление: read-only для ребёнка, создание/изменение только родителю; `perform_create` также должен требовать роль parent.
- Проверка: child GET разрешён по продуктовому контракту, child POST/PATCH/DELETE 403; чужие семьи изолированы.

### F04. P1 — Premium не истекает без webhook

- B `subscriptions/services.py:31–55`; поля B `accounts/models.py:41–46`.
- Воспроизведено: `is_premium=True`, expiry вчера → `has_premium_access=True`.
- Причина: gate и лимит детей читают только boolean. Нет scheduled expiration/reconciliation.
- Исправление: единый расчёт entitlement/grant с UTC expiry, отдельным lifetime и grace policy; периодическая сверка с RevenueCat.
- Проверка: mock времени после expiry закрывает платный API даже без нового webhook; валидный lifetime остаётся активным.

### F05. P1 — устаревшие события и конкурирующие webhook

- B `subscriptions/services.py:80–114,119–137`.
- Воспроизведено: новая RENEWAL, затем старая EXPIRATION → Premium false. `premium_updated_at` записывается, но не сравнивается.
- Идемпотентность частичная: `event_id unique` и последовательный duplicate работают; `select_for_update().filter(...).exists()` не блокирует отсутствующую строку и не блокирует User. Два одновременных одинаковых insert могут дать IntegrityError/500; разные события могут перезаписать одного User.
- Исправление: unique insert с обработкой конфликта, блокировка владельца подписки, монотонное применение состояния, статус processing/processed/retry; предпочтительно событие как сигнал к authoritative subscriber sync.
- Проверка: перестановка/повтор/параллельные события дают одинаковый конечный статус; concurrency проверять на PostgreSQL, не SQLite.

### F06. P1 — неполная модель жизненного цикла подписки

- B `subscriptions/services.py:66–116,141–168,184–229`.
- `environment` сохраняется, но не фильтруется; `app_id` не проверяется. Lifetime product всегда возвращает true, включая refund/cancellation event. Transfer-specific `transferred_from/transferred_to` не обрабатываются: resolver ищет только app_user_id/original/aliases. Unknown-user событие сохраняется и получает 200, повтор того же id уже duplicate.
- Последствия: смешение sandbox/production, неотозванный lifetime, несинхронные владельцы после transfer/restore, навсегда пропущенное событие.
- Исправление: явные store/app/environment rules; subscriber sync всех затронутых transfer users; revocation отдельно от обычной отмены renewal; retry unknown users с диагностикой. Отмена автопродления при ещё действующем сроке не должна немедленно отключать доступ.
- Проверка: INITIAL_PURCHASE/RENEWAL/CANCELLATION/UNCANCELLATION/EXPIRATION/BILLING_ISSUE/TRANSFER/refund/lifetime, multi-product и sandbox isolation.

### F07. P1 — покупка успешна, backend ещё возвращает 403

- M `lib/core/subscriptions/subscription_service.dart:450–500,598–610`, `lib/features/subscription/premium_paywall_screen.dart:95–118`; B `subscriptions/urls.py:5–9`, `services.py:31–39`.
- Клиент обновляет только CustomerInfo. Backend получает права только через webhook; endpoint безопасной reconciliation отсутствует. Paywall закрывается немедленно по клиентскому entitlement.
- Причина/последствие: задержка, ошибка авторизации, потеря webhook или wrong user mapping оставляют покупателя без серверных функций. Повтор `getCustomerInfo` не исправляет БД Django.
- Исправление: authenticated `/subscriptions/sync/`, сервер сам запрашивает RevenueCat по привязанному user id; клиентское поле premium не принимать. После оплаты/restore ждать согласованного состояния с ограниченным retry и понятным pending UI.
- Проверка: задержанный/потерянный webhook, restore, новый телефон; sync идемпотентен, forged client payload не даёт Premium.

### F08. P1 — фиксированные цены и экономия на paywall

- M `lib/core/subscriptions/subscription_catalog.dart:1–4`, `lib/features/subscription/premium_paywall_screen.dart:672–688`.
- Monthly/annual намеренно показывают `$5.99/$29.99/$2.50`, минуя `StoreProduct.priceString`; savings = 58 константой.
- Последствия: несоответствие валюте/стране/base plan/offer пользователя и итоговому Play checkout.
- Исправление: локализованные store prices/period, вычисление эквивалента и скидки из фактических продуктов, явные условия trial/intro/base plan. При пустых Offerings не подставлять продаваемые фиктивные тарифы.
- Проверка: минимум две валюты, год/месяц, eligibility/no offer, смена цены без нового AAB; экран совпадает с Play purchase sheet.

### F09. P1 — архитектура фонового запуска микрофона

- M `lib/core/services/child_webrtc_service.dart:77–118`; `background_command_service.dart:870–898`; Kotlin `packages/kid_security_android_bridge/android/src/main/kotlin/com/example/kid_security/bridge/MicrophoneForegroundService.kt:29–51`.
- Запрос разрешения заранее и отдельный microphone FGS присутствуют. Но команда запускает новый microphone service из фона; Dart глотает исключения, native `startForeground` ловит любой Throwable без остановки/передачи ошибки. Location FGS не даёт while-in-use microphone capability.
- На Android 12+ действуют ограничения фонового FGS, на 14+ проверка while-in-use может сразу дать SecurityException. High-priority FCM не является общим разрешением на фоновый микрофон. [Android restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).
- Исправление: запрос родителя → видимое уведомление ребёнку → открытие Activity и согласие → запуск microphone FGS при видимой Activity → getUserMedia. Активная сессия может продолжиться при сворачивании в пределах платформенных правил. Stop action и предельная длительность обязательны для устойчивости и контроля пользователя.
- Проверка: Android 12–16, отказ/one-time permission/revocation/privacy toggle/занятый микрофон, фон/lock/force-stop; исключения видны в диагностике, нет скрытой записи.

### F10. P1 — ложное подтверждение обработки WebRTC-команды

- M `background_command_service.dart:870–898,485–497`, `child_live_audio_service.dart:34–43`.
- `_startWebrtcSession` ловит ошибку `startMonitoring`, затем всё равно посылает `handled_by_background:true`; main isolate игнорирует такой запрос, внешний обработчик может отправить `success:true`.
- Исправление: явный результат startup/awaiting-consent/failed; success только после требуемого этапа, fallback UI запускать после проверки актуальности сессии и согласия.
- Проверка: искусственная ошибка getUserMedia/FGS → failed или awaiting-consent, не completed; родитель видит точную причину.

### F11. P1 — гонки и потеря signaling

- M `parent_webrtc_service.dart:419–422,457–514`, `child_webrtc_service.dart:223–227,358–400,405–416`.
- Timer.periodic не ждёт async poll. При RTT больше 150/200 ms запросы накладываются. Cursor `_lastSignalId` продвигается до успешного `_handleSignal`. ICE отправляется отдельными HTTP-запросами и может попасть раньше SDP; очереди до remoteDescription нет. Send errors только логируются.
- Последствия: повтор SDP, invalid signaling state, потерянный offer/answer/ICE; это подтверждённый риск порядка исполнения, не запись конкретного production network trace.
- Исправление: один poll/обработчик на сессию; cursor после подтверждённой обработки; очередь ICE до remoteDescription; последовательный outbound SDP/ICE с retry/idempotency, generation id, cancellation при stop.
- Проверка: network fault injection с задержками/перестановкой/дубликатами, stop во время HTTP, повторный start, ICE restart и Wi-Fi↔LTE.

### F12. P1 — remote commands теряются до исполнения

- B `tracking/views.py:1079–1097`: GET pending меняет статус на delivered; следующие GET выбирают только pending.
- Воспроизведено: первый poll = 1 команда; второй без complete ACK = 0. Если ответ потерян или процесс погиб, fallback не доставит её вновь.
- Исправление: lease/ack deadline, retry delivered после истечения lease, TTL и idempotency ключи; старый start не должен выполняться после stop.
- Проверка: потеря HTTP-ответа, падение до ACK, повторная доставка, offline несколько часов, перестановка start/stop.

### F13. P1 — завершение сессии зависит от Premium; нет lease сессии

- B `tracking/views.py:1394–1398,1030–1042`, `tracking/models.py:MonitorSession`; M `parent_webrtc_service.dart:335–385,595–602`.
- Stop защищён тем же Premium, что start. Если права отозваны во время записи, родитель получает 403 при остановке. MonitorSession не имеет expires_at/heartbeat lease; потеря родителя не гарантирует закрытие. После появления remote stream родитель отменяет watchdog до проверки фактических RTP-пакетов (`176–216`).
- Исправление: stop всегда разрешён владельцу/ребёнку независимо от оплаты; локальный hard timeout, server lease и heartbeat, termination при недоступности control plane, RTP stats отдельно от onTrack.
- Проверка: отзыв Premium, kill родителя, потеря API, idle RTP при существующем track; микрофон останавливается за заданный предел.

### F14. P1 — восстановленная сессия не запускает жизненный цикл сервисов

- M `lib/main.dart:31–45,62–84,91–101`, `lib/app.dart:64–94,117–126`.
- Session bootstrap завершается до runApp. Listener в build не fireImmediately: уже восстановленный user не вызывает `_syncNotificationSession`. Инициализация Firebase/FCM/background асинхронна; ошибка Firebase пропускает последующие startup-сервисы в общем try. `_syncNotificationSession` сначала await registerToken, затем audio/background.
- Последствие: холодный запуск с токеном и свежий login проходят разные пути; сервисы могут остаться незапущенными или соревноваться с Firebase init.
- Исправление: единый идемпотентный coordinator после регистрации зависимостей, immediate sync текущего user, независимые failure domains, serialized account switch, cleanup listeners.
- Проверка: cold start с child/parent token, logout/login, Firebase init failure, медленная сеть — сервисы приходят в ожидаемое состояние.

### F15. P1 — offline startup уничтожает авторизацию

- M `lib/core/providers/session_providers.dart:105–123` (аналогичный путь Lite).
- Любая ошибка `/me`, включая timeout/offline/5xx, вызывает logout и удаление токена.
- Исправление: отзывать локальную сессию только при подтверждённом 401/revocation; сетевую недоступность представлять отдельно, хранить минимальный cached profile безопасно, retry.
- Проверка: airplane mode на старте не разлогинивает; неверный токен даёт контролируемый выход.

### F16. P1 — HTTP audio broker не общий для Gunicorn workers

- B `tracking/live_audio.py:53–64` и последний `live_audio_broker = LiveAudioBroker()`; `DEPLOY_NGINX.md` рекомендует `--workers 3`.
- Upload и download в разных процессах получают разные `_sessions`, поток родителя выдаёт silence. Nginx buffering не устраняет разделённую память.
- Исправление: сохранить endpoint совместимость, но перевести broker на общий streaming transport/отдельный сервис; основным оставить WebRTC. Один worker с достаточными threads — только временный диагностический режим, не гарантия масштабируемости. Не сохранять оба транспорта как автоматическое средство обхода mic restrictions.
- Проверка: параллельные upload/download через разные workers и рестарт процесса; счётчики реальных audio bytes, bounded buffers/TTL.

### F17. P2 — незаписанная миграция AppIcon

- B `tracking/migrations/0014_appicon.py:16`, `tracking/models.py:190–204`, `config/settings.py:136`.
- `makemigrations --check --dry-run` exit 1: требуется `0017_alter_appicon_id.py`, AutoField → BigAutoField. В этом аудите миграция не создавалась.
- Исправление: сознательно сохранить AutoField либо подготовить миграцию с проверкой PostgreSQL schema/locking/backup. Нельзя автоматически менять production schema по одному dry-run.
- Проверка: dry-run exit 0 и migrate на копии PostgreSQL с существующими данными.

### F18. P1 — повторное использование кода подключения и слабая защита auth

- B `accounts/views.py:328–383`, `accounts/models.py:75–81`, `accounts/serializers.py:79–81`; `config/settings.py` REST_FRAMEWORK без throttles/password validators.
- Код 6 цифр генерируется `random`, handler проверяет expiry, но не `used_by`; выданный child token повторно возвращается по тому же коду. Воспроизведено два 200 с одним token. Min password = 4. Не доказано отсутствие rate limit на внешнем proxy: его конфигурация недоступна.
- Исправление: secrets, одноразовая атомарная привязка, подтверждённый re-pair с rotation token, лимиты попыток по account/IP/invite, audit и блокировка перебора, нормальная password policy. Ветка создания ребёнка через parent-level code также должна проверять лимит детей.
- Проверка: повтор/гонка кода отклонены, re-pair отзывает старое устройство, rate limits проверены без перебора production.

### F19. P1 — небезопасные defaults и test endpoint

- B `config/settings.py:27–29,37,84–92`, `subscriptions/services.py:58–63`, `accounts/views.py:480–518`.
- Без ENV: DEBUG true, известные dev secret/DB password, allowed hosts wildcard. Пустой webhook auth допускается при DEBUG. `IS_TEST=True` открывает анонимную выдачу токена общего Premium-аккаунта. Локальный `.env` содержит IS_TEST true; production read-only GET вернул false — production-уязвимость этого endpoint не утверждается.
- Исправление: fail closed production settings, обязательные ENV; test route отключать структурно в prod и изолировать тестовую БД/аккаунты. Не переносить локальную .env на сервер.
- Проверка: запуск без обязательных production параметров завершается ошибкой; без webhook auth 401; test login в prod всегда 403/404.

### F20. P1 — неполное удаление файлов и платёжных персональных данных

- B `accounts/views.py:106–145,208–213`, `chat/models.py:25`, `subscriptions/models.py:17–28`; W `delete-account.html:115`, `privacy-policy.html:299–302`.
- MeView удаляет avatars/audio clips вручную, но не chat FileField. ChildDetail DELETE делает только child.delete(). Django cascade удаляет строки, а не файлы FileField. Webhook event FK SET_NULL сохраняет raw_payload с идентификаторами клиента. Обещание полного удаления всех персональных данных этим кодом не обеспечивается.
- Исправление: централизованная deletion job/transactional outbox, cleanup storage и raw payload согласно определённому retention, обработка RC customer deletion и законно сохраняемых billing records, доказуемый backup retention. Публиковать только исполнимую политику.
- Проверка: account/child delete удаляет DB rows и storage objects; residual webhook payload анонимизирован или обоснован retention; восстановление backup не возвращает удалённые данные.

### F21. P1 — XSS на invite landing

- B `accounts/views.py:387–433`: display_name/username/child_name вставляются напрямую в HTML f-string без escaping.
- Причина: пользовательские имена становятся разметкой. Это статически подтверждённая injection sink; эксплуатация в чужом браузере не выполнялась.
- Исправление: Django template с autoescape или `format_html`; CSP как дополнительная защита.
- Проверка: имя `<img ...>` отображается текстом, HTML entities экранированы; нет исполнения JS.

### F22. P1 — Lite manifest и идентичность приложения

- L `android/app/src/main/AndroidManifest.xml:1–91` не содержит isMonitoringTool; bridge manifest также не содержит его. Это дефект проверенных исходников; итоговый Lite AAB не получен.
- L `android/app/build.gradle.kts:39–45` default applicationId тот же `com.company.familysecurity`, что у платного. Без override Lite не может быть отдельным Play-приложением и установится как вариант того же package при подходящей подписи; фактический release override неизвестен.
- Исправление: отдельная подтверждённая identity/package для отдельного продукта, соответствующие Firebase/Maps/Integrity настройки; monitoring declaration во всех распространяемых вариантах.
- Проверка: финальный Lite AAB и все активные track version codes; side-by-side install при отдельных package.

### F23. P2 — FCM не имеет полноценной диагностики доставки/токенов

- B `tracking/fcm.py:19–38,67–100,175–178`; M `fcm_service.dart:283–307`; B `accounts/models.py:40`, `accounts/views.py:235–251`.
- Любая send ошибка только логируется; Unregistered token не очищается; один token на User означает последнее устройство вместо нескольких. Каждый registerToken добавляет новый onTokenRefresh listener без сохранения/cancel.
- Исправление: DeviceInstallation модель, timestamp/revoke, классификация Firebase ошибок, delivery/ACK telemetry, один lifecycle listener, retry регистрации. High-priority не означает гарантированную доставку.
- Проверка: refresh/invalid token, два устройства, logout/account switch, FCM отключён — fallback и UI статуса работают.

### F24. P2 — клиентская модель подписки может расходиться с аккаунтом

- M `subscription_service.dart:225–235,372–405,573–609`: `backendIsPremium || RC entitlement`; при `syncSessionUser(null)` backendIsPremium не обнуляется. `originalAppUserId` записывается как текущий state.appUserId, хотя при aliases/merge это может быть прежний ID.
- Дополнительно `_applyCustomerInfo(clearAppUserId:true)` передаёт `appUserId:null`, но не передаёт `clearAppUserId` в `copyWith`; null там означает сохранить старое значение (`300–303`). Поэтому успешный SDK logout не гарантирует очищение state.appUserId.
- Исправление: очищать весь account-scoped state при logout, сериализовать login/logout, хранить текущий SDK identity отдельно от original ID, обновлять backend snapshot после sync.
- Проверка: Premium A → logout → free B, anonymous→identified→restore, быстрые переключения; ни одного промежуточного платного UI для B по данным A.

### F25. P2 — iOS получает Android SDK key по умолчанию

- M `subscription_service.dart:14–25,137–157`; B `config/settings.py:166–177`. Production config GET также возвращает iOS key с префиксом `goog_`.
- Это платформенно неверный fallback для App Store; для Android сам по себе дефект не объясняет отказ оплаты.
- Исправление: отдельный iOS public SDK key из iOS app в RevenueCat, обязательная platform validation. Проверка: iOS sandbox configure/offerings; Android key не меняется без Dashboard-сверки.

### F26. P2 — разные правила для location endpoints

- B `tracking/views.py:346–355,380–390`: single-child endpoint всегда требует Premium; aggregate разрешает free при ≤1 ребёнке и отдаёт ту же геопозицию.
- Причина: политика доступа распределена между views. Это контрактная несогласованность; бизнес-решение «один ребёнок бесплатно» надо подтвердить.
- Исправление: единая capability policy и одинаковые разрешения для эквивалентных представлений данных. Проверка: матрица free/paid/lite и 0/1/2 детей для обоих endpoints.

### F27. P1 — известные advisory зависимостей и расхождение окружения с requirements

- B `requirements.txt:1–4`; фактическое окружение `.venv`, результаты `audit_evidence/pip-audit-{installed,pins}.json`.
- Exact-pin scan: 114 advisory в Django 5.0.6, DRF 3.15.2, Pillow 10.3.0. Installed snapshot scan: 131 advisory в 5 пакетах. Это совпадения версий с базой advisories, не 131 доказанная эксплуатация приложения; нужен анализ применимости.
- Установлен Pillow **12.2.0**, хотя requirements требует **10.3.0**. Поэтому pip check и tests существующего venv не доказывают результат clean install requirements.
- Первоначальный resolver-based pip-audit не прошёл из-за сборки Pillow на Python 3.13; повторные no-deps scans успешно выполнены. Детали ограничений в SECURITY_AUDIT.md.
- Исправление: поддерживаемые patched dependencies, lock/hash и фиксированный Python, triage advisories, clean staging environment. Проверка: reproducible install + regression + повторный dependency audit.

### F28. P2 — в Git отслеживается готовое Python-окружение

- B `.gitignore:1–8` исключает `.venv/__pycache__`, но Git index содержит **6099 файлов `.venv/`**. Ignore не отменяет прежнее отслеживание.
- Следствие: огромный непереносимый репозиторий, generated bytecode changes при проверках, расхождение installed/pinned dependencies.
- Исправление отдельной веткой: удалить из index generated environment/cache, сохранить requirements/lock и instructions; отдельно проверить историю на секреты. Не удалять рабочую среду пользователя автоматически.
- Проверка: чистый clone создаёт окружение из lock, `git ls-files .venv` пуст; tests не меняют tracked files. Автоматически изменённые audit bytecode восстановлены, pre-existing `.DS_Store` оставлен.

### F29. P1 — старая GPS-точка может выглядеть свежей

- M `lib/core/services/location_service.dart:16–24,138–155,210`, `background_command_service.dart:332–344,419–427`; B `tracking/serializers.py:34–40`, `tracking/models.py:14–20`, `tracking/views.py:178–186`.
- После неудачи GPS берётся last-known position без age limit. Клиент отправляет координаты, не `Position.timestamp/accuracy`; backend ставит новый `created_at`, active=true. LocationFix также теряет timestamp.
- Следствие: кэшированная позиция может отображаться как новая, искажать историю/геозоны и оценку актуальности данных. Это подтверждённый путь в коде; конкретный production false alert не наблюдался.
- Исправление: captured_at отдельно от received_at, accuracy/source/is_cached, возрастной лимит, stale UI и исключение старых точек из новых zone transitions; backward-compatible контракт для старых клиентов.
- Проверка: lastKnown вчера при GPS timeout не становится «сейчас»; актуальный fix корректно обновляет маршрут/зоны.

### F30. P2 — API принимает невозможные координаты и battery

- B `tracking/serializers.py:34–40`, `tracking/models.py:14–19`, `tracking/views.py:175–186`.
- Дополнительное локальное воспроизведение: lat=1234, lng=9999, battery=900 → HTTP 201. Validation ranges отсутствуют.
- Последствие: повреждённые входные данные попадают в карту/историю/расчёт расстояний и статистику; safe-zone lat/lng/radius также требуют явных физических диапазонов.
- Исправление: finite lat −90..90, lng −180..180, battery 0..100, положительный ограниченный radius и размер payload; на миграции не ломать существующие корректные записи.
- Проверка: invalid/NaN/Infinity/out-of-range возвращают 400, валидные границы приняты.

### F31. P2 — privacy data-flow не описывает геокодирование Nominatim

- M `lib/core/services/location_service.dart:181–202,279–292`: fallback отправляет lat/lng в `nominatim.openstreetmap.org`; W `privacy-policy.html:278–285` перечисляет Google/Firebase/RevenueCat, Nominatim/OpenStreetMap не найден.
- Последствие: неполная карта внешних получателей координат и зависимость от внешнего публичного geocoder. Юридическое заключение о достаточности disclosure этим аудитом не делается.
- Исправление: явный data-flow/consent/retention review, согласованные policy/Data safety; caching/rate limiting или контролируемый geocoder, отдельные ограниченные server/client Maps keys по назначению.
- [Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/) также требует суммарный лимит и возможность сменить публичный endpoint без обновления app; текущий URL hardcoded, глобальный лимитер не найден. Фактический production объём запросов не измерен.
- Проверка: network trace разрешённого тестового устройства соответствует заявленному списку processors, geocoding outage не блокирует отправку координат.

### F32. P1 — Lite запускает tracking FGS сразу с microphone/mediaPlayback types

- `Baby-locator-lite/lib/core/services/background_command_service.dart:27–45`, `android/app/src/main/AndroidManifest.xml:63–69`.
- Tracking service конфигурируется одновременно как location + microphone + mediaPlayback, даже когда аудиосессии нет; autoStartOnBoot true. В отличие от актуального платного проекта, отдельный microphone FGS в Lite bridge manifest отсутствует.
- Причина: старый общий сервис не разделяет tracking и согласованную audio session. На Android 14+ объявленный mic type требует RECORD_AUDIO/while-in-use prerequisites на старте; отсутствие разрешения или background start может сорвать не только аудио, но и tracking service. Это вывод из кода и платформенных требований; на устройстве не воспроизводился.
- Исправление: tracking только location; microphone service запускать из видимой consent Activity для конкретной сессии, не при boot. Не переносить только manifest из paid без соответствующей Dart/native логики.
- Проверка: Lite child login без mic grant всё равно даёт допустимый tracking; mic появляется только после consent; Android 12–16/boot/revoke matrix.

### F33. P1 — Lite Accessibility capability противоречит общей Privacy Policy

- `Baby-locator-lite/packages/kid_security_android_bridge/android/src/main/res/xml/blocking_accessibility_config.xml:3–6`: `canRetrieveWindowContent=true`, `flagRetrieveInteractiveWindows|flagReportViewIds`.
- Kotlin `BlockingAccessibilityService.kt:146–165` читает window roots для packageName. `lib/core/compliance/app_compliance.dart:8–9` направляет на общую W Privacy Policy, где `privacy-policy.html:272,349,395` заявляет строго `canRetrieveWindowContent=false`.
- Подтверждена разница capability и заявленного ограничения. Чтение/отправка текста сообщений этим наблюдением **не доказаны**: проверенный код использует packageName.
- Исправление: минимизировать capability по реальной задаче блокировки и согласовать все тексты/Console declaration. Проверить, что отказ window content не ломает допустимый механизм определения foreground app.
- Проверка: final Lite merged resource и runtime service capabilities совпадают с policy/consent; тесты блокировки на поддерживаемых устройствах.

### F34. P1 — вложенный backend Lite несовместим с собственным клиентом

- `Baby-locator-lite/backend/subscriptions/urls.py:1–8` содержит только webhook; `backend/subscriptions/services.py:31–47` не знает `_lite_full_access`; клиент `lib/core/subscriptions/subscription_service.dart:123–155` требует `/api/revenuecat/lite-token/`.
- Если развернуть bundled backend, exchange получает 404, ошибка тихо скрывается, UI считает Premium true, сервер продолжает запрещать paid API. Отдельный актуальный `Baby-locator-backend` имеет exchange, но небезопасный F01. Доказательства использования bundled backend в production нет.
- Исправление: выбрать canonical backend/версию, явно указать supported API contract; удалить из deployment выбора устаревший snapshot только отдельным согласованным изменением, без автоматического удаления функций в аудите. Lite должен обрабатывать unavailable exchange как понятный статус.
- Проверка: checkout/release metadata однозначно определяют сервер; contract suite требует endpoint и capabilities; legacy deployment не выдаётся за совместимый.

### F35. P1 — Lite Git содержит БД с credentials и пользовательскими данными

- `Baby-locator-lite/backend/db.sqlite3` отслеживается Git; также 3 файла в `backend/media/` и 4599 файлов вложенной venv. Это установлено через Git index и read-only SQLite metadata.
- В БД: 2 User, 2 DRF token, 14 location rows, 4 chat messages; webhook event table отсутствует. Значения токенов/имён/координат/сообщений не выводились. Не установлено, синтетические это данные или реальные, и действуют ли токены на каком-либо сервере.
- Последствие: repository readers получают потенциальные credentials/персональные данные; один `.gitignore` не удаляет историю.
- Исправление: установить происхождение данных, revoke реально действующих токенов/паролей при подтверждении exposure, согласованный cleanup index/history/artifacts; fixtures только обезличенные synthetic. Не публиковать дамп в issue/чат.
- Проверка: tracked DB/media/venv отсутствуют в новой поставке; secret/history scan, старые действующие tokens отозваны, clean checkout создаёт отдельную test DB.

### F36. P2 — автоматические проверки Lite не проходят

- `Baby-locator-lite/test/widget_test.dart:6–10`, `lib/features/stats/stats_menu_feature_screens.dart:1068`, `third_party/record_linux/lib/record_linux.dart:176–184`.
- `flutter analyze`: 90 issues = 0 errors, 2 warnings, 88 info. Warnings: unused `_formatMinutes`, `unawaited_return_in_try_block`. `flutter test`: единственный `App boots to root` failed; первый exception ProviderScope/framework `!_dirty`, затем expected MaterialApp found 0.
- Подтверждён failed test suite на Flutter 3.47.2; точная первопричина mount assertion и его проявление в Android release не установлены. Нельзя объявить это доказанным production crash.
- Исправление: изолировать startup/provider lifecycle от platform services, уточнить test harness с overrides/mocks, исследовать synchronous provider updates при mount; исправить await/finally и warnings. Не просто заменить expectation, чтобы скрыть exception.
- Проверка: clean dependency resolution, analyze без warnings, widget test без suppressed exceptions плюс cold-start на реальном устройстве. Diff автоматической Flutter migration сохранён отдельно.

### F37. P1 — зависимости окружения/вложенного backend не обеспечивают загрузку настроек

- Standalone B `requirements.txt:6–8` требует python-dotenv/gunicorn/psycopg2-binary, но **в текущем локальном venv все три отсутствуют**. B `config/settings.py:1–5` скрывает ImportError dotenv, поэтому локальная .env автоматически не загружается этим интерпретатором. Tests прошли только с явно заданными synthetic ENV и SQLite, а не с PostgreSQL deployment stack.
- Lite `backend/config/settings.py:1` безусловно импортирует dotenv, тогда как `backend/requirements.txt:1–5` не содержит его. Все четыре попытки `check`, `check --deploy`, `test`, migration dry-run на bundled backend остановились на `ModuleNotFoundError: dotenv` до проверки Django. Использовался standalone Python venv; это не clean install bundled requirements, но отсутствующая declaration подтверждена самим manifest зависимостей.
- Последствие: настройки могут тихо остаться defaults в standalone окружении или backend не стартует; gunicorn/PostgreSQL path этим локальным venv не проверяется. Production installed packages неизвестны.
- Исправление: clean environment из полного reviewed lock, обязательная загрузка production ENV и fail-fast validation, удалить зависимость от случайно committed venv. Проверка: import smoke, `pip check` **и** сверка manifest→installed, PostgreSQL/gunicorn staging startup. `pip check` один не обнаруживает отсутствующий пакет, если никакой установленный distribution его не требует.

## Часть 3 — Возможные проблемы, требующие внешних данных

| Гипотеза | Что уже известно | Как подтвердить |
|---|---|---|
| Wrong RevenueCat project/key или отсутствует offering | Код использует goog_ key, `default` и fallback current; фактический Dashboard неизвестен | Project/App/public key и Offering products/package export, SDK debug log |
| Play products/base plans неактивны/не доступны стране | В коде monthly/yearly и сопоставление `:` segments; Dashboard/API store catalog не получены | ProductId/basePlanId/offerId, countries, status, account country и responseCode |
| Backend webhook auth не совпадает/не настроен | Production config публичен, auth secret им не раскрывается | Dashboard webhook attempt status/response и redacted server logs |
| Firebase service account отсутствует на сервере | В workspace JSON есть уровнем выше backend, project_id совпадает с Android; default path backend не существует, `.env` не переопределяет путь | На сервере проверить resolved path/readability/credential project и одну разрешённую тестовую доставку |
| TURN не развёрнут/закрыты relay ports | По default backend только STUN; production ICE endpoint требует auth и не вызывался | Redacted ICE response, coturn logs, forced-relay test через разные сети |
| HTTP media публичны/не обслуживаются | DEBUG route отдаёт MEDIA без auth, prod routes не видны; URL файлов включён в serializers | Anonymous GET специально созданного тестового файла, nginx/private storage config |
| Ошибки только Google Play Release | Target/package/подписи/Maps restrictions и Play account eligibility зависят от артефакта и установки | App Bundle Explorer + Play-installed build, logcat и сертификаты |
| Неполная Android 16 native совместимость | compile/target 36; ELF-проверка AAB 23 нашла 18 .so: все 64-bit PT_LOAD alignment ≥16 KB, только armv7 WebRTC =4 KB | Это не доказательство сбоя на 16 KB устройстве: 32-bit ABI оценивать отдельно. Нужны APK packaging alignment и runtime test на 16 KB device |
| Неисправная батарея/Doze/OEM ограничения | Polling требует живого процесса/FGS | Матрица Pixel/Samsung/Xiaomi, Doze, network loss; нельзя обещать работу после Force stop |

Наличие JSON на рабочей машине не подтверждает работоспособность FCM на сервере. Отсутствие TURN в defaults не доказывает отсутствие TURN в deployment ENV. Не следует компенсировать неизвестные настройки выдачей всем пользователям Premium.

## Часть 4 — Что исправить в исходном коде

Изменения реализации готовить **в отдельных ветках каждого репозитория**, после фиксации приведённых проблем и acceptance criteria. В этом аудите такие изменения не делались.

| Файлы | Изменение | Проверяемый результат |
|---|---|---|
| B subscriptions/views.py, accounts/authentication.py, services.py + grant model/migration | scoped grants, убрать header-based privilege escalation, revoke/expiry | F01 negative tests, совместимость разрешённых Lite функций |
| B tracking/views.py + permissions module | ownership deactivate; read-only zones child; stop без Premium | F02/F03/F13 API tests |
| B subscriptions/services.py/models.py + tests | event validation, environment/app filtering, lock owner, robust dedupe, ordering, transfer/revocation | Event suite + PostgreSQL concurrent tests |
| B subscriptions/views.py/urls.py + server RC client | authenticated reconciliation + rate limit, timeout, server-only secret | Потеря webhook устраняется sync без client trust |
| M subscription_service.dart, premium_paywall_screen.dart/catalog.dart | store prices, identity state reset, backend sync/pending UI | Реальные локализованные цены и Premium API после test purchase |
| M main.dart/app.dart/session_providers.dart/fcm_service.dart | coordinator startup, offline state, listener cleanup, secure token storage | cold start/offline/switch стабильны |
| M background_command_service.dart/child_live_audio_service.dart/child_webrtc_service.dart + Kotlin service/plugin | consent Activity → FGS handshake, typed errors, actual command status, stop notification/timeout | Нет скрытой записи, корректные Android 12–16 состояния |
| M child_webrtc_service.dart/parent_webrtc_service.dart | serialized signaling, ICE queue/retry/generation, RTP stats, bounded reconnect | Симуляция network faults и LTE relay |
| B RemoteDeviceCommand/MonitorSession models, views/migrations | lease, expiry, ACK/retry, consent/session lifecycle | Нет поздних start/вечного mic после потери parent |
| B tracking/live_audio.py и DEPLOY_NGINX.md | общий broker/stream service, bounded lifetime; согласовать HTTP fallback | Cross-worker тест воспроизводимо передаёт PCM |
| B accounts/views.py/models.py, serializers.py/settings.py | invite одноразовый, throttles, password policy, escaped template, fail closed config | Reuse/XSS/auth tests |
| B deletion service + chat/subscriptions storage cleanup; W policies | реальное удаление/retention; частное медиа | Проверка DB/storage/backup policy |
| B tracking/models.py/migrations | решить AppIcon PK drift | makemigrations --check exit 0 |
| L manifest/Gradle/subscription service | monitoring, identity, server capabilities вместо unconditional premium | Отдельный AAB + проверенный Lite API контракт |
| B requirements/lock, M pubspec/lock | обновление поддерживаемых зависимостей с регрессией | Dependency audit и repeatable release |
| M location_service.dart/background_command_service.dart/API client; B location serializers/models/views | captured_at/accuracy/source/stale и ranges; backward-compatible migration | Старый GPS cache не становится свежей точкой; invalid inputs 400 |
| W privacy-policy.html + M geocoding config | полная карта recipients, согласованные переводы/disclosures, geocoder quotas/cache | Network trace совпадает policy, GPS не блокируется address lookup |

## Часть 5 — Что настроить вручную

Подробные инструкции вынесены в [PRODUCTION_SETUP_CHECKLIST.md](PRODUCTION_SETUP_CHECKLIST.md), [REVENUECAT_GOOGLE_PLAY_CHECKLIST.md](REVENUECAT_GOOGLE_PLAY_CHECKLIST.md), [WEBRTC_FIREBASE_TURN_CHECKLIST.md](WEBRTC_FIREBASE_TURN_CHECKLIST.md). Безопасный шаблон — [.env.production.example](.env.production.example). Он не исправляет код и не должен автоматически заменять действующую .env.

## Часть 6 — Какие данные отсутствуют

1. Google Play Console read-only release/catalog/policy export: package, tracks/versionCodes, countries/base plans/offers, license testers, Play App Signing fingerprints, Data safety/FGS/background location/accessibility/full-screen declarations, rejection messages. Пароли аккаунта не нужны.
2. RevenueCat Project/App identifiers, public SDK key equality (можно masked), Entitlement/Offering/package-to-product mappings, credential validation result, redacted events по одному test customer, webhook delivery status, restore/transfer policy. Приватные JSON/secret API keys в чат не передавать.
3. Ошибка покупки: время/таймзона, versionCode, install source, Android version, country, PurchasesErrorCode + underlying Billing responseCode/debugMessage, anonymized appUserID, CustomerInfo entitlement и событие Dashboard. Не передавать purchase token целиком.
4. Сервер: deployed Git SHA/image digest, redacted ENV presence, DEBUG/IS_TEST booleans, migration list, worker config, nginx config с закрытыми секретами, webhook/Firebase logs по correlation id, service account file readable/project match. Shell history/полную .env не присылать.
5. ICE server types/URL transports без credentials, coturn config без secret, DNS/public IP topology/firewall/relay range, selected candidate pair/getStats с замаскированными IP.
6. Два разрешённых тестовых Android-устройства и воспроизводимый сценарий: parent/child foreground/background/lock/Doze/force-stop, mic privacy, battery policy, Wi-Fi/LTE; test accounts с изолированными данными.
7. Lite final AAB, effective applicationId, сертификат, Firebase project/client entry, продуктовая политика бесплатных функций и право переносить entitlement между edition.
8. Политика retention и доказательства выполнения удаления в storage/backups/RevenueCat. Живой сайт и юридические декларации автоматически полностью не верифицированы.

## Часть 7 — План исправления

1. **Critical production blockers:** закрыть F01/F02/F03; fail closed settings и prod test mode; зафиксировать артефакт/серверный SHA. Изменения на сервере — отдельное разрешённое внедрение, не часть аудита.
2. **Покупки:** в тестовом треке сверить package/key/catalog; заменить цены, добавить диагностируемые pending/cancel/error состояния. Не менять product IDs действующих подписчиков без миграционного плана.
3. **Синхронизация Premium:** event processing, expiry, transfer/revoke, reconciliation; одинаковая capability policy на всех API.
4. **Firebase:** безопасный deploy credential, startup coordinator, device tokens/ACK/invalid-token handling и реальная доставка уведомления.
5. **WebRTC/микрофон:** согласие ребёнка, visible Activity/FGS handshake, signal serialization, TURN relay и network recovery, stop/lease/timeout.
6. **Безопасность:** invites/auth throttles/XSS/private files/deletion, Lite identity/grants, dependency patching; удалить generated environment из Git index отдельной веткой. Исправить GPS freshness/validation и раскрытие geocoder data flow.
7. **Тестирование:** backend PostgreSQL integration, Flutter unit/widget, Play license tests, Android 12–16 E2E с двумя устройствами, отрицательные authorization tests.
8. **Новый Google Play Release:** воспроизводимый AAB с новым неиспользованным code (не считать 24 свободным без Console); verify final manifest/certificate/native libs; staged rollout после smoke test всех треков и policy review.

## Часть 8 — Проверки перед публикацией

Полная матрица в [RELEASE_QA_CHECKLIST.md](RELEASE_QA_CHECKLIST.md). Обязательные release gates: нет открытых P0/P1, миграции чистые, статический анализ/тесты проходят, test purchase/restore подтверждены Dashboard и Premium API, consent mic корректен, relay выбран на двух мобильных сетях, stop после потери связи ограничен по времени, auth семей изолирован, track manifests compliant, rollback rehearsal.

### Что проверено автоматически

| Команда / проверка | Фактический результат | Ограничение |
|---|---|---|
| flutter doctor -v | SDK 3.47.2 / Dart 3.13.2; проблемы Android licenses | Лицензии автоматически не принимались |
| flutter pub get | Успешно | Исходная версия pubspec уже изменена пользователем; lock git diff не появился |
| flutter analyze | No issues found | Не проверяет Dashboard/FGS runtime |
| flutter test | 8 passed | Только существующие widget/disclosure/test-mode tests |
| Django manage.py check | exit 0 | Изолированная SQLite конфигурация |
| check --deploy | exit 0, security.W008 | SSL redirect намеренно false для local test harness; это не production scan |
| manage.py test | 15 passed | SQLite, mocked/отсутствующие внешние сервисы; платежного lifecycle и WebRTC integration suite нет |
| makemigrations --check --dry-run | exit 1, AppIcon.id | Миграция не записана и не применена |
| pip check | No broken requirements found | Совместимость установленных Python пакетов, не отсутствие CVE |
| custom backend reproductions | 7 наблюдений дефектов | `audit_evidence/reproduce_backend.py`, memory DB, synthetic data |
| production GET test-mode/config | 200; is_test false; entitlement family_security_pro | Только публичные read-only GET, не проверка оплаты/webhook |
| SHA-256 AAB | Совпали с ранее сохранёнными JSON | Не доказывает опубликованный versionCode или исходный Git SHA |
| Повторный AAB 23 verifier | PASS: bundletool, JAR signature, metadata, package/version | Не создавался новый release и не проверены active Console tracks |
| Hardened synthetic check --deploy | No issues (0 silenced) | SSL redirect true, synthetic ENV; не фактический сервер |
| Static API URL resolve | Paid 54 literal paths, Lite 50, все resolved; backend 60 route patterns | Не проверка HTTP методов/JSON/семантики, dynamic Lite exchange проверен отдельно |
| Дополнительные воспроизведения | Out-of-range location 201; lifetime refund true; sandbox/wrong app processed; unescaped HTML | Synthetic accounts/events, memory DB; первоначальные 7 результатов также повторились |
| pip-audit exact pins / installed snapshot | 114 / 131 advisory hits | no-deps/version scan, применимость требует triage; первый resolver-based scan failed |
| ELF PT_LOAD AAB 23 | Проверены 18 .so | Все 64-bit align ≥16 KB; не APK ZIP alignment/runtime verification |
| Lite flutter pub get | Успешно, 14 dependency changes относительно tracked lock | Автоматические tool changes сохранены как diff и восстановлены; полноценный lock review нужен |
| Lite flutter analyze | FAILED gate: 90 issues, 0 errors / 2 warnings / 88 info | Выполнено после auto migration analysis_options, без Android release build |
| Lite flutter test | FAILED: 0 passed / 1 failed | ProviderScope `!_dirty` и MaterialApp expectation, не доказанный release crash |
| Lite embedded DB metadata | Tracked DB/media/venv; 2 users/2 tokens/14 locations/4 messages | Только counts/schema, значения данных не выводились; происхождение/валидность неизвестны |
| Lite bundled backend check/deploy/test/migrations | Все exit 1: ModuleNotFoundError dotenv | Не дошли до Django checks/tests; использован основной локальный venv |
| Backend required environment tools | python-dotenv/gunicorn/psycopg2-binary NOT_INSTALLED | Production package set неизвестен; PostgreSQL/Gunicorn этим окружением не проверены |

Логи команд находятся в `audit_evidence/`. Python harness задаёт отдельную SQLite DB, synthetic secret и несуществующий Firebase credential path; подключения к live production БД не было. Отдельно read-only проверена метаинформация bundled SQLite из Lite Git. CVE нельзя вывести только из количества устаревших пакетов. `pip-audit` результаты и ошибки resolver разделены в SECURITY_AUDIT.md.

### Совместимость API двух мобильных клиентов

Автоматическая инвентаризация Django URL resolver сохранена в [audit_evidence/api-inventory.md](audit_evidence/api-inventory.md), исходные результаты — `api-contracts.json`. 54 различных literal API path основного клиента и 50 Lite разрешаются локальным Django URLconf; неизвестных маршрутов в этой выборке нет. Lite исключает app-config/test-mode/test-premium/revenuecat-config из найденных literal путей, а Lite token exchange строит URL интерполяцией и проверен вручную отдельно. Это не исчерпывающий анализ всех динамически построенных URL.

| Контракт | Совместимость путей | Семантическая проблема |
|---|---|---|
| Auth/register/me/children/invite | Пути совпадают | Reuse кода, weak auth, offline logout, lifecycle restored user |
| Location/history/zones | Пути совпадают | Single/aggregate rights различаются, child zone writes, нет captured_at/accuracy/range |
| Stats/app limits/blocks | Пути совпадают | Lite UI unconditional premium, actual server token exchange может тихо не пройти; API 403 скрывается helper, который всегда false |
| Commands pending/complete | Пути совпадают | Delivered без lease/ACK retry; fake WebRTC completed |
| Monitoring send/poll/activate/deactivate/ICE | Пути совпадают | Ownership stop, отсутствуют leases/consent/serialized signaling |
| RevenueCat | Платный SDK + webhook, Lite stub | Один backend с разными клиентскими моделями прав; signed Lite token переносим |
| Chat/tasks/rewards | Пути совпадают | Нужны file limits/private storage/pagination/deletion |

Таким образом, основной обнаруженный конфликт — правила доступа и жизненный цикл, а не простая опечатка URL. Для каждого endpoint нужны contract tests методов, полей, error codes и прав; один URL resolve не подтверждает все функции.

## Часть 9 — Критерии готовности функций

| Функция | Реальный код / состояние | Что должно доказать готовность |
|---|---|---|
| Регистрация/login/logout | accounts views + SessionNotifier; реализованы, offline/logout flaws | Weak password/invalid creds/401/rate limit, session survives offline, revoke token |
| Подключение ребёнка | InviteCode/RegisterChildWithCode; небезопасный reuse | Одноразовый код и re-pair, concurrent redemption, free-child limit |
| Геопозиция/фон | ShareLocation, LocationService/background telemetry; статически реализованы | 30+ мин background/lock, актуальные timestamps, permission revoke, bounded battery usage |
| Карта | Google/Apple adaptive maps; конфигурация Maps нужна | Play-signed build с верной package/SHA, marker matches DB, нет fake fresh location |
| История/зоны | LocationHistory/SafeZone/alerts; history ограничена 100 | Вход/выход/расписание/UTC, границы суток, child read-only, pagination policy |
| SOS/уведомления | SosView, Alert, FCM/local notification/fallback | Два устройства, ACK/latency, denied notifications, offline delivery и clear status; full-screen eligibility отдельно |
| Сигнал | RemoteDeviceCommand loud/loud_stop | Видимое выполнение, stop, TTL, volume/DND поведение документировано |
| Статистика/блокировка | device-stats sync, app limits, blocked apps, Usage/Accessibility bridge | Usage access/consent, non-bypass scope, reboot, family permissions, Google Play declaration |
| Premium | SDK calls реализованы, backend lifecycle дефектен | License test purchase/restore→RC→webhook/sync→API 200, expiry/refund→403 |
| WebRTC | offer child/answer parent, ICE, audio track, restart, cleanup реализованы частично | Mic consent + actual RTP/audio, relay two carriers, stop/timeouts, lifecycle matrix |
| HTTP audio | raw PCM streaming + clip endpoints сохранены | Cross-worker streaming, privacy/retention, не используется как обход Android |
| Восстановление/сеть | SharedPreferences + bootstrap | Cold-start child/parent, no logout on timeout, no duplicate listeners/services |
| Сайт/удаление | Статические страницы и API delete существуют | Реальные публичные URLs, согласованные переводы, удаление всех заявленных категорий/файлов |

## Часть 10 — Финальный вердикт

- **Работает и проверено локально:** разрешение Flutter dependencies обоих клиентов; основной analyze, 8 основных Flutter и 15 Django tests; Django import/system check, API reproductions и публичные production GET. Lite analyze gate и widget test **не прошли**.
- **Исправлено и протестировано:** исходные дефекты в этом аудите не исправлялись. Созданы документы и воспроизводимые диагностические материалы.
- **Требует ручной настройки:** Play catalog/testers/tracks, RevenueCat mappings/credentials/webhook, Firebase server credential, TURN/firewall/TLS, deployment hardening, Play disclosures.
- **Не удалось проверить:** реальная неуспешная/успешная покупка, опубликованный code/SHA, production webhook/FCM/TURN, E2E аудио и Android battery lifecycle, полный Lite build, приватные dashboards.
- **Блокирует production:** F01 и нарушения семейных прав, Premium lifecycle/sync, Android mic launch/stop reliability, незавершённые release QA gates.
- **Готово к публикации:** подтверждения готовности нет. Исправление одного `isMonitoringTool` не означает готовность платежей и аудио.

## Официальные источники

- [Android: background FGS restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start) — while-in-use mic, исключения и типы ошибок.
- [Android: microphone foreground service type](https://developer.android.com/develop/background-work/services/fgs/service-types#microphone) — manifest/runtime prerequisites.
- [Google Play: monitoring flag](https://support.google.com/googleplay/android-developer/answer/12955211) — все распространяемые version codes во всех tracks.
- [Google Play: target API](https://support.google.com/googleplay/android-developer/answer/11926878) — требования на дату проверки; target 36 в локальных release manifests.
- [Billing version deadlines](https://developer.android.com/google/play/billing/deprecation-faq) — для новых загрузок на 03.11.2026 Billing 7 уже вне срока, локальный manifest указывает 8.3.0.
- [RevenueCat Play credentials](https://www.revenuecat.com/docs/service-credentials/creating-play-service-credentials) — server credentials и validation Dashboard.
- [RevenueCat webhooks](https://www.revenuecat.com/docs/integrations/webhooks) и [event fields](https://www.revenuecat.com/docs/integrations/webhooks/event-types-and-fields) — Authorization header, delivery, lifecycle/transfer schema.
- [Firebase Flutter receive](https://firebase.google.com/docs/cloud-messaging/flutter/receive-messages) — background handlers и ограничения доставки.
- [coturn configuration reference](https://github.com/coturn/coturn/blob/master/examples/etc/turnserver.conf) — shared-secret authentication, TLS, relay options.
- [Django supported releases](https://www.djangoproject.com/download/) — используемая 5.0.6 требует перехода на поддерживаемую и исправленную версию.
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/) — ограничения публичного geocoding endpoint и privacy.
