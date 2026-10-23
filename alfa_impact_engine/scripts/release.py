"""Package an explicit source allowlist; never include runtime, keys or private PDFs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def included(path):
    rel=path.relative_to(ROOT)
    if any(part.startswith('.') or part in ('__pycache__','node_modules') for part in rel.parts):
        return len(rel.parts)==1 and rel.name in ('.gitignore','.gitattributes','.dockerignore','.env.example')
    if rel.parts[0] in ('backend','frontend','contracts','db','docs','evaluation','scripts'):
        return path.suffix.lower() in ('.py','.ps1','.md','.json','.txt','.html','.css','.js','.sql','.png','.jpg','.yml')
    if rel.parts[0]=='THIRD_PARTY_LICENSES':return True
    return str(rel).replace('\\','/').startswith('data/synthetic/') or (len(rel.parts)==1 and rel.name in ('README.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md','Dockerfile','docker-compose.yml','pyproject.toml')) or str(rel).replace('\\','/')=='materials/demo/README.md'


def release():
    output=ROOT/'dist';output.mkdir(exist_ok=True)
    target=output/'Alfa_Impact_Engine_v1.0.0.zip'
    files=[p for p in ROOT.rglob('*') if p.is_file() and included(p)]
    manifest={'version':'1.0.0','created_at':datetime.now(timezone.utc).isoformat(),'files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
    try:
        result=subprocess.run(['git','-c','safe.directory='+ROOT.parent.as_posix(),'rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,timeout=5)
        manifest['git_commit']=result.stdout.strip() if result.returncode==0 else None
        status=subprocess.run(['git','-c','safe.directory='+ROOT.parent.as_posix(),'status','--porcelain','--','.'],cwd=ROOT,capture_output=True,text=True,timeout=5)
        manifest['git_worktree_dirty']=bool(status.stdout.strip()) if status.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):manifest['git_commit']=None
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):archive.write(path,'alfa_impact_engine/'+path.relative_to(ROOT).as_posix())
        archive.writestr('alfa_impact_engine/RELEASE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert all('/.runtime/' not in n and '/.venv/' not in n and not n.endswith(('.pdf','vault.key','/.env')) for n in archive.namelist())
    checksum=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(checksum+'  '+target.name+'\n',encoding='ascii')
    print(str(target));print(f'{len(files)} source files; archive integrity OK; SHA256 {checksum}')
    return target


if __name__=='__main__':release()
