PLUGIN_META = {
    "name": "Gesture Sequence Mode",
    "description": "Performs saved operations using two sequential gestures, with fist resetting the buffer"
}

SEQUENCE_MAP = {
    ('open_palm', 'point'): 0,
    ('open_palm', 'peace'): 1,
    ('open_palm', 'three_fingers'): 2,
    ('point', 'peace'): 3,
}

action_gestures = {
    "open_palm",
    "peace",
    "three_fingers",
    "pinch",
    "point",
    "fist",
}


#constants
pinch_threshold = 0.07
REQUIRED_STABLE_FRAMES = 2
WINDOW_MS = 3000
COOLDOWN_MS = 1500

#global variables
sequence_buffer = []
last_gesture = None
last_gesture_time = 0
last_trigger_time = 0
STABILITY = {}


#setup for global variables
def setup(payload):
    global sequence_buffer, last_gesture, last_gesture_time, last_trigger_time, STABILITY

    sequence_buffer = []
    last_gesture = None
    last_gesture_time = 0
    last_trigger_time = 0
    STABILITY = {}
    return {
        "status": 'Sequence plugin ready',
        "available": len(payload.get("saved_operations", [])),
    }
    
#helper functions below

# helper to fetch a saved operation based on manual
def index_operation(frame, index):
    saved = frame.get("saved_operations", [])
    if index is None or index < 0 or index >= len(saved):
        return None
    return saved[index]

def finger_states(hand):
    return hand.get('fingerStates') or {}

def hand_label(hand):
    return hand.get('handedness') or hand.get('viewerSide') or 'Unknown'


def count_no_thumb(hand):
    runtime_value = hand.get('fingerCountNoThumb')
    if runtime_value is not None:
        return int(runtime_value)
    states = finger_states(hand)
    return sum(
        1 for key in ('indexExtended', 'middleExtended', 'ringExtended', 'pinkyExtended')
        if states.get(key)
    )

def count_with_thumb(hand):
    runtime_value =  hand.get('fingerCountWithThumb')
    if runtime_value is not None:
        return int(runtime_value)
    return count_no_thumb(hand) + (1 if finger_states(hand).get('thumbExtended') else 0)

#returns name of gesture and the confidence based on hand dict
def what_gesture(hand):
    states = finger_states(hand)
    pinch_distance = hand.get('pinchDistance', 1.0)
    no_thumb = count_no_thumb(hand)
    with_thumb = count_with_thumb(hand)

    index_up = bool(states.get('indexExtended'))
    middle_up = bool(states.get('middleExtended'))
    ring_up = bool(states.get('ringExtended'))
    pinky_up = bool(states.get('pinkyExtended'))

    if pinch_distance < pinch_threshold and index_up:
        return 'pinch', 0.97
    if no_thumb >=4 and with_thumb >= 4 and pinch_distance > 0.075:
        return 'open_palm', 0.95
    if index_up and middle_up and ring_up and not pinky_up:
        return 'three_fingers', 0.91
    if index_up and middle_up and not ring_up and not pinky_up:
        return 'peace', 0.89
    if index_up and not middle_up and not ring_up and not pinky_up:
        return 'point', 0.87
    if with_thumb <= 1 and pinch_distance >0.08:
        return 'fist', 0.84
    return 'hover', 0.55

def get_active_hand(frame):
    primary = frame.get("primary_hand")
    if primary:
        return primary
    
    hands = frame.get('hands', [])
    if hands:
        return hands[0]
    
    return None

def update_stability(target_id):
    global STABILITY

    if target_id is None:
        STABILITY = {}
        return 0
    
    next_counts = {}
    next_counts[target_id] = STABILITY.get(target_id, 0) + 1
    STABILITY = next_counts
    return STABILITY[target_id]

#main function based on manual
def process_frame(frame):
    global sequence_buffer, last_gesture, last_gesture_time, last_trigger_time, STABILITY
    now = frame.get('timestamp_ms', 0)
    hand = get_active_hand(frame)
    if hand is None:
        sequence_buffer = []
        last_gesture = None
        STABILITY = {}
        return {
            "label": 'No hand detected',
            "confidence": 0.0,
            "debug_text": [
                "show one hand to the camera",
                "sequences: open palm + point/open palm + peace/open palm + three fingers/ point + peace",
                "show fist to reset"
            ],
        }
    
    gesture, confidence = what_gesture(hand)
    frames_held = update_stability(gesture)
    gesture_stable = frames_held >= REQUIRED_STABLE_FRAMES
    action_taken = "waiting"

    if gesture == 'fist' and gesture_stable:
        sequence_buffer = []
        last_gesture = None
        action_taken = 'sequence cleared'

    elif gesture_stable and gesture in action_gestures:
        if gesture != last_gesture:
            gap = now - last_gesture_time

            if last_gesture_time > 0 and gap > WINDOW_MS:
                sequence_buffer = [gesture]
                action_taken = f'too long, restart. [{gesture}]'
            else:
                sequence_buffer.append(gesture)
                action_taken = f"added '{gesture}' to buffer: {sequence_buffer}"
            
            last_gesture = gesture
            last_gesture_time = now

            if len(sequence_buffer) >= 2:
                last_two = tuple(sequence_buffer[-2:])
                op_index = SEQUENCE_MAP.get(last_two)

                if op_index is not None:
                    operation = index_operation(frame, op_index)

                    if operation and now - last_trigger_time > COOLDOWN_MS:
                        last_trigger_time = now
                        sequence_buffer = []
                        last_gesture = None
                        action_taken = f"fired: {operation['name']}"

                        return {
                            "label": f'sequence match: {operation['name']}',
                            "confidence": confidence,
                            "trigger_operation_id": operation['id'],
                            "trigger_operation_name": operation['name'],
                            "cooldown_ms": COOLDOWN_MS,
                            "debug_text": [
                                f"sequence {last_two} triggered {operation['name']}",
                                "buffer cleared and ready for next sequence",
                                "sequence: open palm+point/open palm+peace/open_palm+three fingers/point+peace",
                                "fist can be used to reset at any time",
                            ],
                        }
                    elif operation is None:
                        action_taken = f"sequence matched but operation {op_index} not saved"
                    else:
                        action_taken = "sequence matched but on cooldown"
        else:
            action_taken = f"holding '{gesture}' ({frames_held} frames)"
    
    window_remaining = max(0, WINDOW_MS - (now - last_gesture_time)) if last_gesture_time > 0 else WINDOW_MS

    return {
        "label": f"{gesture} buffer: {sequence_buffer}",
        "confidence": confidence,
        "debug_text": [
            F"gesture: {gesture} (confidence: {confidence: .2f}, stable: {frames_held}f)",
            f"buffer: {sequence_buffer}",
            f"time window remaining: {window_remaining}ms",
            f"action: {action_taken}",
            "sequence: open palm+point/open palm+peace/open_palm+three fingers/point+peace",
            "fist can be used to reset at any time",
        ],
        "cooldown_ms": COOLDOWN_MS,
    }


