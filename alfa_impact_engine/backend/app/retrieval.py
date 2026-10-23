"""Page-aware lexical retrieval; content never becomes execution instructions."""
from collections import Counter
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
from threading import RLock

from .news_rules import CHANNEL_PATTERNS
from .pdf_reader import extract_pdf
from .storage import encode, now

STOP = set('это как что для или при над под его она они оно был была были быть будет будут есть так еще также уже нас вам все эту этого который которая которые после перед между можно нужно если чем через именно своих свою мы вы из на от до по не ни но то же об со за во и а в с у к о г'.split())


def terms(text):
    result = []
    for value in re.findall(r'[а-яёa-z]{3,}', text.lower().replace('ё', 'е')):
        if value not in STOP:
            result.append(value[:6] if len(value) > 6 else re.sub(r'(ами|ями|ов|ах|ях|ый|ий|ая|ое|ые|ам|ям|ом|ем|ы|и|а|у|е|я)$', '', value))
    return [value for value in result if len(value) > 2]


def document_channels(title, text):
    if re.search(r'потреблен|спрос|рознич|consumption', title, re.I):
        return ['DEMAND', 'MACRO']
    if re.search(r'ставк|облигац|финанс', title, re.I):
        return ['FINANCE', 'MACRO']
    counts = {key: len(re.findall(pattern, title + '\n' + text[:10000], re.I)) for key, pattern in CHANNEL_PATTERNS.items()}
    return [key for key, count in sorted(counts.items(), key=lambda item: -item[1])[:2] if count] or ['OTHER']


def chunks_for(pages, document_id):
    chunks = []
    for page in pages:
        text = page['text']
        for start in range(0, len(text), 1000):
            end = min(start + 1200, len(text))
            fragment = text[start:end]
            if len(fragment.strip()) >= 20:
                chunks.append({'id': f'{document_id}:p{page["page"]}:{start}', 'document_id': document_id,
                               'page': page['page'], 'start': start, 'text': fragment, 'method': page.get('method', 'TEXT')})
    return chunks


