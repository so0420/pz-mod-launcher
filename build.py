"""Build a neutral Windows EXE, optionally embedding settings and a Java agent."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import launcher_config

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="JSON settings to embed as defaults")
    parser.add_argument("--java-agent", type=Path, help="Optional agent JAR to bundle")
    parser.add_argument("--agent-options", help="Optional Java-agent options")
    parser.add_argument("--name", default="PZModLauncher", help="EXE filename without extension")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows EXEs must be built on Windows. Use the GitHub Actions build on other platforms.")
    if not args.name or any(c in args.name for c in '/\\:<>"|?*') or args.name.endswith((".", " ")):
        parser.error("Invalid EXE name")
    if args.config and not args.config.is_file():
        parser.error("--config must be an existing JSON file")
    private_config = args.config or ROOT / "launcher-build.json"
    settings = (launcher_config.load(private_config, environ={}) if private_config.is_file()
                else dict(launcher_config.DEFAULTS))
    agent = args.java_agent.resolve() if args.java_agent else None
    if agent:
        if not agent.is_file() or agent.suffix.lower() != ".jar" or not zipfile.is_zipfile(agent):
            parser.error("--java-agent must be an existing Java archive (.jar)")
        settings["java_agent"] = "patches/" + agent.name
    if args.agent_options is not None:
        settings["java_agent_options"] = args.agent_options
    settings = launcher_config.validate(settings)
    with tempfile.TemporaryDirectory(prefix="pz-launcher-build-") as temp:
        config = Path(temp) / "bundled-config.json"
        config.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                   "--name", args.name, "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
                   "--specpath", str(ROOT / "build"), "--add-data", str(ROOT / "launcher_connect.lua") + ";.",
                   "--add-data", str(config) + ";."]
        if agent:
            command.extend(["--add-data", str(agent) + ";patches"])
        command.append(str(ROOT / "pz_mod_installer.py"))
        subprocess.run(command, cwd=ROOT, check=True)
    print("Built:", ROOT / "dist" / (args.name + ".exe"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
