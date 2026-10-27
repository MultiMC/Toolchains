#!/usr/bin/env python3
"""hopper-top: the overview (overview.py) live in the terminal, like top; read-only.

    ssh -t hopper@mikoshi Toolchains/automation/hopper-top.py

SSH is the access control and the transport: whoever may log in as hopper may look.
It refreshes every REFRESH seconds. Keys:

  overview   up/down, PgUp/PgDn, Home/End  select a run
             Enter    that run's log
             h        that run's setup's own log (hopper.log: its looks, and crashes)
             r        refresh now
             q        quit
  log        up/down, PgUp/PgDn/space, Home/g, left/right   scroll
             End/G, f follow the end as it grows (on by default for a running run;
                      f turns it off again, so does scrolling up)
             / n N    search (case-insensitive), next, previous
             q, Esc   back

Nothing here changes anything; actions will be requests the running hopper picks up.
"""

import curses
import locale
import os
import time

import overview

REFRESH = 2.0
LOG_REFRESH = 1.0

GREEN, RED, YELLOW, CYAN = 1, 2, 3, 4
STATUS_COLORS = {"published": GREEN, "failed": RED, "interrupted": RED, "running": YELLOW}


def main():
    locale.setlocale(locale.LC_ALL, "")
    if "utf" not in (locale.nl_langinfo(locale.CODESET) or "").lower():
        try:  # ssh often brings no locale; logs are UTF-8
            locale.setlocale(locale.LC_ALL, "C.UTF-8")
        except locale.Error:
            pass
    try:
        curses.setupterm()
    except curses.error:  # the client's terminal isn't known here (kitty, ...)
        os.environ["TERM"] = "xterm-256color"
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(Top().run)


class Screen:
    def __init__(self, window):
        self.window = window

    def size(self):
        return self.window.getmaxyx()

    def line(self, y, pieces, fill=0):
        """Draw (text, attribute) pieces from the left of row y, clipped to the width."""
        height, width = self.size()
        if not 0 <= y < height:
            return
        x = 0
        if fill:
            self.put(y, 0, " " * width, fill)
        for text, attr in pieces:
            if x >= width:
                break
            self.put(y, x, text[:width - x], attr | fill)
            x += len(text)

    def put(self, y, x, text, attr):
        try:
            self.window.addstr(y, x, text, attr)
        except curses.error:  # the bottom right corner can't be written without scrolling
            pass


def color(number, bold=False):
    return curses.color_pair(number) | (curses.A_BOLD if bold else 0)


def age(text):
    """Seconds since a "YYYY-MM-DD HH:MM:SS" time."""
    return time.time() - time.mktime(time.strptime(text, overview.TIME)) if text else None


