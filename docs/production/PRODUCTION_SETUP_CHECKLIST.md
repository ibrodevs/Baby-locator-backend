# Production setup — Baby Locator

> Обновление 03.11.2026: этот документ сохраняет исходный аудит/чеклист до исправлений. Текущий статус — [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md), актуальные шаги и ключи — [PRODUCTION_START_HERE_RU.md](PRODUCTION_START_HERE_RU.md). Lite отложен по указанию владельца.

Дата: 03.11.2026. Выполнять после исправления блокеров из `BABY_LOCATOR_FULL_AUDIT.md`. Это инструкция оператору: команды deployment в рамках аудита не выполнялись. Значения секретов не отправлять в чат, Git, issue, build logs или screenshots.

## A. Google Play Console

| Где | Что заполнить / с чем сверить | Подтверждение | Если неверно |
|---|---|---|---|
| Выбор приложения / App Bundle Explorer | package итогового AAB платной версии `com.company.familysecurity`; проверить effective APP_APPLICATION_ID | В Console, bundle manifest и установленном Play приложении одинаково | Billing products/Firebase/Maps другого приложения, невозможность обновления |
| Test and release → Production/Internal/Closed/Open | Все распространяемые version codes и rollout status | Export release details всех треков; учесть прежнюю инструкцию об AAB 2 | Старая сборка продолжает нарушать policy или тестеры получают другой код |
| App integrity → App signing | App Signing SHA-1/SHA-256 и Upload certificate | Upload key соответствует загрузке; Maps/Integrity используют правильный Play signing fingerprint | Локальный APK работает, Play APK теряет Maps/attestation |
| Monetize → Products → Subscriptions | Реальные subscription Product ID, basePlanId, offers | Сверить таблицу в `REVENUECAT_GOOGLE_PLAY_CHECKLIST.md` | Offerings пусты, product unavailable |
| Каждый subscription/base plan | Active/published, доступность стран, цена, period, offers eligibility | Тестер нужной страны видит product и ожидаемую валюту | Товар недоступен или выбран неверный offer |
| Settings → License testing; Internal testing → Testers | Email Play аккаунта тестового устройства, opt-in, доступ к track | Приложение установлено из Play нужным аккаунтом; test payment method | Sideload/не тот account даёт нерепрезентативный Billing результат |
| Users and permissions | RevenueCat service account с доступом к этому приложению | RevenueCat validates Play credentials | Purchase validation отклоняется |
| Policy and programs → App content | Data safety, background location, FGS types, Accessibility, full-screen intent, monitoring, account deletion, privacy URL | Декларации совпадают с финальным merged manifest и реальными потоками данных | Отказ или удаление приложения |
| Store settings/listing | Описание родительского контроля, видимое уведомление мониторинга, support contact | Пользователь понимает, какие данные собираются и как остановить | Несоответствие monitoring/disclosure policy |

