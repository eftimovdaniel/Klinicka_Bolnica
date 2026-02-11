"""
Заеднички функции за сите routers
"""
from datetime import datetime
import json
import os

def debug_log(location: str, message: str, data: dict = None, run_id: str = "run1", hypothesis_id: str = None):
    """Безбедно логирање кое не фрла exception ако фајлот не може да се отвори"""
    try:
        log_path = '/Users/danieleftimov/Desktop/UGD/XML/Klinicka_Bolnica_Stip_XML/.cursor/debug.log'
        log_entry = {
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
            "runId": run_id
        }
        if hypothesis_id:
            log_entry["hypothesisId"] = hypothesis_id
        
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except (PermissionError, OSError):
            print(f"[DEBUG] {location}: {message} - {json.dumps(data or {})}")
    except Exception:
        pass

def transliterate_mk_to_lat(text):
    """Конвертира македонски текст од кирилица во латиница"""
    if not text:
        return ""
    
    translit_map = {
        'Ѓ': 'gj', 'ѓ': 'gj', 'Ѕ': 'dz', 'ѕ': 'dz', 'Љ': 'lj', 'љ': 'lj',
        'Њ': 'nj', 'њ': 'nj', 'Ќ': 'kj', 'ќ': 'kj', 'Џ': 'dzh', 'џ': 'dzh',
        'Ч': 'ch', 'ч': 'ch', 'Ш': 'sh', 'ш': 'sh', 'Ж': 'zh', 'ж': 'zh',
        'А': 'a', 'а': 'a', 'Б': 'b', 'б': 'b', 'В': 'v', 'в': 'v',
        'Г': 'g', 'г': 'g', 'Д': 'd', 'д': 'd', 'Е': 'e', 'е': 'e',
        'З': 'z', 'з': 'z', 'И': 'i', 'и': 'i', 'Ј': 'j', 'ј': 'j',
        'К': 'k', 'к': 'k', 'Л': 'l', 'л': 'l', 'М': 'm', 'м': 'm',
        'Н': 'n', 'н': 'n', 'О': 'o', 'о': 'o', 'П': 'p', 'п': 'p',
        'Р': 'r', 'р': 'r', 'С': 's', 'с': 's', 'Т': 't', 'т': 't',
        'У': 'u', 'у': 'u', 'Ф': 'f', 'ф': 'f', 'Х': 'h', 'х': 'h',
        'Ц': 'c', 'ц': 'c',
    }
    
    result = ""
    for char in text:
        result += translit_map.get(char, char.lower())
    return result
