"""
Реекспорт на prompts — вистинските текстови се во backend/data/agent_prompts.txt

Користи load_prompt("ime") во нов код; константите подолу се за постоечки import-и.
"""

from ai._kernel.prompt_loader import load_prompt

CHAT_SYSTEM_PROMPT = load_prompt("chat_system")
LEKAR_EXTRACT_PROMPT = load_prompt("lekar_extract")
ZAKAZI_EXTRACT_PROMPT = load_prompt("zakazi_extract")
SIMPTOM_PROMPT = load_prompt("simptom")
ODDEL_EXTRACT_PROMPT = load_prompt("oddel_extract")
