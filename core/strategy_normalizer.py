import re
from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class StrategyNormalizationResult:
    original_args: str
    normalized_args: str
    changed: bool
    requires_white_host: bool
    applied_rules: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

def requires_white_host(args: str) -> bool:
    """Возвращает True, если строка аргументов требует белого хоста."""
    try:
        if not args:
            return False
        tokens = args.split()
        return "--dpi-desync=hostfakesplit" in tokens
    except Exception:
        return False

def _is_valid_white_host(wh: str) -> bool:
    """Валидирует white_host."""
    if not wh:
        return False
    if ' ' in wh or '\t' in wh or '\n' in wh:
        return False
    if len(wh) > 253:
        return False
    if not re.match(r'^[A-Za-z0-9._-]+$', wh):
        return False
    if wh == "localhost":
        return True
    if '.' not in wh:
        return False
    return True

def normalize_strategy_args(args: str, white_host: Optional[str] = None) -> StrategyNormalizationResult:
    """Нормализует строку аргументов стратегии."""
    try:
        original_args = args or ""
        
        if not original_args.strip():
            return StrategyNormalizationResult(
                original_args=original_args, normalized_args="", changed=False, requires_white_host=False
            )
        
        requires_wh = requires_white_host(original_args)
        
        # Валидация white_host
        if white_host is not None and not _is_valid_white_host(white_host):
            return StrategyNormalizationResult(
                original_args=original_args, normalized_args=original_args,
                changed=False, requires_white_host=requires_wh, error="invalid_white_host"
            )
        
        # Требуется white_host, но его нет
        if requires_wh and not white_host:
            return StrategyNormalizationResult(
                original_args=original_args, normalized_args=original_args,
                changed=False, requires_white_host=requires_wh, error="white_host_required"
            )
        
        tokens = original_args.split()
        applied_rules = []
        warnings = []
        
        # Глобальная замена placeholder'ов во всех токенах
        if white_host:
            new_tokens = []
            placeholder_replaced = False
            for t in tokens:
                if "<WHITE_HOST>" in t or "${WHITE_HOST}" in t:
                    t = t.replace("<WHITE_HOST>", white_host).replace("${WHITE_HOST}", white_host)
                    placeholder_replaced = True
                new_tokens.append(t)
            tokens = new_tokens
            if placeholder_replaced:
                applied_rules.append("placeholder_replaced")
        
        # Обработка hostfakesplit
        if requires_wh and white_host:
            mod_tokens_indices = [i for i, t in enumerate(tokens) if t.startswith("--dpi-desync-hostfakesplit-mod=")]
            
            if len(mod_tokens_indices) == 0:
                # A: Параметра нет, нужно вставить
                new_mod = f"--dpi-desync-hostfakesplit-mod=host={white_host}"
                
                insert_idx = len(tokens)
                for i, t in enumerate(tokens):
                    if t.startswith("--hostlist=") or t == "--hostlist":
                        insert_idx = i
                        break
                    if t == "--new":
                        insert_idx = i
                        break
                
                tokens.insert(insert_idx, new_mod)
                applied_rules.append("white_host_injected")
                
            else:
                # B/C/D: Параметры есть
                if len(mod_tokens_indices) > 1:
                    warnings.append("multiple_hostfakesplit_mod_params")
                
                replaced = False
                for idx in mod_tokens_indices:
                    token = tokens[idx]
                    value_part = token[len("--dpi-desync-hostfakesplit-mod="):]
                    
                    if value_part.startswith("host="):
                        rest = value_part[len("host="):]
                        if ',' in rest:
                            first_part, extra = rest.split(',', 1)
                            if first_part != white_host:
                                new_value = f"host={white_host},{extra}"
                                tokens[idx] = f"--dpi-desync-hostfakesplit-mod={new_value}"
                                replaced = True
                        else:
                            if rest != white_host:
                                tokens[idx] = f"--dpi-desync-hostfakesplit-mod=host={white_host}"
                                replaced = True
                    else:
                        if value_part:
                            tokens[idx] = f"--dpi-desync-hostfakesplit-mod=host={white_host},{value_part}"
                        else:
                            tokens[idx] = f"--dpi-desync-hostfakesplit-mod=host={white_host}"
                        replaced = True
                
                if replaced:
                    if "white_host_replaced" not in applied_rules and "placeholder_replaced" not in applied_rules:
                        applied_rules.append("white_host_replaced")
        
        normalized_args = " ".join(tokens)
        changed = (normalized_args != original_args)
        
        return StrategyNormalizationResult(
            original_args=original_args, normalized_args=normalized_args,
            changed=changed, requires_white_host=requires_wh,
            applied_rules=applied_rules, warnings=warnings, error=None
        )
        
    except Exception:
        return StrategyNormalizationResult(
            original_args=args or "", normalized_args=args or "",
            changed=False, requires_white_host=False, error="normalization_failed"
        )
