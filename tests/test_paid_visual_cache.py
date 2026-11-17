"""Paid OpenAI image outputs survive partial failure without repeated charges.

All upstream calls are mocked; CI never spends tokens or image credits.
"""
import base64
import io

import pytest
from PIL import Image

from app import openai_service
from app.render import default_brief


def _encoded_result(color):
    data = io.BytesIO()
    Image.new('RGB', (128, 64), color).save(data, format='PNG')
    datum = type('Datum', (), {'b64_json': base64.b64encode(data.getvalue()).decode()})()
    return type('Result', (), {'data': [datum]})()


def test_successful_first_aspect_is_preserved_after_second_fails(monkeypatch, tmp_path):
    class Images:
        calls = []
        fail_portrait = True

        def generate(self, **kwargs):
            self.calls.append(kwargs['size'])
            if kwargs['size'] == '1024x1536' and self.fail_portrait:
                raise RuntimeError('Mocked second image API failure')
            return _encoded_result('blue')

    images = Images()
    monkeypatch.setattr(openai_service, 'client', lambda: type('API', (), {'images': images})())
    params = dict(brief=default_brief(), hero_present=True, references=[],
                  cache_dir=tmp_path / 'private-cache')

    with pytest.raises(RuntimeError, match='Mocked second'):
        openai_service.generate_visuals(**params)

    assert (tmp_path / 'private-cache' / '4x3.png').is_file()
    assert images.calls == ['1536x1024', '1024x1536']

    images.fail_portrait = False
    outputs = openai_service.generate_visuals(**params)
    assert set(outputs) == {'4x3', '9x16'}
    assert images.calls == ['1536x1024', '1024x1536', '1024x1536']
    assert (tmp_path / 'private-cache' / '9x16.png').is_file()

    # A later retry must incur zero paid calls.
    openai_service.generate_visuals(**params)
    assert len(images.calls) == 3


def test_corrupt_cached_file_is_regenerated(monkeypatch, tmp_path):
    root = tmp_path / 'cache'
    root.mkdir()
    (root / '4x3.png').write_bytes(b'not a PNG')

    class Images:
        calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs['size'])
            return _encoded_result('green')

    images = Images()
    monkeypatch.setattr(openai_service, 'client', lambda: type('API', (), {'images': images})())
    result = openai_service.generate_visuals(
        default_brief(), True, [], cache_dir=root)
    assert set(result) == {'4x3', '9x16'}
    assert images.calls == ['1536x1024', '1024x1536']
    with Image.open(root / '4x3.png') as image:
        image.verify()
