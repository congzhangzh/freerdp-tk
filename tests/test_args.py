from freerdp_tk.app import build_args, client_kind


def test_minimal():
    assert build_args({"host": " pc.example.com "}, "")[:2] == ["/v:pc.example.com", "/cert:tofu"]


def test_password_and_options():
    args = build_args({"host": "h", "user": "alice", "domain": "LAB", "gfx": "AV1:i444",
                       "fullscreen": True, "clipboard": False}, "pw")
    assert {"/u:alice", "/d:LAB", "/p:pw", "/gfx:AV1:i444", "/f", "-clipboard"} <= set(args)
    assert not any(a.startswith("/size:") for a in args)  # full screen wins over a size


def test_extra_arguments_are_split_like_a_shell():
    assert build_args({"host": "h", "extra": "/scale:140 '/t:a b'"}, "")[-2:] == [
        "/scale:140", "/t:a b"]


def test_drive_is_named_after_the_folder():
    assert "/drive:share,/srv/share" in build_args({"host": "h", "drive": "/srv/share"}, "")


def test_client_kind():
    assert [client_kind(p) for p in ("/usr/bin/sdl3-freerdp", "xfreerdp", "wfreerdp.exe")] == [
        "sdl3", "x11", "windows"]
