# Google Play → RevenueCat → Django → Premium

> Обновление 03.11.2026: этот документ сохраняет исходный аудит/чеклист до исправлений. Текущий статус — [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md), актуальные шаги и ключи — [PRODUCTION_START_HERE_RU.md](PRODUCTION_START_HERE_RU.md). Lite отложен по указанию владельца.

Дата проверки: 03.11.2026. Реальных покупок аудит не выполнял. Все дальнейшие финансовые проверки проводить license tester/test payment method в разрешённом тестовом окружении. Не создавать новые продукты взамен действующих до сверки существующих подписчиков.

## 1. Карта идентификаторов по реальному коду

| Уровень | Что найдено | Где | Что подтвердить вручную |
|---|---|---|---|
| Android app | default `com.company.familysecurity` | M android/app/build.gradle.kts:137–144,197–203 | Effective ID final AAB и выбранное приложение Play/RC |
| RevenueCat Android public key | Непустой `goog_` default; remote/cache имеет приоритет | M subscription_service.dart:14–24,94–161 | Ровно key нужного Android App внутри нужного RC Project |
| Backend public config | android/ios/fallback keys и entitlement/products | B subscriptions/views.py:13–35 | Production GET не означает, что Dashboard mapping верен |
| Entitlement | `family_security_pro` | M subscription_service.dart:26,168–169; B settings.py:179–182 | Case-sensitive ID в RC; products прикреплены |
| Offering | `default`, иначе `offerings.current` | M subscription_service.dart:27,238–239,409–431 | Есть default или выбран правильный current; targeting/placement не исключает тестера |
| Monthly lookup | `monthly` и iOS long ID; fallback Package.monthly | M subscription_service.dart:28–40,241–247 | Product ID и basePlanId нельзя считать одним и тем же |
| Yearly lookup | `yearly` и iOS long ID; fallback Package.annual | Там же | Реальный годовой продукт/план и package type |
| Product aliases | Match по любому сегменту `:` | M subscription_service.dart:44–55; B services.py:184–204 | Это permissive fallback, а не доказательство соответствия каталога |
| Backend product allowlist | monthly/yearly/lifetime + iOS long IDs | B settings.py:183–196 | Не принимать чужой продукт только из-за base plan alias |
| App User ID | строка Django user.id | M subscription_service.dart:613–619; B services.py:206–239 | Один реальный пользователь в обоих системах; child права принадлежат parent |
| Webhook | `/api/revenuecat/webhook/` | B subscriptions/urls.py | Полный Authorization header, правильное приложение/environment, успешные attempts |

**`family_security_pro` в коде — entitlement.** Он может также оказаться subscription product ID в реальном Play catalog, но это не доказано. `default` — offering, `$rc_monthly/$rc_annual` — стандартные package identifiers RevenueCat; `monthly/yearly` в коде используются как product aliases. Не переименовывать сущности для визуального сходства: сначала заполнить фактическую таблицу.

| Тариф | Play subscription Product ID | Play basePlanId | offerId/eligibility | RC imported Product ID | RC package identifier/type | entitlement |
|---|---|---|---|---|---|---|
| Месяц | `<ACTUAL_PRODUCT_ID>` | `<ACTUAL_BASE_PLAN_ID>` | `<ACTUAL_OFFER_OR_NONE>` | `<ACTUAL_RC_PRODUCT_ID>` | `<ACTUAL_PACKAGE>` / monthly | family_security_pro |
| Год | `<ACTUAL_PRODUCT_ID>` | `<ACTUAL_BASE_PLAN_ID>` | `<ACTUAL_OFFER_OR_NONE>` | `<ACTUAL_RC_PRODUCT_ID>` | `<ACTUAL_PACKAGE>` / annual | family_security_pro |

Возможны отдельные subscriptions `monthly`/`yearly` или одна subscription с разными base plans. Нельзя выбрать между ними по исходному коду. Проверить импортированные RC identifiers вида `product:base_plan` и store identifiers фактически полученных StoreProduct.

## 2. Play Console: пошагово

