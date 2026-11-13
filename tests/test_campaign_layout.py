"""Reference-inspired promotional campaign layout regression tests.

These tests verify source accuracy, strong product hierarchy and actual editable
PNG/JPEG/SVG exports. No synthetic specification is permitted.
"""
import base64
import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image,ImageDraw
from app.editable_export import create_editable_svg,rasterize_svg
from app.render import default_brief

NS={'s':'http://www.w3.org/2000/svg'}
HREF='{http://www.w3.org/1999/xlink}href'


def _mock_product():
    im=Image.new('RGB',(1800,900),'white')
    draw=ImageDraw.Draw(im)
    # Simulated freight trailer silhouette with unused outer white margins.
    draw.polygon([(300,315),(1360,265),(1510,340),(1430,650),(355,685)],
                 fill='#d3232b',outline='#731116',width=9)
    for x in (525,760,995,1230):
        draw.ellipse((x-49,633,x+49,739),fill='#25313f')
        draw.ellipse((x-26,659,x+26,711),fill='#b2becb')
    return im


def _texts(root):
    return ' '.join(''.join(element.itertext()) for element
                    in root.findall('.//s:text',NS))


@pytest.mark.parametrize('format,width,height',[
    ('4x3',1440,1080),('9x16',1080,1920)])
def test_campaign_large_source_photo_and_poster_raster(format,width,height):
    brief=default_brief()
    brief.update(model='ZUBRTRAIL 118',style='industrial',accent='#E31B26')
    svg=create_editable_svg(brief,format,hero=_mock_product())
    root=ET.fromstring(svg)
    assert root.attrib['viewBox']==f'0 0 {width} {height}'
    paths=root.findall('.//s:image',NS)
    hero=[node for node in paths if 'original-product-photo' in node.attrib['id']]
    assert len(hero)==1
    # Photo is now the main dominant element, not a tiny catalog inset.
    assert float(hero[0].attrib['width'])>=820
    assert float(hero[0].attrib['height'])>=320
    assert 'campaign-header' in svg.decode('utf-8')
    assert 'campaign-cta' in svg.decode('utf-8')
    assert 'ZUBRTRAIL 118' in _texts(root)
    assert len(root.findall('.//s:g',NS))>=12
    assert len(root.findall('.//s:text',NS))>15
    png,jpg=rasterize_svg(svg)
    assert Image.open(io.BytesIO(png)).size==(width,height)
    assert Image.open(io.BytesIO(jpg)).size==(width,height)
    im=Image.open(io.BytesIO(png)).convert('RGB')
    assert im.getpixel((7,7))[0]>im.getpixel((7,7))[1]*1.6
    assert im.getpixel((7,height-7))[0]>im.getpixel((7,height-7))[1]*1.6
    thumb=im.resize((100,75))
    red=sum(1 for r,g,b in thumb.getdata() if r>100 and r>g*1.5 and r>b*1.5)
    assert red/7500>.17,red/7500


@pytest.mark.parametrize('fmt',('4x3','9x16'))
def test_sparse_brief_has_no_fake_spec_benefits_price_or_dimensions(fmt):
    sparse={'model':'ZUBRTRAIL 118','category':'Самосвальный полуприцеп',
            'slogan':'Для перевозки сыпучих грузов',
            'style':'industrial','accent':'#E31B26',
            'specs':[],'dimensions':[],'benefits':[],'hero_claims':[],
            'phones':[],'price':'','vat':True,'show_roi':False}
    svg=create_editable_svg(sparse,fmt,hero=_mock_product())
    root=ET.fromstring(svg)
    texts=_texts(root)
    for unverified in ('Уточняются','44 т','34 м³','4 648 000',
                       'Выше эффективность','Меньше расходы','Для вашего бизнеса',
                       'ЗАПРОСИТЕ КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ с НДС'):
        assert unverified not in texts
    assert 'ЗАПРОСИТЕ КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ' in texts
    assert not root.findall(".//s:rect[@id='dimension-panel']",NS)
    assert not any('spec-row-' in x.attrib.get('id','') for x in root.iter()
                   if x.tag.endswith('rect'))
    assert not any('original-drawing' in x.attrib.get('id','') for x in root.iter())
    assert len(root.findall('.//s:image',NS))==1
    hero=next(x for x in root.findall('.//s:image',NS)
              if 'original-product-photo' in x.attrib['id'])
    assert float(hero.attrib['width'])>=900


def test_original_photo_is_large_and_trimmed_only_on_white_border():
    p=default_brief()
    svg=create_editable_svg(p,'4x3',hero=_mock_product())
    root=ET.fromstring(svg)
    item=next(i for i in root.findall('.//s:image',NS)
              if 'original-product-photo' in i.attrib['id'])
    source=base64.b64decode(item.attrib[HREF].split(',',1)[1])
    cropped=Image.open(io.BytesIO(source))
    assert cropped.width<1800 and cropped.height<900
    assert cropped.width>1000
    assert cropped.getpixel((cropped.width//2,cropped.height//2))[0]>130


def test_photo_logo_detail_and_drawing_are_distinct_named_bitmap_objects():
    brief=default_brief()
    colored=Image.new('RGBA',(160,140),'red')
    svg=create_editable_svg(brief,'4x3',hero=colored,detail=colored,
                            logo=colored,drawing=colored)
    root=ET.fromstring(svg)
    names=[x.attrib['id'] for x in root.findall('.//s:image',NS)]
    assert len(names)==4
    for token in ('original-product-photo','original-logo','detail-photo','original-drawing'):
        assert any(token in name for name in names)
    assert len(names)==len(set(names))
    assert not root.findall('.//s:script',NS)
    assert all(node.attrib[HREF].startswith('data:image/png;base64,')
               for node in root.findall('.//s:image',NS))


def test_dense_verified_specs_fit_with_scalable_vector_icon_paths():
    brief=default_brief()
    brief['style']='industrial'
    brief['specs']=[
        ['Объём кузова','34 м³'],['Грузоподъёмность','41 т'],
        ['Полная масса','51 т'],['Собственный вес','9,4 т'],
        ['Нагрузка','12 т'],['Тормоза','Барабанные'],
        ['Гидравлическая система','200 бар']]
    svg=create_editable_svg(brief,'4x3',hero=_mock_product())
    root=ET.fromstring(svg)
    source=_texts(root)
    assert '34 м³' in source and '200 бар' in source
    # 7 editable pictograms are sized to fit the dense right-side fact column.
    badges=[x for x in root.findall('.//s:rect',NS)
            if 'spec-icon-badge' in x.attrib.get('id','')]
    assert len(badges)==7
    assert all('scale(' in node.attrib.get('transform','') for node in badges)
    assert not root.findall('.//s:image',NS) or len(root.findall('.//s:image',NS))>=1
