"""The window's languages: every text has its translations, and the window shows them."""

import ast
import json
import string
from pathlib import Path

import pytest
from helpers import widgets

from freerdp_tk import app, i18n

SOURCE = Path(app.__file__)


def keys_in_source() -> set[str]:
    """The English texts the window passes to tr() and tr_in(), plus the list choices."""
    keys = {app.PLACEHOLDERS, *app.SHOWN_CHOICES}
    for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        arg = {"tr": 0, "tr_in": 1}.get(name)
        if arg is not None and len(node.args) > arg and isinstance(node.args[arg], ast.Constant):
            keys.add(node.args[arg].value)
    return keys


def fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_the_source_uses_tr():
    assert {"Connect", "Save", "Password for {user} on {name}", "(auto: SDL client)"} <= \
        keys_in_source()


@pytest.mark.parametrize("code", ["zh", "ja", "fr"])
def test_every_text_has_a_translation(code):
    table, keys = i18n.TEXTS[code], keys_in_source()
    assert sorted(keys - table.keys()) == [], "not translated"
    assert sorted(table.keys() - keys) == [], "translated, but not used"
    for key, text in table.items():
        assert fields(text) == fields(key), key
        assert text.strip(), key


def test_the_languages_are_the_four():
    assert set(i18n.LANGUAGES) == {"en", "zh", "ja", "fr"} and set(i18n.TEXTS) == {"zh", "ja", "fr"}


@pytest.mark.parametrize("name, code", [
    ("zh_CN.UTF-8", "zh"), ("zh-Hans-CN", "zh"), ("ja_JP.UTF-8", "ja"), ("fr_FR", "fr"),
    ("fr_CA:en", "fr"), ("en_US.UTF-8", "en"), ("C", ""), ("de_DE.UTF-8", ""), ("", ""),
])
def test_code_of(name, code):
    assert i18n.code_of(name) == code


def test_tr_fills_in_and_falls_back():
    i18n.use("fr")
    assert i18n.tr("Delete {names}?", names="a, b") == "Supprimer a, b ?"
    assert i18n.tr("not a key") == "not a key"
    assert i18n.tr_in("zh", "Connect") == "连接"
    i18n.use("xx")
    assert i18n.language == "en" and i18n.tr("Connect") == "Connect"


@pytest.fixture
def system(monkeypatch):
    """Set the system's language through the environment, as gettext reads it."""
    monkeypatch.delenv("FREERDP_TK_LANG", raising=False)
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(var, raising=False)
    return lambda value: monkeypatch.setenv("LANG", value)


def test_choose(system, monkeypatch):
    system("ja_JP.UTF-8")
    assert i18n.choose(i18n.AUTO, core_fonts=False) == ("ja", "")
    assert i18n.choose("fr", core_fonts=False) == ("fr", "")  # chosen beats the system
    code, note = i18n.choose(i18n.AUTO, core_fonts=True)  # no fonts for it: English, and why
    assert code == "en" and "core fonts" in note
    assert i18n.choose("ja", core_fonts=True) == ("ja", "")  # chosen by hand: tried anyway
    system("fr_FR.UTF-8")
    assert i18n.choose(i18n.AUTO, core_fonts=True) == ("fr", "")
    system("de_DE.UTF-8")
    assert i18n.choose(i18n.AUTO, core_fonts=False) == ("en", "")
    monkeypatch.setenv("FREERDP_TK_LANG", "zh")
    assert i18n.choose("fr", core_fonts=False) == ("zh", "")


def combobox_with(ui, value):
    return next(w for w in widgets(ui)
                if w.winfo_class() == "TCombobox" and value in w.cget("values"))


def test_the_window_in_chinese(make_ui, home, system):
    system("en_US.UTF-8")
    settings = home / "cfg" / "freerdp-tk" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"language": "zh"}))
    ui = make_ui()
    assert ui.connect_button.cget("text") == "连接"
    assert [ui.tabs.tab(t, "text") for t in ui.tabs.tabs()] == [
        "连接", "显示", "设备", "连接前后", "高级"]

    # the list shows Chinese, the form keeps English, both ways
    kinds = combobox_with(ui, "端口有响应")
    ui.vars["pre_wait_kind"].set(app.WAIT_TIME)
    assert kinds.get() == "过了若干秒"
    kinds.set("输出中出现")
    assert ui.vars["pre_wait_kind"].get() == app.WAIT_OUTPUT
    client = combobox_with(ui, "（自动：SDL 客户端）")
    assert client.get() == "（自动：SDL 客户端）" and ui.vars["client"].get() == app.AUTO
    client.set("/opt/freerdp/sdl-freerdp")  # typed in: kept as it is
    assert ui.vars["client"].get() == "/opt/freerdp/sdl-freerdp"

    ui.name.set("lab")
    ui.vars["host"].set("rdp.example.com")
    assert ui.change_note.cget("text") == "4 处更改未保存"  # name, host, wait, client
    assert ui._save()
    saved = json.loads(ui.store.read_text())["lab"]
    assert saved["pre_wait_kind"] == app.WAIT_OUTPUT and saved["gfx"] == "(default)"
    assert "过了" not in ui.store.read_text() and "默认" not in ui.store.read_text()
    assert "saved 'lab'" in ui.log.get("1.0", "end")  # the log stays English


def test_the_language_button(make_ui, home, monkeypatch):
    told = []
    monkeypatch.setattr(app.messagebox, "showinfo", lambda title, text: told.append(text))
    ui = make_ui()
    menu = ui.language_menu
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
    assert labels == ["Same as the system", *i18n.LANGUAGES.values()]
    menu.invoke(labels.index(i18n.LANGUAGES["fr"]))
    settings = home / "cfg" / "freerdp-tk" / "settings.json"
    assert json.loads(settings.read_text()) == {"language": "fr"}
    assert told == ["freerdp-tk affichera cette langue à son prochain démarrage."]
    assert ui.connect_button.cget("text") == "Connect"  # from the next start
    menu.invoke(labels.index("English"))  # the language it shows now: nothing to say
    assert json.loads(settings.read_text()) == {"language": "en"} and len(told) == 1
