import struct


def inspect(data):
    """Return (width, height) of a baseline/progressive JPEG or raise ValueError."""
    # UVC cameras may pad a byte or two after EOI, so look for EOI in the last 16 bytes
    if len(data) < 128 or data[:3] != b"\xff\xd8\xff" or data.rfind(b"\xff\xd9") < len(data) - 16:
        raise ValueError("not a complete JPEG")
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7 or m == 0xFF:
            i += 1 if m == 0xFF else 2
            continue
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            if w and h:
                return w, h
            break
        if m == 0xDA:
            break
        i += 2 + ln
    raise ValueError("no valid SOF header")
