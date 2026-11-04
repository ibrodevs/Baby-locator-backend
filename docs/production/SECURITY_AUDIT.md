# Security audit — Baby Locator

> Обновление 03.11.2026: этот документ сохраняет исходный аудит/чеклист до исправлений. Текущий статус — [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md), актуальные шаги и ключи — [PRODUCTION_START_HERE_RU.md](PRODUCTION_START_HERE_RU.md). Lite отложен по указанию владельца.

Дата: 03.11.2026. Статический анализ и локальные синтетические воспроизведения. Production pen-test, перебор invite codes, анонимный доступ к данным реальных детей, реальные платежи и изменение сервера не выполнялись.

## 1. Подтверждённые границы доверия, которые нарушены

| Приоритет / ID | Файл / строки | Доказательство и последствия | Требуемый контроль |
|---|---|---|---|
| P0 F01 | B subscriptions/views.py:39–68; accounts/authentication.py:12–59; subscriptions/services.py:31–55 | Header-only privilege mint; любой auth user получает Lite full access | Server-owned capability grants, scoped/expiring/revocable access, проверенная licensing policy |
| P1 F02 | B tracking/views.py:1394–1428 | Чужой Premium parent создаёт stop command для чужого child, локально 200 | Ownership по session+child, запрещённая команда не создаётся |
| P1 F03 | B tracking/views.py:141–156 | Child DELETE parent zone 204 | Child read-only; parent-only mutations |
| P1 F04–F06 | B subscriptions/services.py:31–55,80–152 | Expired boolean trusted; stale event overwrite; sandbox/app unchecked; lifetime refund/transfer incomplete | Central grant evaluation, expiry, environment/app, authoritative sync, dedupe/ordering |
| P1 F13 | B tracking/views.py:1394–1398; MonitorSession model | Stop блокируется после отзыва Premium; session lease отсутствует | Stop независимо от оплаты, actor ownership, TTL и local cutoff |
| P1 F18 | B accounts/views.py:328–383; models.py:75–81; serializers.py:79–81 | Reused 6-digit invite возвращает постоянный token; weak password, нет app throttles | Atomic single-use pairing, rotation/revoke, rate limit, secrets RNG, strong password policy |
| P1 F19 | B settings.py:27–36,86–94; services.py:58–63; accounts/views.py:480–518 | DEBUG/default secret/host wildcard; пустой webhook auth при DEBUG; test premium token если IS_TEST | Fail closed prod settings, test routes excluded, webhook secret mandatory |
| P1 F20 | B accounts/views.py:106–145,208–213; chat/models.py:25; subscriptions/models.py:17–28 | DB deletion не равно storage deletion; raw webhook payload сохраняется | Complete deletion service + retention/access controls |
| P1 F21 | B accounts/views.py:387–433 | Unescaped user names в HTML f-string | Autoescaping templates/format_html, CSP defense in depth |
| P1 F22 | Lite source manifests/Gradle | Нет monitoring metadata; default paid/Lite package одинаков | Separate verified identity для отдельных app, final merged manifest |
| P2 F23–F24 | M fcm_service.dart:283–307; subscription_service.dart:372–405,573–609 | Duplicate token listeners, account state cleanup недостаточен | Per-device registration, revoke/logout cleanup, serialized session changes |
| P1 F32–F33 | Lite background_command_service.dart:27–45; blocking_accessibility_config.xml:3–6 | Постоянный microphone tracking FGS и window-content capability вопреки общей policy | Разделение FGS, минимальные permissions, фактические consent/declarations |
| P1 F34–F35 | Lite backend/subscriptions/urls.py:1–8; backend/db.sqlite3 | Старый bundled API несовместим с Lite; tracked DB с tokens/locations/messages | Canonical backend и contract tests; sensitive data/history cleanup |

Полные причины, последствия и acceptance tests каждой ошибки приведены в `BABY_LOCATOR_FULL_AUDIT.md`, часть 2. Все номера B/M относятся к полным путям, указанным там.

## 2. Безопасная модель Lite и платных лицензий

HTTP-заголовок, User-Agent, package name в JSON, public SDK key и секрет, встроенный в APK, не являются доказательством официального приложения или права на Premium. HMAC подпись полезна только если сервер выдаёт grant на правильном основании.

