import evdev
import selectors
import sys

def discover_devices() -> list[evdev.InputDevice]:
    devices = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            cap = dev.capabilities()
            
            if evdev.ecodes.EV_KEY not in cap:
                continue
                
            supported_keys = cap[evdev.ecodes.EV_KEY]
            
            has_enter = evdev.ecodes.KEY_ENTER in supported_keys
            has_kp_enter = evdev.ecodes.KEY_KPENTER in supported_keys
            has_letters = evdev.ecodes.KEY_A in supported_keys and evdev.ecodes.KEY_Z in supported_keys
            
            if has_enter or has_kp_enter or has_letters:
                devices.append(dev)
                
        except PermissionError:
            sys.stderr.write(f"WARNING: Permission denied for device at {path}. Run 'newgrp input' or check group membership.\n")
            continue
        except OSError as e:
            sys.stderr.write(f"WARNING: OSError for device at {path}: {str(e)}\n")
            continue
        except Exception as e:
            sys.stderr.write(f"ERROR: Unexpected exception for device at {path}: {str(e)}\n")
            continue
    return devices

def poll_devices(devices: list[evdev.InputDevice], input_queue, stats_queue):
    sel = selectors.DefaultSelector()
    for dev in devices:
        try:
            sel.register(dev, selectors.EVENT_READ)
        except Exception as e:
            sys.stderr.write(f"ERROR: Failed to register device {dev.path}: {e}\n")
            continue
        
    while True:
        try:
            events = sel.select(timeout=0.5)
            for key, _ in events:
                dev = key.fileobj
                try:
                    for event in dev.read():
                        if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                            input_queue.put({"key_code": event.code})
                            stats_queue.put(1)
                except (OSError, evdev.EvdevError):
                    try:
                        sel.unregister(dev)
                    except Exception:
                        pass
        except Exception as e:
            sys.stderr.write(f"ERROR: Exception in selector loop: {e}\n")
            continue