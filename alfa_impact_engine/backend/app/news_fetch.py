"""Explicit bounded public URL ingestion, DNS pinned, no redirects or proxies."""
import http.client
import ipaddress
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit


def public_address(host):
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError
        return addresses[0]
    except (ValueError, OSError):
        raise ValueError('URL должен указывать на общедоступный интернет-источник.') from None


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.skip, self.in_title = [], [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.skip += 1
        if tag == 'title':
            self.in_title = True
        if tag in ('p', 'h1', 'h2', 'div', 'br', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.skip = max(0, self.skip - 1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.in_title:
                self.title.append(data)


def fetch_article(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None
                or any(c.isspace() or ord(c) < 32 for c in url)):
            raise ValueError('Используйте HTTPS URL без логина и нестандартного порта.')
        address = public_address(parsed.hostname)
        connection = PinnedHTTPS(parsed.hostname, address)
        try:
            target = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
            connection.request('GET', target, headers={'User-Agent': 'AlfaImpactEngine/1.0 (explicit article import)',
                               'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError('Источник не отдал статью. Перенаправления не выполняются; вставьте конечный URL или текст.')
            media = response.getheader('Content-Type', '').lower()
            if not media.startswith(('text/html', 'text/plain')) or response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Источник должен возвращать HTML или обычный текст без сжатия.')
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError('Статья превышает лимит загрузки 2 МБ.')
        finally:
            connection.close()
        charset = 'utf-8'
        if 'charset=' in media:
            charset = media.split('charset=', 1)[1].split(';')[0].strip(' "')
        try:
            text = data.decode(charset, errors='replace')
        except LookupError:
            text = data.decode('utf-8', errors='replace')
        title = ''
        if media.startswith('text/html'):
            parser = ArticleParser()
            parser.feed(text)
            text, title = ''.join(parser.parts), ' '.join(parser.title)
        text = '\n'.join(' '.join(line.split()) for line in text.splitlines() if line.strip())
        if len(text) < 20:
            raise ValueError('В источнике недостаточно текста. Вставьте текст новости вручную.')
        return {'title': title[:240] or None, 'text': text[:20000], 'source_url': url,
                'truncated': len(text) > 20000, 'warning': 'Проверьте извлечённый текст перед анализом: HTML может содержать меню и другие публикации.'}
    except (socket.timeout, OSError, ssl.SSLError, http.client.HTTPException):
        raise ValueError('Не удалось загрузить источник. Вставьте текст новости вручную.') from None
