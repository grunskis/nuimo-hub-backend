import logging

from time import sleep

from lifxlan import Light

from . import BaseComponent, clamp_value, normalize_delta

from .. import matrices


logger = logging.getLogger(__name__)


class Component(BaseComponent):
    MATRIX = matrices.LIGHT_BULB

    def __init__(self, config):
        super().__init__(config)

        self.light = Light(config['mac_address'], config['ip_address'])

        self.brightness_range = range(0, 65535)

        self.update_state()

    def update_state(self):
        self.on = self.light.get_power()
        _, _, self.brightness, _ = self.light.get_color()

        logger.debug("state: %s brightness: %s", self.on, self.brightness)

    def on_button_press(self):
        self.on = not self.on
        self.light.set_power(self.on)

    def on_rotation(self, delta):
        normalized_delta = normalize_delta(delta, self.brightness_range.stop)
        self.brightness = round(clamp_value(self.brightness + normalized_delta, self.brightness_range))
        self.light.set_brightness(self.brightness, duration=200, rapid=True)

    def run(self):
        self.stopping = False
        while not self.stopping:
            sleep(0.05)
