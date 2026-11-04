# «Звук вокруг»: WebRTC, Firebase, Android, TURN

> Обновление 03.11.2026: этот документ сохраняет исходный аудит/чеклист до исправлений. Текущий статус — [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md), актуальные шаги и ключи — [PRODUCTION_START_HERE_RU.md](PRODUCTION_START_HERE_RU.md). Lite отложен по указанию владельца.

Дата: 03.11.2026. Проверены исходники, а не реальный аудиоканал двух телефонов. Ниже операторские инструкции; серверные команды ещё не выполнялись.

## 1. Реальная цепочка и точки диагностики

1. UI `Baby-locator/lib/features/stats/stats_menu_feature_screens.dart:36–38,140–148` создаёт `ParentWebRTCService` и вызывает startListening.
2. Parent создаёт recv-only peer/audio transceiver, получает ICE config, POST `/api/monitor/activate/` с child_id.
3. Backend проверяет parent/Premium/связь, закрывает старые sessions, создаёт MonitorSession + RemoteDeviceCommand, отправляет data-only FCM `webrtc_monitor_start`.
4. FCM handler будит background service; fallback poll реально раз в **5 секунд** (`background_command_service.dart:142`), несмотря на комментарий backend про 2 секунды.
5. Child background handler пытается включить microphone FGS и getUserMedia; ребёнок создаёт **offer**, родитель отвечает **answer**. Не искать offer у родителя в этой реализации.
6. POST `/api/monitor/signal/send/` и GET `/api/monitor/signal/poll/` переносят SDP/ICE; DB relay, не WebSocket.
7. STUN/TURN обеспечивают ICE connectivity; Opus RTP идёт peer-to-peer/через TURN, не через Django media API.
8. Parent audio route/speaker и remote track включаются; callback onTrack ещё не доказывает поступление RTP или слышимый звук.
9. Stop закрывает backend session, child peer/tracks и FGS. Нужны исправления ownership, stop без Premium, leases/timeouts и error handling.

Для каждого stage собирать correlation/session id, timestamp, actor/role, state/error code, ACK. Не собирать полные SDP, ICE IP, access tokens и аудио пользователей в обычных логах.

## 2. Android 12–16: разрешения и состояния

В main manifest платной версии есть RECORD_AUDIO, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MICROPHONE, POST_NOTIFICATIONS, background location. Bridge объявляет отдельный MicrophoneForegroundService. Основной background service имеет type location. Manifest declaration и runtime microphone grant сами по себе не дают права стартовать mic из фона.

**Lite отличается:** `background_command_service.dart:41–45` сразу объявляет location+microphone+mediaPlayback для постоянного tracking service; отдельного microphone service в его bridge нет. Не считать Lite эквивалентом исправленного по типам FGS платного клиента. Это может сорвать tracking startup при отсутствии mic prerequisites; переносить нужно согласованную Dart/native/consent архитектуру целиком.

