# Baby Locator: что сделать для запуска после исправлений

Дата: 3 ноября 2026. Относится к обновлённому платному приложению и основному Django backend. Lite по вашему указанию не изменялся. Изменения пока локальные: сервер, магазины, Firebase и RevenueCat не перенастраивались. Начните с этого файла; результат работы и ограничения — в [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md).

## 1. Сначала зафиксируйте фактический production

1. В Google Play Console откройте опубликованный релиз приложения `com.company.familysecurity`. Запишите versionCode/versionName, активные треки, Play App Signing SHA-1/SHA-256 и upload certificate. Локальные AAB 22/23 не доказывают, что именно они опубликованы.
2. На сервере запишите текущий commit, версию Python, `pip freeze`, используемые переменные окружения (только имена, не секреты), схему запуска, пути БД и media. Не отправляйте содержимое `.env`, JSON и keystore в чат.
3. Сделайте резервную копию PostgreSQL и media в закрытое хранилище; проверьте восстановление на отдельной базе. Сохраните предыдущий код и env.
4. Подготовьте staging с отдельной БД, Redis, API-доменом и синтетическими семьями. Сначала выполняйте следующие шаги там.
5. Уточните, подключён ли Lite к этому же backend. Сервер больше не выдаёт Premium по заголовку `X-App-Edition`. Клиент Lite остаётся прежним, но его доступ на общем сервере может измениться. Не выкатывайте общий backend для пользователей Lite, пока не принято отдельное решение. Серверная команда `grant_lite_access` существует для явных лицензий, но массовые лицензии автоматически не выдавались.

## 2. Какие ключи нужны и где они должны находиться

Полный актуальный шаблон: [.env.production.example](.env.production.example), копия внутри backend: `Baby-locator-backend/.env.production.example`. Все `<...>` замените. Реальный env не коммитьте.

| Переменная / файл | Откуда взять | Где хранить |
|---|---|---|
| `DJANGO_SECRET_KEY` | Новый криптографически случайный секрет ≥50 символов | Только серверный env |
| `DJANGO_DB_PASSWORD` | Учётная запись вашей PostgreSQL | Только серверный env |
| `REDIS_URL`, `LIVE_AUDIO_REDIS_URL` | Закрытый Redis, пароль/ACL, разные logical DB | Только серверный env |
| `REVENUECAT_PUBLIC_API_KEY_ANDROID` | RevenueCat → соответствующее Android App → SDK key `goog_…` | Серверный public config; допустим в клиенте |
| `REVENUECAT_PUBLIC_API_KEY_IOS` | Отдельное iOS App → `appl_…` | Пусто, пока iOS не настроен |
| `REVENUECAT_SECRET_API_KEY` | RevenueCat → API keys, secret API v1 subscriber read/delete | Только сервер; никогда Flutter/public config |
| `REVENUECAT_APP_IDS` | Поле `app_id` реального webhook нужного RevenueCat App | Серверный env; это не Android package name и не project ID |
| `REVENUECAT_WEBHOOK_AUTH_HEADER` | Отдельный случайный секрет; полная строка `Bearer …` | Одинаково в серверном env и Authorization header webhook в Dashboard |
| `REVENUECAT_ENTITLEMENT_ID` | RevenueCat entitlement; ожидаем `family_security_pro` | Сервер и каталог RevenueCat должны совпадать |
| `REVENUECAT_PREMIUM_PRODUCT_IDS` | Реальные идентификаторы продуктов/базовых планов | Сервер; не выдумывать `monthly`/`yearly` |
| `FIREBASE_SERVICE_ACCOUNT_KEY` | Firebase/Google Cloud service account для FCM | Путь к закрытому JSON на сервере |
| `FIREBASE_EXPECTED_PROJECT_ID` | Firebase project Android приложения | В текущем Android config: `kid-security-994a0`; перепроверьте перед выпуском |
| `google-services.json` | Firebase → Android app с точным package | Android проект; это клиентская конфигурация, не Admin private key |
| Google Play service account JSON | Google Cloud + доступ к приложению в Play Console | Загружается в RevenueCat для интеграции Play; Django он не нужен |
| `WEBRTC_TURN_SECRET` | Ваш случайный coturn `static-auth-secret` | Совпадает только на backend и TURN; не Flutter |
| `GOOGLE_MAPS_ANDROID_API_KEY` | Google Cloud, включён Maps SDK for Android | Клиентский ключ, ограничения package + Play signing SHA-1 |
| `GOOGLE_GEOCODING_API_KEY` | Отдельный ключ Geocoding API | Только сервер, ограничения API + IP сервера; можно оставить пустым |
| Upload keystore/password/alias | Ваш существующий ключ загрузки Play | Защищённое локальное/CI хранилище, не Dart defines и не Git |