Предлагаемая модель:

1. User/Family — владелец данных. DeviceInstallation — конкретная установка, edition/package/certificate attestation, notification token и revocation state. Эти сущности не подменяют друг друга.
2. CapabilityGrant — server record: owner/family, источник (verified subscription, явно разрешённый бесплатный Lite tier, admin grant), scopes, valid_until, revoked_at, audit reference. Все endpoint читают одну policy.
3. Если Lite действительно бесплатно получает тот же набор функций, это должно быть осознанной серверной продуктовой политикой. Невозможно сохранить строгую платную эксклюзивность того же аккаунта/данных одним названием клиента. Определить ограничения тарифа/семьи/ресурсов, не маскировать их заголовком.
4. Если official-app attestation необходима, backend проверяет Play Integrity server-side: ожидаемые package/certificate/version, app recognition/licensing по требованиям продукта, request hash/nonce, freshness и replay. Attestation не подтверждает subscription и не заменяет family authorization.
5. Access token — короткий срок, audience/scope/session binding и server revocation. Refresh/device credential хранить через Android Keystore-backed secure storage. Не полагаться на SharedPreferences как секретное хранилище.
6. Paid subscription подтверждает серверный RevenueCat API/store integration. Клиент не присылает авторитетный `is_premium` или expiry. Вход ребёнка наследует только разрешённые parent grants, не новую покупку ребёнка.
7. Отдельно проверить downgrade, account switch, восстановление покупки и перенос между app edition. Active mic Stop не должен требовать оплаченного grant.

## 3. Секреты и репозитории

Факты проверки:

- `.env` backend и mobile keystore paths не найдены среди tracked sensitive path names трёх локальных репозиториев; `.env.pythonanywhere.example` отслеживается как шаблон.
- Локально в workspace есть Firebase service account JSON и signing-related файлы. Их значения в отчёт не копировались. Наличие локального private credential не доказывает утечку в Git или корректную установку на production.
- У локального `firebase-service-account.json` при осмотре mode 0644: доступ на чтение шире владельца. Рекомендуются 0600 и secret storage с узкими правами; права файла в аудите не менялись.
- Поиск `BEGIN ... PRIVATE KEY` и `"type":"service_account"` в текущих tracked текстовых файлах трёх репозиториев (исключая vendored `.venv`/bytecode) не нашёл совпадений. Результат: `audit_evidence/secret-scan-summary.json`.
- Это ограниченный pattern scan текущего дерева: Git history, remote branches, GitHub Actions artifacts/logs, binary archives, окружения CI и все форматы credentials не просканированы. Отсутствие совпадений не означает отсутствие всех секретов.
- RevenueCat `goog_` SDK key, Firebase client config и Android Maps key — публичные клиентские идентификаторы. Их нельзя считать server secrets. Maps key требует restrictions по package/Play signing SHA и API, а не только сокрытия в .env.
- В B `.gitignore` нет явного запрета `firebase-service-account.json`; если положить его в backend default path, появляется риск случайного добавления. Root workspace тоже не имеет общей проверенной политики исключений для credentials.
- **6099 файлов `.venv/` уже отслеживаются Git**, несмотря на `.gitignore`. Порядка 508 tracked `.pyc` изменились при запуске проверок; восстановлены только эти автоматически изменённые bytecode-файлы, исходники не откатывались. Это проблема репозитория: `.gitignore` не удаляет уже tracked файлы.

Действия отдельной веткой: исключить `.venv`, `__pycache__`, credential files и signing secrets из index, оставить исходники/lockfiles; просканировать историю и CI artifacts. Не удалять историю или rotate все ключи автоматически без анализа фактической утечки. Если private credential действительно публиковался — revoke/rotate и incident review; простое удаление файла из последнего commit недостаточно.

CI/CD: secret manager/OIDC где применимо, ограниченные GitHub/Cloud роли, environment approvals для production по политике владельца, masked variables, secret scanning, protected artifacts. Android signing password не передавать через Dart defines. App signing/upload keys хранить раздельно и учитывать Play App Signing.

