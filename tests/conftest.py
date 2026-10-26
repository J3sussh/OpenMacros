import os

# Sem barramento de acessibilidade (AT-SPI) nos testes: evita o aviso/falha
# intermitente "SpiRegistry" quando a sessão D-Bus privada não tem a11y bus.
# Definido antes de qualquer import de GTK e herdado pelos subprocessos.
os.environ.setdefault("NO_AT_BRIDGE", "1")
os.environ.setdefault("GTK_A11Y", "none")

import pytest

from openmacros.hidpp.channel import Channel
from openmacros.hidpp.device import Device
from openmacros.hidpp.fake import SimulatedDevice
from openmacros.hidpp.transport import FakeTransport


@pytest.fixture
def make_device():
    def _make(features, handlers=None, versions=None, index=1):
        sim = SimulatedDevice(features, handlers, index=index, versions=versions)
        tr = FakeTransport(sim.respond)
        ch = Channel(tr, timeout=0.2)
        return Device(ch, index), sim, tr, ch
    return _make
