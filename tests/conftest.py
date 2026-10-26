import pytest

from clique.hidpp.channel import Channel
from clique.hidpp.device import Device
from clique.hidpp.fake import SimulatedDevice
from clique.hidpp.transport import FakeTransport


@pytest.fixture
def make_device():
    def _make(features, handlers=None, versions=None, index=1):
        sim = SimulatedDevice(features, handlers, index=index, versions=versions)
        tr = FakeTransport(sim.respond)
        ch = Channel(tr, timeout=0.2)
        return Device(ch, index), sim, tr, ch
    return _make
