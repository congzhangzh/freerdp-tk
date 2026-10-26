from freerdp_tk import app
from freerdp_tk.app import build_args


def test_minimal():
    assert build_args({"host": " pc.example.com "}, "")[:2] == ["/v:pc.example.com", "/cert:tofu"]


def test_password_and_options():
    args = build_args({"host": "h", "user": "alice", "domain": "LAB", "gfx": "AV1:i444",
                       "fullscreen": True, "clipboard": False}, "pw")
    assert {"/u:alice", "/d:LAB", "/p:pw", "/gfx:AV1:i444", "/f", "-clipboard"} <= set(args)
    assert not any(a.startswith("/size:") for a in args)  # full screen wins over a size


def test_extra_arguments_are_split_like_a_shell():
    assert build_args({"host": "h", "extra": "/scale:140 '/t:a b' /t:\"c d\""}, "")[-3:] == [
        "/scale:140", "/t:a b", "/t:c d"]


def test_backslashes_in_extra_arguments(monkeypatch):
    monkeypatch.setattr(app, "IS_WIN", True)  # a path separator there, not an escape
    assert app.split_extra(r'/drive:s,C:\share "/t:a b"') == [r"/drive:s,C:\share", "/t:a b"]
    monkeypatch.setattr(app, "IS_WIN", False)
    assert app.split_extra(r"/t:a\ b") == ["/t:a b"]
    assert app.split_extra("/t:#1 /scale:140") == ["/t:#1", "/scale:140"]


def test_drive_is_named_after_the_folder():
    assert "/drive:share,/srv/share" in build_args({"host": "h", "drive": "/srv/share"}, "")


def test_monitor_list_is_parsed():
    output = ("listing 3 monitors:\n"
              "     * [1] [Built-in Retina Display] 1512x982\t+0+0\n"
              "       [4] [DELL U2720Q] 2560x1440\t+-2560+0\n"
              "       [5] [] 1920x1080\t+1512+-200\n")
    assert app.parse_monitors(output) == [
        {"id": "1", "name": "Built-in Retina Display", "size": "1512x982", "at": "+0+0",
         "primary": True},
        {"id": "4", "name": "DELL U2720Q", "size": "2560x1440", "at": "+-2560+0",
         "primary": False},
        {"id": "5", "name": "", "size": "1920x1080", "at": "+1512+-200", "primary": False}]
    assert app.parse_monitors("listing 0 monitors:\n") == []


def test_chosen_monitors():
    args = build_args({"host": "h", "monitors": " 2, 3"}, "")
    assert "/multimon" in args and "/monitors:2,3" in args  # the client needs one or the other
    args = build_args({"host": "h", "monitors": "2", "fullscreen": True}, "")
    assert "/f" in args and "/monitors:2" in args and "/multimon" not in args
    args = build_args({"host": "h", "monitors": "2", "multimon": True}, "")
    assert args.count("/multimon") == 1
    assert not any(a.startswith(("/monitors", "/multimon")) for a in build_args({"host": "h"}, ""))
