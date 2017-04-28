from threading import Thread

from .. import matrices


def clamp_value(value, range_):
    return min(max(value, range_.start), range_.stop)


class EncoderRing:
    NUM_POINTS = 1800

    @classmethod
    def normalize(cls, points, range_):
        return points / cls.NUM_POINTS * range_.stop


class BaseComponent:
    MATRIX = matrices.ERROR

    def __init__(self, config):
        self.name = config['name']

    def run(self):
        """
        Concrete components must implement run() method
        """
        raise NotImplementedError()

    def start(self):
        self.thread = Thread(target=self.run)
        self.thread.start()

    def stop(self):
        self.stopping = True
