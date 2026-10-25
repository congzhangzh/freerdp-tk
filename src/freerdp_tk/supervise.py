"""Run a shell command so that it, and everything it starts, can be stopped for sure (POSIX).

freerdp-tk runs this file as  python supervise.py <command>  and keeps a pipe
to its stdin. The command's output passes straight through; when the command
itself exits, a line EXIT_MARK + <code> follows. Whatever the command left
running (a tunnel, a daemon) stays up until the pipe closes, because
freerdp-tk asked for it or because freerdp-tk died, even from SIGKILL: the
kernel closes a dead process's pipes. Then everything is stopped: SIGTERM,
then SIGKILL after GRACE seconds, until nothing is left.

What counts as "everything": every descendant of this process, plus every
member of the command's process group. On Linux this process is a child
subreaper (prctl PR_SET_CHILD_SUBREAPER), so orphans, even double-forked
daemons that called setsid, are reparented to it rather than to init and stay
descendants. macOS has no subreaper: a double-forked daemon that also left
the process group escapes to launchd there.
"""

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time

EXIT_MARK = "\x1efreerdp-tk exit "
GRACE = 3.0  # seconds between SIGTERM and SIGKILL
PR_SET_CHILD_SUBREAPER = 36


def become_subreaper():
    if sys.platform.startswith("linux"):
        ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)


def processes() -> list[tuple[int, int, int]]:
    """(pid, parent pid, process group) of every live process; zombies are left out."""
    found = []
    if os.path.isdir("/proc"):
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/stat") as f:
                    state, ppid, pgid = f.read().rsplit(")", 1)[1].split()[:3]
            except (OSError, ValueError):
                continue  # gone meanwhile
            if state != "Z":
                found.append((int(name), int(ppid), int(pgid)))
        return found
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat="], capture_output=True,
                         text=True).stdout
    for line in out.splitlines():
        pid, ppid, pgid, stat = line.split()[:4]
        if not stat.startswith("Z"):
            found.append((int(pid), int(ppid), int(pgid)))
    return found


def targets(group: int) -> list[int]:
    """Our descendants and the members of the command's process group."""
    procs = processes()
    children: dict[int, list[int]] = {}
    for pid, ppid, _ in procs:
        children.setdefault(ppid, []).append(pid)
    found, todo = set(), [os.getpid()]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    found |= {pid for pid, _, pgid in procs if pgid == group}
    found.discard(os.getpid())
    return sorted(found)


def stop_all(group: int):
    for sig, wait in ((signal.SIGTERM, GRACE), (signal.SIGKILL, 1.0)):
        deadline = time.monotonic() + wait
        while (pids := targets(group)) and time.monotonic() < deadline:
            for pid in pids:
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
            time.sleep(0.05)
    for _ in range(20):  # anything forked while we were killing
        pids = targets(group)
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(0.05)


def main():
    become_subreaper()
    command = subprocess.Popen(sys.argv[1], shell=True, stdin=subprocess.DEVNULL,
                               start_new_session=True)
    done = threading.Event()
    stopping = threading.Lock()

    def stop():
        if stopping.acquire(blocking=False):
            stop_all(command.pid)
            done.set()

    def watch_stdin():
        sys.stdin.buffer.read()  # returns at EOF: freerdp-tk closed the pipe, or died
        stop()

    threading.Thread(target=watch_stdin, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, lambda *_: threading.Thread(target=stop, daemon=True).start())

    # Reap every child, adopted orphans included; report the command's own exit.
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
        except ChildProcessError:  # nothing left to reap: wait for the stop, then go
            done.wait()
            return
        if pid == command.pid:
            command.returncode = os.waitstatus_to_exitcode(status)
            report(f"{EXIT_MARK}{command.returncode}")


def report(line: str):
    """Tell freerdp-tk; if it is gone (a crash closes the pipe), carry on cleaning up."""
    try:
        print(line, flush=True)
    except (BrokenPipeError, ValueError):
        sys.stdout = open(os.devnull, "w")  # nor fail when Python flushes it at exit


if __name__ == "__main__":
    main()