**Дополнение после полного clone Lite:** `Baby-locator-lite/backend/db.sqlite3` отслеживается Git и содержит 2 пользователей, 2 DRF token, 14 геопозиций, 4 chat messages; рядом 3 tracked media files и 4599 файлов вложенного venv. Проверка была read-only и выводила только counts/schema, не значения. Нельзя считать эти данные production или тестовыми без подтверждения. Происхождение/валидность tokens установить оператору; при реальной утечке отозвать действующие credentials и согласовать очистку истории. Ранее отрицательный private-key pattern scan трёх репозиториев не охватывает токены внутри этой SQLite и не отменяет найденный риск.

## 4. Dependency audit и воспроизводимость

Фактические команды:

- `pip check`: No broken requirements found в существующем Python 3.12.12 venv.
- `uvx pip-audit -r requirements.txt ...`: **не завершил аудит**, dependency resolution использовал Python 3.13 и упал на сборке Pillow 10.3.0 (`KeyError '__version__'`). Лог `audit_evidence/pip-audit.log`. Это не доказательство сбоя production Python 3.12.
- Повторный аудит **установленных pinned name==version без resolver**: `pip-audit --no-deps --disable-pip -r audit_evidence/installed-python-requirements.txt`; найдено **131 advisory в 5 пакетах**. JSON `pip-audit-installed.json`.
- Отдельный аудит exact `==` pins из requirements: **114 advisory в 3 пакетах**; диапазоны и транзитивные зависимости этим запуском не разрешались. JSON `pip-audit-pins.json`.

| Пакет | requirements pin | Установлено | Advisory installed / pin scan |
|---|---|---|---|
| Django | 5.0.6 | 5.0.6 | 43 / 43 |
| djangorestframework | 3.15.2 | 3.15.2 | 5 / 5 |
| Pillow | 10.3.0 | **12.2.0** | 64 / 66 |
| pip | Не pinned runtime requirement | 25.3 | 10 / не сканировался как direct pin |
| sqlparse | Транзитивная | 0.5.5 | 9 / не входил в direct-pin scan |

