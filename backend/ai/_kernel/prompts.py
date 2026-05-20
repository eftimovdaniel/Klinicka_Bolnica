"""
Реекспорт на prompts — вистинските текстови се во backend/data/agent_prompts.txt

Користи load_prompt("ime") во нов код; константите подолу се за постоечки import-и.
"""

from ai._kernel.prompt_loader import load_prompt

# Glaven sistemski prompt za chat - definira kako AI da odgovara
CHAT_SYSTEM_PROMPT = load_prompt("chat_system")
# Prompt za izvlekuvanje na lekar od korisnichko prashanje
LEKAR_EXTRACT_PROMPT = load_prompt("lekar_extract")
# Prompt za izvlekuvanje na parametri za zakazuvanje (datum, vreme, lekar)
ZAKAZI_EXTRACT_PROMPT = load_prompt("zakazi_extract")
# Prompt za analiza na simptomi i predlog na oddel/lekar
SIMPTOM_PROMPT = load_prompt("simptom")
# Prompt za izvlekuvanje na oddel od prashanje
ODDEL_EXTRACT_PROMPT = load_prompt("oddel_extract")
