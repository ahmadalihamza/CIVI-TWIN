import pytest

from civitwin_engine.optimizer.linmodel import available_backends

BACKENDS = available_backends()


@pytest.fixture(params=BACKENDS)
def backend(request):
    """Run solver tests on every installed backend (CP-SAT and/or HiGHS)."""
    return request.param
