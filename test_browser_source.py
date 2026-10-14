import unittest
from browser_source import playlist_children, check_playlists, safe_media_url, browser_input, lesson_pages, close_browser
import threading


class Sources(unittest.TestCase):
    def test_real_panda_cdn_segments_and_lookalikes(self):
        root = 'https://b-vz-ded14ebd-85a.tv.pandavideo.com.br/video/480p/video.m3u8'
        cdn = 'https://cdn.pandavideo.com/vz-example/video/480p/video0.ts'
        self.assertEqual(playlist_children(f'#EXTM3U\n#EXTINF:4.000000,\n{cdn}\n#EXT-X-ENDLIST\n', root), [])
        self.assertEqual(safe_media_url(cdn), cdn)
        for url in ['https://cdn.pandavideo.com.evil.example/video.ts', 'https://evil.pandavideo.com/video.ts', 'http://cdn.pandavideo.com/video.ts']:
            with self.assertRaises(RuntimeError): safe_media_url(url)

    def test_navigation_updates_while_waiting_for_enter(self):
        updated = threading.Event()
        class Page:
            url = 'https://www.subido.com.br/cst/id/conteudos'
            def is_closed(self): return False
            def wait_for_timeout(self, _):
                self.url = 'https://www.subido.com.br/cst/id/conteudos/aula/aula-id'
                updated.set()
        page = Page()
        class Context:
            pages = [page]
        def reader(_):
            if not updated.wait(timeout=1):
                raise AssertionError('Eventos do navegador ficaram bloqueados pelo input.')
            return ''
        self.assertEqual(browser_input(page, 'Enter', reader), '')
        self.assertEqual(lesson_pages(Context()), [page])

    def test_cancel_and_driver_close_failure(self):
        class Page:
            def wait_for_timeout(self, _): pass
        def interrupt(_): raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            browser_input(Page(), 'Enter', interrupt)
        class Context:
            def close(self): raise RuntimeError('Connection closed while reading from driver')
        close_browser(Context())

    def test_relative_variant_and_encrypted_playlist(self):
        root = 'https://b-vz-example.tv.pandavideo.com.br/video/playlist.m3u8'
        self.assertEqual(playlist_children('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n480/index.m3u8\n', root), ['https://b-vz-example.tv.pandavideo.com.br/video/480/index.m3u8'])
        with self.assertRaises(RuntimeError):
            playlist_children('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n', root)

    def test_blocks_foreign_source_and_file_segment(self):
        with self.assertRaises(RuntimeError):
            safe_media_url('https://pandavideo.com.br.evil.example/movie.mp4')
        with self.assertRaises(RuntimeError):
            playlist_children('#EXTM3U\nfile:///private/example.ts\n', 'https://b.tv.pandavideo.com.br/list.m3u8')

    def test_checks_encryption_in_child_not_just_master(self):
        class Response:
            ok = True
            def __init__(self, url): self.url = url
            def text(self):
                if self.url.endswith('master.m3u8'):
                    return '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nchild.m3u8\n'
                return '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXT-X-ENDLIST\n'
            def dispose(self): pass
        class Request:
            def get(self, url, **kwargs): return Response(url)
        with self.assertRaisesRegex(RuntimeError, 'criptografada'):
            check_playlists(Request(), 'https://b.tv.pandavideo.com.br/master.m3u8', 'https://player.tv.pandavideo.com.br/')


if __name__ == '__main__': unittest.main()
