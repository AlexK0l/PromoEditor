"""Editing a finished promo with a user-selected mask, without changing the original."""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image,ImageDraw

from app import editor_service
from app.main import app

client=TestClient(app)

def png(color=(10,120,15),width=640,height=480):
    im=Image.new('RGB',(width,height),color)
    buff=io.BytesIO()
    im.save(buff,format='PNG')
    return buff.getvalue()

def mask(width=640,height=480,valid=True):
    im=Image.new('RGBA',(width,height),(255,255,255,255))
    if valid:ImageDraw.Draw(im).rectangle((100,100,260,230),fill=(255,255,255,0))
    b=io.BytesIO();im.save(b,'PNG');return b.getvalue()

def test_validates_image_masks_and_instruction():
    with pytest.raises(ValueError,match='Маска'):
        editor_service._mask(mask(width=500),(640,480))
    with pytest.raises(ValueError,match='Выделите'):
        editor_service._mask(mask(valid=False),(640,480))
    with pytest.raises(ValueError,match='Разрешение'):
        editor_service._source(png(width=5000,height=128))

def test_requires_openai_key_even_with_valid_upload(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    response=client.post('/api/edit',data={'instruction':'Убрать старый значок'},
                         files={'image':('poster.png',png(),'image/png')})
    assert response.status_code==400
    assert 'OPENAI_API_KEY' in response.json()['detail']

def test_rejects_blank_request_and_invalid_mask(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    response=client.post('/api/edit',data={'instruction':'  '},
                         files={'image':('poster.png',png(),'image/png')})
    assert response.status_code==400
    response=client.post('/api/edit',data={'instruction':'Заменить объект'},
        files={'image':('poster.png',png(),'image/png'),
               'mask':('mask.png',mask(width=500),'image/png')})
    assert response.status_code==400

def test_edit_uses_mask_and_retains_exact_pixels_outside(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    calls=[]
    class Images:
        def edit(self,**kw):
            calls.append(kw)
            from base64 import b64encode
            b64=b64encode(png(color=(250,0,0),width=1536,height=1024)).decode()
            return type('Answer',(),{'data':[type('Part',(),{'b64_json':b64})()]})()
    monkeypatch.setattr(editor_service,'client',lambda:type('API',(),{'images':Images()})())
    raw=png()
    response=client.post('/api/edit',data={'instruction':'Заменить область красным','model':'gpt-image-2.5-flare'},
        files={'image':('poster.png',raw,'image/png'),
               'mask':('region.png',mask(),'image/png')})
    assert response.status_code==200,response.text
    link=response.json()['image']
    assert link.startswith('/files/') and link.endswith('/edit.png')
    assert response.json()['width']==640 and response.json()['height']==480
    assert len(calls)==1 and calls[0]['mask'].name=='selected_region.png'
    edited=Image.open(io.BytesIO(client.get(link).content))
    assert edited.getpixel((10,10))==(10,120,15)
    assert edited.getpixel((180,150))==(250,0,0)
    # original unchanged, and URL serves no arbitrary filenames
    assert client.get(link.replace('edit.png','../../etc/passwd')).status_code in (404,422)

def test_full_image_edit_without_mask_is_explicit(monkeypatch):
    raw=png()
    calls=[]
    def fake_edit(image,instruction,**kw):
        calls.append((instruction,kw))
        return Image.new('RGB',(640,480),(25,25,25))
    monkeypatch.setattr('app.main.edit_promotional_image',fake_edit)
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    response=client.post('/api/edit',data={'instruction':'Сделать новый стиль'},
       files={'image':('poster.png',raw,'image/png')})
    assert response.status_code==200
    assert calls[0][1]['mask_raw'] is None
    assert client.get(response.json()['image']).status_code==200
