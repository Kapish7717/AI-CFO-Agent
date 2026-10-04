"""Shared pytest fixtures.

Every async test in this suite is marked ``@pytest.mark.anyio``, and anyio's
pytest plugin parametrizes such a test over *both* backends it supports:
``asyncio`` and ``trio``. Nothing here is written against trio, and trio is not
a dependency (``requirements-dev.txt`` lists pytest and anyio only), so each of
those tests also collected a ``[trio]`` variant that failed at import with
``ModuleNotFoundError: No module named 'trio'``.

That produced 84 failures across eight files that had nothing to do with trio
and nothing to do with any real defect: the suite was red purely because a
second backend was requested and not installed. Pinning the backend to asyncio
removes the duplicate parametrization, so each async test runs once, on the
backend the code actually targets.

If trio support is ever genuinely wanted, install trio and delete the fixture
below rather than skipping the ``[trio]`` ids.
"""

import pytest


@pytest.fixture
def anyio_backend():
    """Run every ``@pytest.mark.anyio`` test on asyncio only.

    Must stay a fixture rather than an ``anyio_mode`` ini setting: the anyio
    plugin reads this fixture name to decide which backends to parametrize, and
    an ini value cannot narrow it back down to one.
    """
    return "asyncio"