1. Открыть нужное Android приложение. В App Bundle Explorer проверить package и versionCode; записать track и install source тестового устройства.
2. Monetize → Products → Subscriptions: открыть месячный тариф; записать exact Product ID; открыть base plan, записать ID, период, статус Active, цены и страны. Повторить для года. Сохранённый черновик не равен активному плану.
3. Проверить offers: trial/intro price, eligibility, страны, совместимость с выбранным SDK/package; не показывать недоступный offer по фиксированному маркетинговому тексту.
4. Проверить, что продукт доступен стране **Play account**, а не только языку/стране телефона. Для новых регионов проверить merchant/payment setup и реальную test eligibility.
5. Internal testing: tester включён, opt-in принят, опубликованный для тестера versionCode совпадает; удалить путаницу нескольких Google аккаунтов устройства.
6. Settings → License testing: добавить разрешённый test Google account. Использовать test card always approves/declines и slow/pending scenario, если доступны. Не расходовать реальные средства.
7. App integrity: сверить signing fingerprint установленного Play APK; для Maps/Integrity использовать Play signing cert, не только upload cert.
8. Google Cloud: Android Publisher / Google Play Developer API включён для service credentials, которые использует RevenueCat. Ссылка только на проект Firebase не предоставляет права магазина автоматически.
9. Users and permissions: grant service account доступ к нужному Play app и требуемые permission на просмотр purchases/финансовой информации и управление orders/subscriptions по текущей инструкции RC. Избыточный Owner доступ не нужен.
10. Отдельно проверить status всех tracks и policy issues, включая старый versionCode 2. Финальный AAB основного приложения должен иметь monitoring metadata во всех распространяемых версиях.

