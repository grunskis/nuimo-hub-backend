import logging

from pprint import pformat
from random import random, seed
from time import sleep, time

from . import icons

from .led import LEDMatrixConfig


COLOR_WHITE_RGB = (255, 255, 255)


logger = logging.getLogger(__name__)


class EncoderRing:
    NUM_POINTS = 1800

    def __init__(self, min_value, max_value):
        self.min_value = min_value
        self.max_value = max_value

    def points_to_value(self, points):
        return points / self.NUM_POINTS * self.max_value

    def normalize_value(self, value):
        return min(max(value, self.min_value), self.max_value)


class Component:
    def __init__(self):
        super().__init__()

        self.deltas = []

    def state_changed(self, state):
        """
        Listen on state change notifications from HA.

        This function gets called automatically by HA when state
        changes for one of the entities known to the component.

        """
        logger.debug("state_changed:")
        logger.debug(pformat(state))

        if "data" in state:
            new_state = state["data"]["new_state"]
        else:
            new_state = state

        self.set_state(new_state)


class PhilipsHue(Component):
    DOMAIN = "light"
    ICON = icons.LIGHT_BULB

    def __init__(self, name, entity_id):
        super().__init__()

        self.name = name
        self.entity_id = entity_id

        self.encoder = EncoderRing(1, 254)

        self.state = None
        self.brightness = None

        self.service = None
        self.updates = {}

        # seed random nr generator (used to get random color value)
        seed()

    def set_state(self, state):
        """
        Set internal state from the HA state.

        """
        self.state = state["state"]
        self.brightness = state["attributes"].get("brightness", 0)

        logger.debug("%s state: %s brightness: %s", self.entity_id, self.state, self.brightness)

    def button_press(self):
        if self.state == "on":
            service = "turn_off"
            icon = icons.LIGHT_OFF
        else:
            service = "turn_on"
            icon = icons.LIGHT_ON

        self.service = service

        self.nuimo.update_led_matrix(LEDMatrixConfig(icon))

    def rotation(self, value):
        self.deltas.append(value)

    def swipe_left(self):
        self.service = "turn_on"

        self.updates["brightness"] = self.brightness
        self.updates["rgb_color"] = COLOR_WHITE_RGB

        self.nuimo.update_led_matrix(LEDMatrixConfig(icons.LETTER_W))

    def swipe_right(self):
        self.service = "turn_on"

        self.updates["xy_color"] = [random(), random()]

        self.nuimo.update_led_matrix(LEDMatrixConfig(icons.SHUFFLE))

    def run(self):
        self.stopping = False
        prev_update_time = 0

        while not self.stopping:
            now = time()
            time_since_last_update = now - prev_update_time
            if (self.deltas or self.service) and time_since_last_update > 0.3:
                self.send_updates()

                prev_update_time = now
            else:
                sleep(0.05)

    def send_updates(self):
        if self.deltas:
            delta = round(self.encoder.points_to_value(sum(self.deltas)))
            new_brightness = self.encoder.normalize_value(self.brightness + delta)
            self.updates["brightness"] = new_brightness
            self.brightness = new_brightness

            if new_brightness > self.encoder.min_value:
                self.service = "turn_on"
                icon = icons.light_bar(self.encoder.max_value, new_brightness)
                self.nuimo.update_led_matrix(LEDMatrixConfig(icon, fading=True, ignore_duplicates=True))
            else:
                self.service = "turn_off"
                self.updates.pop("brightness", None)
                self.nuimo.update_led_matrix(LEDMatrixConfig(icons.POWER_OFF, fading=True, ignore_duplicates=True))

        def on_success(result):
            # TODO show icon here?
            pass

        def on_error():
            self.nuimo.show_error_icon()

        self.updates["transition"] = 1
        self.updates["entity_id"] = self.entity_id
        self.ha.call_service(self.DOMAIN, self.service, self.updates, on_success, on_error)

        self.service = None
        self.deltas.clear()
        self.updates.clear()


class Sonos(Component):
    DOMAIN = "media_player"
    ICON = icons.MUSIC_NOTE

    def __init__(self, name, entity_id):
        super().__init__()

        self.name = name
        self.entity_id = entity_id

        self.encoder = EncoderRing(0.0, 1.0)

        self.state = None
        self.volume = None
        self.service = None

        self.update_in_progress = False

    def set_state(self, state):
        """
        Set internal state from the HA state.

        """
        self.state = state["state"]
        self.volume = state["attributes"].get("volume_level", 0)

        logger.debug("%s state %s volume: %s", self.entity_id, self.state, self.volume)

    def button_press(self):
        if self.state == "playing":
            service = "turn_off"
            icon = icons.PAUSE
        else:
            service = "turn_on"
            icon = icons.PLAY

        self.service = service
        self.nuimo.update_led_matrix(LEDMatrixConfig(icon))

    def rotation(self, delta):
        self.deltas.append(delta)

    def swipe_left(self):
        self.service = "media_previous_track"
        self.nuimo.update_led_matrix(LEDMatrixConfig(icons.PREVIOUS_SONG))

    def swipe_right(self):
        self.service = "media_next_track"
        self.nuimo.update_led_matrix(LEDMatrixConfig(icons.NEXT_SONG))

    def run(self):
        self.stopping = False
        prev_update_time = 0

        while not self.stopping:
            now = time()
            time_since_last_update = now - prev_update_time
            if not self.update_in_progress and (self.deltas or self.service) and time_since_last_update > 0.2:
                self.send_updates()

                prev_update_time = now
            else:
                sleep(0.05)

    def send_updates(self):
        service_data = {}

        if self.deltas:
            delta = self.encoder.points_to_value(sum(self.deltas))
            new_volume = round(self.encoder.normalize_value(self.volume + delta), 2)
            service_data["volume_level"] = new_volume
            self.service = "volume_set"

            icon = icons.light_bar(self.encoder.max_value, new_volume)
            self.nuimo.update_led_matrix(LEDMatrixConfig(icon, fading=True, ignore_duplicates=True))

        def on_success(result):
            # TODO show icon here?
            self.update_in_progress = False

        def on_error():
            self.update_in_progress = False
            self.nuimo.show_error_icon()

        service_data["entity_id"] = self.entity_id
        self.update_in_progress = True
        self.ha.call_service(self.DOMAIN, self.service, service_data, on_success, on_error)

        self.service = None
        self.deltas.clear()
