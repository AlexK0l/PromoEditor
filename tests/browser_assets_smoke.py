"""Chromium smoke: cumulative file uploads -> reviewed selection -> PNG/JPEG/SVG ZIP."""
import io, json, os, zipfile
from PIL import Image,ImageDraw
from playwright.sync_api import sync_playwright

BASE=os.environ.get('PROMO_BROWSER_BASE','http://127.0.0.1:18200')

def png(color,size,step):
    im=Image.new('RGB',size,color)
    draw=ImageDraw.Draw(im)
    for x in range(0,size[0],step):
        draw.line((x,0,min(x+70,size[0]-1),size[1]),fill='white',width=3)
    b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()

def upload(page,field,name,data,mime):
    page.locator('#'+field).set_input_files({'name':name,'mimeType':mime,'buffer':data})

def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(accept_downloads=True,viewport={'width':1380,'height':900})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(BASE,wait_until='domcontentloaded')
        page.locator('#model').fill('Промышленный подъёмник A1')
        upload(page,'hero','small.png',png('yellow',(360,240),15),'image/png')
        upload(page,'hero','large.png',png('red',(1320,840),10),'image/png')
        assert page.locator('#hero').evaluate('(e)=>e.files.length')==2
        upload(page,'logo','brand-a.png',png('blue',(310,190),11),'image/png')
        upload(page,'logo','brand-b.png',png('green',(340,190),17),'image/png')
        assert page.locator('#logo').evaluate('(e)=>e.files.length')==2
        upload(page,'documents','facts.csv','Нагрузка;44 т\nОбъём;55 м³'.encode('utf-8'),'text/csv')
        upload(page,'references','reference.png',png('cyan',(480,315),12),'image/png')
        assert page.locator('[data-asset-id]').count()==6
        assert page.locator('#asset-files-list img.asset-thumb').count()==5
        assert page.locator('#assets-use-ai').is_disabled()  # CI uses no paid key
        page.locator('#analyze-assets-btn').click()
        page.wait_for_function('!document.getElementById("asset-selection").hidden')
        assert 'Технический отбор' in page.locator('#asset-analysis-method').inner_text()
        assert 'large.png' in page.locator('#asset-picked').inner_text()
        assert '55 м³' in page.locator('#asset-specs-list').inner_text()
        # A reviewer can FORCE an inferior photo and exclude the preferred one.
        page.locator('[data-asset-id="photo_1"] .asset-pref').select_option('include')
        page.locator('[data-asset-id="photo_2"] .asset-pref').select_option('exclude')
        page.locator('#asset-rebuild').click()
        page.wait_for_function(
            'document.getElementById("assets-analysis-status").textContent.includes("Анализ выполнен")')
        assert 'small.png' in page.locator('#asset-picked').inner_text()
        assert 'large.png' in page.locator('#asset-unused').inner_text()
        # Prompt now includes chosen and excluded filenames without inventing specs.
        page.locator('#build-prompt-btn').click()
        page.wait_for_function('document.getElementById("promo-prompt").value.includes("small.png")')
        prompt=page.locator('#promo-prompt').input_value()
        assert 'НЕ ИСПОЛЬЗОВАТЬ' in prompt and 'large.png' in prompt
        assert '44 т' not in page.locator('#specs').input_value()
        page.locator('#generate-btn').click()
        page.wait_for_function('!document.getElementById("download-panel").hidden',timeout=60000)
        with page.expect_download() as download_event:
            page.locator('#download-all').click()
        archive=zipfile.ZipFile(download_event.value.path())
        assert 'asset_selection.json' in archive.namelist()
        report=json.loads(archive.read('asset_selection.json'))
        assert report['selected_assets']['primary_photo']=='photo_1'
        assert report['selected_assets']['logo'] in ('logo_1','logo_2')
        assert set(report['selected_assets']['references'])=={'reference_1'}
        for key in ('4x3','9x16'):
            assert 'poster_'+key+'.png' in archive.namelist()
            assert 'poster_'+key+'.jpg' in archive.namelist()
            assert 'corel_'+key+'.svg' in archive.namelist()
        # Remove an individual logo; current report becomes stale, preventing
        # silent generation with old IDs.
        page.locator('[data-asset-id="logo_1"] .asset-remove').click()
        assert page.locator('#logo').evaluate('(e)=>e.files.length')==1
        assert 'пересоберите' in page.locator('#assets-analysis-status').inner_text().lower() or (
            'повторите анализ' in page.locator('#assets-analysis-status').inner_text().lower())
        page.set_viewport_size({'width':390,'height':820})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+2')
        assert not errors,errors
        browser.close()
    print('Browser multi-asset review: add, analyze, override, prompt, ZIP, remove, mobile — PASS')

if __name__=='__main__':
    main()
