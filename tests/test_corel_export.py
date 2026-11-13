"""Prompt and the same editable CorelDRAW SVG source for PNG/JPEG both formats."""
import base64
import io
import json
import xml.etree.ElementTree as ET
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.render import default_brief
from app.editable_export import create_editable_svg, rasterize_svg

client=TestClient(app)
NS={'s':'http://www.w3.org/2000/svg'}
XLINK='{http://www.w3.org/1999/xlink}href'


def payload():
    return json.dumps(default_brief(),ensure_ascii=False)


def test_free_prompt_from_submitted_brief_without_key(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    r=client.post('/api/prompt',json=default_brief())
    assert r.status_code==200,r.text
    data=r.json()
    assert data['ai_required'] is False
    assert 'ZubrTrail 500' in data['prompt']
    assert 'Основные' not in data['prompt'] or 'Технические' in data['prompt']
    assert 'CorelDRAW' in data['prompt'] and 'JPEG' in data['prompt']
    assert client.post('/api/prompt',json={'model':''}).status_code==400
    assert client.post('/api/prompt',data='not-json',headers={'Content-Type':'application/json'}).status_code==400


def test_generate_png_jpeg_corel_svg_and_prompt_zip(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    prompt='Светлая промышленная сцена, никаких лишних надписей.'
    r=client.post('/api/generate',data={
      'payload':payload(),'use_openai':'false','use_demo':'true','prompt':prompt})
    assert r.status_code==200,r.text
    result=r.json()
    assert set(result['images'])=={'4x3','9x16'}
    assert set(result['jpeg'])=={'4x3','9x16'}
    assert set(result['corel'])=={'4x3','9x16'}
    for key,wh in (('4x3',(1440,1080)),('9x16',(1080,1920))):
        png=client.get(result['images'][key]).content
        jpg=client.get(result['jpeg'][key]).content
        answer=client.get(result['corel'][key])
        svg=answer.content
        assert answer.status_code==200
        assert 'attachment' in answer.headers['content-disposition']
        assert Image.open(io.BytesIO(png)).size==wh
        assert Image.open(io.BytesIO(png)).format=='PNG'
        assert Image.open(io.BytesIO(jpg)).size==wh
        assert Image.open(io.BytesIO(jpg)).format=='JPEG'
        root=ET.fromstring(svg)
        assert root.attrib['viewBox']==f'0 0 {wh[0]} {wh[1]}'
        texts=root.findall('.//s:text',NS)
        images=root.findall('.//s:image',NS)
        assert len(texts)>15
        assert images
        assert any('ZubrTrail' in ''.join(x.itertext()) for x in texts)
        assert all(i.attrib[XLINK].startswith('data:image/png;base64,') for i in images)
        assert len(root.findall('s:g',NS))>=10
        png_from_svg,_=rasterize_svg(svg)
        assert png_from_svg==png
    names={'poster_4x3.png','poster_9x16.png',
           'poster_4x3.jpg','poster_9x16.jpg',
           'corel_4x3.svg','corel_9x16.svg',
           'promo_prompt.txt','brief.json','CORELDRAW_README.txt'}
    archive=zipfile.ZipFile(io.BytesIO(client.get(result['zip']).content))
    assert set(archive.namelist())==names
    assert archive.read('promo_prompt.txt').decode('utf-8')==prompt
    assert client.get(result['prompt_file']).status_code==200
    assert 'CorelDRAW' in archive.read('CORELDRAW_README.txt').decode('utf-8')
    info=json.loads(archive.read('brief.json'))['_metadata']
    assert 'CorelDRAW' in info['editable_source']


def test_photo_logo_drawing_are_separate_editable_bitmap_elements():
    p=default_brief()
    p['model']='<script>alert(1)</script> & Подъёмник'
    p['specs']=[['Мощность','55 кВт'],['Цена','10 < 20']]
    image=Image.new('RGBA',(160,140),'red')
    svg=create_editable_svg(p,'4x3',hero=image,logo=image,detail=image,drawing=image)
    root=ET.fromstring(svg)
    images=root.findall('.//s:image',NS)
    assert len(images)==4
    assert len({i.attrib['id'] for i in images})==len(images)
    assert not root.findall('.//s:script',NS)
    assert b'&lt;script&gt;' in svg
    assert any('55 кВт' in ''.join(n.itertext()) for n in root.findall('.//s:text',NS))
    assert all(i.attrib[XLINK].startswith('data:image/png;base64,') for i in images)


def test_prompt_reaches_two_ai_generation_requests(monkeypatch):
    from app import openai_service
    raw=io.BytesIO();Image.new('RGB',(128,64),'blue').save(raw,'PNG')
    encoded=base64.b64encode(raw.getvalue()).decode()
    calls=[]
    class Images:
        def generate(self,**kwargs):
            calls.append(kwargs)
            return type('Result',(),{'data':[type('Datum',(),{'b64_json':encoded})()]})()
    monkeypatch.setattr(openai_service,'client',lambda:type('API',(),{'images':Images()})())
    monkeypatch.setenv('OPENAI_API_KEY','fake-for-test-only')
    prompt='Красивый светлый фон с мягкой подсветкой техники.'
    r=client.post('/api/generate',data={'payload':payload(),'use_openai':'true','prompt':prompt})
    assert r.status_code==200,r.text
    assert len(calls)==2
    assert all(prompt in c['prompt'] for c in calls)
    assert r.json()['ai_used'] is True


def test_rejects_prompt_over_limit_and_unknown_paths():
    r=client.post('/api/generate',data={'payload':payload(),'use_demo':'true','prompt':'x'*8001})
    assert r.status_code==400
    assert client.get('/files/'+'a'*32+'/bad.svg').status_code==404


def test_frontend_prompt_and_corel_download_controls():
    page=client.get('/').text
    js=client.get('/static/app.js').text
    for identifier in ('prompt-workflow','promo-prompt','build-prompt-btn','promo-prompt-status',
                       'download-jpeg-4x3','download-jpeg-9x16','download-svg-4x3','download-svg-9x16'):
        assert f'id="{identifier}"' in page
    assert "fetch('/api/prompt'" in js
    assert "form.append('prompt',prompt)" in js
    assert "latest?.corel?.['9x16']" in js
