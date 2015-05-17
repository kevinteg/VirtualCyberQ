import unittest
from VirtualCyberQ.status import Status

class TestStatus(unittest.TestCase):
    """Test that the initializer works and gets all of the needed variables"""
    def setUp(self):
        pass

    def tearDown(self):
        """None"""
        pass

    def testProperInit(self):
        """Test initializes with accepted values"""
        status = Status.instance()
        self.assertEqual(status.time_remaining(), "00:00:00")

    def testSetTimer(self):
        status = Status.instance()
        status.set_timer("44:33:22")
        self.assertEqual(status.time_remaining(), "44:33:22")

    def testStatusIsSingleton(self):
        status1 = Status.instance()
        status2 = Status.instance()
        status1.set_timer("00:10:00")
        self.assertEqual(status2.time_remaining(), "00:10:00")

    def testStatusAttributes(self):
        status = Status.instance()
        assert(status.output_percent is not None)
        assert(status.cook_temp is not None)
        assert(status.cook_status is not None)
        assert(status.deg_units is not None)

        assert(status.cook_status is not None)
        assert(status.food1_status is not None)
        assert(status.food2_status is not None)
        assert(status.food3_status is not None)
        assert(status.control_status is not None)
        assert(status.system_status is not None)
        assert(status.wifi_status is not None)
        assert(status.smtp_status is not None)

    def testFoodProperInit(self):
        food_status = Status.Food("tofu burgers", 150)
        self.assertEqual(food_status.name, "tofu burgers")
        self.assertEqual(food_status.temp_set, 150)
        assert(food_status.status is not None)
        assert(food_status.temp >= 0)

    def testCookProperInit(self):
        cook_status = Status.Cook("My Awesome Grill", 400)
        self.assertEqual(cook_status.name, "My Awesome Grill")
        self.assertEqual(cook_status.temp_set, 400)
        assert(cook_status.status is not None)
        assert(cook_status.temp >= 0)

    def testSystemProperInit(self):
        system_status = Status.System()
        assert(system_status.menu_scrolling is not None)
        assert(system_status.lcd_backlight is not None)
        assert(system_status.lcd_contrast is not None)
        assert(system_status.deg_units is not None)
        assert(system_status.alarm_beeps is not None)
        assert(system_status.key_beeps is not None)

    def testControlProperInit(self):
        control_status = Status.Control()
        assert(control_status.timeout_action is not None)
        assert(control_status.cookhold is not None)
        assert(control_status.alarmdev is not None)
        assert(control_status.cookramp is not None)
        assert(control_status.opendetect is not None)
        assert(control_status.cyctime is not None)
        assert(control_status.propband is not None)

    def testWifiProperInit(self):
        wifi_status = Status.Wifi()
        assert(wifi_status.ip is not None)
        assert(wifi_status.nm is not None)
        assert(wifi_status.gw is not None)
        assert(wifi_status.dns is not None)
        assert(wifi_status.wifimode is not None)
        assert(wifi_status.dhcp is not None)
        assert(wifi_status.ssid is not None)
        assert(wifi_status.wifi_enc is not None)
        assert(wifi_status.wifi_key is not None)
        assert(wifi_status.http_port is not None)

    def testSmtpProperInit(self):
        smtp_status = Status.Smtp()
        assert(smtp_status.host is not None)
        assert(smtp_status.port is not None)
        assert(smtp_status.user is not None)
        assert(smtp_status.pwd is not None)
        assert(smtp_status.msg_to is not None)
        assert(smtp_status.msg_from is not None)
        assert(smtp_status.msg_subj is not None)
        assert(smtp_status.alert is not None)

    def testUpdate(self):
        status = Status.instance()
        status.update("COOK_TIMER", "01:00:00")
        self.assertEqual(status.time_remaining(), "01:00:00")
