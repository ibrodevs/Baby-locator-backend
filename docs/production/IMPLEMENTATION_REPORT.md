# Baby Locator — отчёт об исправлениях

Дата: 3 ноября 2026. Инструкция по запуску: [PRODUCTION_START_HERE_RU.md](PRODUCTION_START_HERE_RU.md). Исходный аудит: [BABY_LOCATOR_FULL_AUDIT.md](BABY_LOCATOR_FULL_AUDIT.md).

## Результат и границы

Локально исправлены платный Flutter-клиент, основной Django backend и тексты сайта. Работа выполнена в ветках `fix/production-readiness-20261103` этих трёх репозиториев. Lite оставлен без изменений по вашему указанию. Коммиты, push, публикация сайта/приложения, изменение production и финансовые операции не выполнялись.

Это готовые изменения исходников с локальной проверкой, а не подтверждение исправления уже опубликованного приложения. Реальные покупки, FCM, TURN, Google Play Console и серверные ключи требуют настройки владельцем аккаунтов и проверки на устройствах. Следующий versionCode необходимо сверить с Play Console; пользовательская версия `1.0.7+23` сохранена.

## Что изменено

**Покупки и Premium.** Авторитетный серверный sync RevenueCat, проверка срока доступа, отдельные product entitlements, защита от дублей/старых/параллельных webhook, фильтры приложения и окружения, cancellation до expiry, grace, refunds, transfers и восстановление через provider snapshot. Secret key не возвращается клиенту. Unknown-user события остаются для повторной обработки; TEST не выдаёт доступ. Login/purchase/restore синхронизируют backend; paywall показывает ожидание подтверждения и реальные цены SDK в валюте магазина. Убраны встроенные SDK keys и Android-key fallback на iOS. Числовой ID родителя используется как RC App User ID.

**Микрофон и WebRTC.** Запрос превращён в приглашение с подтверждением на видимом экране ребёнка. Только после согласия запускается микрофон. Request TTL 2 минуты, максимальная сессия 10 минут, heartbeat/lease и остановка без зависимости от оставшегося Premium. Native service имеет уведомление и Stop, ошибки запуска доходят до UI. Push служит сигналом получить актуальные команды, не запускает микрофон напрямую. Signaling отправляется последовательно с idempotency ID и ограниченными повторами; ICE ждёт соответствующий SDP/generation; polling не пересекается. У родителя подтверждение получения WebRTC-звука основано на inbound RTP bytes. Реальное поведение Android/OEM и слышимость остаются обязательным device QA.

**Backend и данные.** Закрыты команды чужим семьям, запись safe zones ребёнком, повторное использование invite и выдача платных прав по заголовку Lite. Токен ребёнка ротируется при pairing. Пароли валидируются, auth ограничен по частоте, JSON должен быть объектом, координаты/accuracy/battery проверяются. GPS хранит время самой точки, cache flag и accuracy. Приватные media доступны через авторизацию семьи; avatar/file клиенты передают auth headers. Удаление аккаунта удаляет связанные файлы после commit, очищает billing payload identifiers и ставит удаление RevenueCat customer в повторяемую очередь. Добавлено предупреждение: удаление аккаунта не отменяет магазинную подписку.

**Сессия приложения.** Token перенесён из обычных preferences в secure storage с миграцией; минимальный профиль кэшируется для offline. Сетевой сбой/5xx не разлогинивает, подтверждённый 401 очищает локальную сессию. Жизненный цикл сервисов привязан и к восстановленной сессии. Firebase, maps и подписки инициализируются независимо с ограничением ожидания. Logout отзывает серверный токен и все установки FCM аккаунта; при offline локальный выход не может гарантировать немедленный серверный revoke.

**FCM и инфраструктура.** Реестр установок с несколькими push tokens, удаление unregistered tokens, ограниченный TTL команд. HTTP audio дополнительно поддерживает общий Redis broker вместо памяти одного worker, ограниченный временный буфер и межпроцессную остановку. Новые systemd/Gunicorn/Nginx примеры, production preflight, maintenance/reconciliation timers, защищённый env template. Адреса больше не запрашиваются у public Nominatim: native OS geocoder, затем необязательный серверный Google Geocoding с отдельным ключом.

