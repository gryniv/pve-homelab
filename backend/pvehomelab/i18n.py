"""Messages the backend shows to people (errors, launch steps, GPU notes).

The language comes from the X-Lang header of each request (see app.errors middleware)
and is kept in a context variable, so background launch jobs keep the caller's language.
"""

import contextvars

lang = contextvars.ContextVar("lang", default="en")

MESSAGES = {
    "en": {
        "bad_login": "Wrong user name or password",
        "forbidden": "Not enough permissions",
        "task_failed": "The task failed",
        "task_slow": "The task is taking too long",
        "no_system": "System not found",
        "not_wired": "This GPU is not connected to your monitor",
        "running_elsewhere": "The system is already running on another GPU",
        "no_power": "Not enough permissions to start this system",
        "no_hw_gpu": "Not enough permissions to change this system's GPU",
        "no_hw_vga": "Not enough permissions to change this system's display adapter",
        "busy": "used by VM {vm}",
        "already_running": "{vm} is already running",
        "suspended": "the system is hibernated, its GPU can't be changed now",
        "other_gpu": "the VM is set up for another GPU",
        "gpu_disabled": "{name}: {why}",
        "step_switch": "Switching the monitor to {gpu}",
        "step_assign": "Assigning {gpu} to {vm}",
        "step_start": "Starting {vm} (VM {id})",
        "step_wake": "Waking up {vm} (VM {id})",
        "step_virgl": "Turning on 3D through {gpu} (VirGL)",
        "step_show": "Opening {vm}'s screen",
        "step_show_short": "Opening the system's screen",
        "city_not_found": "City \"{city}\" not found",
        "ddc_no_monitor": "DDC: monitor not found",
    },
    "uk": {
        "bad_login": "Невірний користувач або пароль",
        "forbidden": "Недостатньо прав",
        "task_failed": "Задача завершилась з помилкою",
        "task_slow": "Задача виконується надто довго",
        "no_system": "Систему не знайдено",
        "not_wired": "Ця відеокарта не підключена до твого монітора",
        "running_elsewhere": "Система вже працює на іншій відеокарті",
        "no_power": "Недостатньо прав, щоб запускати цю систему",
        "no_hw_gpu": "Недостатньо прав, щоб змінити відеокарту цієї системи",
        "no_hw_vga": "Недостатньо прав, щоб змінити відеоадаптер цієї системи",
        "busy": "зайнята VM {vm}",
        "already_running": "{vm} уже працює",
        "suspended": "система приспана на диск, відеокарту їй зараз змінити не можна",
        "other_gpu": "VM налаштована на іншу відеокарту",
        "gpu_disabled": "{name}: {why}",
        "step_switch": "Перемикаю монітор на {gpu}",
        "step_assign": "Призначаю {gpu} системі {vm}",
        "step_start": "Стартую {vm} (VM {id})",
        "step_wake": "Розбуджую {vm} (VM {id})",
        "step_virgl": "Вмикаю 3D через {gpu} (VirGL)",
        "step_show": "Відкриваю екран {vm}",
        "step_show_short": "Відкриваю екран системи",
        "city_not_found": "Місто «{city}» не знайдено",
        "ddc_no_monitor": "DDC: монітор не знайдено",
    },
}


def _(key, **kw):
    table = MESSAGES.get(lang.get()) or MESSAGES["en"]
    text = table.get(key) or MESSAGES["en"].get(key, key)
    return text.format(**kw) if kw else text


def pick(header):
    """First supported language from an X-Lang / Accept-Language style value."""
    for part in (header or "").replace(" ", "").split(","):
        code = part.split(";")[0].split("-")[0].lower()
        if code in MESSAGES:
            return code
    return None
