import logging

from pprint import pformat
from random import random, seed
from time import sleep, time

from phue import Bridge

from . import BaseComponent, EncoderRing

from .. import matrices


COLOR_WHITE_XY = (0.32, 0.336)


logger = logging.getLogger(__name__)


class HueBase:
    @property
    def sync_interval(self):
        """
        How often to sync with the bridge to detect changes made by
        external apps.
        """
        return 5  # seconds

    def parse_responses(self, responses, request_attributes):
        errors = [x['error'] for x in responses[0] if 'error' in x]
        if errors:
            return {'errors': errors}

        merged = self.merge_success_responses(responses)

        logger.debug("response: %s", merged)

        self.update_state_from_response(merged)

        return merged

    def merge_success_responses(self, responses):
        updates = [x['success'] for x in responses[0] if not list(x['success'])[0].endswith('transitiontime')]
        return {k.rsplit("/", 1)[-1]: v for u in updates for k, v in u.items()}

    def update_state_from_response(self, response):
        for key, value in response.items():
            if key == 'bri':
                self.brightness = value

            elif key == 'on':
                self.on = value

            elif key == 'bri_inc':
                # response to bri_inc applied to a group doesn't return actual brightness for some reason...
                self.brightness = min(max(self.brightness + value, 0), 254)


class NoLights(HueBase):
    """
    Wrapper used when we don't have any reachable lights to control
    """

    def __init__(self):
        self._on = False
        self._brightness = 0

    @property
    def on(self):
        return self._on

    @property
    def brightness(self):
        return self._brightness

    @property
    def update_interval(self):
        return 1

    def update_state(self):
        pass

    def set_attributes(self, attributes):
        return {'errors': "No reachable lights"}

    @property
    def sync_interval(self):
        """
        How often to sync with the bridge to detect changes made by
        external apps.
        """
        return 60  # seconds


class Lights(HueBase):
    """
    Wraps one or multiple lights
    """

    TRANSITION_TIME = 1  # * 100 milliseconds

    def __init__(self, bridge, light_ids):
        self.bridge = bridge
        self.light_ids = light_ids

        self._on = None
        self._brightness = None
        self._state = None

    @property
    def on(self):
        return self._on

    @on.setter
    def on(self, other):
        self._on = other

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, other):
        self._brightness = other

    @property
    def update_interval(self):
        return 0.1

    def update_state(self):
        """
        Get current state of all the lights from the bridge
        """
        response = self.bridge.get_light()
        self._state = {k: v['state'] for k, v in response.items() if k in self.light_ids}

        logger.debug("state: %s", pformat(self._state))

        self._on = any(s['on'] for s in self._state.values())
        self._brightness = min(s['bri'] for s in self._state.values())

        logger.debug("on: %s brightness: %s", self._on, self._brightness)

    def set_attributes(self, attributes):
        for light_id in self.light_ids:
            responses = self.bridge.set_light(int(light_id), attributes, transitiontime=self.TRANSITION_TIME)
            response = self.parse_responses(responses, attributes)
            if 'errors' in response:
                # exit early if a call fails
                return response

        return response


class Group(HueBase):
    """
    Wraps a Philips Hue group
    """

    GROUP_NAME = "Senic hub"
    TRANSITION_TIME = 4  # * 100 ms

    def __init__(self, bridge, light_ids):
        self.bridge = bridge
        self.light_ids = light_ids

        self.group_id = self.get_or_create_group()

        self._on = None
        self._brightness = None
        self._state = None

    def get_or_create_group(self):
        groups = self.bridge.get_group()
        group_id = next((k for k, v in groups.items() if v['name'] == self.GROUP_NAME), None)
        if not group_id:
            return self.create_group()

        group_light_ids = set(groups[group_id]['lights'])
        if group_light_ids != set(self.light_ids):
            return self.update_group(int(group_id))

        return int(group_id)

    def create_group(self):
        responses = self.bridge.create_group(self.GROUP_NAME, self.light_ids)
        logger.debug("create_group responses: %s", responses)
        response = responses[0]
        if 'error' in response:
            logger.error("Error while creating the group: %s", response['error'])
            return None
        return int(response['success']['id'])

    def update_group(self, group_id):
        responses = self.bridge.set_group(group_id, 'lights', self.light_ids)
        logger.debug("update_group responses: %s", responses)
        response = responses[0][0]
        if 'error' in response:
            logger.error("Error while updating the group: %s", response['error'])
            return None

        return group_id

    @property
    def update_interval(self):
        return 1  # second

    @property
    def on(self):
        return self._on

    @on.setter
    def on(self, other):
        self._on = other

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, other):
        self._brightness = other

    def update_state(self):
        """
        Get current state of the group from the bridge
        """
        state = self.bridge.get_group(self.group_id)

        logger.debug("state: %s", pformat(state))

        self._on = state['action']['on']
        self._brightness = state['action']['bri']

        self._state = state

    def set_attributes(self, attributes):
        responses = self.bridge.set_group(self.group_id, attributes, transitiontime=self.TRANSITION_TIME)
        return self.parse_responses(responses, attributes)


