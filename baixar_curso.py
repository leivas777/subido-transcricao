#!/usr/bin/env python3
"""Escolhe um curso no Chrome e baixa vídeos MP4 por módulo, sem chamadas LLM."""
import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from urllib.parse import urlparse
from browser_source import START_URL, browser_input, close_browser, safe_media_url, check_playlists, hash_file

BASE = Path(__file__).resolve().parent
COURSE = re.compile(r'/cst/([a-zA-Z0-9-]+)/conteudos/((?!aula$)[a-zA-Z0-9-]+)$')
CARDS = '''els => els.map(a => ({url:a.href, text:a.innerText,
    heading:a.querySelector('h2')?.innerText || '',
    paragraphs:Array.from(a.querySelectorAll('p')).map(p=>p.innerText),
    alt:a.querySelector('img')?.alt || ''}))'''
COURSE_TITLE = '''() => {
    for (const heading of document.querySelectorAll('main h3')) {
        const rect = heading.getBoundingClientRect();
        const style = getComputedStyle(heading);
        const text = heading.innerText.trim();
        if (rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && text) return text;
    }
    return null;
}'''


def site_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'www.subido.com.br' or parsed.username or parsed.password:
        raise RuntimeError('Use uma página HTTPS do curso em www.subido.com.br.')
    # Persistir somente a rota: nenhum parâmetro de sessão entra no manifesto.
    return f'https://www.subido.com.br{parsed.path.rstrip("/")}'


def course_url(url):
    url = site_url(url)
    if not COURSE.fullmatch(urlparse(url).path):
        raise RuntimeError('Abra a página de um curso, com a lista de módulos.')
    return url


def resolve_course_page(page):
    try:
        return course_url(page.url)
    except RuntimeError:
        pass
    try:
        url = site_url(page.url)
    except RuntimeError:
        return None
    module = re.fullmatch(r'(/cst/[a-zA-Z0-9-]+/conteudos/[a-zA-Z0-9-]+)/modulo/[a-zA-Z0-9-]+', urlparse(url).path)
    if module:
        return course_url('https://www.subido.com.br'+module.group(1))
    if re.fullmatch(r'/cst/[a-zA-Z0-9-]+/conteudos/aula/[a-zA-Z0-9-]+', urlparse(url).path):
        for href in page.locator('a[href*="/conteudos/"]:has(h3)').evaluate_all('els => els.map(a => a.href)'):
            try:
                return course_url(href)
            except RuntimeError:
                continue
    return None


def clear_search(page):
    # O Subido renderiza versões desktop/mobile; uma delas fica oculta.
    fields = page.get_by_placeholder('Pesquisar...', exact=True)
    for index in range(fields.count()):
        field = fields.nth(index)
        if field.is_visible() and field.input_value():
            field.fill('')


def read_course_title(page):
    # O cabeçalho "Módulos" pode aparecer antes dos dados/título do curso.
    handle = page.wait_for_function(COURSE_TITLE, timeout=60000)
    try:
        title = handle.json_value()
    finally:
        handle.dispose()
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError('Nome do curso não carregado. Confira o acesso e tente novamente.')
    return title.strip()


@contextmanager
def navigation_step(label):
    try:
        yield
    except Exception as error:
        if isinstance(error, RuntimeError):
            detail = str(error)
        elif 'strict mode violation' in str(error).lower():
            detail = 'Mais de um elemento corresponde ao controle da página.'
        elif 'timeout' in type(error).__name__.lower():
            detail = 'Tempo limite ao aguardar a página/controle. Confira login e conexão.'
        else:
            detail = f'Falha no navegador ({type(error).__name__}).'
        # Não imprimir mensagens brutas do driver: podem conter URLs de sessão.
        raise RuntimeError(f'Etapa "{label}": {detail}') from None


def slug(value, limit=60):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', value).strip('-')[:limit].rstrip('-') or 'sem-titulo'


def atomic_json(path, value):
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def modules_from_cards(cards, selected):
    root = urlparse(course_url(selected)).path + '/modulo/'
    modules, seen = [], set()
    for card in cards:
        url = site_url(card['url'])
        path = urlparse(url).path
        if not re.fullmatch(re.escape(root) + '[a-zA-Z0-9-]+', path) or url in seen:
            continue
        title = card['heading'].strip() or card['alt'].strip()
        if not title:
            raise RuntimeError('Módulo sem título; não é possível nomear os arquivos.')
        seen.add(url)
        modules.append({'url': url, 'title': title, 'order': len(modules)+1})
    if not modules:
        raise RuntimeError('Nenhum módulo encontrado. Confira o curso e o filtro Todos.')
    return modules


