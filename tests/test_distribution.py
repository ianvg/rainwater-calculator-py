from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_windows_installer_is_per_user_and_preserves_application_data() -> None:
    installer = (REPOSITORY_ROOT / "installer" / "RainwaterCalculator.iss").read_text(
        encoding="utf-8"
    )

    assert "PrivilegesRequired=lowest" in installer
    assert "DefaultDirName={localappdata}\\Programs\\RWH Calculator" in installer
    assert "[UninstallDelete]" not in installer
    assert "rainwater_projects.db" not in installer
    assert 'Name: "climatenormals"' in installer
    assert "https://noaa-normals-pds.s3.amazonaws.com/" in installer
    assert (
        'DestDir: "{localappdata}\\RWH Calculator\\Cache\\weather"' in installer
    )
    assert "ExternalSize: 54176270" in installer
    assert (
        'Hash: "{#ClimateNormalsArchiveSha256}"' in installer
    )


def test_installer_build_is_included_in_windows_release_workflow() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "build-exe.yml").read_text(
        encoding="utf-8"
    )

    assert "build_installer.ps1 -SkipExecutableBuild" in workflow
    assert "RainwaterCalculator-Setup-*.exe" in workflow
