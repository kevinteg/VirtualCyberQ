from datetime import datetime
from datetime import timedelta

class Timer:
    """
    Simple timer class
    """

    def __init__(self,hours=0,minutes=0,seconds=0,time_string="00:00:00"):
        if time_string != "00:00:00":
            hours,minutes,seconds = [int(s) for s in time_string.split(":")]

        self.seconds = hours*3600 + minutes*60 + seconds
        self._start_time = datetime.today()

    def minutes_remaining(self):
        return self.seconds_remaining() / 60.0

    def hours_remaining(self):
        return self.minutes_remaining() / 60.0

    def seconds_remaining(self):
        seconds_elapsed = (datetime.today() - self._start_time).seconds
        return max(0, self.seconds - seconds_elapsed)

    @staticmethod
    def pad_time(value):
        return "{0:02d}".format(value)

    def __str__(self):
        hours = self.seconds_remaining() / 3600
        remaining = self.seconds_remaining() % 3600
        minutes = remaining / 60
        seconds = remaining % 60
        return ":".join([Timer.pad_time(t) for t in [hours, minutes, seconds]])
