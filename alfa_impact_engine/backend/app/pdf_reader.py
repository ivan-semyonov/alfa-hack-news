"""Bounded local PDF extraction, with optional local OCR for scanned pages."""
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from pypdf import PdfReader

PROJECT = Path(__file__).resolve().parents[2]


def ocr_image(image_path):
    if os.name == 'nt':
        executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        command = [str(executable), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                   '-File', str(PROJECT / 'scripts/windows_ocr.ps1'), '-ImagePath', str(image_path)]
        method = 'WINDOWS_OCR'
    elif shutil.which('tesseract'):
        command = ['tesseract', str(image_path), 'stdout', '-l', 'rus+eng', '--psm', '3']
        method = 'TESSERACT_OCR'
    else:
        return '', 'UNAVAILABLE'
    completed = subprocess.run(command, capture_output=True, timeout=90, encoding='utf-8', errors='replace',
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if completed.returncode:
        return '', 'OCR_FAILED'
    return completed.stdout.strip()[:100_000], method


def extract_pdf(data, *, ocr=True):
    if not data.startswith(b'%PDF') or len(data) > 10_000_000:
        raise ValueError('Ожидается PDF размером до 10 МБ.')
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError('Зашифрованный PDF не поддерживается.')
        if not 1 <= len(reader.pages) <= 200:
            raise ValueError('PDF должен содержать от 1 до 200 страниц.')
        pages, warnings = [], []
        runtime = PROJECT / '.runtime' / 'ocr'
        runtime.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as temporary:
            work = Path(temporary).resolve()
            original = work / 'source.pdf'
            original.write_bytes(data)
            total_chars = 0
            for number, page in enumerate(reader.pages, 1):
                text = (page.extract_text() or '').strip()[:100_000]
                method = 'PDF_TEXT'
                if len(text) < 40 and ocr and number <= 20:
                    image_path = work / f'page-{number}.png'
                    poppler = shutil.which('pdftoppm')
                    if poppler:
                        result = subprocess.run([poppler, '-f', str(number), '-l', str(number), '-scale-to', '2200',
                                                 '-singlefile', '-png', str(original), str(image_path.with_suffix(''))],
                                                capture_output=True, timeout=60,
                                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    else:
                        # Fallback for simple image-only PDFs; complex layouts
                        # need Poppler so no page content is silently assembled.
                        images = page['/Resources'].get('/XObject', {})
                        dimensions = [value.get_object() for value in images.values()]
                        if any(int(item.get('/Width', 0)) * int(item.get('/Height', 0)) > 20_000_000 for item in dimensions):
                            raise ValueError('Слишком большое изображение PDF.')
                        if len(page.images) == 1:
                            from PIL import Image
                            with Image.open(BytesIO(page.images[0].data)) as bitmap:
                                bitmap.thumbnail((2200, 2200))
                                bitmap.convert('RGB').save(image_path)
                        else:
                            warnings.append(f'Страница {number}: для распознавания сложного скана нужен Poppler.')
                    if image_path.exists():
                        text, method = ocr_image(image_path)
                if len(text.strip()) < 20:
                    warnings.append(f'Страница {number}: текст не распознан; она не используется как доказательство.')
                    continue
                total_chars += len(text)
                if total_chars > 1_000_000:
                    raise ValueError('Извлечённый PDF превышает лимит 1 млн символов.')
                pages.append({'page': number, 'text': text, 'method': method})
        if not pages:
            raise ValueError('В PDF нет доступного текста. Для скана включите локальный OCR или добавьте текстовую версию.')
        if any(page['method'].endswith('OCR') for page in pages):
            warnings.append('Текст получен локальным OCR: цитаты следует сверять с оригиналом страницы.')
        return {'pages': pages, 'page_count': len(reader.pages), 'warnings': warnings}
    except (ValueError, TimeoutError):
        raise
    except Exception:
        raise ValueError('Не удалось безопасно прочитать PDF. Проверьте формат и наличие текстового слоя.') from None
