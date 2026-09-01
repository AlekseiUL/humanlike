"""Hermes directory-plugin registration shim for repository-root installs."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import stat
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(os.path.abspath(__file__)).parent
_REAL_PLUGIN_ROOT = _PLUGIN_ROOT.resolve(strict=True)
_SOURCE_ROOT = _PLUGIN_ROOT / "src"
_SOURCE_DETAILS = _SOURCE_ROOT.lstat()
if not stat.S_ISDIR(_SOURCE_DETAILS.st_mode) or stat.S_ISLNK(_SOURCE_DETAILS.st_mode):
    raise ImportError("plugin source root is not a regular directory")
_REAL_SOURCE_ROOT = _SOURCE_ROOT.resolve(strict=True)
if _REAL_SOURCE_ROOT.parent != _REAL_PLUGIN_ROOT:
    raise ImportError("plugin source root escapes the installed plugin")

_CORE_PACKAGE = _SOURCE_ROOT / "humanlike_agent"
_CORE_PACKAGE_DETAILS = _CORE_PACKAGE.lstat()
if not stat.S_ISDIR(_CORE_PACKAGE_DETAILS.st_mode) or stat.S_ISLNK(_CORE_PACKAGE_DETAILS.st_mode):
    raise ImportError("plugin core package is not a regular directory")
_REAL_CORE_PACKAGE = _CORE_PACKAGE.resolve(strict=True)
if _REAL_CORE_PACKAGE.parent != _REAL_SOURCE_ROOT:
    raise ImportError("plugin core package escapes the installed plugin")

_CORE_INIT = _CORE_PACKAGE / "__init__.py"
_CORE_DETAILS = _CORE_INIT.lstat()
if not stat.S_ISREG(_CORE_DETAILS.st_mode) or stat.S_ISLNK(_CORE_DETAILS.st_mode):
    raise ImportError("plugin core entry point is not a regular file")
if _CORE_INIT.resolve(strict=True).parent != _REAL_CORE_PACKAGE:
    raise ImportError("plugin core entry point escapes the installed plugin")
_ROOT_DIGEST = hashlib.sha256(os.fsencode(_REAL_PLUGIN_ROOT)).hexdigest()[:16]
_CORE_NAMESPACE = f"_humanlike_agent_kit_core_{_ROOT_DIGEST}"


def _validate_import_tree() -> None:
    pending = [_CORE_PACKAGE]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            raise ImportError("plugin core tree is not accessible") from error
        for entry in entries:
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ImportError("plugin core entry is not accessible") from error
            if stat.S_ISLNK(details.st_mode):
                raise ImportError("plugin core tree must not contain symlinks")
            path = Path(entry.path)
            if stat.S_ISDIR(details.st_mode):
                pending.append(path)
            elif not stat.S_ISREG(details.st_mode):
                raise ImportError("plugin core tree contains an unsafe entry")
            try:
                path.resolve(strict=True).relative_to(_REAL_CORE_PACKAGE)
            except (OSError, ValueError) as error:
                raise ImportError("plugin core entry escapes the installed plugin") from error


def _load_private_core() -> object:
    existing = sys.modules.get(_CORE_NAMESPACE)
    if existing is not None:
        origin = getattr(existing, "__file__", None)
        if origin is not None and Path(origin).resolve(strict=True) == _CORE_INIT.resolve(
            strict=True
        ):
            return existing
        raise ImportError("private plugin namespace collision")
    spec = importlib.util.spec_from_file_location(
        _CORE_NAMESPACE,
        _CORE_INIT,
        submodule_search_locations=[str(_CORE_INIT.parent)],
    )
    if spec is None or spec.loader is None:
        raise ImportError("plugin core could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_CORE_NAMESPACE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        for name in tuple(sys.modules):
            if name == _CORE_NAMESPACE or name.startswith(f"{_CORE_NAMESPACE}."):
                del sys.modules[name]
        raise
    return module


_validate_import_tree()
_load_private_core()


def register(context: object) -> None:
    """Register the installed repository with a Hermes PluginContext."""

    adapter_module = importlib.import_module(f"{_CORE_NAMESPACE}.adapters.hermes")

    adapter_module.register(context, plugin_root=_REAL_PLUGIN_ROOT)


__all__ = ["register"]
