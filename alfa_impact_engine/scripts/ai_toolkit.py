"""Offline AI utilities. Run from the project root: python -m scripts.ai_toolkit."""
import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.ai_toolkit import build_prompt, output_schemas, validate_output  # noqa: E402
from app.taxonomy import taxonomy_document  # noqa: E402


def _read(path: Path) -> dict:
    if path.stat().st_size > 1_000_000:
        raise ValueError('JSON input exceeds the 1 MB utility limit')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('JSON input must be an object')
    return value


def _write(value: dict, path: Path | None = None):
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path is None:
        print(text, end='')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Offline contracts and prompts; no model calls')
    commands = parser.add_subparsers(dest='command', required=True)
    taxonomy = commands.add_parser('taxonomy', help='Print or save the impact taxonomy')
    taxonomy.add_argument('--output', type=Path)
    schemas = commands.add_parser('schemas', help='Export three JSON output schemas')
    schemas.add_argument('--output-dir', type=Path, required=True)
    prompt = commands.add_parser('prompt', help='Build transport-neutral system/user messages')
    prompt.add_argument('--task', choices=('event', 'hypotheses', 'insight'), required=True)
    prompt.add_argument('--context', type=Path, required=True)
    prompt.add_argument('--model', required=True, help='Exact identifier from TECH_SPEC section 1.2')
    prompt.add_argument('--output', type=Path)
    validate = commands.add_parser('validate', help='Check JSON structure and trusted references')
    validate.add_argument('--task', choices=('event', 'hypotheses', 'insight'), required=True)
    validate.add_argument('--input', type=Path, required=True)
    validate.add_argument('--context', type=Path, required=True)
    validate.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'taxonomy':
            _write(taxonomy_document(), args.output)
        elif args.command == 'schemas':
            paths = []
            for name, schema in output_schemas().items():
                path = args.output_dir / f'{name}.schema.json'
                _write(schema, path)
                paths.append(str(path))
            _write({'schema_version': '0.2.0', 'files': paths})
        elif args.command == 'prompt':
            _write(build_prompt(args.task, _read(args.context), args.model), args.output)
        else:
            result = validate_output(args.task, _read(args.input), _read(args.context))
            _write({'valid': True, 'task': args.task,
                    'checks': ['structure', 'scope', 'references'],
                    'semantic_factuality_checked': False,
                    'result': result.model_dump(mode='json')}, args.output)
    except ValidationError as exc:
        _write({'valid': False, 'errors': [
            {'location': list(error['loc']), 'message': error['msg'], 'type': error['type']}
            for error in exc.errors(include_input=False, include_url=False)
        ]})
        return 1
    except (OSError, ValueError, TypeError) as exc:
        _write({'valid': False, 'error': str(exc)})
        return 1
    return 0


if __name__ == '__main__':
    # JSON is UTF-8 even when Windows redirects stdout through a legacy code page.
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
