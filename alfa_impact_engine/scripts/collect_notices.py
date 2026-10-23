"""Copy license files shipped by installed distributions, preserving attribution."""
from importlib import metadata
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def collect():
    out=ROOT/'THIRD_PARTY_LICENSES';out.mkdir(exist_ok=True)
    inventory=[]
    for distribution in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        name=distribution.metadata['Name']
        copied=[]
        for entry in distribution.files or []:
            parts=entry.parts
            if not any('.dist-info' in part for part in parts):continue
            if not any(word in entry.name.upper() for word in ('LICENSE','LICENCE','COPYING','NOTICE','AUTHORS')):continue
            source=distribution.locate_file(entry)
            if not source.is_file():continue
            index=next(i for i,p in enumerate(parts) if '.dist-info' in p)
            relative=Path(*parts[index+1:])
            target=out/name/relative
            if not target.resolve().is_relative_to(out.resolve()):raise ValueError('Unsafe license path')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes());copied.append(target.relative_to(ROOT).as_posix())
        inventory.append({'name':name,'version':distribution.version,'license_expression':distribution.metadata.get('License-Expression'),
                          'license_files':copied,'project_urls':distribution.metadata.get_all('Project-URL',[])})
    (out/'inventory.json').write_text(json.dumps(inventory,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f'{len(inventory)} distribution records; '+str(sum(len(d['license_files']) for d in inventory))+' upstream notice files')


if __name__=='__main__':collect()
