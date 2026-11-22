"""Restore exact public trial receipts without replacing any changed local file."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def restore(destination):
    manifest = json.loads((HERE / 'RECEIPTS-MANIFEST.json').read_text(encoding='utf8'))
    archive_path = REPO / manifest['archive']
    archive = archive_path.read_bytes()
    if digest(archive) != manifest['archive_sha256']:
        raise ValueError('Archive checksum differs')
    entries = manifest['files']
    allowed = {e['path'] for e in entries if e['storage'] == 'archive'}
    data = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        for member in tar:
            if not member.isfile() or member.name not in allowed or member.name in data:
                raise ValueError('Unexpected archive entry: ' + member.name)
            data[member.name] = tar.extractfile(member).read()
    if set(data) != allowed:
        raise ValueError('Archive file list differs')
    pending = []
    for entry in entries:
        relative = PurePosixPath(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[:2] != ('experiments', 'tax_graph_trial_20261119'):
            raise ValueError('Unexpected destination: ' + str(relative))
        target = destination / str(relative)
        if not target.resolve().is_relative_to(destination):
            raise ValueError('Destination leaves the requested directory')
        if entry['storage'] == 'git_blob':
            raw = subprocess.check_output(['git', '-C', str(REPO), 'cat-file', 'blob', entry['git_blob']])
        elif entry['storage'] == 'checkout':
            raw = (REPO / str(relative)).read_bytes()
        else:
            raw = data[str(relative)]
        if digest(raw) != entry['sha256'] or len(raw) != entry['bytes']:
            raise ValueError('Receipt checksum differs: ' + str(relative))
        if target.exists():
            if not target.is_file() or digest(target.read_bytes()) != entry['sha256']:
                raise ValueError('Refusing to replace a changed local file: ' + str(relative))
        else:
            pending.append((target, raw))
    # Validate every existing file and every receipt before creating anything.
    for target, raw in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as out:
            out.write(raw)
    print('Verified %d receipts; restored %d; changed files overwritten: 0.' % (len(entries), len(pending)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=REPO,
                        help='Defaults to the checkout; another directory can be used to inspect the restored files.')
    args = parser.parse_args()
    restore(args.destination.resolve())
