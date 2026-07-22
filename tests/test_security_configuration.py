from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_is_explicitly_bound_to_loopback() -> None:
    config = (REPOSITORY_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    launcher = (REPOSITORY_ROOT / "run_streamlit_viewer.bat").read_text(encoding="utf-8")

    assert 'address = "127.0.0.1"' in config
    assert "--server.address 127.0.0.1" in launcher
    assert "--browser.serverAddress 127.0.0.1" in launcher


def test_viewer_launcher_does_not_install_packages() -> None:
    launcher = (REPOSITORY_ROOT / "run_streamlit_viewer.bat").read_text(encoding="utf-8")

    executable_lines = [
        line.strip().casefold()
        for line in launcher.splitlines()
        if line.strip() and not line.lstrip().casefold().startswith("echo ")
    ]
    assert not any("pip install" in line for line in executable_lines)


def test_release_locks_enable_hash_check_mode() -> None:
    for name in ("desktop-build.txt", "viewer.txt"):
        lockfile = (REPOSITORY_ROOT / "requirements" / name).read_text(encoding="utf-8")
        assert "--hash=sha256:" in lockfile
        assert "==" in lockfile


def test_release_build_audits_dependencies_and_emits_sbom() -> None:
    build_script = (REPOSITORY_ROOT / "build_exe.ps1").read_text(encoding="utf-8")

    assert '"--require-hashes"' in build_script
    assert '"--no-build-isolation", "--no-deps"' in build_script
    assert '"pip_audit"' in build_script
    assert '"cyclonedx_py", "environment"' in build_script
    assert "RainwaterCalculator.cdx.json" in build_script
