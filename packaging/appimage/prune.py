#!/usr/bin/env python3
"""Shrink the PySide6 wheel contents bundled in the AppImage.

dmpkeys only uses QtCore, QtGui, QtWidgets, QtSvg, QtSvgWidgets and (indirectly)
QtDBus. Everything else (Quick/Qml/Designer/WebEngine bindings, translations,
tools, type stubs, unused Qt libraries and plugins) is deleted. Qt libraries are kept
by following DT_NEEDED from the kept bindings and plugins, so nothing a kept file
links against can go missing.

usage: prune.py <site-packages dir>
"""
import re
import subprocess
import sys
from pathlib import Path

KEEP_MODULES = {"QtCore", "QtGui", "QtWidgets", "QtSvg", "QtSvgWidgets", "QtDBus"}
KEEP_PLUGINS = {
    "platforms": {"libqxcb.so", "libqwayland.so", "libqoffscreen.so", "libqminimal.so"},
    "platformthemes": None,  # keep all
    "platforminputcontexts": {  # no Qt Virtual Keyboard (it drags in Qt Quick)
        "libcomposeplatforminputcontextplugin.so", "libibusplatforminputcontextplugin.so"},
    "iconengines": None,
    "imageformats": None,
    "xcbglintegrations": None,
    "wayland-decoration-client": None,
    "wayland-graphics-integration-client": None,
    "wayland-shell-integration": None,
}
DROP_PYSIDE_ENTRIES = {
    "assistant", "designer", "linguist", "lrelease", "lupdate", "qmlformat", "qmllint",
    "doc", "glue", "include", "scripts", "typesystems", "support", "examples", "lib",
    "qmlls", "svgtoqml",
}
DROP_QT_ENTRIES = {"qml", "translations", "metatypes", "libexec"}


def needed(path: Path) -> list[str]:
    out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\).*\[(.+)\]", out)


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        for child in path.iterdir():
            remove(child)
        path.rmdir()
    else:
        path.unlink()


def main(site: Path) -> None:
    pyside = site / "PySide6"
    qt = pyside / "Qt"

    for entry in DROP_PYSIDE_ENTRIES:
        if (pyside / entry).exists():
            remove(pyside / entry)
    for pyi in list(pyside.glob("*.pyi")) + list(pyside.glob("*.json")) + [pyside / "py.typed"]:
        pyi.unlink(missing_ok=True)
    for entry in DROP_QT_ENTRIES:
        if (qt / entry).exists():
            remove(qt / entry)
    for so in pyside.glob("Qt*.abi3.so"):
        if so.name.split(".")[0] not in KEEP_MODULES:
            so.unlink()
    for so in pyside.glob("libpyside6qml*"):
        so.unlink()

    plugins = qt / "plugins"
    for group in list(plugins.iterdir()):
        if group.name not in KEEP_PLUGINS:
            remove(group)
            continue
        keep = KEEP_PLUGINS[group.name]
        if keep is not None:
            for plugin in list(group.iterdir()):
                if plugin.name not in keep:
                    remove(plugin)

    # Keep exactly the Qt libraries reachable from the kept bindings and plugins.
    lib = qt / "lib"
    available = {p.name: p for p in lib.glob("lib*.so*")}
    roots = list(pyside.glob("Qt*.abi3.so")) + list(pyside.glob("libpyside6*")) + [
        p for p in plugins.rglob("*.so")]
    keep_libs: set[str] = set()
    queue = roots[:]
    while queue:
        for dep in needed(queue.pop()):
            if dep in available and dep not in keep_libs:
                keep_libs.add(dep)
                queue.append(available[dep])
    for name, path in available.items():
        if name not in keep_libs:
            path.unlink()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