Не заменяйте существующий upload key случайным новым: обновление Play должно подписываться разрешённым ключом. Если private keys/passwords когда-либо попадали в Git или публичный доступ, перевыпустите их у провайдера; удаление файла из текущего дерева не очищает историю. Существующие пользовательские секреты автоматически не менялись.

## 3. Настройка backend на VPS

Примеры рассчитаны на Linux VPS с systemd, Nginx, PostgreSQL и Python 3.12. Для PythonAnywhere см. отдельный пункт ниже. Сначала используйте staging.

1. Создайте отдельного системного пользователя `baby-locator`; разместите **основной** backend в `/srv/baby-locator/backend`. Каталоги media и staticfiles должны быть доступны этому пользователю на запись, а код и venv — на чтение/исполнение. Не используйте backend, вложенный в Lite.
2. Установите Python 3.12 с venv/dev headers, C build tools и libpq development headers (для сборки psycopg2). Создайте venv `/srv/baby-locator/venv` и установите зависимости:

```sh
python3.12 -m venv /srv/baby-locator/venv
/srv/baby-locator/venv/bin/python -m pip install --require-hashes -r /srv/baby-locator/backend/requirements.txt
```

3. Создайте PostgreSQL database/role с доступом только к нужной базе. Не открывайте PostgreSQL и Redis в интернет. Redis нужен для общих throttles/cache и совместимого HTTP-аудио; используйте поддерживаемую исправленную версию, private bind, пароль/ACL, выключите persistence для отдельного временного аудиохранилища. Не допускайте попадания аудиобуфера в Redis snapshots/backups.
4. Создайте `/etc/baby-locator/backend.env` из полного шаблона и `/etc/baby-locator/firebase-admin.json`. Владелец `baby-locator`, права файлов `600`, каталога `700`. Укажите все значения из таблицы, `DJANGO_DEBUG=False`, `IS_TEST=False`, конкретные host/origin. `PYTHON_DOTENV_DISABLED=1` исключает незаметное чтение старого checkout `.env`.
5. Для management-команд используйте тот же env, что и systemd:

```sh
cd /srv/baby-locator/backend
sudo -u baby-locator /srv/baby-locator/venv/bin/python deploy/manage-production.py check
sudo -u baby-locator /srv/baby-locator/venv/bin/python deploy/manage-production.py migrate --plan
sudo -u baby-locator /srv/baby-locator/venv/bin/python deploy/manage-production.py production_check
```

`production_check` проверяет обязательную конфигурацию, JSON metadata/права, DB/Redis connectivity. Он **не проверяет** действительность всех внешних ключей, покупки или доставку push.

6. В согласованное окно остановите старый backend, выполните резервное копирование и миграции:

```sh
sudo systemctl stop baby-locator
sudo -u baby-locator /srv/baby-locator/venv/bin/python deploy/manage-production.py migrate
sudo -u baby-locator /srv/baby-locator/venv/bin/python deploy/manage-production.py collectstatic --noinput
sudo -u baby-locator /srv/baby-locator/venv/bin/python deploy/manage-production.py check --deploy
```

