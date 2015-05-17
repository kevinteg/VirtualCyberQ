import unittest
from mock import patch
from datetime import datetime
from VirtualCyberQ.timer import Timer

class TestTimer(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        """None"""
        pass

    def testProperInit(self):
        """Test initializes with accepted values"""
        timer = Timer()
        self.assertEqual(str(timer), "00:00:00")

    def testTimeRemaining(self):
        with patch('VirtualCyberQ.timer.datetime') as mock_datetime:
            mock_datetime.today.return_value = datetime(2015, 5, 17, 13, 20, 0)
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            timer = Timer(hours=5,minutes=30,seconds=45)
            self.assertEqual(timer.seconds_remaining(), 19845)
            self.assertEqual(timer.minutes_remaining(), 330.75)
            self.assertEqual(timer.hours_remaining(), 5.5125)

    def testTimeRepresentation(self):
        with patch('VirtualCyberQ.timer.datetime') as mock_datetime:
            mock_datetime.today.return_value = datetime(2015, 5, 17, 13, 20, 0)
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            
            timer = Timer(hours=6,minutes=10,seconds=11)
            self.assertEqual(str(timer), "06:10:11")

    def testTimeCountdown(self):
        with patch('VirtualCyberQ.timer.datetime') as mock_datetime:
            mock_datetime.today.return_value = datetime(2015, 5, 17, 13, 20, 0)
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            timer = Timer(hours=1)
            self.assertEqual(timer.minutes_remaining(), 60)
            mock_datetime.today.return_value = datetime(2015, 5, 17, 14, 15, 0)
            self.assertEqual(timer.minutes_remaining(), 5)

    def testTimeoutExpired(self):
        with patch('VirtualCyberQ.timer.datetime') as mock_datetime:
            mock_datetime.today.return_value = datetime(2015, 5, 17, 13, 20, 0)
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            timer = Timer(minutes=1)
            mock_datetime.today.return_value = datetime(2015, 5, 17, 14, 25, 0)
            self.assertEqual(timer.seconds_remaining(), 0)
