"""Seleção de aula no Chrome e obtenção de áudio da fonte exposta pelo player."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import queue
import threading
from urllib.parse import urlparse, urljoin

START_URL = 'https://www.subido.com.br/cst/a7f2ebbd-d42f-450c-a596-950ae9d4de4c/conteudos?courseType=CST'


def browser_input(page, prompt, reader=None):
    """Mantém o driver atendendo navegações enquanto o Terminal aguarda entrada."""
    reader = reader or input
    results = queue.Queue()
    def read():
        try:
            results.put((True, reader(prompt)))
        except BaseException as error:
            results.put((False, error))
    threading.Thread(target=read, daemon=True).start()
    while results.empty():
        # Apenas a thread principal usa Playwright. A espera bombeia seus eventos.
        page.wait_for_timeout(100)
    # Processar também os eventos pendentes se Enter chegou imediatamente.
    page.wait_for_timeout(100)
    success, value = results.get_nowait()
    if not success:
        raise value
    return value


def lesson_pages(context):
    return [p for p in context.pages if not p.is_closed() and
            re.match(r'https://www\.subido\.com\.br/cst/[^/]+/conteudos/aula/[^/?]+', p.url)]


def close_browser(context):
    # O encerramento não pode mascarar Ctrl+C ou uma falha anterior do driver.
    try:
        context.close()
    except Exception:
        pass


def safe_media_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    allowed = host.endswith('.pandavideo.com.br') or host == 'cdn.pandavideo.com'
    if parsed.scheme != 'https' or parsed.username or parsed.password or not allowed:
        raise RuntimeError(f'Fonte HTTPS não reconhecida do player Panda (host: {host or "ausente"}). Download interrompido.')
    return url


def playlist_children(text, base):
    if not text.lstrip().startswith('#EXTM3U'):
        raise RuntimeError('O player não retornou uma playlist HLS válida.')
    if re.search(r'^#EXT-X-(?:SESSION-)?KEY:', text, re.M):
        raise RuntimeError('Playlist criptografada. Este script não processa mídia protegida.')
    children = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('#EXT-X-STREAM-INF:'):
            following = next((x.strip() for x in lines[index+1:] if x.strip() and not x.startswith('#')), None)
            if following:
                children.append(safe_media_url(urljoin(base, following)))
        elif line.startswith('#EXT-X-MEDIA:'):
            uri = re.search(r'URI="([^"]+)"', line)
            if uri:
                children.append(safe_media_url(urljoin(base, uri.group(1))))
        elif line.strip() and not line.startswith('#'):
            safe_media_url(urljoin(base, line.strip()))
        elif line.startswith('#EXT-X-MAP:'):
            uri = re.search(r'URI="([^"]+)"', line)
            if uri:
                safe_media_url(urljoin(base, uri.group(1)))
    return children


def check_playlists(request, root, referer):
    pending, seen = [root], set()
    while pending:
        url = pending.pop()
        if url in seen:
            continue
        if len(seen) >= 30:
            raise RuntimeError('Playlist complexa demais para o piloto.')
        seen.add(url)
        try:
            response = request.get(safe_media_url(url), headers={'Referer': referer}, timeout=30000)
        except Exception:
            raise RuntimeError('Falha ao carregar a playlist. Confira o acesso e a conexão.') from None
        try:
            if not response.ok:
                raise RuntimeError(f'Acesso à mídia falhou: HTTP {response.status}.')
            safe_media_url(response.url)
            text = response.text()
            if '#EXT-X-ENDLIST' not in text and '#EXT-X-STREAM-INF' not in text and '#EXT-X-MEDIA:' not in text:
                raise RuntimeError('Transmissão ao vivo/incompleta não é suportada neste piloto.')
            pending.extend(playlist_children(text, response.url))
        finally:
            response.dispose()


def extract_audio(source, destination, referer, user_agent, expected_duration):
    executable = shutil.which('ffmpeg')
    if not executable:
        raise RuntimeError('FFmpeg não instalado. No Mac: brew install ffmpeg')
    part = destination.with_suffix('.part.m4a')
    command = [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
               '-protocol_whitelist', 'http,https,tcp,tls', '-rw_timeout', '30000000',
               '-user_agent', user_agent, '-referer', referer, '-i', source,
               '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'aac', '-b:a', '48k', str(part)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=max(180, expected_duration * 2 + 120))
        if result.returncode or not part.exists() or part.stat().st_size < 1000:
            raise RuntimeError('Não foi possível obter o áudio. Confira reprodução/acesso; URLs e tokens não foram registrados.')
        from av import open as open_media
        with open_media(str(part)) as container:
            actual = container.duration / 1000000 if container.duration else 0
            if not container.streams.audio or abs(actual - expected_duration) > max(3, expected_duration * .02):
                raise RuntimeError('Áudio incompleto ou duração incompatível; não será transcrito.')
        part.replace(destination)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Tempo limite ao obter o áudio. Nenhum arquivo parcial será usado.') from None
    finally:
        part.unlink(missing_ok=True)


def hash_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def select_lesson(output, profile=None):
    if not shutil.which('ffmpeg'):
        raise RuntimeError('Instale FFmpeg antes de iniciar: brew install ffmpeg')
    from playwright.sync_api import sync_playwright
    profile = profile or Path(__file__).resolve().parent / '.perfil-transcricao'
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(profile, 0o700)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(profile), channel='chrome', headless=False, viewport={'width': 1440, 'height': 1000})
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(START_URL, wait_until='domcontentloaded')
            while True:
                browser_input(page, '\nNa janela do Chrome aberta pelo script: faça login, abra uma aula e clique em Reproduzir. Depois pressione Enter aqui: ')
                candidates = lesson_pages(context)
                if not candidates:
                    print('Abra a página de uma aula, não apenas a página do curso.'); continue
                if len(candidates) > 1:
                    for i, candidate in enumerate(candidates):
                        print(f'{i+1}: {candidate.locator("h2").first.inner_text()}')
                    selection = browser_input(page, 'Número da aba da aula: ')
                    if not selection.isdigit() or not 1 <= int(selection) <= len(candidates):
                        print('Escolha inválida.'); continue
                    page = candidates[int(selection)-1]
                else:
                    page = candidates[0]
                break
            lesson_url = page.url.split('?')[0]
            lesson_id = urlparse(lesson_url).path.rsplit('/', 1)[-1]
            title = page.locator('h2').first.inner_text()
            print(f'Aula selecionada: {title}')
            player_frame = next((f for f in page.frames if (urlparse(f.url).hostname or '').endswith('.tv.pandavideo.com.br')), None)
            if not player_frame:
                raise RuntimeError('Player Panda não encontrado nesta aula.')
            try:
                player_frame.locator('video').first.wait_for(state='attached', timeout=20000)
            except Exception:
                raise RuntimeError('Vídeo não carregado. Clique em Reproduzir antes de pressionar Enter.') from None
            media = player_frame.locator('video').first.evaluate('''el => ({duration:el.duration, sources:[el.currentSrc, el.getAttribute('src'), ...Array.from(el.querySelectorAll('source')).map(s=>s.src)].filter(Boolean)})''')
            duration = media['duration']
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                raise RuntimeError('Duração do vídeo indisponível. Aguarde o carregamento e tente novamente.')
            source = next((s for s in media['sources'] if s.startswith('https:') and urlparse(s).path.endswith(('.m3u8', '.mp4'))), None)
            if not source:
                raise RuntimeError('O player não expõe uma fonte de mídia compatível.')
            safe_media_url(source)
            referer = player_frame.url
            storage = output / 'audios'
            storage.mkdir(parents=True, exist_ok=True)
            audio = storage / f'{lesson_id}.m4a'
            meta_path = storage / f'{lesson_id}.json'
            metadata = {'lesson_url': lesson_url, 'title': title, 'duration': duration}
            if audio.exists() and meta_path.exists():
                previous = json.loads(meta_path.read_text(encoding='utf-8'))
                if previous.get('lesson_url') == lesson_url and previous.get('audio_sha256') == hash_file(audio) and abs(previous.get('duration', 0)-duration) < 1:
                    print('Áudio já obtido e íntegro. Reutilizando.')
                    return audio, metadata
            if urlparse(source).path.endswith('.m3u8'):
                check_playlists(context.request, source, referer)
            print('Obtendo áudio da aula selecionada...', flush=True)
            extract_audio(source, audio, referer, page.evaluate('navigator.userAgent'), duration)
            metadata['audio_sha256'] = hash_file(audio)
            temp = meta_path.with_suffix('.json.tmp')
            temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(meta_path)
            return audio, metadata
        finally:
            close_browser(context)
