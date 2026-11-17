"""Latest Wheel-Dragoon feedback framing. All wire fields are preserved."""
import struct

SIZES = {0x85: 20, 0x86: 15, 0x87: 29, 0x84: 63, 0xA0: 18, 0xA1: 56}

def xor_checksum(data):
    result = 0
    for byte in data:
        result ^= byte
    return result

def try_parse_packet(buffer, on_error=None):
    while True:
        start = buffer.find(b"\xaa\x55")
        if start < 0:
            buffer[:] = b"\xaa" if buffer.endswith(b"\xaa") else b""
            return None
        del buffer[:start]
        if len(buffer) < 4:
            return None
        size = buffer[2] + 4
        if SIZES.get(buffer[3]) != size:
            del buffer[0]
            continue
        if len(buffer) < size:
            return None
        packet = bytes(buffer[:size])
        if xor_checksum(packet):
            del buffer[0]
            if on_error:
                on_error("Invalid MCU checksum")
            continue
        del buffer[:size]
        kind = packet[3]
        if kind not in (0x85, 0x86, 0x87):
            continue  # Consume complete diagnostic frames, never scan their payload.
        if packet[4] != 1:
            if on_error:
                on_error("Unsupported telemetry version")
            continue
        seq = struct.unpack_from("<H", packet, 5)[0]
        if kind in (0x85, 0x86):
            identity = packet[7]
            if identity >= (4 if kind == 0x85 else 2):
                if on_error:
                    on_error("Invalid telemetry ID")
                continue
            fields = dict(seq=seq, rx_timestamp_us=struct.unpack_from("<I", packet, 8)[0])
            if kind == 0x85:
                status, rpm, encoder = struct.unpack_from("<Bhi", packet, 12)
                fields.update(wheel_id=identity, status=status, rpm=rpm, encoder_count=encoder)
            else:
                fields.update(driver_id=identity, voltage_mv=struct.unpack_from("<H", packet, 12)[0])
        else:
            mode, transition = packet[8] & 15, packet[8] >> 4
            if mode > 4 or transition > 5:
                if on_error:
                    on_error("Unsupported mode or transition")
                continue
            flags, errors = struct.unpack_from("<HH", packet, 9)
            fields = dict(seq=seq, state=packet[7], mode=mode, transition=transition,
                          flags=flags, system_error=errors, validity=packet[13],
                          applied_mode=packet[26], session=packet[27])
            names = ("requested_v_milli", "requested_theta_milli", "requested_w_milli",
                     "applied_v_milli", "applied_theta_milli", "applied_w_milli")
            fields.update(zip(names, struct.unpack_from("<hhhhhh", packet, 14)))
        return kind, fields
