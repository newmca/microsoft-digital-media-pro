import pytest

from dmpkeys.core.config import Action, Config, Kind


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path, monkeypatch):
    """Never touch the real user's config, state or launchers."""
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var.lower()))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.delenv("APPIMAGE", raising=False)


@pytest.fixture
def owner_setup() -> Config:
    """The setup the app was built around: every special key in use."""
    c = Config()
    c.set_action("slider_up", Action(Kind.KEY, "brightnessup"))
    c.set_action("slider_down", Action(Kind.KEY, "brightnessdown"))
    c.set_action("fav_star", Action(Kind.APP, "systemsettings.desktop", "System Settings"))
    for n, app in enumerate(["org.kde.konsole.desktop", "herdr-app.desktop", "unityhub.desktop",
                             "com.microsoft.VSCode.desktop", "steam.desktop"], 1):
        c.set_action(f"fav{n}", Action(Kind.APP, app))
    c.set_action("my_documents", Action(Kind.FOLDER, "/home/u/Documents"))
    c.set_action("my_pictures", Action(Kind.FOLDER, "/home/u/Pictures"))
    c.set_action("my_music", Action(Kind.APP, "rocks.spotifast.Spotifast.desktop"))
    c.set_action("mail", Action(Kind.APP, "net.thunderbird.Thunderbird.desktop"))
    c.set_action("web_home", Action(Kind.APP, "org.mozilla.firefox.desktop"))
    c.set_action("messenger", Action(Kind.APP, "org.telegram.desktop.desktop"))
    return c
