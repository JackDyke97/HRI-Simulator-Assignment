PLUGIN_META = {
    "name": "Gesture Action Mode",
    "description": "Performs actions based on gestures of hand"
}

hand_map = {
    ('Left', 'open_palm'): 0,
    ('Left', 'peace'): 0,
    ('Left', 'three_fingers'): 0,
    ('Left', 'pinch'): 1,
    ('Left', 'point'): 1,
    ('Left', 'fist'): 1,
    ('Right', 'open_palm'): 2,
    ('Right', 'peace'): 2,
    ('Right', 'three_fingers'): 2,
    ('Right', 'pinch'): 3,
    ('Right', 'point'): 3,
    ('Right', 'fist'): 3,
}
action_gestures = {
    "open_palm",
    "peace",
    "three_fingers",
    "pinch",
    "point",
    "fist",
}
gesture_priority = {
    "pinch": 7,
    "open_palm": 6,
    "peace": 5,
    "three_fingers": 4,
    "point": 3,
    'fist': 2,
    'hover': 1,
}
pinch_threshold = 0.07
required_stable_frames = 2
cooldown_ms = 1000

#global variables
selection_queue = []
current_target = None
start_time = 0
last_added_target = None
last_confirm_time = 0
last_clear_time = 0
STABILITY = {}

#setup for global variables
def setup(payload):
    global selection_queue, STABILITY, last_added_target, current_target

    selection_queue = []
    STABILITY = {}
    last_added_target = None
    current_target = None
    return {
        'status': 'Object queueing plugin ready',
        'available': len(payload.get("saved_operations", [])),
    }

# helper to fetch a saved operation from manual
def index_operation(frame,index):
    saved = frame.get("saved_operations", [])
    if index is None or index < 0 or index >= len(saved):
        return None
    return saved[index]

def finger_states(hand):
    return hand.get('fingerstates') or {}

def hand_label(hand):
    return hand.get('handedness') or hand.get('viewerside') or 'Unknown'

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
    states = finger_states(hand)
    return count_no_thumb(hand) + (1 if states.get('thumbExtended') else 0)

def get_active_hand(frame):
    if frame ['primary_hand']:
        return frame['primary_hand']
    elif frame["hands"] == None:
        return first_hand
    else:
        return None
    
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

def box_centers(frame):
    center = {}
    boxes = {}
    for box in frame.get("bayes_boxes", {}).get('boxes', []):
        center[box['id']] = {
            'x': box['x'] + box['width'] * 0.5,
            'y': box['y'] + box['height'] * 0.5,
        }
        boxes[box['id']] = box
        return center, boxes
    
def inside_box(point, box):
    return (
        box['x'] <= point['x'] <= box['x'] + box['width']
        and box['y'] <= point['y'] <= box['y'] + box['height']
    )


def process_frame(frame):
    global LAST_TRIGGER_AT, LAST_TRIGGER_KEY, STABILITY

    hand = frame.get("primary_hand")
    if not hand:
        LAST_TRIGGER_KEY = None
        STABILITY = {}
        return {
            "label": "No hand detected",
            "confidence": 0.5,
            "debug_text": [
                "Perform a gesture with a hand"
            ],
        }