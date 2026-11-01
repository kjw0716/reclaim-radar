"""Create an allowlisted source archive; exclude all runtime/session data."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ['README.md', 'README.zh-CN.md', 'LICENSE', 'ACCEPTANCE.md', 'CONTRIBUTING.md',
         'SECURITY.md', 'CHANGELOG.md', 'pyproject.toml', 'requirements.lock.txt',
         'config.example.json', '.gitignore', '.gitattributes']
DIRECTORIES = ['radar', 'frontend/src', 'frontend/public', 'frontend/scripts',
               'scripts', 'tests', 'third_party', 'docs', '.github']


def main():
    paths = {ROOT / name for name in FILES}
    paths.update(ROOT.glob('*.cmd'))
    paths.update((ROOT / 'frontend').glob('*.json'))
    paths.update([ROOT / 'frontend/vite.config.ts', ROOT / 'frontend/index.html'])
    for directory in DIRECTORIES:
        paths.update(p for p in (ROOT / directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.log'})
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.exists()]
    if missing:
        raise SystemExit('Required release files missing: ' + ', '.join(missing))
    output = ROOT / 'release/reclaim-radar-0.2.0-source.zip'
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, 'reclaim-radar/' + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(output) as archive:
        bad = [name for name in archive.namelist() if any(part in name.split('/')
               for part in {'.data', '.venv', '.git', 'node_modules', '.env', 'test-results'})]
        if bad:
            raise SystemExit('Unsafe archive paths: ' + ', '.join(bad))
        assert archive.testzip() is None
    print(f'{output}\n{len(paths)} files; {output.stat().st_size:,} bytes; runtime data excluded.')


if __name__ == '__main__':
    main()