class Materials:
    def __init__(self, store, folder, runtime):
        self.store = store
        self.folder = Path(folder).resolve()
        self.runtime = Path(runtime).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def add(self, tenant, *, title, kind='ALFA_REPORT', published_at=None, author='', source_url=None,
            text=None, pdf=None, filename=None):
        if published_at:
            date.fromisoformat(published_at)
        raw = pdf if pdf is not None else (text or '').encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        with self.lock:
            existing = self.store.one('SELECT id FROM documents WHERE tenant=? AND content_hash=?', (tenant, digest))
            if existing:
                if pdf is not None:
                    directory = self.runtime / 'documents' / tenant
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / (digest + '.pdf')).write_bytes(pdf)
                return self.get(tenant, existing['id']), False
            parsed = extract_pdf(pdf) if pdf is not None else {'pages': [{'page': 1, 'text': (text or '').strip(), 'method': 'TEXT'}], 'page_count': 1, 'warnings': []}
            if not parsed['pages'] or len(parsed['pages'][0]['text']) < 20:
                raise ValueError('Материал должен содержать хотя бы 20 символов текста.')
            doc_id = 'doc:' + digest[:24]
            if not published_at:
                # A date is inferred only from the cover, never file creation.
                from .news_extraction import DATE_PATTERN, normalized_date
                cover = parsed['pages'][0]['text'][:250]
                match = DATE_PATTERN.search(cover)
                published_at = normalized_date(match.group()) if match else None
            chunks = chunks_for(parsed['pages'], doc_id)
            original = None
            if pdf is not None:
                directory = self.runtime / 'documents' / tenant
                directory.mkdir(parents=True, exist_ok=True)
                archive = directory / (digest + '.pdf')
                archive.write_bytes(pdf)
                original = str(Path('documents') / tenant / (digest + '.pdf'))
            doc = {'id': doc_id, 'title': title, 'kind': kind, 'author': author,
                   'published_at': published_at, 'source_url': str(source_url) if source_url else None,
                   'filename': Path(filename).name if filename else None, 'is_synthetic': kind == 'SYNTHETIC',
                   'content_hash': digest, 'page_count': parsed['page_count'], 'indexed_pages': len(parsed['pages']),
                   'chunk_count': len(chunks), 'warnings': parsed['warnings'], 'created_at': now(),
                   'channels': document_channels(title, parsed['pages'][0]['text']),
                   'original_path': original, 'pages': parsed['pages']}
            with self.store.transaction() as db:
                db.execute('INSERT INTO documents(tenant,id,content_hash,title,kind,published_at,is_synthetic,payload,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                           (tenant, doc_id, digest, title, kind, published_at, int(doc['is_synthetic']), encode(doc), doc['created_at']))
                for chunk in chunks:
                    db.execute('INSERT INTO chunks(tenant,id,document_id,page,text) VALUES(?,?,?,?,?)',
                               (tenant, chunk['id'], doc_id, chunk['page'], encode(chunk)))
            return self.public(doc), True

    def public(self, doc):
        return {key: value for key, value in doc.items() if key not in ('pages', 'original_path')}

    def get(self, tenant, doc_id, full=False):
        row = self.store.one('SELECT payload FROM documents WHERE tenant=? AND id=?', (tenant, doc_id))
        if not row:
            return None
        doc = json.loads(row['payload'])
        if doc.get('original_path'):
            doc['original_path'] = str(self.runtime / 'documents' / tenant / (doc['content_hash'] + '.pdf'))
        return doc if full else self.public(doc)

    def list(self, tenant):
        return [self.public(json.loads(row['payload'])) for row in self.store.all(
            'SELECT payload FROM documents WHERE tenant=? ORDER BY created_at DESC LIMIT 200', (tenant,))]

    def sync(self, tenant):
        root = (self.folder / tenant).resolve()
        root.mkdir(parents=True, exist_ok=True)
        result = {'added': 0, 'unchanged': 0, 'errors': [], 'folder': str(root)}
        with self.lock:
            eligible = [p for p in sorted(root.glob('*')) if p.suffix.lower() in ('.pdf', '.txt', '.md') and p.is_file() and p.name.lower() != 'readme.md']
            if len(eligible) > 40:
                result['errors'].append({'file': '', 'message': 'Обработаны первые 40 файлов. Разделите папку материалов на меньшие наборы.'})
            for path in eligible[:40]:
                resolved = path.resolve()
                if not resolved.is_relative_to(root) or path.suffix.lower() not in ('.pdf', '.txt', '.md') or not path.is_file():
                    continue
                if path.stat().st_size > 10_000_000:
                    result['errors'].append({'file': path.name, 'message': 'Файл превышает 10 МБ.'})
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if self.store.one('SELECT id FROM documents WHERE tenant=? AND content_hash=?', (tenant, digest)):
                    result['unchanged'] += 1
                    continue
                try:
                    kwargs = {'pdf': path.read_bytes()} if path.suffix.lower() == '.pdf' else {'text': path.read_text(encoding='utf-8-sig')}
                    self.add(tenant, title=path.stem.replace('_', ' '), filename=path.name, kind='ALFA_REPORT', **kwargs)
                    result['added'] += 1
                except Exception:
                    result['errors'].append({'file': path.name, 'message': 'Материал не удалось проиндексировать. Проверьте PDF/текст и OCR.'})
        self.store.put_record(tenant, 'materials_sync', 'last', {**result, 'at': now()})
        return result

    def search(self, tenant, query, channels=None, limit=4):
        query_terms = Counter(terms(query))
        if not query_terms:
            return []
        documents = {doc['id']: doc for doc in self.list(tenant)}
        candidates = []
        for row in self.store.all('SELECT document_id,text FROM chunks WHERE tenant=? ORDER BY id LIMIT 5000', (tenant,)):
            doc = documents.get(row['document_id'])
            if not doc or (channels and not set(channels).intersection(doc['channels']) and 'OTHER' not in doc['channels']):
                continue
            chunk = json.loads(row['text'])
            counts = Counter(terms(chunk['text']))
            matched = set(counts).intersection(query_terms)
            if len(matched) < 2:
                continue
            score = sum((1 + math.log(1 + counts[word])) for word in matched) / (1 + len(counts) / 250)
            title_bonus = len(set(terms(doc['title'])).intersection(query_terms))
            candidates.append((score + title_bonus, chunk, doc, sorted(matched)))
        candidates.sort(key=lambda item: (-item[0], item[1]['id']))
        results = []
        seen = set()
        for score, chunk, doc, matched in candidates:
            key = (doc['id'], chunk['page'])
            if key in seen:
                continue
            seen.add(key)
            results.append({'id': chunk['id'], 'document_id': doc['id'], 'title': doc['title'], 'page': chunk['page'],
                            'quote': chunk['text'], 'start': chunk['start'], 'published_at': doc['published_at'],
                            'kind': doc['kind'], 'is_synthetic': doc['is_synthetic'], 'method': chunk['method'],
                            'match_terms': matched, 'retrieval_score': round(score, 3), 'source_url': doc['source_url']})
            if len(results) >= limit:
                break
        return results