def lessons_from_cards(cards, selected, module):
    tenant = COURSE.fullmatch(urlparse(course_url(selected)).path).group(1)
    root = f'/cst/{tenant}/conteudos/aula/'
    lessons, seen = [], set()
    for card in cards:
        url = site_url(card['url'])
        if not re.fullmatch(re.escape(root) + '[a-zA-Z0-9-]+', urlparse(url).path) or url in seen:
            continue
        paragraphs = card.get('paragraphs', [])
        title = card.get('heading', '').strip() or (paragraphs[1].strip() if len(paragraphs) >= 2 else '')
        if not title:
            raise RuntimeError('Aula sem título; estrutura da página não reconhecida.')
        seen.add(url)
        lessons.append({'url': url, 'title': title, 'order': len(lessons)+1,
                        'module_title': module['title'], 'module_order': module['order'], 'module_url': module['url']})
    if not lessons:
        raise RuntimeError('Nenhuma aula encontrada no módulo; verifique seu acesso.')
    return lessons


def media_path(course_title, lesson):
    mod = f'{lesson["module_order"]:03}-{slug(lesson["module_title"], 55)}'
    aula = f'{lesson["order"]:03}-{slug(lesson["title"], 70)}'
    return Path(mod) / f'{slug(course_title, 55)}-{mod}-{aula}.mp4'


def safe_destination(folder, relative):
    relative = Path(relative)
    if relative.is_absolute() or len(relative.parts) != 2 or '..' in relative.parts or relative.suffix != '.mp4':
        raise RuntimeError('Caminho de vídeo inválido no manifesto.')
    destination = folder / relative
    if not destination.resolve().is_relative_to(folder.resolve()):
        raise RuntimeError('Caminho de vídeo fora da pasta do curso.')
    return destination


def listing(page, selector):
    page.locator(selector).first.wait_for(state='attached', timeout=60000)
    # Inclui cartões carregados ao rolar; parar somente após estabilização.
    previous, stable = -1, 0
    for _ in range(50):
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(600)
        cards = page.locator(selector).evaluate_all(CARDS)
        count_text = page.locator('h1').first.evaluate('el => el.parentElement.parentElement.innerText')
        count = re.search(r'(?:Módulos?|Vídeos?)\s+(\d+)', count_text)
        expected = int(count.group(1)) if count else None
        if len(cards) == previous:
            stable += 1
        else:
            previous, stable = len(cards), 0
        if stable >= 3 and (expected is None or len(cards) >= expected):
            return cards
    raise RuntimeError('A lista não estabilizou; inventário interrompido para evitar omissões.')


def discover(page, selected, module_filter=None):
    selected = course_url(selected)
    with navigation_step('listar módulos do curso'):
        page.goto(selected + '?courseType=CST', wait_until='domcontentloaded')
        page.get_by_role('heading', name=re.compile(r'^Módulos?$')).wait_for(timeout=60000)
        page.get_by_role('button', name='Todos', exact=True).click()
        clear_search(page)
        title = read_course_title(page)
        modules = modules_from_cards(listing(page, 'a[href*="/modulo/"]'), selected)
    lessons = []
    for module in modules:
        if module_filter and module['order'] != module_filter:
            continue
        print(f'Listando módulo {module["order"]}: {module["title"]}', flush=True)
        with navigation_step(f'listar aulas do módulo {module["order"]}'):
            page.goto(module['url'] + '?courseType=CST', wait_until='domcontentloaded')
            page.get_by_role('heading', name=re.compile(r'^Vídeos?$')).wait_for(timeout=60000)
            page.get_by_role('button', name='Todos', exact=True).click()
            clear_search(page)
            lessons.extend(lessons_from_cards(listing(page, 'a[href*="/conteudos/aula/"]'), selected, module))
    if not lessons:
        raise RuntimeError('O módulo solicitado não foi encontrado.')
    return {'course_url': selected, 'course_title': title, 'modules': modules, 'lessons': lessons}


