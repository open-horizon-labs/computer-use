"""Explicitly build the opt-in Stage worker; never installs or runs it."""
import argparse
import json
import hashlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spaceo-checkout', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    args = parser.parse_args()
    checkout = args.spaceo_checkout.resolve()
    if not (checkout/'Package.swift').is_file():
        parser.error('SpaceO checkout must contain Package.swift')
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    source = build/'Sources'/'OHSpaceODisplayWorker'
    source.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/'computer_use/spaces/spaceo-display-worker.swift', source/'main.swift')
    # JSON string quoting is also a valid Swift string literal for ordinary paths.
    quoted = json.dumps(str(checkout), ensure_ascii=False)
    (build/'Package.swift').write_text('''// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "OHSpaceODisplayWorker", platforms: [.macOS(.v14)],
    dependencies: [.package(name: "SpaceO", path: %s)],
    targets: [.executableTarget(name: "OHSpaceODisplayWorker",
        dependencies: [.product(name: "SpaceOKit", package: "SpaceO")])])
''' % quoted)
    subprocess.run(['swift', 'build', '-c', 'release', '--package-path', str(build)], check=True)
    head = subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
    diff = subprocess.check_output(['git','-C',str(checkout),'diff','HEAD'])
    version = subprocess.check_output(['swift','--version'],text=True).strip()
    (build/'build-provenance.json').write_text(json.dumps({
        'spaceoHead':head,'spaceoWorkingDiffSHA256':hashlib.sha256(diff).hexdigest(),
        'workerSourceSHA256':hashlib.sha256((source/'main.swift').read_bytes()).hexdigest(),
        'swiftVersion':version,'liveQualified':False},indent=2)+'\n')
    print(build/'.build/release/OHSpaceODisplayWorker')


if __name__ == '__main__':
    main()
