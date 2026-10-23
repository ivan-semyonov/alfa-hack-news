"""Small offline vocabulary; never a proof of causality or actuality."""
import re

CHANNEL_PATTERNS = {
    'SUPPLY': r'\b(?:постав\w*|экспорт\w*|импорт\w*|дефицит\w*|логист\w*|сырь\w*)',
    'DEMAND': r'\b(?:спрос\w*|потреблен\w*|продаж\w*)',
    'FINANCE': r'\b(?:ставк\w*|кредит\w*|облигац\w*|финансирован\w*)',
    'REGULATION': r'\b(?:закон\w*|регулирован\w*|пошлин\w*|налог\w*)',
    'TECHNOLOGY': r'\b(?:технолог\w*|автоматизац\w*|программ\w*)',
    'LABOR': r'\b(?:работник\w*|зарплат\w*|кадр\w*|занятост\w*)',
    'INFRASTRUCTURE': r'\b(?:электроснабжен\w*|инфраструктур\w*|электросет\w*)',
    'COMPETITION': r'\b(?:конкурен\w*|конкурент\w*|монопол\w*)',
    'GEOGRAPHY': r'\b(?:регион\w*|границ\w*|территори\w*)',
    'MACRO': r'\b(?:инфляц\w*|ввп|макроэконом\w*)',
}
TARGET_PATTERN = re.compile(r'\bкомпонент(?:а|у|ом|е)?\s+[xх](?!\w)', re.IGNORECASE)
CHANGE_PATTERN = re.compile(
    r'\b(?:огранич\w*|задерж\w*|дефицит\w*|запрет\w*|перебо\w*|'
    r'останов\w*|нехват\w*|подорож\w*|возобнов\w*|сокращ\w*)', re.IGNORECASE,
)