Числа — результаты базы advisories в момент запуска, не число реально эксплуатируемых уязвимостей приложения. Advisory IDs, aliases, descriptions и fix_versions сохранены в JSON; применимость к используемым Django API/native decoder paths надо триажить. Пример подтверждённого устаревшего pin: Django 5.0.6 имеет scanner hits CVE-2024-39330/39329/38875/39614; смотреть [официальные Django security releases](https://docs.djangoproject.com/en/5.0/releases/5.0.7/) и поддерживаемые серии на [Django downloads](https://www.djangoproject.com/download/).

**Установленный Pillow не соответствует requirements**, поэтому успешные tests не описывают чистую установку requirements полностью. Сформировать воспроизводимый lock с hashes и поддерживаемой версией Python; обновить Django на поддерживаемую patched ветку, DRF/Pillow/transitives — до версий, закрывающих релевантные advisories, с тестами загрузки изображений, auth, ORM, migrations и API. Не выбирать минимальную fix version одного advisory как универсально безопасную версию.

Также в основном локальном venv отсутствуют python-dotenv, gunicorn и psycopg2-binary, указанные в requirements. `pip check` этого не выявляет: он проверяет зависимости установленных distributions, а не полноту requirements проекта. Основной settings скрывает dotenv ImportError и игнорирует .env; embedded Lite settings импортирует dotenv безусловно и падает до check/test. Успешные SQLite tests не верифицируют Gunicorn/PostgreSQL deployment.

Flutter `pub outdated`: 82 upgradable locked dependencies и 29 constrained older than resolvable; `pub get` сообщает 115 newer incompatible with constraints. Это разные категории, их не суммировать. Отдельного полного Flutter/native CVE scan не было. Android dependency graph в сохранённом merger log включает Billing 8.3.0; актуальный final AAB/native .so нужны для полноценного SBOM/16 KB compatibility scan.

## 5. API hardening и хранение данных

- Семейную связь проверять на каждом data/command endpoint, включая stop, list, upload/download и admin actions. Токен сессии не заменяет actor ownership. Signaling send/poll сейчас проверяют membership, это полезная существующая защита; входящие payload type/size и допустимые направления надо дополнительно валидировать.
- Добавить auth/invite/subscription sync/TURN quotas, request body/file limits, pagination и bounded retention. Chat messages сейчас отдаются целиком без pagination (`chat/views.py:51–60`); uploads обходятся без явного size/type validator (`63–88`).
- Private chat/audio/media не раздавать общим публичным nginx alias. В DEBUG Django static media открыты; production nginx неизвестен. Использовать authenticated download или короткие signed URLs с авторизацией перед выдачей, private bucket и отдельный media origin без исполнения HTML.
- `AroundAudioUploadView` сохраняет audio FileField и принимает session token как строку без сверки с разрешённой recording session (`tracking/views.py:1130–1151`). Нужны active session membership/expiry, retention и quota. Существование legacy upload endpoint учитывается в Privacy Policy, даже если основной UI уже WebRTC.
- SharedPreferences auth token: риск extraction/backups/device compromise; внедрить secure storage и серверное revoke. Текущий logout удаляет только local token (`api_client.dart`, logout); endpoint серверного logout отсутствует, DRF tokens не имеют срока.
- TLS/CSRF/CORS различать. Token-auth native mobile не требует CORS; browser admin требует CSRF. Заголовки forwarded доверять только своему proxy, app listener закрыть от внешних запросов.
- Raw webhook payload, координаты, usage stats, чаты и детские профили — sensitive data. Минимизировать поля/логи, определить retention и доступ операторов, шифрование backups/storage и процедуры удаления.
- GPS fallback теряет исходное время fix, а API не валидирует диапазоны координат/battery (F29/F30). Исправить freshness и input validation; дополнительный synthetic test принимает lat=1234/lng=9999/battery=900 с HTTP 201.
- Nominatim получает координаты в geocoding fallback (`location_service.dart:279–292`), но не указан в перечне сторонних сервисов Privacy Policy (F31). Проверить реальный data-flow/disclosure; не объявлять список processors полным по одному перечню SDK.

Дополнительно локально воспроизведены sandbox/wrong-app webhook → processed Premium, lifetime refund → true и unescaped HTML в invite response. Лог: `audit_evidence/backend-additional-reproductions.log`. Ни один из этих запросов не отправлялся в production.

## 6. Google Play / privacy проверка

Подтверждено кодом: disclosure widgets location/mic/accessibility существуют, основной source и повторно проверенный AAB 23 содержат `isMonitoringTool=child_monitoring`. Это не равно одобрению Google.

Lite использует общую Privacy Policy с обещанием `canRetrieveWindowContent=false`, но его XML устанавливает true; Kotlin использует window roots для packageName. Это подтверждённое несоответствие capability и policy, не доказательство чтения текста переписки. Исправить минимизацию/декларации до выпуска Lite.

Нужны ручные проверки: monitoring marketing/use case, пользовательское уведомление и согласие, microphone FGS declaration, background location prominent disclosure/video, Accessibility permission declaration/usage, Data safety по реальному SDK/data flow, account deletion URL и фактическое удаление, безопасные subscription terms и localized prices, eligibility full-screen SOS. Lite source требует monitoring metadata отдельно.

Нельзя обходить while-in-use ограничения, скрывать запись, убирать privacy indicator или обещать mic после Force stop. WebRTC и HTTP capture подчиняются одинаковым правилам устройства.

## 7. Минимальные security regression gates

- [ ] Free paid-client token + forged Lite header не получает paid capabilities.
- [ ] Любой другой parent/child не читает данные/не отправляет команды чужой семье; stop ownership проверяется отдельно.
- [ ] Child не меняет parent safe zones; family read permissions не повышают mutation rights.
- [ ] Expired/revoked/refunded entitlement блокируется; stop остаётся доступен владельцу.
- [ ] Sandbox/wrong app/old/duplicate/concurrent webhook не повышают и не портят production grants.
- [ ] Invite single-use, concurrent/replayed pairing запрещены; re-pair отзывает старый token.
- [ ] HTML в display name безопасно экранирован на invite landing.
- [ ] Delete account/child очищает DB/storage/raw event PII в пределах заявленной retention.
- [ ] Private test file не доступен анонимно по media URL.
- [ ] Production startup без secret/host/webhook settings не допускается; test login отключён.
- [ ] Из репозитория исключены generated environments, credentials; dependency advisories разобраны и исправлены либо обоснованно исключены.

Подробный release QA — `RELEASE_QA_CHECKLIST.md`. Полный pentest и юридическая проверка privacy/детских данных не заменены этим аудитом.
