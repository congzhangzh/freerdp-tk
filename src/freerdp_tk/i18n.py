"""The languages of the window: English, Chinese, Japanese and French.

tr() takes the English text, the key, and gives it back in the window's
language; named {fields} are filled in from its keyword arguments. A text
without a translation stays English. Only what the window shows is
translated: the log stays English, so it can be searched and pasted into a
bug report, and the client writes English there anyway.

The language is picked once, before the window is built:
$FREERDP_TK_LANG, else the choice under the language button (settings.json
in the config folder), else the system's language. A Tk that draws with X
core fonts has no fonts for Chinese or Japanese, so there the system's
language only counts when it is English or French; choosing one by hand
still works.
"""

import os
import subprocess
import sys

LANGUAGES = {  # code -> its name in the menu, readable in any font
    "en": "English",
    "zh": "中文 (Chinese)",
    "ja": "日本語 (Japanese)",
    "fr": "Français (French)",
}
NEEDS_CJK = {"zh", "ja"}
AUTO = "auto"  # the setting that follows the system

language = "en"


def tr(text: str, /, **fields) -> str:
    """text in the window's language, with its {fields} filled in."""
    shown = TEXTS.get(language, {}).get(text, text)
    return shown.format(**fields) if fields else shown


def tr_in(code: str, text: str, /, **fields) -> str:
    """tr() in another language, as for the note that says the choice comes later."""
    shown = TEXTS.get(code, {}).get(text, text)
    return shown.format(**fields) if fields else shown


def code_of(name: str) -> str:
    """A language code from a locale name: zh_CN.UTF-8, zh-Hans-CN, fr_FR, ja: zh, fr, ja."""
    code = name.strip().split(":")[0].split(".")[0].replace("-", "_").split("_")[0].lower()
    return code if code in LANGUAGES else ""


def system_language() -> str:
    """The language the system speaks, as a code from LANGUAGES; "" when not one of them.

    The environment first, in gettext's order, then what Windows or macOS
    say for a window started without one (from the Start menu or Finder).
    """
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return code_of(value)
    if sys.platform == "win32":
        try:
            import ctypes
            import locale
            ui = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return code_of(locale.windows_locale.get(ui, ""))
        except (AttributeError, OSError):
            return ""
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
        first = out.strip("() \n").split(",")[0]  # ("zh-Hans-CN", "en-CN")
        return code_of(first.strip().strip('"'))
    return ""


def choose(setting: str, core_fonts: bool) -> tuple[str, str]:
    """The language to show, and a line for the log when the system's one was passed over."""
    forced = code_of(os.environ.get("FREERDP_TK_LANG", ""))
    if forced:
        return forced, ""
    if setting in LANGUAGES:
        return setting, ""
    system = system_language() or "en"
    if system in NEEDS_CJK and core_fonts:
        return "en", (f"language: English, not the system's {LANGUAGES[system]}: this Tk draws "
                      "with X core fonts, which usually lack its characters (choose it under "
                      "the language button to try)")
    return system, ""


def use(code: str) -> None:
    global language
    language = code if code in LANGUAGES else "en"