Официальный [порядок Play credentials](https://www.revenuecat.com/docs/service-credentials/creating-play-service-credentials) включает создание Cloud identity, права в Play и загрузку ключа в RC. Изменения credentials могут распространяться с задержкой; статус ошибки и рекомендации Dashboard важнее повторного изменения product IDs.

## 3. RevenueCat Dashboard: пошагово

1. Выбрать Project → Apps & providers → Google Play app. Сверить package. Public SDK key из этого App должен совпадать с фактически выбранным Flutter key после remote/cache precedence.
2. Public keys не являются серверными secret API keys; их присутствие в Flutter нормально. Secret key для будущего backend sync хранить только на сервере, вводить вместе с реализацией sync endpoint.
3. Установить/проверить Google service account credentials. JSON из Play/Cloud предназначен для RC store validation; Firebase Admin credential на Django решает другую задачу. Не считать один JSON универсальным.
4. Дождаться успешного validation всех нужных Play APIs. Проверить разрешения этого service account и app-specific access при ошибке.
5. Products: импортировать/выбрать существующие подписки и base plans. Сверить IDs по таблице выше; проверить status и store association.
6. Entitlements: открыть `family_security_pro`, прикрепить реальные monthly/annual products. CustomerInfo active entitlements без этого ID не откроет Premium Flutter, даже если purchase transaction существует.
7. Offerings: создать/проверить `default`, сделать intended current; добавить monthly/annual packages и соответствующие Android store products. Пустой offering код корректно превращает в ошибку, а не рабочую оплату.
8. Проверить RevenueCat targeting/experiments/placements, если используются. Основной код выбирает `default` прежде current; динамическое изменение только current может не переключить реально отображаемый offering.
9. Restore/transfer policy: выбрать поведение при входе с другой учётной записью. Текущий backend не умеет правильно переносить entitlement, поэтому этот сценарий — release blocker до исправления.
10. Integrations → Webhooks: endpoint `https://<YOUR_API_HOST>/api/revenuecat/webhook/`, установить длинное случайное Authorization значение. В Django ENV записать **всю строку**, например `Bearer <YOUR_RANDOM_SECRET>`, без двойного `Bearer` и лишних кавычек.
11. Filter приложения/environment: production события в production, sandbox в изолированный staging или по осознанной политике тестовых аккаунтов. Текущий код сам environment не проверяет: Dashboard filter нужен сейчас, server filter нужен в исправлении.
12. Отправить Dashboard test event в staging, проверить HTTP status/auth/parsing. Test event может не иметь реального numeric App User ID и получить `ignored unknown_user`; это не подтверждает Premium lifecycle.
13. Выполнить разрешённую test purchase и открыть Customers → exact numeric ID → history. Проверить store product, environment, expiration, entitlement, delivered webhook event id. Сопоставить со строкой БД и Premium API.
14. Настроить RTDN по RC-инструкции. RTDN магазина→RC и webhook RC→Django — разные каналы; их надо проверять оба.

По [документации webhook](https://www.revenuecat.com/docs/integrations/webhooks) доставка асинхронна и имеет retry. Поэтому мгновенный клиентский success не доказывает серверную активацию. Заложить измеримый SLA синхронизации и reconciliation fallback.

## 4. Что уже реализовано во Flutter и что исправить

| Этап | Реальный код | Оценка |
|---|---|---|
| configure | single-flight `_configureFuture`, PurchasesConfiguration, numeric ID | Реализован; key ownership не доказан, startup/account race требует тестов |
| offerings | getOfferings, empty/null error, retry UI | Реализован; actual products неизвестны |
| purchase | Purchases.purchase + Package | Правильный SDK путь; не тестировался с Play |
| cancel | purchaseCancelledError → isCancelled | Реализован; UX test нужен |
| pending/deferred | Нет отдельной state machine; generic errors/entitlement pending message | Нужна явная обработка без преждевременного Premium |
| restore | restorePurchases + CustomerInfo | Реализован; Django resync отсутствует |
| entitlement | active.containsKey(family_security_pro) | Корректная форма проверки, если mapping верен |
| login/logout | logIn/logOut; listener CustomerInfo | Нужно reset backendIsPremium и различить current/original ID |
| prices | monthly/yearly фиксированные USD | Подтверждённый дефект F08 |
| server rights | client RC entitlement OR backend flag | Нельзя считать API согласованными; нужен sync |

## 5. Дерево диагностики неуспешной оплаты

1. Не открылся paywall / startup error: проверить Firebase/session/subscription независимость, `_configure` error, effective key platform, user ID, internet/API_BASE. Не менять Play products до получения лога.
2. `getOfferings` null/empty/configurationError: проверить Project/App/key, offering packages и entitlement mappings, products/base plans availability/eligibility, install source и country.
3. Play sheet не открывается: записать underlying Billing responseCode/debugMessage, Android Play Store version/account/test track, network и status товара.
4. Purchase success, entitlement отсутствует: Customer history + purchased product→entitlement association, original/current user aliases, pending/ack state.
5. Entitlement есть, Django 403: сравнить numeric user id, webhook delivery status 401/4xx/5xx/ignored, environment, stale event ordering, DB expiry. `getCustomerInfo()` не меняет Django; нужен серверный sync после исправления.
6. После restore/смены аккаунта доступ неверный: сравнить transfer policy, transferred_from/to events и обоих владельцев; не активировать Premium по присланному клиентом boolean.

| Ошибка/сигнал | Типичная область проверки | Что логировать безопасно |
|---|---|---|
| USER_CANCELED / purchaseCancelledError | Пользователь закрыл sheet | Код/время, без alert как будто деньги списаны |
| BILLING_UNAVAILABLE / FEATURE_NOT_SUPPORTED | Play services/store/device/account | responseCode, SDK/device versions, install source |
| ITEM_UNAVAILABLE | Product/base plan/country/track | Exact product/base plan, country, debugMessage |
| DEVELOPER_ERROR | Package/config/параметры Billing | Error domain/code, product/package ids, app version |
| ITEM_ALREADY_OWNED | Existing subscription/restore/user mapping | RC customer id masked, active entitlement, restore result |
| SERVICE_DISCONNECTED / NETWORK_ERROR / SERVICE_UNAVAILABLE | Сеть/Play service | stage, elapsed, retry count; bounded retry |
| configurationError / invalidCredentialsError | RC key/store credentials/catalog | RC error code + underlying detail, masked project/app identifiers |
| payment pending | Ожидание решения магазина | pending UI, без выдачи Premium до verified active entitlement |
| webhook 401 | Authorization mismatch/secret отсутствует | event id/status; не сам header |
| webhook 200 ignored | unknown_user/irrelevant_entitlement | reason/event id, безопасно обезличенный user mapping |

Коды разных SDK слоёв не взаимозаменяемы. Сохранять и PurchasesErrorCode, и underlying Billing code; не выводить весь receipt/purchase token/Authorization. [Billing response handling](https://developer.android.com/google/play/billing/errors) — официальный справочник.

## 6. Acceptance tests покупок и backend

- [ ] Fresh free parent: paid endpoint 403, один бесплатный ребёнок согласно единой политике; Lite не обходит paid права заголовком.
- [ ] Test monthly и annual: локализованный экран/Play sheet совпадают, одна операция, entitlement active, backend API разрешён в согласованный SLA.
- [ ] User cancel, declined и pending: без Premium и без ложного success; pending разрешается после store confirmation.
- [ ] Restore на том же/новом устройстве: тот же владелец, backend sync, нет дублирования/утечки другой семье.
- [ ] Cancel renewal: доступ до expiry; expiration/revoke/refund после нужного момента закрывает доступ; billing grace/hold по политике.
- [ ] Lifetime, если существует: refund/revoke отнимает доступ; если нет продукта — lifetime allowlist пуст.
- [ ] Дубли/старые/параллельные webhook: идемпотентность и устойчивый final state PostgreSQL.
- [ ] Потеря webhook: server reconciliation восстанавливает статус; rate limit не позволяет abuse RC API.
- [ ] Unknown user/alias/transfer: queued diagnostic/retry; нет ложного отключения нового владельца и остаточного Premium старого.
- [ ] Sandbox event не активирует обычного production пользователя; wrong app_id/store не принимаются.
- [ ] Logout Premium A → login free B: UI и API не используют состояние A.
- [ ] Активная mic-сессия безопасно останавливается даже при отзыве Premium.

Готовность подтверждается тестовыми событиями и результатом API, а не только зелёным значком credentials в Dashboard.