def capture_player(page, lesson, selected):
    page.goto(lesson['url'] + '?courseType=CST', wait_until='domcontentloaded')
    page.locator('h2').first.wait_for(state='visible', timeout=60000)
    # Breadcrumb comprova que a aula pertence ao curso escolhido.
    breadcrumbs = page.locator(f'a[href*="{urlparse(selected).path}"]:has(h3)')
    breadcrumbs.first.wait_for(state='attached', timeout=60000)
    urls = breadcrumbs.evaluate_all('els => els.map(a => a.href)')
    if not any(site_url(url) == selected for url in urls):
        raise RuntimeError('A aula não pertence ao curso escolhido.')
    deadline = time.monotonic() + 60
    clicked = False
    while time.monotonic() < deadline:
        frame = next((f for f in page.frames if (urlparse(f.url).hostname or '').endswith('.tv.pandavideo.com.br')), None)
        if frame:
            if not clicked:
                play = frame.get_by_role('button', name='Reproduzir', exact=True)
                if play.count() and play.first.is_visible():
                    play.first.click(timeout=10000)
                    clicked = True
            video = frame.locator('video').first
            if video.count():
                media = video.evaluate('''el => ({duration:el.duration, sources:[el.currentSrc,el.getAttribute('src'),
                    ...Array.from(el.querySelectorAll('source')).map(s=>s.src)].filter(Boolean)})''')
                duration = media['duration']
                source = next((s for s in media['sources'] if s.startswith('https:') and
                               urlparse(s).path.endswith(('.m3u8', '.mp4'))), None)
                if source and isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0:
                    return safe_media_url(source), frame.url, duration
        page.wait_for_timeout(250)
    raise RuntimeError('O player não carregou uma fonte compatível automaticamente. Verifique acesso/reprodução da aula.')


def validate_video(path, expected_duration):
    executable = shutil.which('ffprobe')
    if not executable:
        raise RuntimeError('FFprobe necessário para conferir o vídeo; instale FFmpeg completo.')
    result = subprocess.run([executable, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                             '-of', 'json', str(path)], capture_output=True, timeout=30)
    try:
        data = json.loads(result.stdout)
        actual = float(data['format']['duration'])
        streams = {s['codec_type'] for s in data['streams']}
    except (ValueError, KeyError, TypeError):
        raise RuntimeError('Não foi possível validar a duração/trilhas do vídeo.') from None
    if result.returncode or not math.isfinite(actual) or not {'video', 'audio'} <= streams or abs(actual-expected_duration) > max(3, expected_duration*.02):
        raise RuntimeError('MP4 incompleto ou duração incompatível.')


def download_video(source, destination, referer, user_agent, duration):
    executable = shutil.which('ffmpeg')
    if not executable:
        raise RuntimeError('Instale FFmpeg: brew install ffmpeg')
    if destination.exists():
        raise RuntimeError('Arquivo existente sem integridade confirmada; preservado sem sobrescrever.')
    part = destination.with_suffix('.part.mp4')
    if part.is_symlink():
        raise RuntimeError('Arquivo parcial é um link simbólico; download interrompido.')
    command = [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
               '-protocol_whitelist', 'http,https,tcp,tls', '-rw_timeout', '30000000',
               '-user_agent', user_agent, '-referer', referer, '-i', safe_media_url(source),
               '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', '-movflags', '+faststart', str(part)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=max(180, duration*2+120))
        if result.returncode or not part.exists() or part.stat().st_size < 1000:
            raise RuntimeError('FFmpeg não conseguiu obter o vídeo completo. Fonte/tokens não foram registrados.')
        validate_video(part, duration)
        part.replace(destination)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Tempo limite ao obter vídeo; arquivo parcial não será usado.') from None
    finally:
        part.unlink(missing_ok=True)


def merge_plan(plan, previous):
    if previous and previous.get('course_url') != plan['course_url']:
        raise RuntimeError('A pasta já pertence a outro curso com nome semelhante. Escolha outro --destino.')
    old = {(x['module_url'], x['url']): x for x in previous.get('lessons', [])}
    for lesson in plan['lessons']:
        lesson['file'] = media_path(plan['course_title'], lesson).as_posix()
        lesson['status'] = 'pendente'
        prior = old.get((lesson['module_url'], lesson['url']), {})
        if prior.get('file') == lesson['file']:
            for field in ('status', 'sha256', 'duration', 'error'):
                if field in prior:
                    lesson[field] = prior[field]
    # Um teste filtrado não deve apagar o inventário/progresso dos demais módulos.
    present = {(x['module_url'], x['url']) for x in plan['lessons']}
    plan['lessons'].extend(x for key, x in old.items() if key not in present)
    plan['lessons'].sort(key=lambda x: (x['module_order'], x['order']))
    return plan


