import logging

from time import sleep

from lightify import Lightify

from . import BaseComponent, clamp_value, normalize_delta

from .. import matrices


logger = logging.getLogger(__name__)


class Component(BaseComponent):
    MATRIX = matrices.LIGHT_BULB

    def __init__(self, config):
        super().__init__(config)

        self.gateway = Lightify(config['ip_address'])
        self.gateway.update_all_light_status()
        self.lights = self.gateway.lights()
        logger.debug("lights: %s", self.lights)
        self.light = list(self.lights.values())[0]

        self.brightness_range = range(0, 100)

        self.update_state()

    def update_state(self):
        self.on = self.light.on()
        self.brightness = self.light.lum()

        logger.debug("state: %s brightness: %s", self.on, self.brightness)

    def on_button_press(self):
        self.on = not self.on
        self.light.set_onoff(self.on)

    def on_rotation(self, delta):
        normalized_delta = normalize_delta(delta, self.brightness_range.stop)
        self.brightness = round(clamp_value(self.brightness + normalized_delta, self.brightness_range))
        self.light.set_luminance(self.brightness, 2)

    def run(self):
        self.stopping = False
        while not self.stopping:
            sleep(0.05)
