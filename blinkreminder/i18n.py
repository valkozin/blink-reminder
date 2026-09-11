"""Tiny two-language string table (English / Russian), picked from the system locale."""

from __future__ import annotations

import locale
import os
import sys

EN = {
    "hud_text": "Blink",
    "state_active": "Watching your blinks",
    "state_paused": "Paused",
    "state_standby": "Standby - no one at the desk",
    "state_no_face": "Face not visible",
    "state_starting": "Calibrating…",
    "state_locked": "Paused - screen locked",
    "state_idle": "Paused - you are away",
    "state_error": "Camera unavailable",
    "rate": "Blink rate: {rate}/min",
    "rate_unknown": "Blink rate: measuring…",
    "pause": "Pause",
    "resume": "Resume",
    "snooze": "Pause for…",
    "snooze_15": "15 minutes",
    "snooze_30": "30 minutes",
    "snooze_60": "1 hour",
    "snooze_until": "Paused until {time}",
    "interval": "Remind after…",
    "interval_item": "{sec} seconds without a blink",
    "sound": "Sound",
    "sound_off": "Silent",
    "sound_volume": "Volume",
    "volume_item": "{percent}%",
    "hud": "Show on-screen hint",
    "show_rate": "Show blink rate in the menu bar",
    "preview": "Check camera framing…",
    "preview_title": "Blink Reminder - camera",
    "camera": "Camera",
    "state_unseen": "Cannot see you - check the camera",
    "state_unusable": "Cannot measure blinks - check the camera angle",
    "unseen_title": "Blink Reminder cannot see you",
    "unseen_body": (
        "You have been at the keyboard for a few minutes, but the camera has not found "
        "your face in all that time, so no reminders are being sent.\n\n"
        "This usually means the camera is not pointed at you - a laptop standing beside "
        "the monitor you actually look at, for instance.\n\n"
        "Open “Check camera framing…” in the menu and move the camera until the frame "
        "turns green, or pick another camera in the Camera submenu."
    ),
    "sensitivity": "Detection sensitivity",
    "sensitivity_low": "Low (fewer false blinks)",
    "sensitivity_normal": "Normal",
    "sensitivity_high": "High (catches light blinks)",
    "pause_when_idle": "Pause when keyboard is idle",
    "pause_when_locked": "Pause when screen is locked",
    "start_at_login": "Start at login",
    "stats": "Today’s statistics…",
    "stats_title": "Blink Reminder - today",
    "stats_body": (
        "Time at the screen: {active}\n"
        "Blinks detected: {blinks}\n"
        "Average rate: {rate}/min\n"
        "Reminders sent: {reminders}\n\n"
        "This session: {session_blinks} blinks, {session_reminders} reminders."
    ),
    "quit": "Quit",
    "camera_error_title": "Camera unavailable",
    "camera_error_body": (
        "Blink Reminder cannot open the camera.\n\n"
        "Check that no other app is using it, and that camera access is granted in "
        "System Settings › Privacy & Security › Camera."
    ),
    "camera_denied_body": (
        "Camera access is turned off for Blink Reminder.\n\n"
        "Open System Settings › Privacy & Security › Camera, allow the entry for Python "
        "(or Terminal, if you started it from there), then start Blink Reminder again."
    ),
    "unusable_body": (
        "Your face is in the frame, but not one blink has been measurable for two "
        "minutes - and nobody goes two minutes without blinking.\n\n"
        "The camera is almost certainly looking at you from too sharp an angle to see "
        "your eyelids move: a laptop standing beside the monitor you are looking at "
        "does exactly this.\n\n"
        "Reminders are paused until blinks become measurable again, because anything "
        "sent now would be guesswork. Open “Check camera framing…” and turn the camera "
        "towards your face."
    ),
    "autostart_error_title": "Could not change the login item",
    "dur_hours": "h",
    "dur_minutes": "min",
}

