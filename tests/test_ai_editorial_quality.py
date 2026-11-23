"""Editorial ad quality regressions: fewer facts, readable fonts, full data saved."""
import xml.etree.ElementTree as ET

from PIL import Image

from app.ai_exact_copy_render import (
    DEFAULT_STYLE, FORMATS, MIN_PX, ROLES,
    _format_money, poster_copy, render_exact_svg, verified_copy,
)
from app.ai_exact_copy_template import _art_prompt


def overloaded_brief():
    return {
        "brand":"ZUBR TRAIL",
        "model":"ZubrTrail 500",
        "category":"ПОЛУПРИЦЕП-ЗЕРНОВОЗ",
        "slogan":"Алюминиевый зерновоз, который везёт больше в каждом рейсе",
        "price":"6527000","currency":"₽","vat":True,
        "specs":[
            ["Грузоподъёмность","44 т"],
            ["Полная масса","52,5 т"],
            ["Собственный вес","8,3 т"],
            ["Объём кузова","55 м³"],
            ["Кузов","Высокопрочный алюминиевый сплав"],
            ["Оси","4 оси SAF Intra CD, нагрузка 9 т"],
            ["Тормоза","Дисковые"],
            ["Тормозная система","WABCO TEBS-E"],
            ["Колёса","Легкосплавные диски"],
            ["Гидроцилиндр","ATLANT, до 250 бар"],
        ],
        "dimensions":[["Длина","12 360 мм"] for _ in range(7)],
        "benefits":[f"Полный список преимущества {i}" for i in range(6)],
        "hero_claims":[
            "Легче на 2,5 т","Больше полезной нагрузки",
            "Не боится коррозии","Выше доходность рейсов",
        ],
        "proof_points":[f"Экономическое утверждение {i}" for i in range(4)],
        "phones":["+7 (951) 704-30-42","+7 (951) 704-29-95"],
        "show_roi":False,
        "accent":"#E31B26","style":"industrial",
    }


def test_no_technical_dossier_is_crammed_into_social_ad():
    full=verified_copy(overloaded_brief())
    front=poster_copy(overloaded_brief())
    assert len(full["specs"])==10
    assert len(full["dimensions"])==7
    assert len(full["benefits"])==6
    assert len(full["claims"])==4
    assert len(front["specs"])==3
    assert "Грузоподъёмность: 44 т" in front["specs"]
    assert "Объём кузова: 55 м³" in front["specs"]
    assert "Собственный вес: 8,3 т" in front["specs"]
    assert front["claims"]==["Легче на 2,5 т","Больше полезной нагрузки"]
    assert front["benefits"]==[]
    assert front["dimensions"]==["Длина: 12 360 мм","Длина: 12 360 мм"]
    assert front["proofs"]==[]
    assert front["brand"]==full["brand"]
    assert front["model"]==full["model"]
    assert front["price"]==["6 527 000 ₽ с НДС"]
    assert front["phones"]==full["phones"]
    assert all(item in full[role] for role,values in front.items()
               for item in values)


def test_money_formatting_preserves_value_and_removes_point_zero():
    assert _format_money(1080000.0)=="1 080 000"
    assert _format_money("43210.25")=="43 210.25"
    assert _format_money(0)=="0"


def test_ai_art_prompt_has_no_fake_infographic_widgets_and_no_long_specs():
    prompt=_art_prompt(overloaded_brief(),"9x16",reference=False)
    assert "NO circular icons" in prompt
    assert "NO standalone" not in prompt or "NO" in prompt
    assert "THREE short technical facts" in prompt or "THREE short" in prompt
    assert "55 м³" not in prompt, "AI background cannot typeset customer data"


def test_actual_editable_svg_contains_only_selected_ad_roles_at_readable_size():
    brief=overloaded_brief()
    slots={role:{"x":22,"y":25,"w":80,"h":35} for role in ROLES}
    slots.update({
        "brand":{"x":24,"y":24,"w":190,"h":60},
        "model":{"x":240,"y":24,"w":500,"h":80},
        "category":{"x":24,"y":102,"w":400,"h":48},
        "slogan":{"x":24,"y":160,"w":840,"h":104},
        "specs":{"x":24,"y":285,"w":720,"h":230},
        "dimensions":{"x":755,"y":285,"w":220,"h":230},
        "claims":{"x":24,"y":540,"w":550,"h":135},
        "price":{"x":24,"y":735,"w":510,"h":130},
        "phones":{"x":550,"y":735,"w":400,"h":130},
    })
    art=Image.effect_noise(FORMATS["4x3"],25).convert("RGB")
    svg=render_exact_svg(brief,"4x3",art,slots,DEFAULT_STYLE,
                         copy_override=poster_copy(brief))
    root=ET.fromstring(svg)
    roles={e.get("data-verified-role"):e for e in root.iter()
           if e.get("data-verified-role")}
    assert set(roles)=={
        "brand","model","category","slogan",
        "specs","dimensions","claims","price","phones",
    }
    for role,el in roles.items():
        assert float(el.get("font-size"))>=MIN_PX[role]
    assert "readability-underlay-price" in svg.decode("utf-8")
    assert roles["price"].get("data-exact-copy")=="6 527 000 ₽ с НДС"
    assert "Проверенные компоненты" not in svg.decode("utf-8")
