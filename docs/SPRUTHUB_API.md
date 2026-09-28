# Полная архитектура и API-схема SprutHub

Документация протокола и всех RPC-методов контроллера **SprutHub**, полученная методом реверс-инжиниринга веб-интерфейса и анализа живого хаба.

---

## 1. Транспорт и авторизация

* **Протокол:** WebSocket JSON-RPC 2.0
* **URL по умолчанию:** `ws://<IP_ИЛИ_ХОСТ>/spruthub`
* **Subprotocols:** `["json-rpc"]`
* **Origin заголовок:** `http://spruthub.local`
* **Формат запроса:**
  ```json
  {
    "id": 1,
    "token": "<ТОКЕН_ИЛИ_ПАРОЛЬ>",
    "serial": "<СЕРИЙНЫЙ_НОМЕР_ХАБА>",
    "params": {
      "<MODULE>": {
        "<ACTION>": { ... }
      }
    }
  }
  ```
* **Формат ответа:**
  ```json
  {
    "id": 1,
    "result": {
      "<MODULE>": {
        "<ACTION>": { ... }
      }
    }
  }
  ```
* **Широковещательные события (Push-уведомления):**
  Хаб отправляет кадры без `id` при любых изменениях характеристик или комнат:
  ```json
  {
    "event": {
      "characteristic": {
        "event": "EVENT_UPDATE",
        "characteristics": [{ "aId": 1126, "sId": 16, "cId": 18, "control": { "value": { "doubleValue": 0.002 } } }]
      }
    }
  }
  ```

---

## 2. Полная карта модулей и методов API (18 модулей, 62 метода)

### 1. Аксессуары и устройства (`accessory`)
* `accessory.list`: получение полного списка устройств (параметр `{"expand": "services,characteristics"}`).
* `accessory.get`: получение детальной структуры устройства (`{"id": <aId>, "expand": "services,characteristics"}`).
* `accessory.update`: переименование, смена комнаты или параметров аксессуара.
* `accessory.create`: добавление виртуального устройства или линка.
* `accessory.delete`: удаление аксессуара по ID (`{"id": <aId>}`).

### 2. Управление характеристиками (`characteristic`)
* `characteristic.update`: запись нового значения в характеристику:
  ```json
  {
    "aId": 1148,
    "sId": 13,
    "cId": 15,
    "control": {
      "value": { "boolValue": true }
    }
  }
  ```
  Поддерживаемые типы значений: `boolValue`, `intValue`, `doubleValue`, `stringValue`.

### 3. История и телеметрия (`history`)
* `history.list`: запрос исторических значений сенсоров и переключателей:
  ```json
  {
    "filter": {
      "accessories": [
        { "aId": 1126, "sId": 16, "cId": 18 }
      ]
    },
    "afterTimestamp": 1790000000000,
    "beforeTimestamp": 1790590000000,
    "afterId": 2204729,
    "limit": 500,
    "group": "hour"
  }
  ```
  Поддерживает пагинацию через `afterId`, фильтрацию по временным окнам и агрегацию.

### 4. Комнаты и зоны (`room`)
* `room.list`: список комнат с текущими агрегированными сенсорами и действиями.
* `room.get`: получение информации по конкретной комнате (`{"id": <roomId>}`).
* `room.create`: создание новой комнаты.
* `room.update`: переименование, смена порядка отображения, назначение иконок.
* `room.delete`: удаление комнаты.

### 5. Сценарии автоматизации (`scenario`)
* `scenario.list`: список всех настроенных сценариев (`index`, `name`, `active`, `rooms`, `iconsIf`, `iconsThen`).
* `scenario.get`: детальное описание сценария по индексу (`{"index": "<index>"}`).
* `scenario.run`: принудительный запуск сценария (`{"index": "<index>"}`).
* `scenario.create`: создание нового сценария.
* `scenario.update`: сохранение логики, шагов или переключение активности (`active: true/false`).
* `scenario.delete`: удаление сценария.

### 6. Системные логи и события (`log`)
* `log.list`: чтение системных логов хаба:
  ```json
  {
    "count": 50
  }
  ```
  Возвращает записи с полями `time`, `level` (`LOG_LEVEL_INFO`, `LOG_LEVEL_ERROR`, etc.), `path`, `message`.

### 7. Расширения и драйверы протоколов (`extension`, `extensionChild`)
* `extension.list`: список установленных драйверов (Zigbee координатор, Z-Wave, BLE, HomeKit, Telegram, MQTT и др.).
* `extension.get`: свойства и конфигурация драйвера по `id`.
* `extensionChild.list`, `extensionChild.get`: дочерние узлы и интерфейсы расширений.

### 8. Логика и правила (`logic`)
* `logic.list`: список логических блоков и правил для аксессуара (`{"aId": <aId>}`).
* `logic.get`, `logic.create`, `logic.update`, `logic.delete`: управление правилами автоматизаций.

### 9. Управление контроллером (`hub`)
* `hub.list`: базовый список доступных контроллеров.
* `hub.get`: системный статус хаба, серийный номер, версия ПО, модель платформы (`{"serial": "..."}`).
* `hub.restart`: перезапуск службы или контроллера.
* `hub.delete`: удаление хаба из аккаунта.

### 10. Дашборды и виджеты (`dashboard`, `dashboardColumn`, `dashboardWidget`)
* `dashboard.list`, `dashboard.get`, `dashboard.create`, `dashboard.update`, `dashboard.delete`
* `dashboardColumn.*`, `dashboardWidget.*`: создание и компоновка экранов управления в интерфейсе.

### 11. Каталог устройств и шаблоны (`catalog`, `bundle`, `link`, `action`)
* `catalog.list`, `catalog.get`, `catalog.create`, `catalog.update`, `catalog.delete`: база поддерживаемых устройств и параметров.
* `bundle.*`: группы и пакетные настройки.
* `link.list`: связи между аксессуарами и сервисами.
* `action.create`, `action.save`: шаблоны действий.
