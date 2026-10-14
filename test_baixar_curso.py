import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import baixar_curso as c

COURSE='https://www.subido.com.br/cst/tenant/conteudos/course'
MODULE=COURSE+'/modulo/module'
LESSON='https://www.subido.com.br/cst/tenant/conteudos/aula/lesson'

class CourseDownloads(unittest.TestCase):
    def lesson(self):
        return {'url':LESSON, 'title':'Objetivos: sua mira a laser', 'order':4,
                'module_title':'O Método Subido de Tráfego', 'module_order':2, 'module_url':MODULE}

    def test_cards_titles_scope_and_duplicates(self):
        modules=c.modules_from_cards([{'url':MODULE+'?courseType=CST','heading':'O Método Subido de Tráfego'},
                                      {'url':MODULE,'heading':'duplicate'}],COURSE)
        self.assertEqual(len(modules),1)
        cards=[{'url':LESSON+'?token=do-not-save','paragraphs':['1','Conceitos','19 minutos']},
               {'url':LESSON,'paragraphs':['1','duplicate']},
               {'url':'https://www.subido.com.br/cst/other/conteudos/aula/foreign','paragraphs':['1','foreign']}]
        lessons=c.lessons_from_cards(cards,COURSE,modules[0])
        self.assertEqual(len(lessons),1)
        self.assertEqual(lessons[0]['title'],'Conceitos')
        self.assertNotIn('token',lessons[0]['url'])
        for url in [COURSE.replace('https:','http:'), COURSE.replace('.com.br','.com.br.evil.example'),LESSON]:
            with self.assertRaises(RuntimeError): c.course_url(url)

    def test_names_and_path_boundaries(self):
        path=c.media_path('CURSO SUBIDO DE TRÁFEGO',self.lesson())
        self.assertEqual(path.parent.name,'002-o-metodo-subido-de-trafego')
        self.assertEqual(path.name,'curso-subido-de-trafego-002-o-metodo-subido-de-trafego-004-objetivos-sua-mira-a-laser.mp4')
        self.assertNotEqual(path,c.media_path('CURSO SUBIDO DE TRÁFEGO',{**self.lesson(),'order':5}))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for value in ['/tmp/foreign.mp4','../foreign.mp4','mod/../foreign.mp4','mod/file.txt']:
                with self.assertRaises(RuntimeError): c.safe_destination(root,value)
            self.assertEqual(c.safe_destination(root,path),root/path)
            (root/'escape').symlink_to(root.parent,target_is_directory=True)
            with self.assertRaises(RuntimeError): c.safe_destination(root,'escape/file.mp4')

    def test_filtered_manifest_keeps_other_modules(self):
        first=c.merge_plan({'course_url':COURSE,'course_title':'Curso','lessons':[self.lesson()]},{})
        first['lessons'][0].update(status='concluido',sha256='test-hash')
        other={**self.lesson(),'module_order':3,'module_url':COURSE+'/modulo/other'}
        merged=c.merge_plan({'course_url':COURSE,'course_title':'Curso','lessons':[other]},first)
        self.assertEqual(len(merged['lessons']),2)
        self.assertEqual(merged['lessons'][0]['status'],'concluido')
        with self.assertRaises(RuntimeError): c.merge_plan({'course_url':COURSE+'/different','lessons':[]},first)

    def test_resume_and_preserve_modified_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            plan=c.merge_plan({'course_url':COURSE,'course_title':'Curso','lessons':[self.lesson()]},{})
            lesson=plan['lessons'][0]
            file=root/lesson['file']
            file.parent.mkdir()
            file.write_bytes(b'previously verified fixture')
            lesson.update(status='concluido',sha256=c.hash_file(file))
            with patch.object(c,'capture_player') as capture:
                self.assertEqual(c.process_downloads(None,None,plan,root),0)
                capture.assert_not_called()
            file.write_bytes(b'user-modified-file')
            with patch.object(c,'capture_player') as capture:
                self.assertEqual(c.process_downloads(None,None,plan,root),1)
                capture.assert_not_called()
            self.assertEqual(file.read_bytes(),b'user-modified-file')
            self.assertEqual(json.loads((root/'manifesto.json').read_text())['lessons'][0]['status'],'falha')

    def test_failures_persist_and_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            plan=c.merge_plan({'course_url':COURSE,'course_title':'Curso','lessons':[self.lesson(),{**self.lesson(),'order':5,'url':LESSON+'-two'}]},{})
            with patch.object(c,'capture_player',side_effect=RuntimeError('Player indisponível')) as capture:
                self.assertEqual(c.process_downloads(None,None,plan,root),2)
                self.assertEqual(capture.call_count,2)
            self.assertTrue(all(x['status']=='falha' for x in json.loads((root/'manifesto.json').read_text())['lessons']))

    def test_listing_waits_for_displayed_count(self):
        class Locator:
            def __init__(self): self.reads=0
            @property
            def first(self): return self
            def wait_for(self,**kwargs): pass
            def evaluate(self,_): return 'Vídeos\n2'
            def evaluate_all(self,_):
                self.reads+=1
                return [{'url':'one'}] if self.reads < 7 else [{'url':'one'},{'url':'two'}]
        class Page:
            def __init__(self): self.cards=Locator(); self.heading=Locator()
            def locator(self,selector): return self.heading if selector=='h1' else self.cards
            def evaluate(self,_): pass
            def wait_for_timeout(self,_): pass
        page=Page()
        self.assertEqual(len(c.listing(page,'cards')),2)
        self.assertGreaterEqual(page.cards.reads,10)

    def test_discovery_accepts_single_video_module_heading(self):
        class Page:
            def goto(self,url,**kwargs): self.url=url
            def get_by_role(self,role,name,**kwargs):
                actual='Vídeo' if '/modulo/' in self.url else 'Módulo'
                matches=name.search(actual) if hasattr(name,'search') else name==actual
                if role=='heading' and not matches:
                    raise TimeoutError('Cabeçalho singular não foi reconhecido')
                return self
            def wait_for(self,**kwargs): pass
            def click(self): pass
        module_cards=[{'url':MODULE,'heading':'Introdução ao Tráfego Pago'}]
        lesson_cards=[{'url':LESSON,'paragraphs':['1','Como ganhar dinheiro com esse curso (ou não)?','11 minutos']}]
        with patch.object(c,'read_course_title',return_value='CURSO SUBIDO DE TRÁFEGO'), patch.object(c,'clear_search'), patch.object(c,'listing',side_effect=[module_cards,lesson_cards]):
            plan=c.discover(Page(),COURSE)
        self.assertEqual(len(plan['lessons']),1)
        self.assertEqual(plan['lessons'][0]['module_order'],1)
        self.assertEqual(plan['lessons'][0]['title'],'Como ganhar dinheiro com esse curso (ou não)?')

    def test_duplicate_search_inputs_only_visible_nonempty_is_cleared(self):
        class Field:
            def __init__(self,visible,value): self.visible=visible; self.value=value; self.fills=0
            def is_visible(self): return self.visible
            def input_value(self):
                if not self.visible: raise AssertionError('Campo oculto não deve ser usado')
                return self.value
            def fill(self,value): self.value=value; self.fills+=1
        class Fields:
            def __init__(self): self.items=[Field(True,'Meta Ads'),Field(False,'mobile')]
            def count(self): return len(self.items)
            def nth(self,i): return self.items[i]
        class Page:
            def __init__(self): self.fields=Fields()
            def get_by_placeholder(self,*args,**kwargs): return self.fields
        page=Page()
        c.clear_search(page)
        self.assertEqual(page.fields.items[0].value,'')
        self.assertEqual(page.fields.items[1].fills,0)
        c.clear_search(page)
        self.assertEqual(page.fields.items[0].fills,1)

    def test_resolves_course_from_module_or_lesson_without_using_catalog_links(self):
        class Page:
            def __init__(self,url): self.url=url
            def locator(self,_): return self
            def evaluate_all(self,_): return [COURSE, MODULE]
        self.assertEqual(c.resolve_course_page(Page(COURSE+'?courseType=CST')),COURSE)
        self.assertEqual(c.resolve_course_page(Page(MODULE)),COURSE)
        self.assertEqual(c.resolve_course_page(Page(LESSON)),COURSE)
        self.assertIsNone(c.resolve_course_page(Page('https://www.subido.com.br/cst/tenant/conteudos')))

    def test_navigation_error_reports_stage_without_sensitive_driver_message(self):
        with self.assertRaises(RuntimeError) as caught:
            with c.navigation_step('listar módulos'):
                raise Exception('strict mode violation; https://example.com?token=private-test')
        self.assertIn('listar módulos',str(caught.exception))
        self.assertNotIn('private-test',str(caught.exception))

    def test_course_title_waits_for_nonempty_visible_heading(self):
        class Handle:
            disposed=False
            def json_value(self): return ' CURSO SUBIDO DE TRÁFEGO '
            def dispose(self): self.disposed=True
        class Page:
            handle=Handle()
            def wait_for_function(self,predicate,timeout):
                self_test.assertEqual(timeout,60000)
                return self.handle
            def locator(self,_): raise AssertionError('Não usar leitura imediata do primeiro h3')
        self_test=self
        page=Page()
        self.assertEqual(c.read_course_title(page),'CURSO SUBIDO DE TRÁFEGO')
        self.assertTrue(page.handle.disposed)

    def test_automatic_player_start_and_course_membership(self):
        class Control:
            @property
            def first(self): return self
            def count(self): return 1
            def is_visible(self): return True
            def wait_for(self,**kwargs): pass
        class Frame:
            url='https://player.tv.pandavideo.com.br/embed'
            def __init__(self): self.clicked=False
            def get_by_role(self,*args,**kwargs):
                frame=self
                class Play(Control):
                    def click(self,**kwargs): frame.clicked=True
                return Play()
            def locator(self,_):
                frame=self
                class Video(Control):
                    def evaluate(self,_):
                        self_test.assertTrue(frame.clicked)
                        return {'duration':60,'sources':['https://b.tv.pandavideo.com.br/list.m3u8']}
                return Video()
        self_test=self
        class Page:
            def __init__(self): self.frames=[Frame()]; self.member=COURSE
            def goto(self,url,**kwargs): self.url=url
            def locator(self,selector):
                page=self
                class Breadcrumb(Control):
                    def evaluate_all(self,_): return [page.member]
                return Breadcrumb()
            def wait_for_timeout(self,_): pass
        page=Page()
        source,referer,duration=c.capture_player(page,self.lesson(),COURSE)
        self.assertTrue(page.frames[0].clicked)
        self.assertEqual(duration,60)
        self.assertEqual(source,'https://b.tv.pandavideo.com.br/list.m3u8')
        page.member=COURSE+'-foreign'
        with self.assertRaises(RuntimeError): c.capture_player(page,self.lesson(),COURSE)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'Requer FFmpeg e FFprobe')
    def test_mp4_duration_atomic_download_and_partial_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            fixture=root/'fixture.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=black:s=160x90:r=10:d=1',
                            '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-c:a','aac','-shortest',str(fixture)],check=True)
            c.validate_video(fixture,1)
            with self.assertRaises(RuntimeError): c.validate_video(fixture,60)
            destination=root/'download.mp4'
            original_run=subprocess.run
            def fake_download(command,**kwargs):
                if '-i' in command:
                    self.assertEqual(command[command.index('-c')+1],'copy')
                    shutil.copyfile(fixture,command[-1])
                    return subprocess.CompletedProcess(command,0)
                return original_run(command,**kwargs)
            with patch('subprocess.run',side_effect=fake_download):
                c.download_video('https://b.tv.pandavideo.com.br/list.m3u8',destination,'https://player.tv.pandavideo.com.br','test',1)
            self.assertTrue(destination.exists())
            self.assertFalse(destination.with_suffix('.part.mp4').exists())
            with self.assertRaises(RuntimeError): c.download_video('https://b.tv.pandavideo.com.br/list.m3u8',destination,'','',1)
            destination=root/'failed.mp4'
            def fail(command,**kwargs):
                Path(command[-1]).write_bytes(b'partial')
                return subprocess.CompletedProcess(command,1)
            with patch('subprocess.run',side_effect=fail),self.assertRaises(RuntimeError):
                c.download_video('https://b.tv.pandavideo.com.br/list.m3u8',destination,'','',1)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix('.part.mp4').exists())

if __name__=='__main__': unittest.main()