TEXTS = {
    "zh": {
        # dialogs
        "Full screen on these monitors:": "在这些显示器上全屏：",
        "monitor": "显示器",
        "{id}: {name}, {size} at {at}": "{id}：{name}，{size}，位置 {at}",
        "{text} (primary)": "{text}（主显示器）",
        "Cancel": "取消",
        "OK": "确定",
        "Save it in the system keyring": "保存到系统密钥环",
        "Changed: {fields}": "已更改：{fields}",
        "Discard": "不保存",
        "Save": "保存",
        # the window
        "Saved connections": "已保存的连接",
        "Empty connection": "空白连接",
        "Copy of this connection": "复制此连接",
        "New": "新建",
        "Delete": "删除",
        "Connection": "连接",
        "Display": "显示",
        "Devices": "设备",
        "Before / after": "连接前后",
        "Advanced": "高级",
        "Reset": "还原",
        "Command": "命令",
        "Connect": "连接",
        "Disconnect": "断开",
        "Copy command": "复制命令",
        "Clear log": "清空日志",
        "Running": "运行中",
        "Log": "日志",
        "Same as the system": "跟随系统",
        "freerdp-tk shows this language the next time it starts.":
            "freerdp-tk 下次启动时会显示这种语言。",
        # Connection
        "Name": "名称",
        "Client": "客户端",
        "Host": "主机",
        "Port": "端口",
        "User": "用户",
        "Domain": "域",
        "Forget": "忘记",
        "Password": "密码",
        "Remember it in the system keyring": "在系统密钥环中记住密码",
        "No system keyring: passwords stay in memory (the log says why)":
            "没有系统密钥环：密码只保存在内存中（原因见日志）",
        "Gateway": "网关",
        "Certificate": "证书",
        # Display
        "Full screen": "全屏",
        "Window size": "窗口大小",
        "Resize the remote desktop with the window": "远程桌面随窗口调整大小",
        "Use all monitors": "使用所有显示器",
        "List{dots}": "列出{dots}",
        "Monitors": "显示器",
        "Full screen on just these (IDs from List{dots}); empty: as above":
            "只在这些显示器上全屏（编号来自“列出{dots}”）；留空：按上面的设置",
        "Graphics codec": "图形编解码器",
        # Devices
        "Clipboard": "剪贴板",
        "Play remote sound here": "在本机播放远程声音",
        "Microphone": "麦克风",
        "Share home folder": "共享主目录",
        "Share folder": "共享文件夹",
        # Advanced
        "Log level": "日志级别",
        "Extra arguments": "额外参数",
        "e.g.  {example}": "例如  {example}",
        # Before / after
        "Before connecting": "连接前运行",
        "Keep it running during the session (don't wait for it to end)":
            "在会话期间保持运行（不等它结束）",
        "Stop it, and all it started, when the session ends": "会话结束时停止它，以及它启动的一切",
        "Then wait until": "然后等待",
        "seconds (empty: {timeout} for the wait, no limit on the command)":
            "秒（留空：等待最多 {timeout} 秒，命令本身不限时）",
        "Give up after": "超时放弃",
        "Client proxy": "客户端代理",
        "After disconnecting": "断开后运行",
        "%h host   %p port   %u user   %L a free local port   %% a %":
            "%h 主机   %p 端口   %u 用户   %L 一个空闲的本地端口   %% 一个 %",
        "Fill in: SSH tunnel{dots}": "填入：SSH 隧道{dots}",
        "SSH jump host: user@host[:port], or a Host from ~/.ssh/config":
            "SSH 跳板机：user@host[:port]，或 ~/.ssh/config 里的 Host",
        # the command preview
        "<no client found>": "<未找到客户端>",
        "error in extra arguments: {error}": "额外参数有误：{error}",
        # messages
        "{name}: no FreeRDP SDL client found. Install FreeRDP 3 with its SDL client, or "
        "choose one under Connection {arrow} Client.":
            "{name}：未找到 FreeRDP SDL 客户端。请安装带 SDL 客户端的 FreeRDP 3，"
            "或在“连接 {arrow} 客户端”中选择一个。",
        "{name}: {client} did not start:\n{error}": "{name}：{client} 没有启动：\n{error}",
        "{name}: {client} is not a FreeRDP 3 client. freerdp-tk passes the password on "
        "standard input (/args-from:stdin), which needs FreeRDP 3.":
            "{name}：{client} 不是 FreeRDP 3 客户端。freerdp-tk 通过标准输入"
            "（/args-from:stdin）传递密码，这需要 FreeRDP 3。",
        "Enter a host to connect to.": "请输入要连接的主机。",
        "{name}: this desktop has no monitor right now (its screen is 0x0), so the client "
        "has nowhere to show the remote desktop. Connect again once a monitor or a remote "
        "session is attached.":
            "{name}：这台桌面现在没有显示器（屏幕为 0x0），客户端无处显示远程桌面。"
            "接上显示器或远程会话后再连接。",
        "Password for {user} on {name}": "{name} 上 {user} 的密码",
        "{name}: extra arguments: {error}": "{name}：额外参数：{error}",
        "{name}: values must not contain line breaks.": "{name}：值里不能有换行。",
        "The server did not accept the password for {user} on {name}.\nTry another one:":
            "服务器没有接受 {name} 上 {user} 的密码。\n请换一个试试：",
        "{count} session(s) still running. Close them and quit?":
            "还有 {count} 个会话在运行。关闭它们并退出吗？",
        "Connect {count}": "连接 {count} 个",
        "1 unsaved change": "1 处更改未保存",
        "{count} unsaved changes": "{count} 处更改未保存",
        "Not saved yet": "尚未保存",
        "Save the changes to {name}?": "保存对 {name} 的更改吗？",
        "Save this new connection?": "保存这个新连接吗？",
        "Enter a name or a host first.": "请先输入名称或主机。",
        "Delete {names}?": "删除 {names} 吗？",
        "The password was not saved.\n\n{error}": "密码没有保存。\n\n{error}",
        "Enter the host and the user whose password to forget.": "请输入要忘记密码的主机和用户。",
        "FreeRDP client": "FreeRDP 客户端",
        "No FreeRDP SDL client found to list the monitors.":
            "没有找到能列出显示器的 FreeRDP SDL 客户端。",
        "The client found no monitors (the log has its output).":
            "客户端没有找到显示器（它的输出见日志）。",
        "Folder to share": "要共享的文件夹",
        # choices in the lists; what is saved stays English
        "(auto: SDL client)": "（自动：SDL 客户端）",
        "a port answers": "端口有响应",
        "the output shows": "输出中出现",
        "seconds have passed": "过了若干秒",
        "(default)": "（默认）",
        "off": "关闭",
    },
    "ja": {
        "Full screen on these monitors:": "次のモニターでフルスクリーン:",
        "monitor": "モニター",
        "{id}: {name}, {size} at {at}": "{id}: {name}、{size}、位置 {at}",
        "{text} (primary)": "{text}（メイン）",
        "Cancel": "キャンセル",
        "OK": "OK",
        "Save it in the system keyring": "システムのキーリングに保存する",
        "Changed: {fields}": "変更: {fields}",
        "Discard": "破棄",
        "Save": "保存",
        "Saved connections": "保存済みの接続",
        "Empty connection": "空の接続",
        "Copy of this connection": "この接続のコピー",
        "New": "新規",
        "Delete": "削除",
        "Connection": "接続",
        "Display": "画面",
        "Devices": "デバイス",
        "Before / after": "前後の処理",
        "Advanced": "詳細",
        "Reset": "元に戻す",
        "Command": "コマンド",
        "Connect": "接続",
        "Disconnect": "切断",
        "Copy command": "コマンドをコピー",
        "Clear log": "ログを消去",
        "Running": "実行中",
        "Log": "ログ",
        "Same as the system": "システムと同じ",
        "freerdp-tk shows this language the next time it starts.":
            "次回の起動から、freerdp-tk はこの言語で表示されます。",
        "Name": "名前",
        "Client": "クライアント",
        "Host": "ホスト",
        "Port": "ポート",
        "User": "ユーザー",
        "Domain": "ドメイン",
        "Forget": "忘れる",
        "Password": "パスワード",
        "Remember it in the system keyring": "システムのキーリングに記憶する",
        "No system keyring: passwords stay in memory (the log says why)":
            "システムのキーリングがありません: パスワードはメモリにだけ保持されます（理由はログに）",
        "Gateway": "ゲートウェイ",
        "Certificate": "証明書",
        "Full screen": "フルスクリーン",
        "Window size": "ウィンドウサイズ",
        "Resize the remote desktop with the window": "ウィンドウに合わせてリモートデスクトップのサイズを変える",
        "Use all monitors": "すべてのモニターを使う",
        "List{dots}": "一覧{dots}",
        "Monitors": "モニター",
        "Full screen on just these (IDs from List{dots}); empty: as above":
            "これらのモニターだけでフルスクリーン（ID は「一覧{dots}」から）。空欄: 上の設定どおり",
        "Graphics codec": "グラフィックコーデック",
        "Clipboard": "クリップボード",
        "Play remote sound here": "リモートの音をここで鳴らす",
        "Microphone": "マイク",
        "Share home folder": "ホームフォルダーを共有",
        "Share folder": "共有フォルダー",
        "Log level": "ログレベル",
        "Extra arguments": "追加の引数",
        "e.g.  {example}": "例:  {example}",
        "Before connecting": "接続前に実行",
        "Keep it running during the session (don't wait for it to end)":
            "セッション中も動かしておく（終わるのを待たない）",
        "Stop it, and all it started, when the session ends":
            "セッションが終わったら、それと、それが起動したものをすべて止める",
        "Then wait until": "その後、次まで待つ",
        "seconds (empty: {timeout} for the wait, no limit on the command)":
            "秒（空欄: 待機は {timeout} 秒、コマンド自体は無制限）",
        "Give up after": "打ち切るまで",
        "Client proxy": "クライアントのプロキシ",
        "After disconnecting": "切断後に実行",
        "%h host   %p port   %u user   %L a free local port   %% a %":
            "%h ホスト   %p ポート   %u ユーザー   %L 空いているローカルポート   %% % そのもの",
        "Fill in: SSH tunnel{dots}": "入力: SSH トンネル{dots}",
        "SSH jump host: user@host[:port], or a Host from ~/.ssh/config":
            "SSH 踏み台ホスト: user@host[:port]、または ~/.ssh/config の Host",
        "<no client found>": "<クライアントが見つかりません>",
        "error in extra arguments: {error}": "追加の引数にエラー: {error}",
        "{name}: no FreeRDP SDL client found. Install FreeRDP 3 with its SDL client, or "
        "choose one under Connection {arrow} Client.":
            "{name}: FreeRDP SDL クライアントが見つかりません。SDL クライアント付きの FreeRDP 3 "
            "をインストールするか、「接続 {arrow} クライアント」で選んでください。",
        "{name}: {client} did not start:\n{error}": "{name}: {client} を起動できませんでした:\n{error}",
        "{name}: {client} is not a FreeRDP 3 client. freerdp-tk passes the password on "
        "standard input (/args-from:stdin), which needs FreeRDP 3.":
            "{name}: {client} は FreeRDP 3 のクライアントではありません。freerdp-tk はパスワードを"
            "標準入力（/args-from:stdin）で渡すので、FreeRDP 3 が必要です。",
        "Enter a host to connect to.": "接続先のホストを入力してください。",
        "{name}: this desktop has no monitor right now (its screen is 0x0), so the client "
        "has nowhere to show the remote desktop. Connect again once a monitor or a remote "
        "session is attached.":
            "{name}: このデスクトップには今モニターがありません（画面が 0x0）。"
            "リモートデスクトップを表示する場所がないため、モニターかリモートセッションを"
            "つないでから接続してください。",
        "Password for {user} on {name}": "{name} の {user} のパスワード",
        "{name}: extra arguments: {error}": "{name}: 追加の引数: {error}",
        "{name}: values must not contain line breaks.": "{name}: 値に改行を含めることはできません。",
        "The server did not accept the password for {user} on {name}.\nTry another one:":
            "サーバーは {name} の {user} のパスワードを受け付けませんでした。\n別のパスワードを試してください:",
        "{count} session(s) still running. Close them and quit?":
            "{count} 個のセッションが実行中です。閉じて終了しますか？",
        "Connect {count}": "{count} 件に接続",
        "1 unsaved change": "未保存の変更が 1 件",
        "{count} unsaved changes": "未保存の変更が {count} 件",
        "Not saved yet": "まだ保存されていません",
        "Save the changes to {name}?": "{name} への変更を保存しますか？",
        "Save this new connection?": "この新しい接続を保存しますか？",
        "Enter a name or a host first.": "先に名前かホストを入力してください。",
        "Delete {names}?": "{names} を削除しますか？",
        "The password was not saved.\n\n{error}": "パスワードは保存されませんでした。\n\n{error}",
        "Enter the host and the user whose password to forget.":
            "パスワードを忘れさせるホストとユーザーを入力してください。",
        "FreeRDP client": "FreeRDP クライアント",
        "No FreeRDP SDL client found to list the monitors.":
            "モニターを一覧表示できる FreeRDP SDL クライアントが見つかりません。",
        "The client found no monitors (the log has its output).":
            "クライアントはモニターを見つけられませんでした（出力はログにあります）。",
        "Folder to share": "共有するフォルダー",
        "(auto: SDL client)": "（自動: SDL クライアント）",
        "a port answers": "ポートが応答する",
        "the output shows": "出力に現れる",
        "seconds have passed": "指定の秒数が経つ",
        "(default)": "（既定）",
        "off": "オフ",
    },
    "fr": {
        "Full screen on these monitors:": "Plein écran sur ces écrans :",
        "monitor": "écran",
        "{id}: {name}, {size} at {at}": "{id} : {name}, {size} à {at}",
        "{text} (primary)": "{text} (principal)",
        "Cancel": "Annuler",
        "OK": "OK",
        "Save it in the system keyring": "L'enregistrer dans le trousseau du système",
        "Changed: {fields}": "Modifié : {fields}",
        "Discard": "Abandonner",
        "Save": "Enregistrer",
        "Saved connections": "Connexions enregistrées",
        "Empty connection": "Connexion vide",
        "Copy of this connection": "Copie de cette connexion",
        "New": "Nouveau",
        "Delete": "Supprimer",
        "Connection": "Connexion",
        "Display": "Affichage",
        "Devices": "Périphériques",
        "Before / after": "Avant / après",
        "Advanced": "Avancé",
        "Reset": "Rétablir",
        "Command": "Commande",
        "Connect": "Connecter",
        "Disconnect": "Déconnecter",
        "Copy command": "Copier la commande",
        "Clear log": "Vider le journal",
        "Running": "En cours",
        "Log": "Journal",
        "Same as the system": "Comme le système",
        "freerdp-tk shows this language the next time it starts.":
            "freerdp-tk affichera cette langue à son prochain démarrage.",
        "Name": "Nom",
        "Client": "Client",
        "Host": "Hôte",
        "Port": "Port",
        "User": "Utilisateur",
        "Domain": "Domaine",
        "Forget": "Oublier",
        "Password": "Mot de passe",
        "Remember it in the system keyring": "Le retenir dans le trousseau du système",
        "No system keyring: passwords stay in memory (the log says why)":
            "Pas de trousseau système : les mots de passe restent en mémoire (le journal dit pourquoi)",
        "Gateway": "Passerelle",
        "Certificate": "Certificat",
        "Full screen": "Plein écran",
        "Window size": "Taille de la fenêtre",
        "Resize the remote desktop with the window": "Redimensionner le bureau distant avec la fenêtre",
        "Use all monitors": "Utiliser tous les écrans",
        "List{dots}": "Lister{dots}",
        "Monitors": "Écrans",
        "Full screen on just these (IDs from List{dots}); empty: as above":
            "Plein écran sur ceux-ci seulement (numéros donnés par Lister{dots}) ; vide : comme ci-dessus",
        "Graphics codec": "Codec graphique",
        "Clipboard": "Presse-papiers",
        "Play remote sound here": "Jouer ici le son distant",
        "Microphone": "Microphone",
        "Share home folder": "Partager le dossier personnel",
        "Share folder": "Partager un dossier",
        "Log level": "Niveau de journal",
        "Extra arguments": "Arguments supplémentaires",
        "e.g.  {example}": "p. ex.  {example}",
        "Before connecting": "Avant la connexion",
        "Keep it running during the session (don't wait for it to end)":
            "Le laisser tourner pendant la session (ne pas attendre sa fin)",
        "Stop it, and all it started, when the session ends":
            "L'arrêter, avec tout ce qu'il a lancé, à la fin de la session",
        "Then wait until": "Puis attendre que",
        "seconds (empty: {timeout} for the wait, no limit on the command)":
            "secondes (vide : {timeout} pour l'attente, pas de limite pour la commande)",
        "Give up after": "Abandonner après",
        "Client proxy": "Proxy du client",
        "After disconnecting": "Après la déconnexion",
        "%h host   %p port   %u user   %L a free local port   %% a %":
            "%h hôte   %p port   %u utilisateur   %L un port local libre   %% un %",
        "Fill in: SSH tunnel{dots}": "Remplir : tunnel SSH{dots}",
        "SSH jump host: user@host[:port], or a Host from ~/.ssh/config":
            "Hôte de rebond SSH : user@host[:port], ou un Host de ~/.ssh/config",
        "<no client found>": "<aucun client trouvé>",
        "error in extra arguments: {error}": "erreur dans les arguments supplémentaires : {error}",
        "{name}: no FreeRDP SDL client found. Install FreeRDP 3 with its SDL client, or "
        "choose one under Connection {arrow} Client.":
            "{name} : aucun client FreeRDP SDL trouvé. Installez FreeRDP 3 avec son client SDL, "
            "ou choisissez-en un sous Connexion {arrow} Client.",
        "{name}: {client} did not start:\n{error}": "{name} : {client} n'a pas démarré :\n{error}",
        "{name}: {client} is not a FreeRDP 3 client. freerdp-tk passes the password on "
        "standard input (/args-from:stdin), which needs FreeRDP 3.":
            "{name} : {client} n'est pas un client FreeRDP 3. freerdp-tk passe le mot de passe "
            "sur l'entrée standard (/args-from:stdin), ce qui demande FreeRDP 3.",
        "Enter a host to connect to.": "Saisissez l'hôte auquel se connecter.",
        "{name}: this desktop has no monitor right now (its screen is 0x0), so the client "
        "has nowhere to show the remote desktop. Connect again once a monitor or a remote "
        "session is attached.":
            "{name} : ce bureau n'a pas d'écran pour le moment (son écran fait 0x0), "
            "le client n'a donc nulle part où afficher le bureau distant. Reconnectez-vous "
            "une fois un écran branché ou une session distante ouverte.",
        "Password for {user} on {name}": "Mot de passe de {user} sur {name}",
        "{name}: extra arguments: {error}": "{name} : arguments supplémentaires : {error}",
        "{name}: values must not contain line breaks.":
            "{name} : les valeurs ne doivent pas contenir de saut de ligne.",
        "The server did not accept the password for {user} on {name}.\nTry another one:":
            "Le serveur n'a pas accepté le mot de passe de {user} sur {name}.\nEssayez-en un autre :",
        "{count} session(s) still running. Close them and quit?":
            "{count} session(s) encore en cours. Les fermer et quitter ?",
        "Connect {count}": "Connecter {count}",
        "1 unsaved change": "1 modification non enregistrée",
        "{count} unsaved changes": "{count} modifications non enregistrées",
        "Not saved yet": "Pas encore enregistrée",
        "Save the changes to {name}?": "Enregistrer les modifications de {name} ?",
        "Save this new connection?": "Enregistrer cette nouvelle connexion ?",
        "Enter a name or a host first.": "Saisissez d'abord un nom ou un hôte.",
        "Delete {names}?": "Supprimer {names} ?",
        "The password was not saved.\n\n{error}": "Le mot de passe n'a pas été enregistré.\n\n{error}",
        "Enter the host and the user whose password to forget.":
            "Saisissez l'hôte et l'utilisateur dont il faut oublier le mot de passe.",
        "FreeRDP client": "Client FreeRDP",
        "No FreeRDP SDL client found to list the monitors.":
            "Aucun client FreeRDP SDL trouvé pour lister les écrans.",
        "The client found no monitors (the log has its output).":
            "Le client n'a trouvé aucun écran (le journal montre sa sortie).",
        "Folder to share": "Dossier à partager",
        "(auto: SDL client)": "(auto : client SDL)",
        "a port answers": "un port réponde",
        "the output shows": "la sortie affiche",
        "seconds have passed": "des secondes passent",
        "(default)": "(par défaut)",
        "off": "désactivé",
    },
}
