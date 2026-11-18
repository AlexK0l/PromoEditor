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
        # Without an API key the default hybrid option falls back to the free template.
        page.wait_for_function("document.getElementById('mode-template').checked")
        assert page.locator('#mode-template').is_checked()
        assert page.locator('#mode-hybrid').is_disabled()
        assert page.locator('#reference_example').count()==1
        assert page.locator('#file-reference_example').is_hidden()
        page.locator('#optional-materials > summary').click()
        assert page.locator('#file-reference_example').is_visible()
        # CI deliberately has no API key: the explicit low-cost fallback
        # must still support the complete existing browser workflow.
        page.locator('#mode-template').check()
        assert page.locator('#ai-concepts-workflow').is_hidden()
        assert page.locator('.media-column label[for="drawing"]').count()==1
        assert page.locator('#advanced-settings label[for="drawing"]').count()==0
        # Regression: after the PRO style rollout, filling a demo must remain
        # clickable and must NOT silently change the chosen layout to industrial.
        page.locator('#design-options > summary').click()
        page.locator('[data-style="reference_pro"]').click()
        assert page.locator('#style').input_value()=='reference_pro'
        page.locator('#advanced-settings > summary').click()
        assert page.locator('#advanced-settings').evaluate('(el)=>el.open')
        page.locator('#data-facts > summary').click()
        page.locator('#proof-points').fill('Старый факт из другого проекта')
        page.locator('#topbar-menu > summary').click()
        page.locator('#reset-btn').click()
        page.wait_for_function(
            "document.getElementById('reset-btn').textContent==='Очистить форму'")
        assert page.locator('#model').input_value()=='ZubrTrail 500'
        assert page.locator('#style').input_value()=='reference_pro'
        assert page.locator('#proof-points').input_value()==''
        assert page.locator('#use-demo').is_checked()
        assert not page.locator('#reset-btn').is_disabled()
        assert 'Пример заполнен' in page.locator('#modebanner').inner_text()
        page.locator('#reset-btn').click()
        assert page.locator('#model').input_value()==''
        assert page.locator('#reset-btn').inner_text()=='Заполнить пример'
        assert not errors,errors
        # Reset stays in safe free mode without API credentials.
        page.locator('#mode-template').check()
        page.locator('#model').fill('Промышленный подъёмник A1')
        upload(page,'hero','small.png',png('yellow',(360,240),15),'image/png')
        upload(page,'hero','large.png',png('red',(1320,840),10),'image/png')
        assert page.locator('#hero').evaluate('(e)=>e.files.length')==2
        upload(page,'logo','brand-a.png',png('blue',(310,190),11),'image/png')
        upload(page,'logo','brand-b.png',png('green',(340,190),17),'image/png')
        assert page.locator('#logo').evaluate('(e)=>e.files.length')==2
        upload(page,'documents','facts.csv','Нагрузка;44 т\nОбъём;55 м³'.encode('utf-8'),'text/csv')
        upload(page,'references','reference.png',png('cyan',(480,315),12),'image/png')
        page.locator('#asset-files-details > summary').click()
        assert page.locator('[data-asset-id]').count()==6
        assert page.locator('#asset-files-list img.asset-thumb').count()==5
        assert page.locator('#assets-use-ai').is_disabled()  # CI uses no paid key
        page.locator('#asset-review-details > summary').click()
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
        page.locator('#expert-prompt > summary').click()
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
        # The photographed engineering drawing can be reassigned in-place:
        # the report must show it in the DRAWING slot rather than as a photo.
        page.locator('[data-asset-id="photo_2"] .asset-pref').select_option('drawing')
        page.locator('#asset-rebuild').click()
        page.wait_for_function(
            'document.getElementById("assets-analysis-status").textContent.includes("Анализ выполнен")')
        picked=page.locator('#asset-picked').inner_text()
        assert 'Чертёж' in picked and 'large.png' in picked
        assert page.locator('[data-asset-id="photo_2"] .asset-pref').input_value()=='drawing'
        # Remove an individual logo; current report becomes stale, preventing
        # silent generation with old IDs.
        page.locator('[data-asset-id="logo_1"] .asset-remove').click()
        assert page.locator('#logo').evaluate('(e)=>e.files.length')==1
        assert 'пересоберите' in page.locator('#assets-analysis-status').inner_text().lower() or (
            'повторите анализ' in page.locator('#assets-analysis-status').inner_text().lower())
        page.set_viewport_size({'width':390,'height':820})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+2')
        assert not errors,errors

        # Second browser scenario: the first uploaded "photo" actually is a
        # black-and-white side/rear engineering sheet. Without a paid AI key
        # it must be placed in the drawing role automatically.
        other=browser.new_page(viewport={'width':1380,'height':900})
        other.goto(BASE,wait_until='domcontentloaded')
        other.locator('#model').fill('ZubrTrail drawing selection')
        sheet=Image.new('RGB',(1200,900),'white')
        pen=ImageDraw.Draw(sheet)
        pen.rectangle((42,22,1140,340),outline='#292929',width=3)
        for x in range(65,1125,28):
            pen.line((x,40,x,338),fill='#313131',width=2)
        for y in (123,173,223,273):
            pen.line((42,y,1140,y),fill='#373737',width=2)
        pen.rectangle((490,550,715,845),outline='#333333',width=3)
        for x in range(510,700,24):
            pen.line((x,560,x,825),fill='#333333',width=2)
        buf=io.BytesIO()
        sheet.save(buf,format='JPEG',quality=92)
        upload(other,'hero','technical-sheet.jpg',buf.getvalue(),'image/jpeg')
        upload(other,'hero','product.png',png('yellow',(950,560),16),'image/png')
        other.locator('#asset-files-details > summary').click()
        other.locator('#asset-review-details > summary').click()
        other.locator('#analyze-assets-btn').click()
        other.wait_for_function(
            'document.getElementById("assets-analysis-status").textContent.includes("Анализ выполнен")')
        drawing_card=other.locator('[data-asset-id="photo_1"]')
        assert 'Чертёж (распознан автоматически)' in drawing_card.inner_text()
        drawing_slot=other.locator('#asset-picked .asset-pick').filter(has_text='Чертёж')
        assert 'technical-sheet.jpg' in drawing_slot.inner_text()
        assert drawing_card.locator('.asset-pref').input_value()=='auto'
        # An override immediately removes OLD summary values from the screen
        # until the server has recomputed the actual roles.
        drawing_card.locator('.asset-pref').select_option('include')
        assert 'Предыдущий выбор устарел' in other.locator('#asset-picked').inner_text()
        other.locator('#asset-rebuild').click()
        other.wait_for_function(
            'document.getElementById("assets-analysis-status").textContent.includes("Анализ выполнен")')
        assert 'Не выбран' in drawing_slot.inner_text()
        other.close()

        # The normal route must NOT require the old manual Analyze button:
        # one click on Create performs a free asset review and renders both SVGs.
        quick=browser.new_page(viewport={'width':1024,'height':780})
        quick.goto(BASE,wait_until='domcontentloaded')
        quick.locator('#model').fill('Простой тестовый товар')
        upload(quick,'hero','product.png',png('orange',(800,500),17),'image/png')
        assert 'Анализ выполнен' not in quick.locator('#assets-analysis-status').inner_text()
        quick.locator('#generate-btn').click()
        quick.wait_for_function('!document.getElementById("download-panel").hidden',timeout=60000)
        assert quick.evaluate('window.PromoAssets.isReady()')
        assert quick.locator('#asset-selection').count()==1
        assert quick.locator('#individual-downloads').evaluate('(el)=>!el.open')
        assert quick.locator('#download-all').is_enabled()
        assert not errors,errors
        quick.close()
        browser.close()
    print('Browser multi-asset review: add, analyze, override, prompt, ZIP, remove, mobile — PASS')

if __name__=='__main__':
    main()
