"""Passwords in the system keyring: Credential Manager, Keychain, Secret Service or KWallet.

Each credential is an entry of its own, named after the account it logs in to:
service "freerdp-tk/<account>@<host>:<port>" (lowercase, port 3389 when empty)
and username "<account>", where the account is DOMAIN\\user or just user. The
key is the account, not the name of a saved connection: renaming a connection
keeps its password, and two connections to one account share it.

One service per credential keeps each Windows entry plain: its target name is
the service. With one service for all, keyring would move older users to
"user@service" targets and copy them on every save. Other clients can find
the entries the native way (CredRead, libsecret, SecItemCopyMatching).

Only the backends in SAFE are used, so a password never ends up in a plain
file, whatever keyring is configured to prefer.
"""

APP = "freerdp-tk"
DEFAULT_PORT = "3389"
SAFE = {  # keyring backends that keep passwords in the system's own store
    "keyring.backends.Windows.WinVaultKeyring",
    "keyring.backends.macOS.Keyring",
    "keyring.backends.SecretService.Keyring",
    "keyring.backends.libsecret.Keyring",
    "keyring.backends.kwallet.DBusKeyring",
    "keyring.backends.kwallet.DBusKeyringKWallet4",
}


class CredentialError(Exception):
    """The system keyring could not be used; the message says why."""


def key(v: dict) -> tuple[str, str] | None:
    """(service, username) for the connection settings v; None without a host or a user."""
    host, user = v.get("host", "").strip().lower(), v.get("user", "").strip()
    if not host or not user:
        return None
    domain = v.get("domain", "").strip()
    account = f"{domain}\\{user}" if domain else user
    port = v.get("port", "").strip() or DEFAULT_PORT
    return f"{APP}/{account.lower()}@{host}:{port}", account


def _name(backend) -> str:
    return f"{type(backend).__module__}.{type(backend).__qualname__}"


def backend():
    """The keyring backend to use; raises CredentialError when no safe one is there.

    keyring chains all backends it finds when there are several; then the
    first safe one in the chain is used, on its own.
    """
    try:
        import keyring
        from keyring.backends.chainer import ChainerBackend
    except ImportError as e:
        raise CredentialError(f"the Python package keyring is not installed ({e})") from e
    try:
        chosen = keyring.get_keyring()
        found = list(chosen.backends) if isinstance(chosen, ChainerBackend) else [chosen]
    except Exception as e:  # a broken keyring configuration
        raise CredentialError(f"no system keyring: {_reason(e)}") from e
    for b in found:
        if _name(b) in SAFE:
            return b
    offered = ", ".join(_name(b) for b in found) or "nothing"
    raise CredentialError(f"no system keyring found (keyring offers {offered})")


def problem() -> str:
    """Why the system keyring cannot be used; "" when it can."""
    try:
        backend()
    except CredentialError as e:
        return str(e)
    return ""


def load(v: dict) -> str | None:
    """The saved password for v, None when there is none."""
    k = key(v)
    return _call(lambda b: b.get_password(*k)) if k else None


def save(v: dict, password: str):
    k = key(v)
    if not k:
        raise CredentialError("saving a password needs a host and a user")

    def replace(b):
        if b.get_password(*k) is not None:  # or the Windows backend keeps a copy of the old one
            b.delete_password(*k)
        b.set_password(*k, password)

    _call(replace)


def forget(v: dict):
    """Remove the saved password for v, if there is one."""
    k = key(v)
    if k:
        _call(lambda b: b.get_password(*k) is not None and b.delete_password(*k))


def _call(action):
    b = backend()
    try:
        return action(b)
    except Exception as e:  # keyring's errors, and D-Bus, Win32 or Security framework ones
        raise CredentialError(f"system keyring: {_reason(e)}") from e


def _reason(e: Exception) -> str:
    return str(e) or type(e).__name__