class Component(BaseComponent):
    MATRIX = matrices.LIGHT_BULB

    def __init__(self, config):
        super().__init__(config)

        self.bridge = Bridge(config['ip_address'], config['username'])

        self.encoder = EncoderRing(-254, 254)
        self.delta = 0

        self.lights = self.create_lights(config['lights'])
        self.lights.update_state()

        # seed random nr generator (used to get random color value)
        seed()

    def create_lights(self, light_ids):
        lights = [i.strip() for i in light_ids.split(',')]

        reachable_lights = self.filter_reachable(lights)
        if not reachable_lights:
            lights = NoLights()
        elif len(reachable_lights) > 10:
            lights = Group(self.bridge, reachable_lights)
        else:
            lights = Lights(self.bridge, reachable_lights)

        return lights

    def filter_reachable(self, light_ids):
        lights = self.bridge.get_light()
        reachable = [i for i in light_ids if i in lights and lights[i]['state']['reachable']]
        logger.debug("lights: %s reachable: %s", list(lights.keys()), reachable)
        return reachable

    def on_button_press(self):
        on = not self.lights.on
        if on and self.lights.brightness:
            self.set_light_attributes(on=on, bri=self.lights.brightness)
        else:
            self.set_light_attributes(on=on)

    def set_light_attributes(self, **attributes):
        response = self.lights.set_attributes(attributes)

        if 'errors' in response:
            logger.error("Failed to set light attributes: %s", response['errors'])
            self.nuimo.display_matrix(matrices.ERROR)
            return

        if 'xy' in attributes:
            if 'bri' in attributes:
                self.nuimo.display_matrix(matrices.LETTER_W)
            else:
                self.nuimo.display_matrix(matrices.SHUFFLE)

        elif 'on' in attributes and not ('bri_inc' in attributes):
            if self.lights.on:
                self.nuimo.display_matrix(matrices.LIGHT_ON)
            else:
                self.nuimo.display_matrix(matrices.LIGHT_OFF)

        elif 'bri' in attributes or 'bri_inc' in attributes:
            if self.lights.brightness:
                matrix = matrices.light_bar(self.encoder.max_value, self.lights.brightness)
                self.nuimo.display_matrix(matrix, fading=True, ignore_duplicates=True)
            else:
                self.turn_off()

    def turn_off(self):
        self.set_light_attributes(on=False)

    def on_swipe_left(self):
        self.set_light_attributes(on=True, bri=self.lights.brightness, xy=COLOR_WHITE_XY)

    def on_swipe_right(self):
        self.set_light_attributes(on=True, xy=(random(), random()))

    def on_rotation(self, value):
        self.delta += value

    def run(self):
        prev_sync_time = time()
        prev_update_time = time()
        self.stopping = False

        while not self.stopping:
            now = time()

            if self.delta and now - prev_update_time >= self.lights.update_interval:
                self.send_updates()
                self.delta = 0

                prev_update_time = now

            if now - max([prev_sync_time, prev_update_time]) >= self.lights.sync_interval:
                self.lights.update_state()

                prev_sync_time = now

            sleep(0.05)

    def send_updates(self):
        delta = round(self.encoder.clamp_value(self.encoder.points_to_value(self.delta)))

        if self.lights.on:
            self.set_light_attributes(bri_inc=delta)
        else:
            if delta > 0:
                self.set_light_attributes(bri_inc=delta, on=True)