**Зависимости и Git.** Backend зависимости обновлены и зафиксированы с hashes в новом чистом Python 3.12 окружении. Старый локальный venv не перезаписывался. Около 6 тысяч файлов `.venv` и tracked bytecode сняты с отслеживания Git; локальные файлы сохранены. Это ожидаемая большая группа staged deletions, не потеря исходников. `.gitignore` дополнен. История Git и существующие секреты автоматически не очищались/не перевыпускались.

## Статус находок исходного аудита

«Исправлено локально» означает изменение и доступную локальную проверку; внешняя интеграция требует шагов инструкции.

| Находки | Статус |
|---|---|
| F01, fake Lite elevation | Общий backend защищён server-owned grants. Lite-клиент не менялся; совместимость и политика доступа требуют решения до общего deploy |
| F02–F05, ownership/expiry/webhook races | Исправлено локально; конкуренция webhook проверена PostgreSQL |
| F06–F08, lifecycle/purchase sync/prices | Исправлено локально; проверить реальный каталог, sandbox, restore/transfer/refund |
| F09–F13, microphone/signaling/commands/stop | Исправлено локально; обязательны Android device QA и relay/network tests |
| F14–F15, restored/offline session | Исправлено локально; добавлены offline и 401 regression tests |
| F16, worker-local HTTP audio | Общий Redis broker реализован и smoke-tested; требуется настройка Redis/proxy на сервере |
| F17, AppIcon migration drift | Исправлено согласованием AutoField с существующей схемой; новая миграция PK не требуется |
| F18–F21, auth/defaults/deletion/XSS | Исправлено локально; provider deletion/cleanup timers и backup retention нужно включить |
| F22, Lite identity/manifest | Отложено по вашему указанию, Lite не менялся |
| F23, FCM | Исправлены token lifecycle/multiple installs; реальная доставка и device acknowledgments не подтверждены, полноценная delivery telemetry не добавлена |
| F24–F26, SDK identity/iOS/location policy | Исправлено локально; iOS key и store setup нужны отдельно |
| F27–F28, dependencies/tracked venv | Основной backend обновлён; pinned dependency scan чист; Git index очищен от venv |
| F29–F31, stale GPS/validation/geocoding | Исправлено локально; Maps/Geocoding API restrictions и quota настраиваются владельцем |
| F32–F36, Lite | Отложено, включая его permissions, privacy mismatch, вложенный backend, tracked DB, failing checks |
| F37, settings import/dependency mismatch | Основной backend исправлен новым requirements/mandatory dotenv; вложенный backend Lite не менялся |

Общая Privacy Policy по-прежнему содержит Accessibility capability, которая не соответствует Lite из исходного аудита. Обновлённый аудио-раздел явно относится к платному приложению. Перед отдельным выпуском Lite потребуется собственная проверка его disclosures/manifest; этот пункт не объявляется закрытым.

## Проверки и доказательства

| Проверка | Результат / evidence |
|---|---|
| Django tests на отдельном PostgreSQL | 48 тестов, OK; `audit_evidence/fix-postgres-tests.log`; временный Unix-socket-only cluster, production DB не использовалась |
| Flutter analyze платного приложения | No issues found; `audit_evidence/fix-flutter-analyze.log` |
| Flutter tests | 14 passed; `audit_evidence/fix-flutter-tests.log` |
| Android debug compile, arm64 | APK собрался на финальной конфигурации; `audit_evidence/fix-android-debug-build.log` |
| Android release AAB | Сборка успешна; `audit_evidence/fix-android-release-build.log`; bundletool validation, package/version/monitoring metadata и JAR signature — PASS (`fix-aab-report.json`, `fix-aab-verify.log`) |
| Django deployment/configuration | `makemigrations --check`: No changes detected; synthetic preflight OK; `check --deploy`: 2 ожидаемых HSTS warnings, без ошибок (`fix-configuration-checks.log`) |
| Native ELF alignment | 18 native libraries inspected; у 64-bit библиотек LOAD alignment ≥16 KB (`fix-elf-alignment.json`); runtime/Play-generated APK alignment отдельно не проверялись |
| Redis real-server smoke | Разные broker instances, ownership denial, frame bound, stop, TTL — PASS; `audit_evidence/fix-redis-smoke.log`. Изолированный временный Redis без persistence, synthetic PCM, не production install |
| Backend dependency advisory scan | No known vulnerabilities found для полностью pinned списка на момент проверки; `audit_evidence/fix-pip-audit.log/json` |

