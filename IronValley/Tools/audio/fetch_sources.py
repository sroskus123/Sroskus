#!/usr/bin/env python3
"""Download the pinned third-party audio sources (Tools/audio/sources.json) into Tools/audio/_src/.

Every file is checked against its SHA-256; a mismatch is an error and the file is not kept.
Files already present with the right hash are skipped. Licence evidence: Shared/audio/SOURCES.md.

    python3 Tools/audio/fetch_sources.py            # fetch missing files
    python3 Tools/audio/fetch_sources.py --src DIR  # use / fill another cache directory
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=os.path.join(HERE, '_src'))
    args = ap.parse_args()
    spec = json.load(open(os.path.join(HERE, 'sources.json'), encoding='utf8'))
    ok = bad = skipped = 0
    for f in spec['files']:
        dst = os.path.join(args.src, f['path'])
        if os.path.exists(dst) and sha256(open(dst, 'rb').read()) == f['sha256']:
            skipped += 1
            continue
        try:
            with urllib.request.urlopen(f['url'], timeout=60) as r:
                data = r.read()
        except Exception as e:  # network / 404
            print(f"FAIL  {f['path']}: {e}", file=sys.stderr)
            bad += 1
            continue
        h = sha256(data)
        if h != f['sha256']:
            print(f"FAIL  {f['path']}: sha256 {h} != pinned {f['sha256']}", file=sys.stderr)
            bad += 1
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as out:
            out.write(data)
        ok += 1
    print(f'fetched {ok}, already present {skipped}, failed {bad} (of {len(spec["files"])})')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
