# PVE Seat

Екран для монітора, підключеного прямо до хоста Proxmox VE. Замість чорної консолі тут вхід для користувачів Proxmox, панель зі станом хоста, контейнерами, VM і вебсервісами, а також запуск «десктопних» VM на відеокарті твого монітора.

*English version below.*

## Можливості

- **Вхід користувачами Proxmox.** Усі дії виконуються з квитком самого користувача, тож кожен бачить і може рівно те, що дозволяють його права в PVE.
- **Місця (seats).** Кожна відеокарта з монітором, яку тримає хост, отримує власне меню з окремим входом. Друга відеокарта означає друге незалежне місце.
- **Запуск систем.** VM з тегом `seat` можна запустити:
  - на дискретній відеокарті, підключеній до твого монітора. Меню саме пропише карту у VM і перемкне вхід монітора через DDC/CI, а після вимкнення VM поверне монітор назад;
  - на вбудованій карті через VirGL. Екран VM тоді відкривається прямо в меню (noVNC).
- **Вебсервіси.** Список береться з admin API Caddy і зіставляється з контейнерами й VM за IP, тож біля кожного сайту видно, чи він працює. Сервіси відкриваються вкладками поруч із меню, а панель на сторінці (Alt+Q) повертає назад.
- **Керування з клавіатури.** Стрілки працюють як на пульті телевізора, Tab не виходить за межі відкритого вікна, Esc закриває. Миша не обов'язкова.
- **Погода й заставка.** Погода з Open-Meteo (без ключа). Живий пейзаж реагує на час доби й погоду: дощ, сніг, туман, грозу.
- **Налаштування для кожного.** Мова, тема, тло, розкладка віджетів, погода, поведінка запуску зберігаються окремо для кожного користувача.
- **Мови:** українська, англійська. Нова мова — це один файл.

## Вимоги

- Proxmox VE 8 або 9.
- Монітор, підключений до відеокарти, яку використовує хост (вбудована підійде). Без монітора працює лише бекенд, а меню можна не ставити (`--no-kiosk`).
- Інтернет на хості: пакети apt, погода й логотипи сервісів.
- За бажанням: Caddy в контейнері з admin API на `localhost:2019`, монітор із DDC/CI для перемикання входів.

## Встановлення

На хості Proxmox, від root:

```bash
git clone <URL цього репозиторію> /root/pve-seat
cd /root/pve-seat
./install.sh
```

Інсталятор:
1. ставить `cage`, `chromium`, `ddcutil`, `python3-aiohttp`;
2. створює системного користувача `pveseat` для кіоску;
3. копіює програму в `/opt/pve-seat`;
4. під час першого запуску визначає залізо і пише `/etc/pve-seat/config.yaml`: відеокарти з моніторами, монітори з DDC та їхні входи, контейнер із Caddy, місто за часовим поясом;
5. вмикає служби `pve-seat` (бекенд на `127.0.0.1:8900`) і `pve-seat-kiosk@<місце>` (меню на tty7, tty8…).

Параметри: `--no-kiosk` (лише бекенд), `--city Lviv`, `--lang uk|en` (для першого конфігу).

Консоль лишається доступною на **Ctrl+Alt+F1**, меню на **Ctrl+Alt+F7**.

Оновлення: `./update.sh` (git pull + install). Видалення: `./uninstall.sh` (налаштування в `/etc/pve-seat` лишаються).

## Після встановлення

1. **Системи.** Додай VM тег `seat` у Proxmox, і вона з'явиться в меню. VM, які не можна позначити тегом (наприклад, приспані на диск), додаються через `systems_extra: [100]`.
2. **Дискретна відеокарта на тому ж моніторі.** Допиши її вхід у розділ `monitors` конфігу. Коди входів показує `ddcutil capabilities | grep -A8 'Feature: 60'`:
   ```yaml
   monitors:
     mon0:
       ddc_bus: 4
       inputs:
         "0000:79:00.0": 0x11   # HDMI-1, меню
         "0000:02:00.0": 0x0f   # DisplayPort-1, відеокарта для VM
   ```
3. **Вебсервіси без Caddy.** Додай посилання в `links:`.
4. Після змін виконай `systemctl restart pve-seat 'pve-seat-kiosk@*'`.

Повний перелік параметрів із поясненнями є в [`etc/config.example.yaml`](etc/config.example.yaml).

## Клавіші

| Де | Клавіші |
|---|---|
| Меню | стрілки: навігація · Tab / Shift+Tab · Enter · Esc: закрити вікно |
| Відкритий сервіс | **Alt+Q**: панель (← → вибір, Enter, Esc назад) |
| Екран VM у меню | **Ctrl+Alt+Q**: назад у меню (VM працює далі) |
| Хост | Ctrl+Alt+F1: консоль · Ctrl+Alt+F7: меню |

## Як розширювати

**Віджет** — це папка `web/widgets/<id>/` з файлом `widget.js` (і за бажанням `widget.css`):

