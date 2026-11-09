"""Termux system names observed in the 2026-11-08 userland and app-source probe."""
import os
import platform

# Fixed names only. PWD and SHLVL are recreated by bash, not inherited.
TERMUX_SYSTEM_NAMES = frozenset({
    "PREFIX", "LD_PRELOAD", "LD_LIBRARY_PATH", "TZ",
    "ANDROID_ART_ROOT", "ANDROID_ASSETS", "ANDROID_DATA", "ANDROID_ROOT",
    "ANDROID_RUNTIME_ROOT", "ANDROID_STORAGE", "ANDROID_TZDATA_ROOT",
    "ASEC_MOUNTPOINT", "BOOTCLASSPATH", "EXTERNAL_STORAGE", "LOOP_MOUNTPOINT",
    "SYSTEMSERVERCLASSPATH",
})


def is_termux():
    return os.environ.get("PREFIX", "").rstrip("/").endswith("/com.termux/files/usr")


def device_os():
    return "Android (Termux)" if is_termux() else platform.system()


def system_environment_names():
    return TERMUX_SYSTEM_NAMES if is_termux() else frozenset()
