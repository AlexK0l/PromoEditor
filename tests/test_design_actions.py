"""Regression: additional visual editing actions are passed through the complete brief."""
import io
import json
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from app.main import _normalize, app
from app import openai_service
from app.render import default_brief

client=TestClient(app)

def test_new_actions_are_normalized_with_bound_and_kept_separate():
    payload={'model':'Tester', 'design_notes':'общий стиль', 'design_actions':'  Осветлить фон  '}
    data=_normalize(payload)
    assert data['design_notes']=='общий стиль'
    assert data['design_actions']=='Осветлить фон'
    assert _normalize({'design_actions':'x'*3000})['design_actions']=='x'*1200
    assert _normalize({})['design_actions']==''

def test_field_is_visible_in_compact_html_and_submitted_by_browser():
    html=client.get('/').text
    script=client.get('/static/app.js').text
    assert 'id="design-actions"' in html
    assert 'maxlength="1200"' in html
    assert 'Дополнительные действия над дизайном' in html
    assert "design_actions:get('design-actions').trim()" in script
    assert "set('design-actions',data.design_actions)" in script
    assert "'design-actions','claims'" in script

def test_saved_in_brief_when_openai_not_used():
    brief=default_brief()
    brief['design_actions']='Сделать фон светлее'
    response=client.post('/api/generate',data={
        'payload':json.dumps(brief,ensure_ascii=False),
        'use_openai':'false',
        'use_demo':'true'
    })
    assert response.status_code==200,response.text
    result=response.json()
    assert any('не применяются' in warning for warning in result['warnings'])
    zip_bytes=client.get(result['zip']).content
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        stored=json.loads(archive.read('brief.json'))
    assert stored['design_actions']=='Сделать фон светлее'
    assert stored['_metadata']['design_actions_sent_to_ai'] is False

def test_openai_image_prompts_include_actions_for_both_formats(monkeypatch):
    calls=[]
    class Images:
        def generate(self,**kwargs):
            calls.append(kwargs)
            buffer=io.BytesIO()
            Image.new('RGB',(80,60),'white').save(buffer,format='PNG')
            import base64
            return type('Response',(),{'data':[type('Item',(),{'b64_json':base64.b64encode(buffer.getvalue()).decode()})()]})()
    monkeypatch.setattr(openai_service,'client',lambda: type('API',(),{'images':Images()})())
    brief=default_brief()
    brief['design_actions']='Добавить мягкую подсветку и объём'
    images=openai_service.generate_visuals(brief,hero_present=False,references=[])
    assert set(images)=={'4x3','9x16'}
    assert len(calls)==2
    assert all('Добавить мягкую подсветку и объём' in c['prompt'] for c in calls)
    assert all('Do not alter documented technical characteristics' in c['prompt'] for c in calls)
