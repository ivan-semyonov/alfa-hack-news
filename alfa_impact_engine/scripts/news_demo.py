"""Run the participant 1 offline proof without an HTTP server."""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from pydantic import ValidationError
from app.fixtures import COMPANIES, EDGES, NODES
from app.graph_engine import ExposureGraph
from app.news_demo import analyze_news
from app.llm_provider import ProviderUnavailable
from app.product_models import NewsInput


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company', required=True, choices=[c.id for c in COMPANIES])
    parser.add_argument('--input', type=Path, required=True, help='UTF-8 text file, max 20,000 characters')
    parser.add_argument('--title', default='')
    parser.add_argument('--source-url', default=None, help='Metadata only; no URL is fetched')
    parser.add_argument('--synthetic', action='store_true', help='Explicitly mark the input as synthetic')
    parser.add_argument('--extraction-mode', choices=('RULES', 'LLM'), default='RULES',
                        help='LLM explicitly transmits article text to configured provider; default RULES is local')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.input.stat().st_size > 100_000:
            raise ValueError('Input file exceeds the 100 KB read limit')
        news = NewsInput(title=args.title, text=args.input.read_text(encoding='utf-8-sig'),
                         source_url=args.source_url, is_synthetic=args.synthetic)
        company = next(c for c in COMPANIES if c.id == args.company)
        result = analyze_news(news, company, ExposureGraph(NODES, EDGES), extraction_mode=args.extraction_mode)
        output = json.dumps(result.model_dump(mode='json'), ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.write_text(output, encoding='utf-8')
        else:
            # PowerShell's default pipe encoding must not corrupt the saved JSON.
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            print(output, end='')
    except ProviderUnavailable as exc:
        parser.exit(3, f'Error: model unavailable ({exc.code}); no fallback was performed.\n')
    except ValidationError as exc:
        problems = ['.'.join(map(str, error['loc'])) + ': ' + error['msg']
                    for error in exc.errors(include_input=False, include_url=False)]
        parser.exit(2, 'Error: invalid news input: ' + '; '.join(problems) + '\n')
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
