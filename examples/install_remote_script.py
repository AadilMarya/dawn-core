"""Install the DAWN Remote Script and check the link to Live.

    python examples/install_remote_script.py

Restart Live afterwards and select DAWN under
Settings > Link, Tempo & MIDI > Control Surface.
"""

from __future__ import annotations

from dawn_core import check_install, default_remote_scripts_dir, install_script


def main() -> None:
    destination = default_remote_scripts_dir()
    print(f"Installing into {destination}")
    for step in install_script(destination, force=True):
        print(f"  {step}")

    print("\nChecking the install:")
    report = check_install(destination)
    for line in report.lines():
        print(f"  {line}")
    raise SystemExit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