RU = {
    "hud_text": "Моргни",
    "state_active": "Слежу за морганием",
    "state_paused": "На паузе",
    "state_standby": "Жду — вас нет за столом",
    "state_no_face": "Лицо не видно",
    "state_starting": "Калибровка…",
    "state_locked": "Пауза — экран заблокирован",
    "state_idle": "Пауза — вы отошли",
    "state_error": "Камера недоступна",
    "rate": "Частота: {rate} в минуту",
    "rate_unknown": "Частота: измеряю…",
    "pause": "Пауза",
    "resume": "Продолжить",
    "snooze": "Пауза на…",
    "snooze_15": "15 минут",
    "snooze_30": "30 минут",
    "snooze_60": "1 час",
    "snooze_until": "Пауза до {time}",
    "interval": "Напоминать через…",
    "interval_item": "{sec} секунд без моргания",
    "sound": "Звук",
    "sound_off": "Без звука",
    "sound_volume": "Громкость",
    "volume_item": "{percent}%",
    "hud": "Показывать подсказку на экране",
    "show_rate": "Показывать частоту в строке меню",
    "preview": "Проверить кадр камеры…",
    "preview_title": "Blink Reminder — камера",
    "camera": "Камера",
    "state_unseen": "Не вижу вас — проверьте камеру",
    "state_unusable": "Не различаю моргания — поверните камеру",
    "unseen_title": "Blink Reminder вас не видит",
    "unseen_body": (
        "Вы уже несколько минут за клавиатурой, но камера всё это время не находит "
        "ваше лицо — значит, напоминания не приходят.\n\n"
        "Обычно причина в том, что камера смотрит не на вас: например, ноутбук стоит "
        "сбоку от монитора, в который вы смотрите.\n\n"
        "Откройте «Проверить кадр камеры…» в меню и поверните камеру так, чтобы рамка "
        "стала зелёной, либо выберите другую камеру в подменю «Камера»."
    ),
    "sensitivity": "Чувствительность",
    "sensitivity_low": "Низкая (меньше ложных срабатываний)",
    "sensitivity_normal": "Обычная",
    "sensitivity_high": "Высокая (ловит лёгкие моргания)",
    "pause_when_idle": "Пауза при бездействии",
    "pause_when_locked": "Пауза при блокировке экрана",
    "start_at_login": "Запускать при входе в систему",
    "stats": "Статистика за день…",
    "stats_title": "Blink Reminder — сегодня",
    "stats_body": (
        "Время за экраном: {active}\n"
        "Зафиксировано морганий: {blinks}\n"
        "Средняя частота: {rate} в минуту\n"
        "Напоминаний: {reminders}\n\n"
        "В этом сеансе: {session_blinks} морганий, {session_reminders} напоминаний."
    ),
    "quit": "Выйти",
    "camera_error_title": "Камера недоступна",
    "camera_error_body": (
        "Blink Reminder не может открыть камеру.\n\n"
        "Проверьте, что её не заняло другое приложение и что доступ разрешён в "
        "Настройках › Конфиденциальность и безопасность › Камера."
    ),
    "camera_denied_body": (
        "Доступ к камере для Blink Reminder выключен.\n\n"
        "Откройте Настройки › Конфиденциальность и безопасность › Камера, разрешите доступ "
        "для Python (или для Терминала, если запускали оттуда) и запустите приложение заново."
    ),
    "unusable_body": (
        "Ваше лицо в кадре, но за две минуты не удалось измерить ни одного моргания — "
        "а две минуты без моргания человек не выдерживает.\n\n"
        "Почти наверняка камера смотрит на вас под слишком острым углом и не видит, "
        "как опускаются веки: так бывает, когда ноутбук стоит сбоку от монитора, "
        "в который вы смотрите.\n\n"
        "Напоминания приостановлены — сейчас они были бы выдумкой. Откройте "
        "«Проверить кадр камеры…» и поверните камеру к лицу."
    ),
    "autostart_error_title": "Не удалось изменить автозапуск",
    "dur_hours": "ч",
    "dur_minutes": "мин",
}

_TABLES = {"en": EN, "ru": RU}
_active = EN


def _detect_language() -> str:
    for env in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env)
        if value:
            return "ru" if value.lower().startswith("ru") else "en"
    if sys.platform == "darwin":
        try:
            from Foundation import NSUserDefaults  # type: ignore

            langs = NSUserDefaults.standardUserDefaults().objectForKey_("AppleLanguages")
            if langs and str(langs[0]).lower().startswith("ru"):
                return "ru"
            if langs:
                return "en"
        except Exception:
            pass
    try:
        code = locale.getlocale()[0] or ""
    except ValueError:  # pragma: no cover - defensive
        code = ""
    return "ru" if code.lower().startswith("ru") else "en"


def set_language(preference: str = "auto") -> str:
    """Select the active table. Returns the language code actually used."""
    global _active
    code = preference if preference in _TABLES else _detect_language()
    _active = _TABLES[code]
    return code


def t(key: str, **kwargs) -> str:
    text = _active.get(key, EN.get(key, key))
    return text.format(**kwargs) if kwargs else text
