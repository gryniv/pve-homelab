# PVE Seat

Екран для монітора, підключеного прямо до хоста Proxmox VE. Замість чорної консолі тут вхід для користувачів Proxmox, панель зі станом хоста, контейнерами, VM і вебсервісами, а також запуск «десктопних» VM на відеокарті твого монітора.

*English version below.*

## Швидкий старт

### A. Подивитися на своєму комп'ютері (без Proxmox)

Потрібен лише Python 3.10 або новіший ([python.org](https://www.python.org/downloads/); на Windows під час встановлення постав галочку «Add python.exe to PATH»).

| Система | Що зробити |
|---|---|
| **Windows** | Двічі клацни `demo.bat` у папці проєкту |
| **Linux / macOS** | У терміналі в папці проєкту: `./demo.sh` |

Перший запуск триває з хвилину: скрипт готує середовище в `.demo/` і ставить дві бібліотеки. Потім браузер сам відкриє **http://127.0.0.1:8900**.

Далі:
1. Обери будь-якого користувача (**Ihor**, **Guest** з обмеженими правами або **root**), введи **будь-який пароль** і натисни Enter.
2. Спробуй усе: ▶ на системі, вебсервіси, вкладку «Контейнери та VM», шестерню налаштувань (мова, тема, віджети), позначку «Оновлення» вгорі.
3. Щоб зупинити, закрий вікно консолі або натисни Ctrl+C.

Усе вигадане: 4 VM, 7 контейнерів, дві відеокарти, сервіси «з Caddy». Жоден справжній сервер не змінюється, а твої налаштування в демо зберігаються в `.demo/`.

Додаткові параметри (для `demo.bat`, `demo.sh` або `python demo.py`): `--lang uk` чи `--lang en`, `--port 9000`, `--no-browser`.

### B. Встановити на хост Proxmox

```bash
git clone <URL репозиторію> /root/pve-seat && cd /root/pve-seat && ./install.sh
```

Подробиці нижче, у розділі [Встановлення](#встановлення).

## Можливості

- **Вхід користувачами Proxmox.** Усі дії виконуються з квитком самого користувача, тож кожен бачить і може рівно те, що дозволяють його права в PVE.
- **Місця (seats).** Кожна відеокарта з монітором, яку тримає хост, отримує власне меню з окремим входом. Друга відеокарта означає друге незалежне місце.
- **Запуск систем.** VM з тегом `seat` можна запустити:
  - на дискретній відеокарті, підключеній до твого монітора. Меню саме пропише карту у VM і перемкне вхід монітора через DDC/CI, а після вимкнення VM поверне монітор назад;
  - на вбудованій карті через VirGL. Екран VM тоді відкривається прямо в меню (noVNC).
- **Вебсервіси знаходяться самі** з трьох джерел:
  - Caddy (admin API): гарні домени;
  - відкриті порти контейнерів, які хост читає напряму з `/proc` без входу в гостя, та типові вебпорти VM. Кожен кандидат перевіряється запитом `GET /`: у список потрапляють лише сторінки з HTML, а назву й логотип визначає заголовок сторінки та ім'я контейнера;
  - посилання в нотатках гостя в Proxmox.

  Біля кожного сервісу видно, чи працює його гість. Сервіси відкриваються вкладками поруч із меню, а панель на сторінці (Alt+Q) повертає назад.
- **Керування з клавіатури.** Стрілки працюють як на пульті телевізора, Tab не виходить за межі відкритого вікна, Esc закриває. Миша не обов'язкова.
- **Погода й заставка.** Погода з Open-Meteo (без ключа). Живий пейзаж реагує на час доби й погоду: дощ, сніг, туман, грозу.
- **Налаштування для кожного.** Мова, тема, тло, розкладка віджетів, погода, поведінка запуску зберігаються окремо для кожного користувача.
- **Оновлення з GitHub** з нагадуванням у меню, за бажанням автоматичні.
- **Мови:** українська, англійська. Нова мова — це один файл.

## Вимоги

- Proxmox VE 8 або 9.
- Монітор, підключений до відеокарти, яку використовує хост (вбудована підійде). Без монітора працює лише бекенд, а меню можна не ставити (`--no-kiosk`).
- Інтернет на хості: пакети apt, погода й логотипи сервісів.
- За бажанням: Caddy в контейнері з admin API на `localhost:2019` (без нього сервіси знаходяться за портами й нотатками), монітор із DDC/CI для перемикання входів.

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

Видалення: `./uninstall.sh` (налаштування в `/etc/pve-seat` лишаються).

## Оновлення

Меню кожні кілька годин перевіряє GitHub. Коли є нова версія:
- у верхній панелі з'являється позначка «Оновлення vX.Y.Z»;
- після входу вискакує нагадування;
- користувач із правом `Sys.Modify` на `/` встановлює її кнопкою в меню;
- решта бачать, що оновлення є, але поставити його може лише адміністратор.

Git на хості не потрібен: оновлювач завантажує архів з GitHub і запускає з нього `install.sh`. Конфіг і налаштування користувачів не змінюються.

Налаштування в `/etc/pve-seat/config.yaml`:

```yaml
update:
  repo: ""          # owner/name; порожньо = репозиторій, з якого встановлено (git clone)
  channel: release  # release = останній реліз або тег vX.Y.Z; main = найновіший коміт гілки
  auto: false       # true = ставити нові версії самостійно щоночі о 04:30
```

Вручну: `python3 -m pveseat.update check|apply` (з `PYTHONPATH=/opt/pve-seat/backend`), або `./update.sh` у клоні репозиторію.

**Як випустити версію:** зміни `VERSION`, закоміть, потім виконай `git tag v0.3.1 && git push --tags`. Реліз на GitHub необов'язковий, досить тегу.

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
3. **Вебсервіси.** Більшість знайдеться сама. Щоб додати посилання вручну, впиши його в нотатки гостя в Proxmox (`[Назва](http://адреса:порт)`) або в `links:` конфігу. Щоб прибрати зайве, допиши його в `discovery.ignore` або сховай у налаштуваннях меню.
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
  options: [                         // налаштування віджета (кнопка ⚙ біля нього в «Налаштуваннях»)
    { key: 'iface', type: 'text', label: 'opt_iface', default: '' },
    { key: 'graph', type: 'toggle', label: 'opt_graph', default: true },
  ],                                 // типи: toggle, select, checks, number, text, date, list, textarea
  render: (data, { t, ui, opts }) => `<h4>${t('title')}</h4>…`,   // opts.graph, opts.iface
};
```

Після `install.sh` віджет з'явиться в меню «Налаштування → Панель» або «Екран входу» → «Додати».

Теми, фони, годинники й шрифти працюють однаково: **один файл = один модуль**. Бекенд сам знаходить файли в теці, а назву й решту метаданих бере з першого коментаря файлу (`@name.uk …`, `@name.en …`, `@desc.uk …`, `@order 10`). Після `install.sh` новий модуль з'являється в «Налаштування → Вигляд» із живим прев'ю.

**Тема**: `web/themes/<id>.css`, лише змінні (`--acc`, `--acc2`, `--glass`, `--solid`, `--display`, `--lf`…) для `.A[data-skin="<id>"],.A [data-skin="<id>"]`.

**Фон / заставка**: `web/backgrounds/<id>.css`. `@group scape` — пейзаж (сонце, місяць, зорі, хмари, туман і сніг рушій малює сам), `@group flat` — простий фон (отримує лише погодну вуаль). `@tod night` закріплює певну пору доби. Малюєш сам `.bgx[data-k="<id>"]` і потрібні шари `.l1`…`.l4`, кольори береш із палітри `--sky1 --sky2 --sky3 --far --mid --ink` (вона вже враховує тему й пору доби). Під погоду чи пору доби підлаштовуєшся через `.bgx[data-k="<id>"][data-wx="snow"]` або `[data-tod="night"]`. Приклад: `web/backgrounds/mountains.css`.

**Годинник**: `web/clocks/<id>.js`, де `export const css` (стилі для `.clock[data-clockk="<id>"]`) і `export function render(el, t)`. Функція викликається щосекунди з `t = {h, m, s, text, date}` і має змінювати лише те, що змінилось. Приклад: `web/clocks/neon.js`.

**Шрифт**: `web/fonts/<id>.css` з `@family "Назва", sans-serif` у заголовку й `@import` вебшрифту. Завантажується лише тоді, коли його вибрано або відкрито прев'ю.

**Мова** — це один файл `web/i18n/<code>.json` з тими самими ключами, що в `en.json`, і полем `"_name"`. Переклади віджетів лежать у їхніх `i18n`, повідомлення бекенда в `backend/pveseat/i18n.py`, панель сервісів у `kiosk/ext/content.js`.

## Як це влаштовано

```
backend/pveseat/   aiohttp: API Proxmox (квиток користувача), стан хоста, відеокарти, DDC,
                   Caddy, погода, запуск систем, проксі noVNC
web/               інтерфейс без збирання: core/, widgets/, themes/, i18n/, vendor/novnc
kiosk/             kiosk.sh (cage + Chromium на відеокарті місця), розширення вкладок і панелі,
                   політика Chromium (системний DNS)
systemd/           pve-seat.service, pve-seat-kiosk@.service, pve-seat-update.{service,timer}
tools/             dryrun.py (тестовий бекенд на хості), screenshots.py (знімки на 10 роздільностях)
demo.py            меню поверх вигаданого хоста, без Proxmox (backend/pveseat/demo.py)
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
- **Журнал помилок:** «Налаштування → Про програму → Журнал помилок» (бачать користувачі з правом `Sys.Audit`). Там збираються попередження й помилки бекенда та самих екранів: помилки JS, віджети, що не змогли намалюватись, і збої API. Файл лежить у `/var/log/pve-seat/errors.log`, по одному JSON у рядку; це до 4 МБ із ротацією.
- **Сервіси відкриваються з «connection refused».** Імена мають резолвитись у внутрішню адресу. Кіоск використовує системний DNS (`/etc/resolv.conf`), тож DNS хоста має знати твої внутрішні імена.
- **Монітор не перемикається.** Перевір `ddcutil detect` і коди в `monitors`. Деякі монітори (наприклад, Dell P2418D) завжди повідомляють той самий вхід, тому меню не читає поточний вхід, а лише перемикає.
- **Меню на дискретній NVIDIA.** Хост може малювати на ній лише з драйвером, що її підтримує. Для RTX 50 з nouveau потрібна прошивка GSP відповідного чипа.

---

# PVE Seat (English)

A screen for a monitor plugged straight into a Proxmox VE host: sign-in with Proxmox accounts, a dashboard with host state, containers, VMs and web services, and a launcher that starts desktop VMs on the GPU your monitor is connected to.

**Features:** per-GPU seats with separate sign-in · VMs start on a discrete GPU wired to your monitor, and the monitor input switches over DDC/CI (and back when the VM stops), or on the integrated GPU through VirGL, shown inside the menu · web services found by themselves: Caddy's admin API, open ports of containers (read from the host) and VMs checked with GET /, and links in guest notes · services open as tabs next to the menu (Alt+Q dock) · fully keyboard driven · weather-reactive landscape and screensaver · per-user language, theme, layout and behaviour · Ukrainian and English.

**Install** (as root on the Proxmox host, PVE 8+):

```bash
git clone <this repository> /root/pve-seat && cd /root/pve-seat && ./install.sh
```

**Try it without Proxmox:** double-click `demo.bat` (Windows) or run `./demo.sh` (Linux/macOS); it prepares `.demo/` on first run and opens http://127.0.0.1:8900. It runs the real menu over a made-up host (any password; nothing real changes).

**Updates:** the menu checks GitHub (latest release or `vX.Y.Z` tag, or the newest commit with `channel: main`), shows "Update vX.Y.Z" in the top bar and reminds after sign-in; users with `Sys.Modify` on `/` install it from there. `update.auto: true` installs new versions nightly.

On first run the installer detects GPUs with monitors, DDC monitors and their inputs, the Caddy container and a weather city, then writes `/etc/pve-seat/config.yaml` (never overwritten later). Tag VMs with `seat` to list them. For a discrete GPU wired to the same monitor, add its input code under `monitors` (see [`etc/config.example.yaml`](etc/config.example.yaml)). Update with `./update.sh`, remove with `./uninstall.sh`.

**Extend:** one file is one module, found by the backend and named from its first comment (`@name.en …`, `@order …`): a widget is `web/widgets/<id>/widget.js` (with `options: [{key, type, label, default}]` it gets a ⚙ form and a live preview in settings; the values arrive as `ctx.opts`), a theme `web/themes/<id>.css` (tokens only), a background `web/backgrounds/<id>.css` (`@group scape|flat`, paint `.bgx[data-k="<id>"]` and layers `.l1`-`.l4` from the `--sky*`/`--far`/`--mid`/`--ink` palette; sun, moon, stars, clouds, fog and weather come from the engine), a clock `web/clocks/<id>.js` (`css` + `render(el, {h, m, s, text})` every second), a font `web/fonts/<id>.css` (`@family` + `@import`), a language `web/i18n/<code>.json`. See the Ukrainian section above for the widget contract and the development tools (`tools/dryrun.py`, `tools/screenshots.py`).

Third-party: noVNC (MPL-2.0) is vendored in `web/vendor/novnc`; weather icons are Meteocons by Bas Milius (MIT); service logos are fetched from homarr-labs/dashboard-icons at runtime.
