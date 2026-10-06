"""Download pinned Devicon SVG source for documentation diagrams."""
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
HEADERS = {'User-Agent': 'DocuMind-documentation', 'Accept': 'application/vnd.github+json'}
def get(url):
    with urlopen(Request(url, headers=HEADERS), timeout=30) as response:
        return response.read()

commit = json.loads(get('https://api.github.com/repos/devicons/devicon/commits/master'))['sha']
tree = json.loads(get(f'https://api.github.com/repos/devicons/devicon/git/trees/{commit}?recursive=1'))
available = {entry['path'] for entry in tree['tree']}
manifest = {'repository': 'https://github.com/devicons/devicon', 'commit': commit, 'icons': []}
for name in ('azure', 'docker', 'google', 'python', 'redis', 'sqlite', 'streamlit', 'github'):
    source = f'icons/{name}/{name}-original.svg'
    if source not in available:
        raise RuntimeError(f'Icon not present in pinned source tree: {source}')
    url = f'https://raw.githubusercontent.com/devicons/devicon/{commit}/{source}'
    content = get(url)
    (ROOT / 'docs/assets/icons' / f'{name}.svg').write_bytes(content)
    manifest['icons'].append({'name': name, 'source': url, 'sha256': hashlib.sha256(content).hexdigest()})
license_source = next(path for path in ('LICENSE', 'LICENSE.md', 'LICENSE.txt') if path in available)
(ROOT / 'docs/assets/icons/DEVICON_LICENSE.txt').write_bytes(get(f'https://raw.githubusercontent.com/devicons/devicon/{commit}/{license_source}'))
(ROOT / 'docs/assets/icons/sources.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
print(f'Downloaded {len(manifest["icons"])} icons from pinned Devicon commit {commit}.')