def process_downloads(page, context, plan, folder, limit=None, module_filter=None):
    manifest = folder / 'manifesto.json'
    processed = failures = 0
    for lesson in plan['lessons']:
        if module_filter and lesson['module_order'] != module_filter:
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        destination = safe_destination(folder, lesson['file'])
        if lesson['status'] == 'concluido' and destination.exists() and lesson.get('sha256') == hash_file(destination):
            print(f'Reutilizando vídeo íntegro: {lesson["file"]}')
            continue
        print(f'Baixando: {lesson["module_title"]} / {lesson["title"]}', flush=True)
        try:
            if destination.exists():
                raise RuntimeError('Arquivo existente sem integridade confirmada; preservado sem sobrescrever.')
            source, referer, duration = capture_player(page, lesson, plan['course_url'])
            lesson.update(status='baixando', duration=duration)
            atomic_json(manifest, plan)
            if urlparse(source).path.endswith('.m3u8'):
                check_playlists(context.request, source, referer)
            destination.parent.mkdir(parents=True, exist_ok=True)
            download_video(source, destination, referer, page.evaluate('navigator.userAgent'), duration)
            lesson.update(status='concluido', sha256=hash_file(destination))
            lesson.pop('error', None)
        except Exception as error:
            failures += 1
            lesson.update(status='falha', error=str(error) if isinstance(error, RuntimeError) else 'Falha de navegação, acesso ou validação do player.')
            print(f'Aula não concluída: {lesson["error"]}')
        finally:
            atomic_json(manifest, plan)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--curso', help='Opcional: URL da página do curso; sem ela você escolhe no Chrome')
    parser.add_argument('--destino', type=Path, default=BASE / 'videos')
    parser.add_argument('--apenas-listar', action='store_true', help='Salvar inventário sem reproduzir nem baixar aulas')
    parser.add_argument('--limite-aulas', type=int, help='Limitar aulas percorridas nesta execução; sem limite baixa todas')
    parser.add_argument('--modulo', type=int, help='Opcional: posição do módulo no curso, começando em 1')
    args = parser.parse_args()
    if any(n is not None and n < 1 for n in (args.limite_aulas, args.modulo)):
        parser.error('Limites e número de módulo devem ser positivos.')
    if args.curso:
        try:
            args.curso = course_url(args.curso)
        except RuntimeError as error:
            parser.error(str(error))
    if not args.apenas_listar and not shutil.which('ffmpeg'):
        parser.error('Instale FFmpeg: brew install ffmpeg')
    from playwright.sync_api import sync_playwright
    profile = BASE / '.perfil-transcricao'
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(profile, 0o700)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(profile), channel='chrome', headless=False,
                                                       viewport={'width': 1440, 'height': 1000})
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto((args.curso + '?courseType=CST') if args.curso else START_URL, wait_until='domcontentloaded')
            while True:
                browser_input(page, '\nNA JANELA DO CHROME ABERTA POR ESTE SCRIPT: faça login e abra o curso desejado. Depois pressione Enter aqui: ')
                if args.curso:
                    # A URL explícita dispensa reconhecer manualmente outra aba.
                    selected = args.curso
                    break
                candidates = []
                for candidate in context.pages:
                    if candidate.is_closed():
                        continue
                    with navigation_step('identificar curso na janela do script'):
                        selected_course = resolve_course_page(candidate)
                    if selected_course and not any(u == selected_course for _, u in candidates):
                        candidates.append((candidate, selected_course))
                if not candidates:
                    print('Nenhum curso identificado na janela do script. Abra o curso nessa janela, não no Chrome habitual. Você também pode informar --curso URL.'); continue
                if len(candidates) > 1:
                    for i, (candidate, url) in enumerate(candidates):
                        print(f'{i+1}: {url}')
                    value = browser_input(page, 'Número da aba do curso: ')
                    if not value.isdigit() or not 1 <= int(value) <= len(candidates):
                        print('Número inválido.'); continue
                    page, selected = candidates[int(value)-1]
                else:
                    page, selected = candidates[0]
                break
            plan = discover(page, selected, args.modulo)
            folder = args.destino.resolve() / slug(plan['course_title'], 55)
            folder.mkdir(parents=True, exist_ok=True)
            manifest = folder / 'manifesto.json'
            previous = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
            plan = merge_plan(plan, previous)
            atomic_json(manifest, plan)
            total = sum(not args.modulo or x['module_order'] == args.modulo for x in plan['lessons'])
            print(f'Curso: {plan["course_title"]}; {len(plan["modules"])} módulos; {total} aulas no escopo. Manifesto: {manifest}')
            if args.apenas_listar:
                return 0
            failures = process_downloads(page, context, plan, folder, args.limite_aulas, args.modulo)
            completed = sum(x['status'] == 'concluido' for x in plan['lessons'])
            print(f'Vídeos íntegros registrados: {completed}/{len(plan["lessons"])}. Falhas nesta execução: {failures}. Saída: {folder}')
            return 2 if failures else 0
        finally:
            close_browser(context)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nCancelado. Vídeos concluídos e manifesto preservados.')
        sys.exit(130)
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else 'Não foi possível concluir o inventário/navegação. Confira acesso ao curso e conexão.')
        sys.exit(2)