def size(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return "%.1f%s" % (n, unit) if unit in ("G", "T") else "%d%s" % (n, unit)
        n /= 1024


class Top:
    def run(self, window):
        self.screen = Screen(window)
        curses.use_default_colors()
        for number, foreground in ((GREEN, curses.COLOR_GREEN), (RED, curses.COLOR_RED),
                                   (YELLOW, curses.COLOR_YELLOW), (CYAN, curses.COLOR_CYAN)):
            curses.init_pair(number, foreground, -1)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        window.timeout(250)
        self.selected = None  # the selected run's log path
        self.offset = 0
        data, loaded = None, 0
        while True:
            if data is None or time.time() - loaded >= REFRESH:
                data, loaded = overview.gather(), time.time()
            runs = [(s, r) for s in data["setups"] for r in s["runs"]]
            runs.sort(key=lambda item: item[1]["time"], reverse=True)
            self.draw(data, runs)
            key = window.getch()
            if key in (ord("q"), ord("Q")):
                return
            if key == ord("r"):
                data = None
            elif key in (curses.KEY_ENTER, 10, 13) and self.current(runs):
                setup, run = self.current(runs)
                LogView(self.screen, run.get("log"), "%s %s %s" % (setup["name"], run["job"], run["label"]),
                        follow=run["status"] == "running").run()
                data = None
            elif key == ord("h"):
                setup = self.current(runs)[0] if self.current(runs) else data["setups"][0]
                LogView(self.screen, setup["log"], "%s hopper.log" % setup["name"], follow=True).run()
                data = None
            elif key in MOVES and runs:
                index = next((i for i, (_, r) in enumerate(runs) if r.get("log") == self.selected), 0)
                index = max(0, min(len(runs) - 1, MOVES[key](index, self.page)))
                self.selected = runs[index][1].get("log")

    def current(self, runs):
        for setup, run in runs:
            if run.get("log") == self.selected:
                return setup, run
        return runs[0] if runs else None

    def draw(self, data, runs):
        window, screen = self.screen.window, self.screen
        window.erase()
        height, width = screen.size()
        disk = data["disk"]
        build = data["release_build"]
        screen.line(0, [(" hopper-top  %s  %s" % (data["host"], data["time"][11:]), curses.A_BOLD),
                        ("   code %s" % data["code"] if data["code"] else "", 0),
                        ("   free %s of %s" % (size(disk["free"]), size(disk["total"])), 0),
                        ("   release build running (pid %d)" % build if build else "", 0)], fill=curses.A_REVERSE)
        y = 2
        for setup in data["setups"]:
            y = self.draw_setup(y, setup, data)
            y += 1
        y = self.draw_meta(y, data["meta"])
        y += 1
        screen.line(y, [("runs", curses.A_BOLD), ("  (Enter: log, h: hopper.log)", curses.A_DIM)])
        y += 1
        self.page = max(1, height - y - 1)
        if runs and self.current(runs)[1].get("log") != self.selected:
            self.selected = runs[0][1].get("log")
        index = next((i for i, (_, r) in enumerate(runs) if r.get("log") == self.selected), 0)
        self.offset = min(max(self.offset, index - self.page + 1), index)
        for i, (setup, run) in enumerate(runs[self.offset:self.offset + self.page]):
            mark = curses.A_REVERSE if self.offset + i == index else 0
            screen.line(y + i, self.run_pieces(setup, run), fill=mark)
        screen.line(height - 1, [(" up/down select  Enter log  h hopper.log  r refresh  q quit", curses.A_DIM)])
        window.refresh()

    def draw_setup(self, y, setup, data):
        screen = self.screen
        service, status = setup["service"], setup["status"] or {}
        enabled = service.get("UnitFileState") in ("enabled", "linked-runtime", "enabled-runtime")
        pieces = [("%-11s" % setup["name"], curses.A_BOLD)]
        running = [r for r in setup["runs"] if r["status"] == "running"]
        if setup["running"]:
            pieces.append(("hopper running", color(GREEN)))
            if service.get("ActiveState") == "active":
                pieces.append((" since %s" % overview.short_time(service.get("ActiveEnterTimestamp")), 0))
            if service.get("NRestarts"):
                pieces.append(("  %d restarts (h: hopper.log)" % service["NRestarts"], color(YELLOW, True)))
            if running:
                r = running[0]
                pieces.append(("  releasing %s %s: %s, %s" % (r["job"], r["label"], r.get("step"),
                                                               overview.duration(r["seconds"])), color(YELLOW, True)))
            elif status.get("looked") and status.get("pid") == setup["running"]:
                late = age(status["looked"])
                stale = late > 3 * status.get("interval", 60)
                pieces.append(("  looked %ds ago" % late, color(RED, True) if stale else curses.A_DIM))
            if status.get("problem"):
                pieces.append(("  last look failed: %s" % status["problem"], color(RED, True)))
            if status.get("code") and data["code"] and status["code"] != data["code"]:
                pieces.append(("  runs %s, checkout is %s: restart it" % (status["code"], data["code"]), color(YELLOW)))
        elif enabled:
            pieces.append(("hopper NOT running: service %s" % service.get("ActiveState"), color(RED, True)))
        else:
            pieces.append(("off (service %s, %s)" % (service.get("ActiveState"), service.get("UnitFileState")), curses.A_DIM))
        screen.line(y, pieces)
        y += 1
        for job in setup["jobs"]:
            screen.line(y, self.job_pieces(job))
            y += 1
        screen.line(y, self.live_pieces(setup["live"]))
        return y + 1

    def job_pieces(self, job):
        source = job["source"].split()[-1] if job["kind"] == "stream" else job["source"]
        if not job["enabled"]:
            return [("  %-13s %-12s off" % (job["name"], source), curses.A_DIM)]
        pieces = [("  %-13s %-12s " % (job["name"], source), 0)]
        last = job["last"]
        if last:
            pieces += self.result_pieces(last)
        seen = job["seen"] or {}
        if job.get("head_handled") is False:
            pieces.append(("  new commit %s" % seen["head"][:10], color(YELLOW, True)))
        if seen.get("next"):
            pieces.append(("  next %s" % seen["next"][5:], curses.A_DIM))
        published = job["last_published"]
        if published and last and published["time"] != last["time"]:
            pieces.append(("  last published %s" % overview.short_time(published["time"]), color(YELLOW)))
        return pieces

    def result_pieces(self, run):
        what = ("#%s " % run["build"] if run.get("build") else "") + run["label"]
        status = run["status"] + (" (%s)" % run["step"] if run.get("step") and run["status"] != "published" else "")
        return [("%-22s" % what, 0), ("%-22s" % status, color(STATUS_COLORS.get(run["status"], 0), run["status"] != "published")
                                     if run["status"] in STATUS_COLORS else curses.A_DIM),
                ("%s  %7s" % (overview.short_time(run["time"]), overview.duration(run["seconds"])), 0)]

    def live_pieces(self, live):
        pieces = [("  %-13s " % "live", curses.A_DIM)]
        for channel, versions in sorted(live["channels"].items()):
            ids = sorted(versions, key=lambda v: int(v) if v.isdigit() else 0, reverse=True)
            pieces.append(("%s %s  " % (channel, " ".join("%s%s" % (v, "x%d" % len(versions[v]) if len(versions[v]) > 1 else "")
                                                          for v in ids)), color(CYAN)))
        website = live["website"]
        if website:
            test, production = website.get("test"), website.get("production")
            pieces.append(("website %s  " % ("test = production" if test == production else "test %s, production %s" % (test, production)), color(CYAN)))
        published = live["published"]
        if published:
            pieces.append(("files: %s, %s" % (published.get("about") or published.get("kind"), published["snapshot"][:13]), curses.A_DIM))
        return pieces

    def draw_meta(self, y, meta):
        service, timer = meta["service"], meta["timer"]
        pieces = [("%-11s" % "meta", curses.A_BOLD)]
        if service.get("ActiveState") in ("active", "activating"):
            started = service.get("ExecMainStartTimestamp")
            pieces.append(("running for %s" % overview.duration(int(age(started))) if started else "running", color(YELLOW, True)))
        elif service.get("ExecMainStartTimestamp"):
            ok = service.get("Result") == "success"
            seconds = overview.seconds_between(service["ExecMainStartTimestamp"], service["InactiveEnterTimestamp"]) \
                if service.get("InactiveEnterTimestamp") else None
            pieces += [("last run %s  " % overview.short_time(service["ExecMainStartTimestamp"]), 0),
                       ("%-10s" % service.get("Result"), color(GREEN) if ok else color(RED, True)),
                       ("%7s" % overview.duration(seconds), 0)]
        else:
            pieces.append(("not run since the machine started", curses.A_DIM))
        if timer.get("NextElapseUSecRealtime"):
            pieces.append(("  next %s" % timer["NextElapseUSecRealtime"][11:16], curses.A_DIM))
        else:
            pieces.append(("  timer off", color(RED, True)))
        self.screen.line(y, pieces)
        self.screen.line(y + 1, [("  its output is only in the system journal (journalctl _SYSTEMD_USER_UNIT=meta.service, as an admin)", curses.A_DIM)])
        return y + 2

    def run_pieces(self, setup, run):
        return [(" %-11s %-13s " % (setup["name"], run["job"]), 0)] + self.result_pieces(run)


MOVES = {
    curses.KEY_UP: lambda i, page: i - 1, ord("k"): lambda i, page: i - 1,
    curses.KEY_DOWN: lambda i, page: i + 1, ord("j"): lambda i, page: i + 1,
    curses.KEY_PPAGE: lambda i, page: i - page, curses.KEY_NPAGE: lambda i, page: i + page,
    curses.KEY_HOME: lambda i, page: 0, curses.KEY_END: lambda i, page: 1 << 30,
}


class LogView:
    """A log file, read as it grows."""

    def __init__(self, screen, path, title, follow):
        self.screen, self.path, self.title, self.follow = screen, path, title, follow
        self.lines, self.read_to, self.partial = [], 0, ""
        self.top, self.left = 0, 0
        self.search, self.message = None, ""

    def load(self):
        try:
            with open(self.path, "rb") as f:
                if os.fstat(f.fileno()).st_size < self.read_to:  # replaced or truncated
                    self.lines, self.read_to, self.partial = [], 0, ""
                f.seek(self.read_to)
                data = f.read()
        except (OSError, TypeError):
            self.message = "can't read %s" % self.path
            return
        self.read_to += len(data)
        text = self.partial + data.decode("utf-8", "replace")
        parts = text.split("\n")
        self.partial = parts.pop()
        # a line rewritten with \r (progress) shows what it said last
        self.lines += [p.rstrip("\r").rsplit("\r", 1)[-1].expandtabs() for p in parts]

    def run(self):
        window = self.screen.window
        loaded = 0
        while True:
            if time.time() - loaded >= LOG_REFRESH:
                self.load()
                loaded = time.time()
            height, width = self.screen.size()
            page = max(1, height - 2)
            last_top = max(0, len(self.lines) - page)
            if self.follow:
                self.top = last_top
            self.top = max(0, min(self.top, last_top))
            self.draw(page)
            key = window.getch()
            if key == -1:
                continue
            if key in (ord("q"), 27):
                return
            moves = {curses.KEY_UP: -1, ord("k"): -1, curses.KEY_DOWN: 1, ord("j"): 1,
                     curses.KEY_PPAGE: -page, curses.KEY_NPAGE: page, ord(" "): page}
            if key in moves:
                self.top += moves[key]
            elif key in (curses.KEY_HOME, ord("g")):
                self.top, self.follow = 0, False
            elif key in (curses.KEY_END, ord("G")):
                self.top, self.follow = last_top, True
            elif key == curses.KEY_LEFT:
                self.left = max(0, self.left - 8)
            elif key == curses.KEY_RIGHT:
                self.left += 8
            elif key == ord("f"):
                self.follow = not self.follow
            elif key == ord("/"):
                self.search = self.prompt("/") or self.search
                self.find(1, start=self.top)
            elif key == ord("n"):
                self.find(1, start=self.top + 1)
            elif key == ord("N"):
                self.find(-1, start=self.top - 1)
            if key in moves and moves[key] < 0 or key in (ord("/"), ord("n"), ord("N")):
                self.follow = False

    def find(self, direction, start):
        if not self.search:
            return
        needle = self.search.lower()
        order = range(max(0, start), len(self.lines)) if direction > 0 else range(min(start, len(self.lines) - 1), -1, -1)
        for i in order:
            if needle in self.lines[i].lower():
                self.top, self.message = i, ""
                return
        self.message = "not found: %s" % self.search

    def prompt(self, label):
        window = self.screen.window
        height, width = self.screen.size()
        self.screen.line(height - 1, [(label, 0)], fill=0)
        window.move(height - 1, len(label))
        curses.echo()
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        window.timeout(-1)
        try:
            text = window.getstr(height - 1, len(label), max(1, width - len(label) - 1)).decode("utf-8", "replace")
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass
            window.timeout(250)
        return text.strip()

    def draw(self, page):
        window, screen = self.screen.window, self.screen
        window.erase()
        height, width = screen.size()
        screen.line(0, [(" %s  " % self.title, curses.A_BOLD), (self.path or "", 0),
                        ("  %d lines" % len(self.lines), 0), ("  following" if self.follow else "", curses.A_BOLD)],
                    fill=curses.A_REVERSE)
        needle = (self.search or "").lower()
        for i, text in enumerate(self.lines[self.top:self.top + page]):
            attr = 0
            if text.startswith("==="):
                attr = color(CYAN, True)
            elif "error" in text.lower() or "traceback" in text.lower() or " crashed:" in text:
                attr = color(RED)
            elif needle and needle in text.lower():
                attr = color(YELLOW, True)
            screen.line(1 + i, [(text[self.left:], attr)])
        bottom = min(len(self.lines), self.top + page)
        screen.line(height - 1, [(self.message or " %d-%d of %d   up/down PgUp/PgDn g/G left/right  f follow  / n N search  q back"
                                  % (self.top + 1 if self.lines else 0, bottom, len(self.lines)), curses.A_DIM)])
        window.refresh()


if __name__ == "__main__":
    main()
