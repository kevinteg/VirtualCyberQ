# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for the device state model and factory/demo defaults (DESIGN 4).

Pins the verified factory defaults (Appendix A) so a regression in the single
source of truth (``core/defaults.py``) is caught immediately: COOK_SET 275, food
180, COOKHOLD 200, ALARMDEV 50, PROPBAND 25, CYCTIME 6, plus the demo seed
values (Big Green Egg / Chicken Quarters 155 / Beef Brisket 180 / Pork Chop 160).
"""

from __future__ import annotations

from virtualcyberq.core.defaults import demo_state, factory_state
from virtualcyberq.core.enums import (
    DegUnits,
    OnOff,
    RampSource,
    StatusCode,
    TimeoutAction,
)
from virtualcyberq.core.state import DeviceState, ProbeState, SimState


class TestFactoryTemperatureDefaults:
    """Verified factory temperature defaults, in tenths-degF."""

    def test_cook_set_is_275(self) -> None:
        assert factory_state().cook.set == 2750

    def test_food_sets_are_180(self) -> None:
        st = factory_state()
        assert st.food1.set == 1800
        assert st.food2.set == 1800
        assert st.food3.set == 1800

    def test_control_bands(self) -> None:
        ctl = factory_state().control
        assert ctl.cookhold == 2000  # 200.0 degF
        assert ctl.alarmdev == 500  # 50.0 degF
        assert ctl.propband == 250  # 25.0 degF
        assert ctl.cyctime == 6


class TestFactoryEnumDefaults:
    def test_control_enum_defaults(self) -> None:
        ctl = factory_state().control
        assert ctl.timeout_action is TimeoutAction.NO_ACTION
        assert ctl.cook_ramp is RampSource.OFF
        assert ctl.opendetect is OnOff.ON

    def test_system_defaults(self) -> None:
        sysc = factory_state().system
        assert sysc.deg_units is DegUnits.FAHRENHEIT
        assert sysc.lcd_backlight == 50
        assert sysc.lcd_contrast == 10
        assert sysc.alarm_beeps == 3
        assert sysc.key_beeps is OnOff.ON
        assert sysc.menu_scrolling is OnOff.OFF

    def test_default_persona(self) -> None:
        assert factory_state().fwver == "3.1"

    def test_read_only_fields_start_clean(self) -> None:
        st = factory_state()
        assert st.output_percent == 0
        assert st.fan_shorted is False


class TestProbesStartOpen:
    def test_probes_start_disconnected_reading(self) -> None:
        # Probes carry no reading (temp=None -> OPEN) until physics runs.
        for probe in factory_state().probes():
            assert probe.temp is None

    def test_probe_order(self) -> None:
        st = factory_state()
        assert st.probes() == [st.cook, st.food1, st.food2, st.food3]
        assert st.food_probes() == [st.food1, st.food2, st.food3]

    def test_generic_factory_names(self) -> None:
        st = factory_state()
        assert st.cook.name == "Cook"
        assert st.food1.name == "Food1"


class TestDemoDefaults:
    def test_demo_names(self) -> None:
        st = demo_state()
        assert st.cook.name == "Big Green Egg"
        assert st.food1.name == "Chicken Quarters"
        assert st.food2.name == "Beef Brisket"
        assert st.food3.name == "Pork Chop"

    def test_demo_food_setpoints(self) -> None:
        st = demo_state()
        assert st.food1.set == 1550  # 155.0
        assert st.food2.set == 1800  # 180.0
        assert st.food3.set == 1600  # 160.0

    def test_demo_shares_factory_config(self) -> None:
        # Demo keeps the factory control/system blocks (only names/sets differ).
        assert demo_state().control.propband == factory_state().control.propband


class TestFactoryWifiSmtp:
    def test_wifi_defaults(self) -> None:
        wifi = factory_state().wifi
        assert wifi.ip == "192.168.101.10"
        assert wifi.http_port == 80
        assert wifi.wifi_key == "1234abcdef"
        # config.xml example uses WPA2_AES == 6.
        assert wifi.wifi_enc == 6
        assert wifi.mac == "00:04:A3:00:00:00"

    def test_smtp_defaults(self) -> None:
        smtp = factory_state().smtp
        assert smtp.host == "mail.cyberqmail.com"
        assert smtp.port == 587


class TestDataclassShapes:
    def test_device_state_is_dataclass_instance(self) -> None:
        assert isinstance(factory_state(), DeviceState)

    def test_probe_defaults(self) -> None:
        p = ProbeState(name="X", temp=None, set=1000)
        assert p.status is StatusCode.OK
        assert p.connected is True

    def test_sim_state_defaults(self) -> None:
        sim = SimState()
        assert sim.fire == 0.0
        assert sim.fuel_remaining == 1.0
        assert not sim.cook_armed
        assert not sim.lid_open
        assert set(sim.meat_moisture) == {"food1", "food2", "food3"}