```js
export default {
  zones: ['side', 'login'],          // де його можна ставити
  public: true,                      // можна показувати на екрані входу
  source: '/api/host', every: 5,     // звідки брати дані і як часто оновлювати (сек)
  i18n: { uk: { title: 'Мережа' }, en: { title: 'Network' } },
  render: (data, { t, ui }) => `<h4>${t('title')}</h4>…`,
};
```

Після `install.sh` віджет з'явиться в меню «Налаштування → Макет і віджети → Додати».

**Тема** — це один файл `web/themes/<id>.css`, що містить лише змінні (`--acc`, `--glass`, `--display`, `--lf`…). Назва задається в заголовку: `@name.uk …`, `@name.en …`.

**Мова** — це один файл `web/i18n/<code>.json` з тими самими ключами, що в `en.json`, і полем `"_name"`. Переклади віджетів лежать у їхніх `i18n`, повідомлення бекенда в `backend/pveseat/i18n.py`, панель сервісів у `kiosk/ext/content.js`.

## Як це влаштовано

```
backend/pveseat/   aiohttp: API Proxmox (квиток користувача), стан хоста, відеокарти, DDC,
                   Caddy, погода, запуск систем, проксі noVNC
web/               інтерфейс без збирання: core/, widgets/, themes/, i18n/, vendor/novnc
kiosk/             kiosk.sh (cage + Chromium на відеокарті місця), розширення вкладок і панелі,
                   політика Chromium (системний DNS)
systemd/           pve-seat.service, pve-seat-kiosk@.service
tools/             dryrun.py (тестовий бекенд), screenshots.py (знімки на 10 роздільностях)
```

## Розробка

На хості, поруч зі справжньою службою:

```bash
python3 tools/dryrun.py --port 8901        # справжні дані, вхід з паролем "test", усі дії лише в журнал
python3 tools/screenshots.py --out /tmp/shots --lang en
```

`screenshots.py` проходить вхід, панель, контейнери, запуск і налаштування на 10 поширених роздільностях (від 1024×768 до 3840×2160 та 3440×1440) і повідомляє про горизонтальну прокрутку, елементи за краєм екрана й обрізаний текст.

Щоб підключатися до Chromium кіоску через DevTools, задай `kiosk.debug_port: 9222` у конфігу. Порт слухає лише `127.0.0.1`.

## Якщо щось не так

- **Журнали:** `journalctl -u pve-seat -u 'pve-seat-kiosk@*' -f`
- **Сервіси відкриваються з «connection refused».** Імена мають резолвитись у внутрішню адресу. Кіоск використовує системний DNS (`/etc/resolv.conf`), тож DNS хоста має знати твої внутрішні імена.
- **Монітор не перемикається.** Перевір `ddcutil detect` і коди в `monitors`. Деякі монітори (наприклад, Dell P2418D) завжди повідомляють той самий вхід, тому меню не читає поточний вхід, а лише перемикає.
- **Меню на дискретній NVIDIA.** Хост може малювати на ній лише з драйвером, що її підтримує. Для RTX 50 з nouveau потрібна прошивка GSP відповідного чипа.

---

# PVE Seat (English)

A screen for a monitor plugged straight into a Proxmox VE host: sign-in with Proxmox accounts, a dashboard with host state, containers, VMs and web services, and a launcher that starts desktop VMs on the GPU your monitor is connected to.

**Features:** per-GPU seats with separate sign-in · VMs start on a discrete GPU wired to your monitor, and the monitor input switches over DDC/CI (and back when the VM stops), or on the integrated GPU through VirGL, shown inside the menu · web services discovered from Caddy and matched to guests · services open as tabs next to the menu (Alt+Q dock) · fully keyboard driven · weather-reactive landscape and screensaver · per-user language, theme, layout and behaviour · Ukrainian and English.

**Install** (as root on the Proxmox host, PVE 8+):

```bash
git clone <this repository> /root/pve-seat && cd /root/pve-seat && ./install.sh
```

On first run the installer detects GPUs with monitors, DDC monitors and their inputs, the Caddy container and a weather city, then writes `/etc/pve-seat/config.yaml` (never overwritten later). Tag VMs with `seat` to list them. For a discrete GPU wired to the same monitor, add its input code under `monitors` (see [`etc/config.example.yaml`](etc/config.example.yaml)). Update with `./update.sh`, remove with `./uninstall.sh`.

**Extend:** a widget is `web/widgets/<id>/widget.js`, a theme is `web/themes/<id>.css` (tokens only), a language is `web/i18n/<code>.json`. See the Ukrainian section above for the widget contract and the development tools (`tools/dryrun.py`, `tools/screenshots.py`).

Third-party: noVNC (MPL-2.0) is vendored in `web/vendor/novnc`; weather icons are Meteocons by Bas Milius (MIT); service logos are fetched from homarr-labs/dashboard-icons at runtime.
