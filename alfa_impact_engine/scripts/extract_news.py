"""Grounded extraction, schema/prompt export and source-bound JSON validation."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.extraction_models import ExtractionDraft
from app.llm_provider import ProviderUnavailable, strict_json_schema
from app.news_extraction import build_extraction_prompt, build_source, extract_news, validate_draft
from app.product_models import NewsInput


def read_text(path):
    if path.stat().st_size > 100_000:
        raise ValueError('Source file exceeds 100 KB')
    return path.read_text(encoding='utf-8-sig')


def write(value, path):
    output = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding='utf-8')
    else:
        print(output, end='')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    schema = commands.add_parser('schema')
    schema.add_argument('--output', type=Path)
    for name in ('extract', 'prompt', 'validate'):
        command = commands.add_parser(name)
        command.add_argument('--news', type=Path, required=True)
        command.add_argument('--title', default='')
        command.add_argument('--source-url', default=None)
        command.add_argument('--synthetic', action='store_true')
        command.add_argument('--output', type=Path)
        if name == 'extract':
            command.add_argument('--mode', choices=('RULES', 'LLM'), default='RULES',
                                 help='LLM sends article text to configured provider; default RULES stays local')
        if name == 'validate':
            command.add_argument('--input', type=Path, required=True, help='Model ExtractionDraft JSON, not a result wrapper')
    args = parser.parse_args(argv)
    try:
        if args.command == 'schema':
            result = strict_json_schema(ExtractionDraft.model_json_schema())
        else:
            news = NewsInput(title=args.title, text=read_text(args.news), source_url=args.source_url,
                             is_synthetic=args.synthetic)
            source, content_hash = build_source(news)
            if args.command == 'prompt':
                result = {'schema_version': '0.3.0', 'source_id': source.id, 'messages': build_extraction_prompt(source)}
            elif args.command == 'validate':
                if args.input.stat().st_size > 1_000_000:
                    raise ValueError('Model JSON exceeds 1 MB')
                draft = validate_draft(json.loads(args.input.read_text(encoding='utf-8-sig')), source)
                result = {'valid': True, 'semantic_factuality_checked': False,
                          'result': draft.model_dump(mode='json')}
            else:
                source, extraction = extract_news(news, mode=args.mode)
                result = {'schema_version': '0.3.0', 'source': source.model_dump(mode='json'),
                          'extraction': extraction.model_dump(mode='json')}
        write(result, args.output)
    except ProviderUnavailable as exc:
        write({'valid': False, 'code': exc.code, 'fallback_performed': False}, None)
        return 3
    except (OSError, ValueError, TypeError, RecursionError):
        # Validation errors may carry raw news/model input; keep CLI errors safe.
        write({'valid': False, 'code': 'INVALID_INPUT_OR_OUTPUT'}, None)
        return 2
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