Новая migration закрывает прежние monitoring sessions и старые незавершённые команды. Не рассчитывайте продолжить активную аудиосессию после обновления. Для отката надёжнее восстановить согласованные backup БД + media + предыдущий код; обратные миграции не воссоздадут закрытые сессии и удалённые данные.

7. Установите `deploy/baby-locator.service` в `/etc/systemd/system/`. Сервис запускает Gunicorn из своего venv, loopback:8000, несколько workers/threads и preflight. Настройте DNS и HTTPS. Адаптируйте `deploy/nginx.conf.example`, выполните `nginx -t`, затем reload. Порт Gunicorn должен быть закрыт снаружи. `/media/` проксируется в Django с авторизацией; **не добавляйте публичный alias media**. Передаваемые Nginx заголовки должны перезаписывать клиентские `X-Forwarded-*`.
8. Установите четыре файла `deploy/baby-locator-{maintenance,reconcile}.{service,timer}` в `/etc/systemd/system/`. Просмотрите `run-maintenance.sh`: он повторяет webhook/provider deletion и удаляет старые (>1 часа) файлы без ссылок в БД. Сначала отдельно выполните `cleanup_media` без `--apply` и проверьте корректность MEDIA_ROOT/БД.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now baby-locator
sudo systemctl enable --now baby-locator-maintenance.timer baby-locator-reconcile.timer
sudo systemctl status baby-locator
sudo journalctl -u baby-locator --since '10 minutes ago'
```

9. Настройте alerts на failed systemd jobs, HTTP 5xx, Redis/DB unavailable, backlog provider deletion/pending webhook и место на диске. Для большой базы reconciliation нужно распределить по расписанию/лимитам RevenueCat; текущая команда проходит родителей последовательно.
10. Определите срок хранения backup (например, 30 дней), автоматическое удаление старых копий и процедуру повторного удаления аккаунтов после восстановления backup. Только после проверки этого процесса обещайте конкретный срок на сайте. Настройте безопасные логи без Authorization, body и query strings. Logout сейчас отзывает общий токен аккаунта и регистрации FCM всех его установок; это выход со всех устройств.

### Если сервер остаётся на PythonAnywhere

Не копируйте systemd/Nginx команды в его консоль. Обновите код и отдельный venv, установите hashed requirements, задайте env до импорта Django в WSGI и scheduled tasks, примените migrations/collectstatic, затем Reload Web App. Проверьте доступ вашего тарифа к PostgreSQL, private shared Redis и исходящему HTTPS Google/RevenueCat. Запускайте аналогичные maintenance/reconciliation tasks с тем же env. Удалите публичное static mapping для `/media/`. Основной звук использует WebRTC и внешний TURN; legacy HTTP streaming зависит также от ограничений WSGI/proxy платформы. Если платформа не обеспечивает нужные Redis/таймауты/сеть, используйте VPS по примеру выше.

## 4. Покупки: Google Play → RevenueCat → Django

1. Google Play Console: убедитесь, что открыто приложение `com.company.familysecurity`; сверьте package из нового AAB. Включите/проверьте подписки, активные base plans, цены, страны и доступность продуктов. Запишите точные ID. Доступность планов и интерфейс Console проверяйте по актуальному кабинету.
2. Создайте/проверьте Google service account для RevenueCat, включите Google Play Android Developer API и выдайте доступ к нужному Play app и необходимым subscription/order данным по [официальной инструкции RevenueCat](https://www.revenuecat.com/docs/service-credentials/creating-play-service-credentials). Загрузите JSON **в RevenueCat**, дождитесь успешной проверки credentials. Firebase Admin JSON не заменяет Play credentials.
3. RevenueCat: нужный Project → Android App с тем же package → импортируйте реальные продукты/base plans. Создайте entitlement `family_security_pro`, прикрепите к нему оба продукта. Создайте Offering, сделайте его Current и добавьте monthly/annual packages с правильными продуктами. Пустой Current Offering означает, что paywall нечего продавать.
4. Скопируйте Android SDK `goog_…` в `REVENUECAT_PUBLIC_API_KEY_ANDROID`, server key в `REVENUECAT_SECRET_API_KEY`; задайте entitlement/product IDs и `REVENUECAT_APP_IDS`. При регистрации приложения RevenueCat App User ID должен совпасть с **числовым ID родителя Django в виде строки**. У ребёнка используется ID родителя, покупка выполняется родителем.
5. RevenueCat → Integrations → Webhooks: URL `https://<API_HOST>/api/revenuecat/webhook/`, Authorization header — **точно** значение `REVENUECAT_WEBHOOK_AUTH_HEADER`. Выберите нужные приложения и события жизненного цикла, включая transfer/refund/expiration. Тестовое событие должно вернуть 200; TEST не выдаёт Premium. SANDBOX по умолчанию игнорируется. О формате и повторах: [RevenueCat webhooks](https://www.revenuecat.com/docs/integrations/webhooks).
6. Для staging включите `REVENUECAT_ALLOWED_ENVIRONMENTS=PRODUCTION,SANDBOX`. На production оставьте `PRODUCTION`; если тестируете sandbox прямо там, ограничьте тестовое окно и затем верните значение. Тестовые покупки не должны незаметно становиться постоянным production-доступом.
7. В Play Console добавьте license testers и пользователей internal testing; tester должен принять opt-in и установить **сборку из Google Play** под тем же Google-аккаунтом. Не проверяйте магазинную цепочку только sideload debug APK. См. [Google Play Billing testing](https://developer.android.com/google/play/billing/test).
8. Купите тестовый monthly plan. Сверьте: Play test transaction → RevenueCat Customer с правильным ID → активный entitlement → webhook 200 → `/api/revenuecat/sync/` 200 → профиль `is_premium=true` → платный API открывается. Не передавайте клиентский `is_premium` как доказательство покупки: backend сам читает RevenueCat.
9. Проверьте annual, отмену пользователем (доступ до expiry), окончание срока, billing grace, refund/revoke, restore, дубли/перестановку webhook и смену аккаунта. Правила переноса restore в RevenueCat выберите явно под продукт; проверьте, кому достаётся покупка при входе другого родителя. Официально: [restore behavior](https://www.revenuecat.com/docs/projects/restore-behavior), [grace periods](https://www.revenuecat.com/docs/subscription-guidance/how-grace-periods-work).
10. При задержке backend paywall сообщает об ожидающей проверке и позволяет повторить. Ошибка/пустой Offering требует проверки ключа, package, Current Offering, Play credentials, состояния планов и страны. Платёж успешен в SDK, но 503 sync — проверьте **серверный** ключ и исходящий HTTPS; 403 — ID/entitlement/expiry/environment/app filter. Не предлагайте пользователю платить повторно ради синхронизации.

## 5. Firebase, карты и TURN

1. Firebase: Android package должен совпасть с Play. Обновите `google-services.json` из нужного проекта при необходимости. На сервере JSON service account того же проекта, путь/права по таблице, FCM HTTP v1 API включён, service account имеет право отправлять сообщения. Проверьте исходящий HTTPS сервера. Ошибочный или отозванный JSON не исправляется одним переименованием файла.
2. Android 13+: разрешите уведомления на обоих тестовых устройствах. Войдите/перезапустите приложение, проверьте регистрацию каждой установки и доставку на двух устройствах одного аккаунта. Unregistered tokens удаляются backend. FCM принят провайдером ≠ гарантированно доставлен устройству.
3. Maps: включите Maps SDK for Android и billing Google Cloud; ограничьте ключ package + **Play App Signing** SHA-1, отдельно debug/upload если нужны тесты. Для reverse geocoding включите Geocoding API у отдельного server key, ограничьте его IP/API; без него API адреса вернёт unavailable, координаты продолжают работать.
4. TURN: используйте поддерживаемый coturn, публичный DNS/IP, действующий TLS certificate, `use-auth-secret` и одинаковый `static-auth-secret` с `WEBRTC_TURN_SECRET`. Откройте 3478 UDP/TCP, 5349 TCP и ограниченный configured relay UDP range (например, 49160–49200). За NAT настройте external IP и firewall. Запретите relay к внутренним/loopback/multicast адресам и мониторьте злоупотребления.
5. Задайте URL из шаблона. Проверка `/api/webrtc/ice-servers/` должна возвращать краткоживущие credentials авторизованной Premium-семье. Не публикуйте shared secret в приложении.
6. Реальный тест: два разных интернета (Wi-Fi и LTE), затем принудительный relay в тестовой сборке. На телефоне ребёнка появляется приглашение; ребёнок открывает приложение и нажимает подтверждение; только после этого разрешается микрофон/FGS. До согласия звука нет. Проверьте Stop у родителя, ребёнка и в системном уведомлении, обрыв сети, expiry 10 минут, повторный запрос, заблокированный экран и смену аккаунта.
7. Отключённый/заблокированный телефон не обязан запускать микрофон по push. Это приглашение к видимому подтверждению. Не пытайтесь вернуть скрытый автозапуск: Android ограничивает microphone foreground services; см. [Android restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start).

## 6. Сборка и выпуск платного приложения

1. Убедитесь, что API_BASE указывает на ваш HTTPS backend и ключ Maps попадает в Android manifest. Приватных RC/Firebase/TURN ключей в Dart defines быть не должно.
2. Проверьте `flutter analyze` и `flutter test`. Согласуйте **новый неиспользованный** versionCode с Console; локальные текущие `1.0.7+23` сохранены, номер следующего релиза автоматически не назначался.
3. Запишите согласованную версию в `pubspec.yaml` (`version: NAME+CODE`), чтобы проверка manifest сравнивала артефакт с той же версией. С существующей upload signing configuration выполните:

```sh
GOOGLE_MAPS_ANDROID_API_KEY=<RESTRICTED_ANDROID_PUBLIC_KEY> flutter build appbundle --release --build-name=<NEW_VERSION_NAME> --build-number=<UNUSED_VERSION_CODE> --dart-define=API_BASE=https://<API_HOST>
```

4. Проверьте подпись, package, versionCode, targetSdk и merged monitoring declaration у **финального AAB**. Локально проверенная debug APK не является финальным магазинным артефактом. Выложите сначала internal testing, установите обновление на оба устройства из Play и выполните [RELEASE_QA_CHECKLIST.md](RELEASE_QA_CHECKLIST.md) с поправками из отчёта.
5. Обновляйте платные родительский и детский клиенты совместно: старый child не поддерживает новый consent handshake и приватные media headers. В backend пока нет обязательного min-version gate; организуйте уведомление/контроль обновления, не обещайте старому клиенту работу нового аудио.
6. Разместите исправленные страницы privacy/delete на реальном web hosting только после соответствующей настройки backend и backup. Проверьте ссылки в Play Store, Data safety, prominent disclosure, permissions и reviewer access по фактическому поведению. Reviewer accounts создавайте с уникальными секретами через защищённый env; встроенные тестовые пароли не использовать.
7. Перед rollout нужны: успешная реальная тестовая покупка+restore, webhook/sync, аудио через TURN, остановка/отказ, GPS, private media, удаление аккаунта/provider queue и мониторинг. После internal → closed testing → постепенный production rollout с наблюдением ошибок.

## 7. Что остаётся сделать вам

- Выбрать/подготовить сервер и домены; заполнить реальные ключи, настроить БД/Redis/HTTPS/TURN и резервные копии.
- Настроить каталог и credentials Play/RevenueCat, webhook и тестеров; подтвердить покупки на Play-installed сборке.
- Согласовать влияние общей backend-авторизации на Lite, не меняя его клиент сейчас.
- Выпустить согласованный платный parent/child update с новым versionCode, проверить два реальных телефона и разместить сайт.

Секреты из аккаунтов сервисов нельзя корректно сгенерировать вместо вас локальным исправлением кода. До выполнения внешних шагов и реальных тестов статус — «локально исправлено и проверено, production ещё не подтверждён».
