import pytest

from humanlike_agent.export import export_plugin


def test_export_runtime_only(tmp_path):
    target = tmp_path / "plugin"
    export_plugin(target)
    assert (target / "plugin.yaml").is_file()
    assert (target / "humanlike_agent/native.py").is_file()
    assert not list(target.rglob("__pycache__"))
    assert not list(target.rglob("test_*.py"))
    with pytest.raises(FileExistsError):
        export_plugin(target)


def test_export_rejects_symlink_parent(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not permitted on this host")
    with pytest.raises(ValueError):
        export_plugin(link / "plugin")
    assert not list(real.iterdir())