Debug APK: `Baby-locator/build/app/outputs/flutter-apk/app-debug.apk`. Release AAB: `Baby-locator/build/app/outputs/bundle/release/app-release.aab`. Проверенный AAB имеет package `com.company.familysecurity`, версию **1.0.7+23**, monitoring metadata `child_monitoring`, SHA-256 `81a9aed35f934982d17f6607a388231b01d3f0e58aab5daeb07347b0bcf495a0`. Это проверочный артефакт с сохранённым номером, не новый релиз для загрузки. Новый versionCode согласуйте с Console и пересоберите. Проверка подписи не доказывает, что Play примет конкретный upload certificate.

Android tooling обновлён до AGP 8.13.2 и Kotlin 2.3.21; JVM target переведён на compilerOptions DSL. Library compileSdk согласован с API 36 приложения, чтобы старый WebRTC plugin не проваливал AndroidX AAR metadata checks. Убран встроенный Maps API key fallback; release требует настроенного ключа. Несовместимая Kotlin metadata больше не появляется. Основание совместимости — [официальная таблица Android](https://developer.android.com/build/kotlin-support).

Остались предупреждения о будущих требованиях Flutter к Gradle/AGP, разных версиях SDK command-line tools и Java 8 API сторонних плагинов; обе финальные сборки завершаются успешно. HSTS includeSubDomains/preload оставлены выключенными до проверки HTTPS всего домена. Preflight прогонялся на синтетических settings/JSON с отключённой проверкой сети; это не проверка настоящих ключей. PostgreSQL и Redis отдельно проверены локальными изолированными экземплярами. Физические Android-устройства, 16 KB runtime, iOS и desktop builds не тестировались.

При повторной debug-сборке закончился диск; после очистки генерируемых промежуточных файлов сборка прошла. Исходники, keystore, Firebase JSON и сохранённые релизные артефакты не удалялись. Права локальных Firebase JSON, backend `.env` и Android `key.properties` ужесточены до 0600, добавлены исключения credentials в Git. Старый пользовательский `.DS_Store` и изменение версии в pubspec сохранены.

## Миграции и эксплуатационные изменения

- `accounts`: 0007 DeviceInstallation, 0008 premium_synced_at, 0009 ExternalAccountDeletion.
- `subscriptions`: 0002 CustomerEntitlement/LiteAccessGrant/webhook status с переносом действующих legacy expiry subscriptions.
- `tracking`: 0017 captured GPS metadata, command/session TTL/consent/heartbeat, signaling delivery ID. Старые audio sessions закрываются, незавершённые команды инвалидируются.
- Новые mandatory production параметры: RC server key/app IDs, private Redis, Firebase expected project; полный список в env template. Без них preflight останавливает запуск примера systemd.
- Три worker теперь допустимы для legacy HTTP relay только с общим Redis. Основной WebRTC audio не идёт через Gunicorn, TURN должен быть доступен отдельно.
- Старые приложения не понимают consent и private media auth. Нужна согласованная миграция parent/child и отдельное решение для Lite.
- Maintenance каждые 5 минут повторяет deletion/webhook и удаляет старые orphan media. Reconciliation раз в час заново читает provider; ошибкам нужен мониторинг. Сам код не включает jobs на сервере.

## Что невозможно подтвердить без ваших аккаунтов и устройств

Фактический опубликованный AAB/commit, активность Play products/base plans/стран, права service account, соответствие RC ключа проекту, Current Offering, webhook delivery, Firebase permissions/token delivery, доступность coturn/TLS/relay, backup retention и реальные покупки/звук на телефонах. Секреты и реальные данные не печатались и не включались в новые документы. Настройка и итоговый release acceptance подробно перечислены в [инструкции](PRODUCTION_START_HERE_RU.md).
