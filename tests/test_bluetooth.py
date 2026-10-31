import subprocess
import unittest
from unittest.mock import patch

from bluetooth_connect import connect


class BluetoothTests(unittest.TestCase):
    def test_connected_speaker_is_left_alone(self):
        with patch('bluetooth_connect.subprocess.run',
                   return_value=subprocess.CompletedProcess([], 0, 'Connected: yes')) as run:
            self.assertTrue(connect('B1:2E:84:76:00:D9'))
            self.assertEqual(run.call_count, 1)

    def test_disconnect_reconnects_only_the_named_device(self):
        with patch('bluetooth_connect.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 0, 'Connected: no'),
                subprocess.CompletedProcess([], 0, 'Connection successful')]) as run:
            self.assertTrue(connect('B1:2E:84:76:00:D9'))
            self.assertEqual(run.call_args.args[0], ['bluetoothctl', 'connect', 'B1:2E:84:76:00:D9'])
        with self.assertRaises(ValueError):
            connect('unapproved arbitrary input')
