from __future__ import annotations

import builtins


class _RaisesContext:
    def __init__(self, expected_exception):
        self.expected_exception = expected_exception
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise AssertionError(f"DID NOT RAISE {self.expected_exception}")
        if not issubclass(exc_type, self.expected_exception):
            raise AssertionError(
                f"Expected {self.expected_exception}, got {exc_type}"
            )
        self.value = exc
        return True


def raises(expected_exception):
    return _RaisesContext(expected_exception)


def fixture(func=None, **kwargs):
    if func is None:
        def _decorator(f):
            return f
        return _decorator
    return func


class _Mark:
    def __getattr__(self, name):
        def _marker(*args, **kwargs):
            if len(args) == 1 and callable(args[0]) and not kwargs:
                return args[0]

            def _decorator(func):
                return func

            return _decorator

        return _marker


mark = _Mark()


def fail(reason: str = ""):
    raise AssertionError(reason or "pytest.fail() called")


def skip(reason: str = ""):
    raise AssertionError(reason or "pytest.skip() called")


def xfail(reason: str = ""):
    raise AssertionError(reason or "pytest.xfail() called")


def approx(expected, rel=1e-6, abs=1e-12):
    class _Approx:
        def __eq__(self, actual):
            delta = builtins.abs(actual - expected)
            limit = max(rel * max(builtins.abs(actual), builtins.abs(expected)), abs)
            return delta <= limit

    return _Approx()