Пути меню могут локализоваться/меняться; ориентироваться на названия функций. Target SDK и Billing deadlines сверять с текущим Console при каждой загрузке. На дату проверки официальный [target API документ](https://support.google.com/googleplay/android-developer/answer/11926878) требует API 36 для обычных новых загрузок; локальный основной проект target 36. По [Billing deadline](https://developer.android.com/google/play/billing/deprecation-faq) версия 7 уже просрочена, в сохранённом финальном manifest основного AAB — Billing 8.3.0. Для Lite фактический AAB требуется отдельно.

Monitoring metadata проверять **внутри `<application>`** итогового manifest. Флаг нужен для всех распространяемых кодов во всех треках, согласно [Play policy](https://support.google.com/googleplay/android-developer/answer/12955211). Наличие флага не заменяет consent, notification и другие правила.

## B. RevenueCat Dashboard

Подробная последовательность и диагностика — [REVENUECAT_GOOGLE_PLAY_CHECKLIST.md](REVENUECAT_GOOGLE_PLAY_CHECKLIST.md). Минимальный обязательный набор:

- [ ] Выбран нужный Project и Google Play Android App с package итоговой платной сборки.
- [ ] Его **public Android SDK key** совпадает с remote config/сборкой; iOS получает свой ключ, не `goog_`.
- [ ] Entitlement ровно `family_security_pro`, products реально прикреплены.
- [ ] Offering `default` или намеренно используемый current имеет monthly/annual packages, доступные этому пользователю.
- [ ] Products импортированы из нужного Play app, subscription/base plan пары корректны.
- [ ] Play service credentials валидны; JSON загружен в защищённый Dashboard, не в приложение.
- [ ] RTDN настроены по инструкции RevenueCat для актуальных статусов магазина; не подменять этим Django webhook.
- [ ] Webhook HTTPS `https://<YOUR_API_HOST>/api/revenuecat/webhook/`, Authorization полный и одинаковый на обеих сторонах, app/environment filters соответствуют окружению.
- [ ] Права плана RevenueCat позволяют использовать требуемую интеграцию; проверить текущую доступность webhook в аккаунте.
- [ ] Numeric App User ID совпадает с Django user.id; transfer/restore behavior выбран осознанно.
- [ ] Test purchase видна в Customer history, entitlement active, webhook delivery успешен, backend и Premium API совпадают.

## C. Firebase Console / Google Cloud

1. Project settings → General: сверить `project_id`. Прочитанный Android config и локальный service account оба указывают `kid-security-994a0`; серверное состояние не подтверждено.
2. Your apps → Android: package платной версии должен совпадать с final AAB. Для отдельного Lite package добавить отдельную Android app и скачать соответствующий `google-services.json`. Этот файл — клиентская конфигурация, не Admin private key.
3. Project settings → Cloud Messaging / Google Cloud APIs: включить Firebase Cloud Messaging API (HTTP v1), проверить project/service account permissions. Не применять инструкции с legacy server key.
4. Project settings → Service accounts: создать/выбрать серверную identity с минимальными правами отправки FCM. Где возможно — workload identity; **текущий код принимает путь JSON**, поддержки ADC автоматически в нём нет.
5. Если используется JSON: установить на сервер вне репозитория, например `/etc/baby-locator/firebase-admin.json`, владелец service user, права 0600, каталог без публичной раздачи, backup зашифрован. Передавать через secret manager/защищённый CI secret file, не чат.
6. Задать `FIREBASE_SERVICE_ACCOUNT_KEY` абсолютным путём; проверить существование и чтение тем же service user. Локальный JSON в workspace root не читается backend default path автоматически.
7. Перезапускать workers только в разрешённое deployment window. `_ensure_firebase()` кеширует инициализацию процесса.
8. На разрешённом тестовом устройстве: открытие/вход → FCM getToken → `/api/auth/fcm-token/`; проверять наличие актуального токена по masked suffix/hash, не выводить полный token.
9. Проверить foreground/background notification/data messages, notification permission на Android 13+, обработку token refresh, logout и двух устройств. Console notification test не проверяет полностью data-only command handler.
10. Сопоставить серверный message id, device receipt, command ACK. Успешный `messaging.send` означает принятие FCM, а не факт выполнения команды на устройстве.
11. Ошибки SenderIdMismatch/invalid credentials/project mismatch диагностировать по project_id и IAM. Unregistered token удалять/помечать invalid после исправления кода. На Force stop обещать доставку нельзя.

Инструкции по [FCM Flutter background handling](https://firebase.google.com/docs/cloud-messaging/flutter/receive-messages) учитывать отдельно от Android разрешения на микрофон.

## D. Django / Server: переменные, которые код действительно читает

Источник: `Baby-locator-backend/config/settings.py`. Пример находится в корне workspace, а backend автоматически ищет свою `.env` через python-dotenv; путь файла и механизм загрузки должны быть явно согласованы с systemd/WSGI. Не копировать шаблон без замены placeholders.

| ENV variable | Для чего нужна | Где получить значение | Обязательна? | Как проверить |
|---|---|---|---|---|
| DJANGO_SECRET_KEY | Django signing и текущая HMAC Lite схема | Криптографический генератор/secret manager | Да | Непустая, уникальная, не dev default; наличие проверять без печати |
| DJANGO_DEBUG | Tracebacks/dev media | `False` оператором | Да для prod | Effective settings bool false; не делать небезопасный вызов с выводом всех settings |
| IS_TEST | Анонимный общий premium test login | `False` для prod | Да | GET `/api/auth/test-mode/` false; POST test login 403 проверять в staging |
| DJANGO_ALLOWED_HOSTS | Разрешённые HTTP hosts | DNS API, comma-separated | Да | Без `*`; unknown Host отклоняется на ingress/app |
| DJANGO_DB_ENGINE | DB backend | `django.db.backends.postgresql` | Да | Effective engine, DB health |
| DJANGO_DB_NAME | Database name | DB operator | Да | Подключение service user, не админ |
| DJANGO_DB_USER | DB username | DB operator | Да | Least-privilege role |
| DJANGO_DB_PASSWORD | DB password | Secret manager / DB operator | Да | Connection succeeds, пароль не в logs |
| DJANGO_DB_HOST | DB hostname/socket | DB deployment | Да | DNS/network allowlist, private routing |
| DJANGO_DB_PORT | DB port | DB deployment, обычно 5432 | Да | Connection; не открывать публично без нужды |
| DJANGO_CORS_ALLOW_ALL_ORIGINS | Cross-origin доступ browser | `False` | Да для hardening | Не возвращать ACAO *; Flutter native не нуждается в CORS |
| DJANGO_CSRF_TRUSTED_ORIGINS | Admin/session CSRF trusted HTTPS origins | Фактические browser origins | Если browser admin/session | Admin login/CSRF; не путать с CORS |
| DJANGO_SECURE_SSL_REDIRECT | Redirect HTTP→HTTPS | `True` при корректном proxy | Да | HTTP 301/308, нет redirect loop |
| DJANGO_SECURE_HSTS_SECONDS | HSTS max age | Политика эксплуатации | Да после проверки HTTPS | Header и валидная TLS цепочка |
| DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS | HSTS всех subdomains | Решение владельца домена | Условно | Все поддомены поддерживают HTTPS до включения |
| DJANGO_SECURE_HSTS_PRELOAD | HSTS preload directive | Решение владельца домена | Условно | Не включать без readiness всех subdomains; header не подаёт preload заявку сам |
| GOOGLE_MAPS_ANDROID_API_KEY | Server config/maps fallback | Google Cloud Credentials | Если используется remote config/Android build fallback | Restricted key, Maps Android SDK enabled |
| GOOGLE_MAPS_API_KEY | Alias/fallback Maps | Google Cloud Credentials | Условно | Предпочитать platform-specific key |
| MAPS_API_KEY | Последний Maps alias | Google Cloud Credentials | Условно | Не задавать конфликтующие aliases |
| FIREBASE_SERVICE_ACCOUNT_KEY | Абсолютный путь Admin JSON | Secret file, Firebase/Cloud IAM | Да для FCM этого кода | Path exists/readable и project match, test delivery |
| REVENUECAT_PUBLIC_API_KEY_ANDROID | Public goog_ SDK key | RC Project → API keys → Android app | Да для платного Android | `/api/revenuecat/config/` и Dashboard equality |
| REVENUECAT_PUBLIC_API_KEY_IOS | iOS SDK public key | RC iOS app | Для iOS | Platform-specific prefix; не Android fallback |
| REVENUECAT_PUBLIC_API_KEY | Legacy fallback public key | RC выбранной платформы | Нет при отдельных keys | Избегать cross-platform fallback |
| REVENUECAT_ENTITLEMENT_ID | Entitlement name | RC Entitlements | Да | `family_security_pro` в Flutter и Dashboard |
| REVENUECAT_PREMIUM_PRODUCT_IDS | Допустимые exact store product/base-plan ids | Play catalog + RC imports | Да | Сверить реальные identifiers; убрать broad aliases после миграции кода |
| REVENUECAT_LIFETIME_PRODUCT_IDS | Lifetime grants | RC/Play one-time catalog | Только если реально продаются | Пусто, если lifetime не используется; обязательно исправить refund handling |
| REVENUECAT_WEBHOOK_AUTH_HEADER | Полная shared Authorization string | Сгенерировать и установить в RC webhook | Да | Нет/неверный header 401, правильный synthetic test проходит в staging |
| WEBRTC_STUN_URLS | STUN URLs | Собственный/разрешённый STUN | Для ICE | Endpoint отдаёт список, gathering srflx где доступно |
| WEBRTC_TURN_URLS | TURN URLs, transports | Оператор coturn | Да для надёжной работы через NAT | В endpoint есть TURN, forced relay проходит |
| WEBRTC_TURN_SECRET | coturn REST shared secret | Secret manager, тот же static-auth-secret | Да в рекомендуемом режиме | HMAC совпадает, allocation проходит, secret не отдаётся API |
| WEBRTC_TURN_USERNAME | Статический username | coturn operator | Только static mode | Не нужен одновременно с secret |
| WEBRTC_TURN_CREDENTIAL | Статический пароль | coturn operator/secret manager | Только static mode | Действует, ограничены quota/rotation |
| WEBRTC_TURN_TTL_SECONDS | TTL временных TURN credentials | Политика сессий, например 3600 | Да в secret mode | Expiry username в UTC, clock sync, не короче поддерживаемого сеанса |

Новые переменные вроде `REVENUECAT_SECRET_API_KEY`, `REVENUECAT_APP_ID`, environment allowlist, CORS allowlist, session TTL **ещё не реализованы** этим backend. Для reconciliation/validation их нужно добавить вместе с кодом. Простое добавление в .env сейчас ничего не изменит. `PYTHON_DOTENV_DISABLED` в audit harness — настройка инструмента проверки, не production requirement.

### Настройка сервера по шагам

1. Зафиксировать deployed SHA и backup БД/storage, проверить restore на изолированном стенде. Не импортировать production дамп на публичный dev сервер.
   Для Lite выбрать canonical `Baby-locator-backend`, а не неявно разворачивать `Baby-locator-lite/backend`: вложенная копия не содержит Lite token exchange и несовместима с собственным клиентом. Tracked bundled SQLite/media не использовать как production seed и не распространять как fixtures.
2. Подготовить отдельный Unix service user, virtualenv и поддерживаемые/исправленные pinned dependencies. Учитывать реальные результаты dependency audit, не обновлять вслепую все major versions.
3. Хранить ENV в защищённом файле/secret manager, исключить из Git/артефактов, назначить 0600. Приватный Firebase JSON не размещать в MEDIA/STATIC.
4. Применить миграции только после review PostgreSQL schema и исправления AppIcon drift. `check`, `check --deploy`, migration dry-run и тесты выполнять с production-like settings на staging.
5. Gunicorn bind на loopback/private socket. Reverse proxy должен перезаписывать Host/X-Forwarded-Proto доверенным значением; app port не открыт напрямую. Иначе текущий trust к forwarded headers небезопасен.
6. Настроить DNS, валидный TLS, redirect, secure cookies, HSTS после проверки. Проверить certificate renewal.
7. Ограничить доступ к admin (MFA на ingress/SSO/VPN по политике), auth endpoints rate limits и upload body limits. Текущий settings не умеет origin allowlist отдельной ENV: для cross-origin browser client понадобится код.
8. Медиа детей и chat/audio — private storage/authenticated download, не общий `location /media/ { alias ...; }`. Django DEBUG media route для production не подходит.
9. Если поддерживается HTTP PCM, перепроектировать общий broker прежде, чем запускать несколько workers. Старый пример `--workers 3 --timeout 0` не исправляет process-local memory и требует отдельных ограничений streams/квот.
10. Логи: correlation id, command/session id, redacted user id, webhook event id/status/reason, FCM error class, session stage, ICE candidate type и RTP stats. Не писать Authorization, purchase tokens, raw JSON keys, точную геолокацию и SDP целиком без обоснованного ограниченного debug mode.
11. Мониторинг: 5xx/403 Premium после purchase, ignored webhook/lag, FCM failures/invalid tokens, pending commands age, mic setup latency, relay allocation/bytes, session leaks. Срок хранения/доступ к логам определить заранее.
12. Прогнать `RELEASE_QA_CHECKLIST.md`, согласовать deploy/rollback отдельно. Не считать этот документ разрешением на изменение сервера.

### Геокодирование и внешние получатели координат

`LocationService` использует native geocoder, затем Nominatim, затем Google HTTP geocoder. Клиентский HTTP geocoder содержит отдельный public key, который не обязательно совпадает с Gradle Maps SDK key. Сверить назначение/restrictions каждого key, включённые API и quotas; Android-restricted Maps SDK key не следует автоматически считать подходящим для прямого REST geocoding. Публичный Nominatim не должен стать бесконтрольной production зависимостью: проверить текущие условия/нагрузку, caching/rate limit или выбрать контролируемый сервис. Реальный получатель lat/lng должен быть отражён в privacy data-flow и disclosures. Не помещать server-secret Maps key в APK.

По [официальной Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/) лимит публичного endpoint — 1 запрос/секунду суммарно для приложения, нужны identifying User-Agent/attribution/caching и возможность сменить сервис без обновления приложения; периодические запросы не являются подходящей масштабируемой основой. Текущий hardcoded mobile URL не даёт оперативной серверной смены и общего лимитера. Превышение лимита реальным production traffic не измерялось. Для координат детей отдельно учитывать запрет отправки personal/confidential material и выбрать соответствующий privacy архитектуре сервис.

## E. TURN / coturn

Полная установка, shared-secret auth, TLS/UDP/TCP/firewall и проверки — [WEBRTC_FIREBASE_TURN_CHECKLIST.md](WEBRTC_FIREBASE_TURN_CHECKLIST.md). HTTPS web hosting само по себе не предоставляет TURN; для PythonAnywhere или хостинга без произвольных relay ports нужен отдельный VPS или managed TURN.

## F. Release

До AAB: проверить Git SHA/dirty state, build defines, separate edition applicationIds, Play signing fingerprints, Firebase/Maps, target/Billing, disclosures/privacy/data safety, native 16 KB page compatibility, tests и миграции. Зафиксировать SHA-256, build tools/lockfiles и привязку к commit.

После публикации: установить именно из нужного Play track, проверить versionCode/package/signature, разрешённую тестовую покупку и restore, webhook→API, child consent→RTP через LTE, SOS и background location, все старые tracks и rollout errors. При отклонении сохранить точный текст Google и affected versionCodes; не исправлять только production track, если старые коды доступны в тестировании.
