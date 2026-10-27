"""Cron-style schedules: "minute hour day-of-month month day-of-week".

Each field is *, a number, a range a-b, a list a,b,c, or any of those with a step (*/15,
1-30/2). Day of week: 0-7, 0 and 7 are Sunday. As in cron, when both day of month and day
of week are restricted, a day matching either one is a match.

    Schedule("0 12 * * *").latest(now)    # the most recent scheduled minute at or before now
    Schedule("0 12 * * *").next(now)      # the first one after now
"""

import datetime

FIELDS = [("minute", 0, 59), ("hour", 0, 23), ("day of month", 1, 31), ("month", 1, 12), ("day of week", 0, 7)]


class Schedule:
    def __init__(self, expression):
        parts = expression.split()
        if len(parts) != 5:
            raise ValueError("a schedule has 5 fields (minute hour day-of-month month day-of-week): %r" % expression)
        self.expression = expression
        self.minutes, self.hours, self.days, self.months, weekdays = (
            parse_field(part, name, low, high) for part, (name, low, high) in zip(parts, FIELDS))
        self.weekdays = {d % 7 for d in weekdays}  # 7 is Sunday too
        self.any_day = parts[2] == "*"
        self.any_weekday = parts[4] == "*"

    def day_matches(self, day):
        if day.month not in self.months:
            return False
        by_date = day.day in self.days
        by_weekday = (day.isoweekday() % 7) in self.weekdays
        if self.any_day or self.any_weekday:
            return by_date and by_weekday
        return by_date or by_weekday

    def latest(self, now, days_back=400):
        """The most recent scheduled minute at or before `now` (a datetime), or None if there
        was none in the last `days_back` days."""
        now = now.replace(second=0, microsecond=0)
        for back in range(days_back + 1):
            day = (now - datetime.timedelta(days=back)).date()
            if not self.day_matches(day):
                continue
            for hour in sorted(self.hours, reverse=True):
                for minute in sorted(self.minutes, reverse=True):
                    moment = datetime.datetime(day.year, day.month, day.day, hour, minute)
                    if moment <= now:
                        return moment
        return None

    def next(self, now, days_ahead=400):
        """The first scheduled minute after `now`, or None if there is none in the next
        `days_ahead` days."""
        now = now.replace(second=0, microsecond=0)
        for ahead in range(days_ahead + 1):
            day = (now + datetime.timedelta(days=ahead)).date()
            if not self.day_matches(day):
                continue
            for hour in sorted(self.hours):
                for minute in sorted(self.minutes):
                    moment = datetime.datetime(day.year, day.month, day.day, hour, minute)
                    if moment > now:
                        return moment
        return None


def parse_field(text, name, low, high):
    values = set()
    for item in text.split(","):
        base, _, step = item.partition("/")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start, end = (int(x) for x in base.split("-", 1))
        else:
            start = end = int(base)
        if not (low <= start <= end <= high):
            raise ValueError("%s: %r is outside %d-%d" % (name, item, low, high))
        values.update(range(start, end + 1, int(step) if step else 1))
    return values
