"""
שכבת הגדרת ה-LLM של "אן".

מאפשרת החלפה קלה בין ספקים (OpenAI / Anthropic) דרך משתנה הסביבה
LLM_PROVIDER, וממפה כל תפקיד (אן / בטיחות / מומחה / מנהל) למודל ולטמפרטורה
המתאימים. ראה llm/config.py לפרטים.
"""
from .config import ROLE_CONFIG, get_llm, get_role_config

__all__ = ["get_llm", "get_role_config", "ROLE_CONFIG"]
