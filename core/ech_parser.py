import base64
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class EchParseResult:
    public_name: Optional[str]
    confidence: str  # "high" | "low" | "none"
    raw_ech: Optional[str]
    error: Optional[str]

def _parse_dns_wire(data: bytes) -> str:
    """Пытается распарсить DNS wire format (length-prefixed labels)."""
    labels = []
    ptr = 0
    while ptr < len(data):
        if data[ptr] == 0:
            break
        label_len = data[ptr]
        if ptr + label_len + 1 > len(data) or label_len == 0:
            return ""
        try:
            label = data[ptr+1 : ptr+1+label_len].decode('ascii')
        except UnicodeDecodeError:
            return ""
        labels.append(label)
        ptr += label_len + 1
    if not labels:
        return ""
    return ".".join(labels)

def _parse_ech_config(data: bytes, offset: int):
    """Пытается распарсить один ECHConfig начиная с offset."""
    if offset + 2 > len(data):
        return None, offset
    config_len = int.from_bytes(data[offset:offset+2], 'big')
    if offset + 2 + config_len > len(data) or config_len < 4:
        return None, offset
    
    start = offset + 2
    end = start + config_len
    
    version = int.from_bytes(data[start:start+2], 'big')
    contents_len = int.from_bytes(data[start+2:start+4], 'big')
    start += 4
    
    if start + contents_len > end:
        return None, offset
        
    if version in (0xFE0D, 0x0001):
        ptr = start
        if ptr + 3 > end: return None, offset
        ptr += 1  # config_id
        ptr += 2  # kem_id
        
        if ptr + 2 > end: return None, offset
        pk_len = int.from_bytes(data[ptr:ptr+2], 'big')
        ptr += 2 + pk_len
        
        if ptr + 2 > end: return None, offset
        cs_len = int.from_bytes(data[ptr:ptr+2], 'big')
        ptr += 2 + cs_len
        
        if ptr + 1 > end: return None, offset
        ptr += 1  # maximum_name_length
        
        if ptr + 1 > end: return None, offset
        pn_len = data[ptr]
        ptr += 1
        
        if ptr + pn_len > end or pn_len == 0:
            return None, offset
            
        public_name_bytes = data[ptr:ptr+pn_len]
        
        try:
            public_name = public_name_bytes.decode('ascii')
            if '.' not in public_name:
                wire_name = _parse_dns_wire(public_name_bytes)
                if wire_name and '.' in wire_name:
                    public_name = wire_name
        except UnicodeDecodeError:
            public_name = _parse_dns_wire(public_name_bytes)
            
        if public_name:
            return public_name, offset + 2 + config_len
            
    return None, offset

def _try_parse_structural(data: bytes) -> Optional[str]:
    """Пытается структурно распарсить ECHConfigList или одиночный ECHConfig."""
    names1 = []
    offset = 0
    while offset < len(data):
        name, next_offset = _parse_ech_config(data, offset)
        if name is None:
            break
        names1.append(name)
        offset = next_offset
    if names1:
        return names1[0]
        
    if len(data) >= 2:
        list_len = int.from_bytes(data[0:2], 'big')
        if 2 + list_len == len(data) and list_len > 0:
            names2 = []
            offset = 2
            while offset < len(data):
                name, next_offset = _parse_ech_config(data, offset)
                if name is None:
                    break
                names2.append(name)
                offset = next_offset
            if names2:
                return names2[0]
                
    return None

def _fallback_parse(data: bytes) -> Optional[str]:
    """Fallback поиск домена в бинарных данных."""
    try:
        text = data.decode('ascii', errors='ignore')
        domains = re.findall(r'[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+', text)
        valid = [d for d in domains if len(d) > 4 and '.' in d]
        if valid:
            return max(valid, key=len)
    except Exception:
        pass
    return None

def extract_ech_from_https_record(https_record: str) -> EchParseResult:
    try:
        if not https_record:
            return EchParseResult(None, "none", None, "Empty string")
            
        match = re.search(r'ech="([^"]+)"|ech=([^\s]+)', https_record)
        if not match:
            return EchParseResult(None, "none", None, "No ECH parameter found")
            
        b64 = match.group(1) or match.group(2)
        
        try:
            padding = 4 - len(b64) % 4
            if padding != 4:
                b64 += "=" * padding
            data = base64.b64decode(b64)
        except Exception as e:
            return EchParseResult(None, "none", b64, f"Invalid base64: {e}")
            
        if len(data) < 4:
            return EchParseResult(None, "none", b64, "Decoded data too short")
            
        public_name = _try_parse_structural(data)
        if public_name:
            return EchParseResult(public_name, "high", b64, None)
            
        public_name = _fallback_parse(data)
        if public_name:
            return EchParseResult(public_name, "low", b64, "Structural parse failed, used fallback regex")
            
        return EchParseResult(None, "none", b64, "All parsing methods failed")
        
    except Exception as e:
        return EchParseResult(None, "none", None, f"Unexpected error: {e}")

def extract_ech_public_name(https_record: str) -> Optional[str]:
    return extract_ech_from_https_record(https_record).public_name