[Android FGS restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start) и [service types](https://developer.android.com/develop/background-work/services/fgs/service-types#microphone) разделяют ограничения запуска и while-in-use permission. High-priority FCM не решает оба ограничения автоматически. Battery exemption и wakelock также не дают microphone permission.

| Состояние детского устройства | Что можно ожидать от платформы | Что делает текущий код | Что проверять после исправления |
|---|---|---|---|
| Activity видима | Пользователь может дать mic permission и подтвердить запись; FGS запускается при prerequisites | Команда обрабатывается background isolate; отдельного session consent handshake нет | Consent Activity → native FGS ready → getUserMedia → offer |
| Приложение свёрнуто, новой записи нет | Новый mic FGS обычно ограничен; уведомление приглашает открыть приложение | Прямой запуск, ошибки глотаются | Awaiting child approval, без записи до открытия/подтверждения |
| Экран заблокирован | Новый удалённый mic-start не гарантирован; уже корректно начатая сессия может продолжаться | Пытается разбудить service и записывать | Внятный статус ожидания; продолжение ранее согласованного сеанса и Stop |
| Battery saver/Doze | Сеть/фон/планирование могут задерживаться; FCM не SLA | Polling и FCM, зависит от живого процесса/OEM | Доставка приглашения/TTL, no false success, power profile |
| Процесс убит системой | FCM иногда восстанавливает background handler; mic start всё равно ограничен | Boot/background attempts, pending token на диске | Только актуальная session после user action, без позднего автозапуска |
| Force stop пользователем | До ручного открытия нет гарантии FCM/фонового исполнения | Код не может снять stopped state | Честный offline/unavailable, запрос открыть приложение |
| Активный mic FGS, пользователь свернул Activity | Допустимо продолжение в рамках уже запущенного FGS/permission | Cleanup существует, но нет hard lease | Постоянное уведомление, Stop action, предельное время, privacy toggle |

Android 12: background FGS restrictions и privacy controls. Android 13: notification permission. Android 14: typed FGS/while-in-use checks на старте и SecurityException. Android 15–16: проверять новые ограничения конкретных типов, boot-start и audio/foreground lifecycle на target 36, не считать autoStartOnBoot разрешением микрофона. Один APK на Android 12 не подтверждает Android 16.

Рекомендуемая архитектура: backend session `requested` → child notification с ограниченным TTL → ребёнок открывает Activity и принимает → Android mic permission → microphone FGS с подтверждением готовности → media capture → session active по фактическому соединению/пакетам → stop/revoke/timeout → tracks и service закрыты. При отказе — `declined`, а не completed. Видимый Stop доступен на устройстве ребёнка всегда. Согласие/раскрытие информации сохранять с версией текста и временем в пределах privacy policy; permission не подменяет информирование.

Для FGS/notification/full-screen дополнительно проверить [Play declaration requirements](https://support.google.com/googleplay/android-developer/answer/13392821). Full-screen SOS нельзя считать гарантированно разрешённым только из-за USE_FULL_SCREEN_INTENT в manifest.

## 3. Firebase: ручная проверка

- [ ] Android config project_id = серверный credential project_id; для текущих локальных файлов совпадает `kid-security-994a0`.
- [ ] Package в final AAB присутствует в Firebase Android app; отдельный Lite package требует своей записи.
- [ ] FCM HTTP v1 enabled, IAM разрешает отправку, credential не отозван.
- [ ] `FIREBASE_SERVICE_ACCOUNT_KEY` указывает на существующий читаемый JSON **на сервере**. Проверить от имени service user без печати содержимого.
- [ ] Backend log не содержит `Firebase service account key not found` / `Firebase not initialized`.
- [ ] После входа device token зарегистрирован за правильным user/device; account switch не оставляет уведомления прежнему пользователю.
- [ ] Token refresh приводит к актуализации backend; listener один, invalid tokens удаляются после исправления.
- [ ] Разрешённая тестовая команда имеет server message id, device receipt, lease/ACK и реальный result. Отдельно проверить notification denied.
- [ ] FCM недоступен: живой service poll доставляет command; потерянный poll/процесс до ACK не теряет command после исправления F12.
- [ ] Установка из Play, foreground, background, locked, Doze, killed и force-stop имеют отдельные результаты.

Текущий backend использует priority high. [Firebase priority guidance](https://firebase.google.com/docs/cloud-messaging/android-message-priority) связывает high priority с срочными пользовательскими уведомлениями и ограниченной обработкой; это не канал бесконечного фонового выполнения. Добавить короткий TTL, видимое приглашение и dedupe по session/command id.

Ранее задокументированная проблема credentials **локально остаётся возможной**: default backend path отсутствует, JSON расположен в родительском workspace. На production наличие/права файла неизвестны. Подробный credential deployment: `PRODUCTION_SETUP_CHECKLIST.md`, раздел C.

## 4. ICE endpoint: что ожидается

`GET /api/webrtc/ice-servers/` требует auth. Он должен вернуть STUN и TURN entries, например:

```json
{
  "iceServers": [
    {"urls": "stun:turn.example.net:3478"},
    {
      "urls": [
        "turn:turn.example.net:3478?transport=udp",
        "turn:turn.example.net:3478?transport=tcp",
        "turns:turn.example.net:5349?transport=tcp"
      ],
      "username": "<EXPIRY_UNIX_SECONDS>:<USER_ID>",
      "credential": "<TEMPORARY_BASE64_HMAC>"
    }
  ]
}
```

Это пример структуры, не реальные credentials. Backend `tracking/views.py:1554–1569` генерирует `base64(HMAC-SHA1(secret, username))`; это coturn REST credential format, не SHA256. В response не должен попадать shared secret. `WEBRTC_TURN_SECRET` имеет приоритет над static pair. При пустом secret и неполной static pair TURN молча отсутствует. Проверять наличие TURN, а не только HTTP 200.

Оба клиента имеют STUN-only fallback при ошибке endpoint. Он помогает на части сетей, но не заменяет TURN. Нельзя по одной Wi-Fi сессии объявить готовность LTE/CGNAT. В будущем выдачу TURN ограничить активной разрешённой сессией/квотами, а не любым зарегистрированным пользователем.

## 5. Coturn: пошаговая установка на отдельном VPS

Это пример для Ubuntu/Debian; выбрать актуальный patched пакет. Выполнять оператором после разрешения внедрения. Reference: [coturn config](https://github.com/coturn/coturn/blob/master/examples/etc/turnserver.conf), [turnserver manual](https://github.com/coturn/coturn/wiki/turnserver).

1. Выделить VPS с публичным IP и UDP, DNS `turn.<YOUR_DOMAIN>`. За NAT нужны 1:1 mapping и корректный advertised public IP. CDN HTTP proxy перед TURN не подходит. IPv6 публиковать только если он реально маршрутизируется и защищён.
2. Установить:

```bash
sudo apt update
sudo apt install coturn
```

3. Получить TLS сертификат для TURN hostname через контролируемый ACME процесс. Не публиковать private key. Обеспечить чтение ключа coturn service user через узкие права/group или deploy hook; не делать private key world-readable.
4. Сгенерировать длинный случайный shared secret локально через secret manager. Установить одно и то же значение в защищённый coturn config и Django `WEBRTC_TURN_SECRET`. Не передавать его клиентам/в чат.
5. Подготовить `/etc/turnserver.conf` с placeholders, заменив пути и адреса:

```ini
listening-port=3478
tls-listening-port=5349
listening-ip=<YOUR_LOCAL_INTERFACE_IP>
relay-ip=<YOUR_LOCAL_INTERFACE_IP>
# Только если VPS за NAT; при прямом public interface строка не нужна:
# external-ip=<YOUR_PUBLIC_IP>/<YOUR_LOCAL_INTERFACE_IP>
realm=<YOUR_TURN_HOST>
fingerprint
use-auth-secret
static-auth-secret=<YOUR_TURN_SECRET>
min-port=49160
max-port=49260
cert=<YOUR_TURN_CERTIFICATE_CHAIN_PATH>
pkey=<YOUR_TURN_PRIVATE_KEY_PATH>
no-cli
# Не включать allow-loopback-peers: loopback запрещён по умолчанию.
no-multicast-peers
no-tlsv1
no-tlsv1_1
user-quota=8
total-quota=200
stale-nonce=600
```

Это starting config: квоты/relay range подбирать по нагрузке. Не включать no-auth. Не смешивать пример с неподтверждённым static password mode. Ограничить relay к внутренним/metadata сетям (`denied-peer-ip` ranges по реальной сетевой топологии), админ-интерфейсы закрыть. Проверить поддержку используемых опций установленной версией.

В актуальном reference старый `no-loopback-peers` заменён opt-in параметром `allow-loopback-peers`; последний в production не включать. Нельзя копировать устаревшие coturn snippets без проверки версии.

6. Host firewall **и cloud security group**: inbound 3478 UDP/TCP, 5349 TCP для TLS; relay UDP 49160–49260. Для дополнительных режимов TURN-TCP relay отдельно согласовать TCP relay rules. Разрешить нужный outbound peer traffic. Не открывать только 3478: allocation может пройти, а media не пойдёт. TLS 443 возможен на отдельном IP/порту без конфликта с HTTPS, проверять фактическую поддержку транспорта клиентом.
7. Задать Django `WEBRTC_TURN_URLS` с UDP/TCP/TLS, `SECRET` и TTL (например 3600); static username/credential оставить пустыми. Синхронизировать время NTP на API/TURN. Перезапускать только после проверки конфигурации в утверждённое окно.
8. Включить unit сервиса по правилам пакета (`systemctl enable --now coturn`), проверить `systemctl status coturn`, `journalctl -u coturn`, listeners и TLS. Не копировать секреты из логов в тикеты.
9. С тестовым аккаунтом получить временный credential через API. В диагностической сборке временно поставить `iceTransportPolicy: relay` и проверить обе стороны; этот флаг ещё не exposed настройкой production-клиента, потребуется отдельное тестовое изменение в ветке.
10. Проверить candidate pair `relay`, bytesSent/bytesReceived/audioLevel и слышимый звук на Wi-Fi↔LTE и LTE↔другая LTE. Повторить UDP blocked → TCP/TLS, handover и истечение credential. После теста восстановить обычную ICE policy.
11. Проверить отказ с неверным/истёкшим credential и отсутствие open relay. Мониторить allocation failures, relay throughput, quota, bandwidth cost, certificate expiry. Rotation secret спланировать с учётом активных сессий/TTL; не ломать действующие allocations неожиданно.

TLS handshake проверяется без секрета:

```bash
openssl s_client -connect <YOUR_TURN_HOST>:5349 -servername <YOUR_TURN_HOST>
```

Успешный TLS handshake не доказывает TURN allocation и RTP. `turnutils_uclient` можно использовать по `--help` установленной версии с временными credentials; не помещать secret/постоянный пароль в shell history или общедоступные process args. Наиболее важный acceptance test — принудительный relay реального WebRTC клиента.

## 6. Диагностика «соединилось, но звука нет»

| Наблюдение | Следующая проверка |
|---|---|
| Нет command receipt | FCM credential/token/project, app force-stop, TTL и жив ли fallback service |
| Receipt есть, offer нет | awaiting consent/FGS exception, permission/privacy toggle, getUserMedia, ложный success F10 |
| Offer есть, answer нет | Parent polling state, serialized SDP, API auth/403/timeout |
| ICE gathering есть, selected pair нет | TURN auth/URL/ports/NAT, remote ICE before SDP, lost candidates |
| Connected/onTrack есть, inbound RTP bytes = 0 | Child track enabled, mic privacy/busy/input route; onTrack не означает звук |
| RTP bytes растут, audioLevel ≈0 | Реальная тишина/заблокированный mic/noise suppression/доступ native recorder |
| audioLevel есть, не слышно | Parent media volume/audio focus/speaker/Bluetooth/headset route; не усиливать вслепую gain |
| Звук пропал после handover | ICE restart generation и новый offer/answer, очередь кандидатов, credential TTL |
| HTTP выдаёт silence | Upload/download попали в разные workers, нет реальных chunks, proxy buffering |
| Stop не действует | Session ownership/token mismatch, Premium 403 на stop, lost delivered command, cleanup race |

Opus capture mono 48 kHz, maxBitrate 64 kbps и FEC/DTX параметры настроены в коде; их качество не измерено. Parent использует speaker routing и Android gain 2.0. Начинать диагностику с actual audio stats, а не новой правки SDP/усиления. Создание remote stream отменяет watchdog слишком рано; добавление stats необходимо.

## 7. WebRTC и HTTP: что оставить

| Свойство | WebRTC, текущий UI | HTTP PCM / clips |
|---|---|---|
| Куда идёт media | P2P/TURN, encrypted WebRTC transport | Через Django/proxy по HTTPS |
| Задержка/сеть | Opus, jitter/congestion/FEC | Raw 16 kHz mono PCM ≈32 KB/s + HTTP overhead, свой playback buffer |
| NAT | Нужен TURN fallback | Обычный HTTPS доступнее через firewall |
| Масштабирование | Signaling DB + TURN bandwidth | Process-local broker сейчас сломан между workers; долгие requests занимают capacity |
| Конфиденциальность | Backend видит signaling/метаданные | Backend принимает PCM; clip endpoint сохраняет audio FileField |
| Android mic restrictions | Применяются | Точно так же применяются |

Рекомендация: основной пользовательский путь оставить WebRTC; старый HTTP интерфейс не удалять в рамках аудита. Решить по telemetry, нужен ли поддерживаемый HTTP fallback. Если нужен — тот же consent/FGS/session authorization, общий streaming broker, backpressure и bounded lifetime, private storage/retention для clips. Не включать HTTP fallback автоматически как попытку продолжить запись после отказа ОС. Privacy Policy «audio не сохраняется» надо согласовать с фактическим clip API и всей доступной функциональностью.

## 8. Критерий готовности аудио

- [ ] Устройство ребёнка явно подтверждает запрос и показывает mic activity/постоянное уведомление; Stop доступен локально.
- [ ] Parent видит requested/awaiting approval/connecting/receiving/failed, без подмены actual RTP callback onTrack.
- [ ] Two-device E2E на Android 12–16, Wi-Fi/LTE разных операторов, forced relay UDP/TCP/TLS.
- [ ] Потери/дубликаты/перестановка signaling не ломают сессию, cursor не пропускает ошибочное сообщение.
- [ ] Stop от чужой семьи запрещён; свой Stop работает без Premium; privacy toggle/permission revoke/timeout немедленно завершают запись.
- [ ] Kill parent, API outage, repeated start/stop и stale FCM не оставляют mic/FGS/peer активными дольше установленного hard limit.
- [ ] Force-stop представлен как неподдерживаемый для удалённого запуска сценарий, без обещаний обхода Android.
