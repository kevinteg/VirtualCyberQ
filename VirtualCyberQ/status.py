import threading
import urllib
from timer import Timer

class Status:
    """
    Virtual implementation of the CyberQ BBQ Control Device.

    This is implemented as a thread-safe singleton because we only
    have one grill :).
    """
    __singleton_lock = threading.Lock()
    __singleton_instance = None

    # TODO: move all the magic variables to a defaults file based on factory defaults.
    class Food:
        def __init__(self, name, temp_set):
            self.name = name
            self.temp_set = temp_set
            self.status = 0
            self.temp = 0

    class Cook:
        def __init__(self, name, temp_set):
            self.name = name
            self.temp_set = temp_set
            self.status = 0
            self.temp = 100

    class System:
        def __init__(self):
            self.menu_scrolling = 1
            self.lcd_backlight = 47
            self.lcd_contrast = 10
            self.deg_units = 1
            self.alarm_beeps= 0
            self.key_beeps = 0

    class Control:
        def __init__(self):
            self.timeout_action = 0
            self.cookhold = 2000
            self.alarmdev = 500
            self.cookramp = 0
            self.opendetect = 1
            self.cyctime = 6
            self.propband = 500

    class Wifi:
        def __init__(self):
            self.ip = "10.0.1.30"
            self.nm = "255.255.255.0"
            self.gw = "10.0.1.1"
            self.dns = "10.0.1.1"
            self.wifimode = 0
            self.dhcp = 0
            self.ssid = "Wireless Network"
            self.wifi_enc = 6
            self.wifi_key = "Secret Key"
            self.http_port = 80

    class Smtp:
        def __init__(self):
            self.host = "smtp.hostname.com"
            self.port = 0
            self.user = ""
            self.pwd = ""
            self.msg_to = "destination@someplace.com"
            self.msg_from = "destination@someplace.com"
            self.msg_subj = "Temperature Controller Status E-Mail"
            self.alert = 0

    @classmethod
    def instance(cls):
        if not cls.__singleton_instance:
            with cls.__singleton_lock:
                if not cls.__singleton_instance:
                    cls.__singleton_instance = cls()
        return cls.__singleton_instance

    def __init__(self):
        self.timer = Timer()
        self.output_percent = 100
        self.timer_status = 0
        self.cook_temp = 3343
        self.cook_status = 0
        self.deg_units = 1

        self.cook_status = Status.Cook("Big Green Egg", 400)
        self.food1_status = Status.Food("Chicken Quarters", 155)
        self.food2_status = Status.Food("Beef Brisket", 180)
        self.food3_status = Status.Food("Pork Chop", 160)

        self.control_status = Status.Control()
        self.system_status = Status.System()
        self.wifi_status = Status.Wifi()
        self.smtp_status = Status.Smtp()

    def time_remaining(self):
        return str(self.timer)

    def set_timer(self,time_string):
        self.timer = Timer(time_string=time_string)

    def update(self, key, value):
        value = urllib.unquote(value)
        # Oh god, the horror.  Refactor this to dispatch table or something...
        if key == "COOK_NAME":
            self.cook_status.name = value
        if key == "COOK_TIMER":
            self.set_timer(value)
        elif key == "COOK_SET":
            self.cook_status.temp_set = value
        elif key == "FOOD1_NAME":
            self.food1_status.name = value
        elif key == "FOOD1_SET":
            self.food1_status.temp_set = value
        elif key == "FOOD2_NAME":
            self.food2_status.name = value
        elif key == "FOOD2_SET":
            self.food2_status.temp_set = value
        elif key == "FOOD3_NAME":
            self.food3_status.name = value
        elif key == "FOOD3_SET":
            self.food3_status.temp_set = value
        elif key == "COOKHOLD":
            self.control_status.cookhold = value
        elif key == "TIMEOUT_ACTION":
            self.control_status.timeout_action = value
        elif key == "ALARMDEV":
            self.control_status.alarmdev = value
        elif key == "COOK_RAMP":
            self.control_status.cookramp = value
        elif key == "OPENDETECT":
            self.control_status.opendetect = value
        elif key == "CYCTIME":
            self.control_status.cyctime = value
        elif key == "PROPBAND":
            self.control_status.propband = value
        elif key == "MENU_SCROLLING":
            self.system_status.menu_scrolling = value
        elif key == "LCD_BACKLIGHT":
            self.system_status.lcd_backlight = value
        elif key == "LCD_CONTRAST":
            self.system_status.lcd_contrast = value
        elif key == "DEG_UNITS":
            self.system_status.deg_units = value
        elif key == "ALARM_BEEPS":
            self.system_status.alarm_beeps = value
        elif key == "KEY_BEEPS":
            self.system_status.key_beeps = value

        # TODO: Do some error handling on invalid keys
            
